"""
Directional Recursive Damage Model (DRDM)
Plate Component
"""

from __future__ import annotations

import math
from enum import Enum
from dataclasses import dataclass, field
from typing import Protocol, Tuple

from configuration import Config, AmmoType, Material

DEFAULT_CONFIG = Config()


# ── Vector helpers ─────────────────────────────────────────────────────────

Vec3 = Tuple[float, float, float]


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]


def _mag(v: Vec3) -> float:
    return math.sqrt(v[0]**2 + v[1]**2 + v[2]**2)


def _normalize(v: Vec3) -> Vec3:
    m = _mag(v)
    if m < 1e-8:
        return (0.0, 0.0, 0.0)
    return (v[0]/m, v[1]/m, v[2]/m)


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


# ── RollProvider protocol ──────────────────────────────────────────────────

class RollProvider(Protocol):
    """
    Anything that can produce a float in [0, 1) given an integer seed.
    Inject a different implementation for tests, replays, or deterministic sim.
    """
    def roll(self, seed: int) -> float:
        ...


class SeededRoller:
    """
    Randomizer helper.
    PCG, deterministic (Murmur3, Austin Appleby, 2008)
    """
    def roll(self, seed: int) -> float:
        h = seed & 0xFFFFFFFF
        h ^= h >> 16
        h  = (h * 0xd2a98b26) & 0xFFFFFFFF
        h ^= h >> 13
        h  = (h * 0x1b873593) & 0xFFFFFFFF
        h ^= h >> 16
        return (h & 0xFFFFFF) / 0x1000000

class ConstantRoller:
    """
    Test roller: always returns the same value.
    ConstantRoller(0.0)  → never ricochet
    ConstantRoller(1.0)  → always ricochet
    """
    def __init__(self, value: float = 0.0):
        self.value = value

    def roll(self, seed: int) -> float:
        return self.value


# ── HitResult ─────────────────────────────────────────────────────────────

class Outcome(Enum):
    STOPPED    = "stopped"
    PENETRATED = "penetrated"
    RICOCHET   = "ricochet"
    SHATTERED  = "shattered"


@dataclass(frozen=True)
class HitResult:
    """
    Immutable result of a plate hit. Does NOT mutate the plate.
    Caller is responsible for committing:  plate.health = result.new_health
    """
    residual_penetration: float   # mm RHAe remaining after this plate (0 if stopped)
    plate_damage:         float   # HP to subtract from plate
    outcome:              Outcome
    new_health:           float   # proposed health after this hit


# ── Plate ─────────────────────────────────────────────────────────────────

@dataclass
class Plate:
    """
    A single armored plate.

    hit() is a pure function of its arguments — it does NOT modify self.
    Call  plate.health = result.new_health  to commit.

    Args (construction):
        thickness:   Physical plate thickness (mm).
        normal:      Outward-facing unit normal (world space).
        health:      Current HP.
        max_health:  HP at full integrity. Used for degradation and HE damage.
        material:    Material enum, drives resistance and hardness lookup.
        air_gap:     Gap between this plate and the next (mm). HEAT jet decays across it.
        config:      Physics config. Defaults to module-level DEFAULT_CONFIG.
    """
    thickness:  float
    normal:     Vec3
    health:     float
    max_health: float    = 100.0
    material:   Material = Material.STEEL
    air_gap:    float    = 0.0
    config:     Config   = field(default_factory=lambda: DEFAULT_CONFIG, repr=False)

    # ── Private helpers ────────────────────────────────────────

    def _ricochet_seed(self, shot_hash: int) -> int:
        """Deterministic seed that varies per plate and per shot."""
        # Encode thickness as integer to avoid float instability.
        # No Python hash() — immune to PYTHONHASHSEED.
        t_int = int(self.thickness * 100) & 0xFFFF
        m_int = self.material.value.__hash__() & 0xFFFF  # enum name, stable
        # FNV-1a mix of the three values
        h = 2166136261
        for word in (shot_hash & 0xFFFFFFFF, t_int, m_int):
            h = ((h ^ word) * 16777619) & 0xFFFFFFFF
        return h

    def _plate_max_energy(self) -> float:
        """
        Notional maximum energy this plate can absorb (mm·η units).
        One full thickness of its own material at base resistance.
        Used as denominator in absorption ratio.
        """
        hardness = self.config.material_hardness.get(self.material, 1.0)
        return self.thickness * hardness

    def _plate_damage_from_absorption(self, absorbed_energy: float) -> float:
        """
        HP damage scaled by how much energy this plate absorbed relative to
        what it can maximally absorb.  No kappa_p / t_ref magic constants.

        absorbed_energy = t_eff * η  (the work done on penetration)
                        = (t_eff * η) capped at P_in for stopped shots.
        """
        ratio = _clamp(absorbed_energy / self._plate_max_energy(), 0.0, 2.0)
        return _clamp(self.max_health * self.config.energy_to_hp_scale * ratio,
                      0.0, self.max_health)

    # ── HE / HESH ─────────────────────────────────────────────

    def _resolve_he_hesh(self) -> HitResult:
        """
        HE and HESH detonate on the outer surface.
        Damage is a flat fraction of max_health (tunable via config).
        No residual penetration.
        """
        dmg        = self.max_health * self.config.he_damage_scale
        new_health = max(0.0, self.health - dmg)
        return HitResult(
            residual_penetration = 0.0,
            plate_damage         = dmg,
            outcome              = Outcome.STOPPED,
            new_health           = new_health,
        )

    # ── Main entry point ──────────────────────────────────────

    def hit(
        self,
        P_in:      float,          # Incoming penetration value (mm RHAe)
        T:         AmmoType,       # Ammo type
        d:         Vec3,           # Direction of travel (need not be pre-normalized)
        hit_point: Vec3,           # World-space impact point (unused here, passed for callers)
        caliber:   float,          # Shell diameter (mm), used for overmatch
        shot_hash: int,            # Stable int identifying this shot (for reproducibility)
        roller:    RollProvider,   # Injected RNG — no default, must be explicit
    ) -> HitResult:
        """
        Resolve a projectile impact against this plate.

        Order of operations:
          1. Back-face cull
          2. HE / HESH early-out
          3. Impact angle → effective thickness
          4. Multi-hit degradation
          5. Overmatch
          6. Ricochet
          7. Penetration check (stopped)
          8. Residual + HEAT air-gap decay
          9. Plate damage from energy absorption

        Returns HitResult (immutable). Does NOT mutate self.health.
        """

        # 1. Back-face cull — plate is facing away, projectile can't hit it.
        d       = _normalize(d)
        dot_dn  = _dot(d, self.normal)
        if dot_dn >= 0.0:
            return HitResult(0.0, 0.0, Outcome.STOPPED, self.health)

        # 2. HE / HESH: surface detonation, no penetration model.
        if T in (AmmoType.HE, AmmoType.HESH):
            return self._resolve_he_hesh()

        # 3. Impact angle → effective thickness.
        theta         = math.degrees(math.acos(abs(dot_dn)))
        theta_clamped = min(theta, 85.0)
        t_eff         = self.thickness / math.cos(math.radians(theta_clamped))

        # 4. Multi-hit degradation: damaged plate offers less resistance.
        if self.health < self.max_health:
            damage_ratio = 1.0 - (self.health / self.max_health)
            t_eff       *= (1.0 - self.config.degradation_factor * damage_ratio)

        # 5. Overmatch: large-caliber shell partially ignores effective thickness.
        overmatch_applied = False
        if caliber > 0.0:
            R = caliber / t_eff
            if R > self.config.overmatch_threshold:
                reduction = max(
                    self.config.overmatch_min_reduction,
                    1.0 - self.config.overmatch_slope * (R - self.config.overmatch_threshold),
                )
                t_eff            *= reduction
                overmatch_applied  = True

        # 6. Ricochet — overmatch suppresses probability.
        theta_ric       = self.config.ricochet_angles.get(T, 60.0)
        ric_modifier    = self.config.overmatch_ricochet_reduction if overmatch_applied else 1.0
        p_ric           = _clamp(
            (theta - theta_ric) / self.config.ricochet_angle_window, 0.0, 1.0
        ) * ric_modifier

        if roller.roll(self._ricochet_seed(shot_hash)) < p_ric:
            dmg        = self.config.surface_scuff_damage
            new_health = max(0.0, self.health - dmg)
            return HitResult(0.0, dmg, Outcome.RICOCHET, new_health)

        # 7. Penetration check: does the round have enough energy to push through?
        if P_in < t_eff:
            # Stopped — partial energy absorbed proportional to how close it got.
            absorbed = min(P_in, t_eff)   # can't absorb more than t_eff
            dmg      = self._plate_damage_from_absorption(absorbed)
            new_health = max(0.0, self.health - dmg)
            return HitResult(0.0, dmg, Outcome.STOPPED, new_health)

        # 8. Residual penetration after subtracting plate resistance.
        eta   = self.config.resistance_matrix[T][self.material]
        P_res = max(0.0, P_in - t_eff * eta)

        # HEAT jet decays across air gap to the next plate.
        if T == AmmoType.HEAT and self.air_gap > 0.0 and P_res > 0.0:
            P_res *= math.exp(-self.air_gap / self.config.heat_jet_decay_length)

        # 9. Plate damage: proportional to how much energy this plate absorbed.
        #    A round that sailed through cleanly absorbed less than one that barely made it.
        absorbed = t_eff * eta              # energy spent on this plate
        dmg      = self._plate_damage_from_absorption(absorbed)
        new_health = max(0.0, self.health - dmg)

        outcome = Outcome.PENETRATED if P_res > 0.0 else Outcome.STOPPED
        return HitResult(P_res, dmg, outcome, new_health)