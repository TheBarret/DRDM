"""
Directional Recursive Damage Model (DRDM)
Plate Component
"""

from __future__ import annotations

import math
from enum import Enum
from dataclasses import dataclass, field
from typing import Protocol, Tuple

from configuration import Config, AmmoType, Material, SpallData

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
    Deterministic hash-based roller using a Murmur3 finalizer.
    Produces a stable float in [0, 1) for a given integer seed.
    Not a PRNG — stateless, same seed always returns same value.
    Immune to PYTHONHASHSEED.
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
    Test roller: always returns the same value regardless of seed.
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
    residual_penetration: float     # mm RHAe remaining after this plate (0 if stopped)
    plate_damage:         float     # HP subtracted from plate
    outcome:              Outcome
    new_health:           float     # proposed health after this hit
    spall:                SpallData = field(default_factory=SpallData.none)


# ── Debug sweep ───────────────────────────────────────────────────────────

def dry_test(plate: "Plate", P_in: float, T: AmmoType, caliber: float, steps: int = 10) -> None:
    """
    Print how the same round performs as plate health degrades from 100% to 0%.

    Uses ConstantRoller(0.0) so ricochet never fires — pure penetration path.
    t_eff shown is the degraded effective thickness at 0° (no angle contribution).

    Example:
        p = Plate(25.0, (0,0,1), 150.0, 150.0, Material.STEEL)
        dry_test(p, 25.0, AmmoType.HMGR_AP, 12.7)
    """
    roller = ConstantRoller(0.0)
    d      = (0.0, 0.0, -1.0)   # dead normal, 0° impact
    cfg    = plate.config

    print(f"\nDry test: plate={plate.thickness}mm, {plate.material.name}, P_in={P_in}mm, {T.name}, cal={caliber}mm")
    print(f"{'Health':>8} | {'t_eff':>8}  | {'Outcome':>10} | {'Damage':>7}  | {'HP':>7}  | {'Spall Frags':>11} | {'Spall Vel':>9}")
    print("-" * 90)

    for i in range(steps + 1):
        health_frac = 1.0 - (i / steps)
        hp          = health_frac * plate.max_health

        p      = Plate(plate.thickness, plate.normal, hp, plate.max_health,
                       plate.material, plate.air_gap, cfg)
        result = p.hit(P_in, T, d, (0.0, 0.0, 0.0), caliber, 0, roller)

        # Recompute t_eff at 0° mirroring steps 3+4 of hit() for display.
        t_eff = plate.thickness
        if hp < plate.max_health:
            damage_ratio = 1.0 - health_frac
            x     = (damage_ratio - 0.5) * cfg.degradation_steepness
            s     = 1.0 / (1.0 + math.exp(-x))
            t_eff *= 1.0 - cfg.degradation_factor * s

        print(f"{health_frac*100:7.1f}% | {t_eff:7.2f}mm | "
              f"{result.outcome.value:>10} | {result.plate_damage:6.1f}HP | "
              f"{result.new_health:6.1f}HP | {result.spall.fragment_count:11d} | "
              f"{result.spall.max_velocity:8.1f}m/s")


# ── Plate ─────────────────────────────────────────────────────────────────

@dataclass
class Plate:
    """
    A single armored plate.

    hit() is a pure function of its arguments — it does NOT modify self.
    Call  plate.health = result.new_health  to commit.

    Construction args:
        thickness:   Physical plate thickness (mm). Must be > 0.
        normal:      Outward-facing unit normal (world space). Must be unit length.
        health:      Current HP. Must be in [0, max_health].
        max_health:  HP at full integrity. Baseline for degradation and HE damage.
        material:    Material enum — drives resistance and hardness lookup.
        air_gap:     Distance to the next plate (mm). HEAT jet decays across it.
        config:      Physics config. Defaults to module-level DEFAULT_CONFIG.
    """
    thickness:  float
    normal:     Vec3
    health:     float
    max_health: float    = 100.0
    material:   Material = Material.STEEL
    air_gap:    float    = 0.0
    config:     Config   = field(default_factory=lambda: DEFAULT_CONFIG, repr=False)

    def __post_init__(self) -> None:
        if self.thickness <= 0:
            raise ValueError(f"Plate thickness must be > 0, got {self.thickness}")
        if self.max_health <= 0:
            raise ValueError(f"Plate max_health must be > 0, got {self.max_health}")
        if not (0.0 <= self.health <= self.max_health):
            raise ValueError(f"Plate health {self.health} outside [0, {self.max_health}]")
        norm_mag = _mag(self.normal)
        if abs(norm_mag - 1.0) > 0.001:
            raise ValueError(f"Plate normal must be a unit vector, got magnitude {norm_mag:.4f}")

    # ── Private helpers ────────────────────────────────────────

    def _ricochet_seed(self, shot_hash: int) -> int:
        """
        Deterministic seed that varies per plate identity and per shot.
        Uses FNV-1a mix of shot_hash, thickness, and material ordinal.
        No Python hash() — immune to PYTHONHASHSEED.
        """
        t_int = int(self.thickness * 100) & 0xFFFF
        m_int = self.material.value & 0xFFFF   # integer enum — stable across runs
        h = 2166136261
        for word in (shot_hash & 0xFFFFFFFF, t_int, m_int):
            h = ((h ^ word) * 16777619) & 0xFFFFFFFF
        return h

    def _plate_max_energy(self) -> float:
        """
        Notional maximum energy this plate can absorb (mm·η units).
        = thickness * material hardness coefficient.
        Used as the denominator in the absorption ratio.
        Raises KeyError on unknown material — fail loud, not silent.
        """
        return self.thickness * self.config.material_hardness[self.material]

    def _plate_damage_from_absorption(self, absorbed_energy: float) -> float:
        """
        HP damage scaled by how much energy this plate absorbed relative to
        its rated capacity.

        absorbed_energy = P_in       on a stopped shot (energy spent trying)
                        = t_eff * η  on a penetrating shot (work done on plate)

        ratio > 1.0 means overkill — clamped to 2.0 so an extreme round deals
        at most max_health * energy_to_hp_scale * 2.0 damage.
        """
        ratio = _clamp(absorbed_energy / self._plate_max_energy(), 0.0, 2.0)
        return _clamp(self.max_health * self.config.energy_to_hp_scale * ratio,
                      0.0, self.max_health)

    # ── Spalling ──────────────────────────────────────────────

    def _compute_spall(self, P_in: float, t_eff: float, caliber: float,
                       theta: float) -> SpallData:
        """
        Derive fragmentation data from the impact geometry.

        Called for both stopped near-penetrations and full penetrations.
        Uses the caliber already resolved by hit() — no local re-derivation.

        Physics rationale:
          - Dead-normal impact (0°) = maximum energy transfer = widest cone, most fragments.
          - Oblique impact (high theta) = energy partly deflected = narrower cone, fewer fragments.
          - penetration_ratio drives fragment count and velocity.
          - caliber drives fragment count ceiling and mass.
        """
        cfg = self.config
        penetration_ratio = P_in / t_eff if t_eff > 0.0 else 0.0

        if penetration_ratio < cfg.spall_threshold:
            return SpallData.none()

        # Fragment count ceiling scales with caliber.
        # 9mm → ~5 max, 12.7mm → ~15 max, 105mm → ~50 max.
        if caliber <= 10.0:
            max_frags = int(5  * (caliber / 9.0))
        elif caliber <= 20.0:
            max_frags = int(15 * (caliber / 12.7))
        else:
            max_frags = int(50 * (caliber / 100.0))
        max_frags = max(1, max_frags)

        # Obliquity factor: 1.0 at 0° (dead-normal, most spall),
        # falls toward 0 at 90° (grazing, almost no spall).
        # cos(theta) gives a natural falloff — 1.0 at 0°, 0.0 at 90°.
        obliquity_factor = math.cos(math.radians(_clamp(theta, 0.0, 89.0)))

        fragment_count = int(max_frags * penetration_ratio * obliquity_factor)
        fragment_count = _clamp(fragment_count, 0, max_frags * 2)

        if fragment_count == 0:
            return SpallData.none()

        # Velocity: rises with penetration stress, scaled by caliber.
        caliber_vel_factor = _clamp(caliber / 20.0, 0.5, 2.0)
        max_velocity = (cfg.spall_base_velocity
                        + cfg.spall_velocity_scale * penetration_ratio) * caliber_vel_factor

        # Cone: widest at 0° (dead-normal), narrows as impact becomes oblique.
        cone_half_angle = (cfg.spall_base_cone * obliquity_factor
                           + cfg.spall_min_cone * (1.0 - obliquity_factor))
        cone_half_angle = _clamp(cone_half_angle, cfg.spall_min_cone, cfg.spall_base_cone)

        # Fragment mass scales with caliber relative to 9mm reference.
        avg_fragment_mass = cfg.spall_base_mass * (caliber / 9.0) * penetration_ratio

        return SpallData(
            fragment_count    = int(fragment_count),
            max_velocity      = round(max_velocity, 1),
            cone_half_angle   = round(cone_half_angle, 1),
            avg_fragment_mass = round(avg_fragment_mass, 3),
            penetration_ratio = round(penetration_ratio, 3),
        )

    # ── HE / HESH ─────────────────────────────────────────────

    def _resolve_he_hesh(self) -> HitResult:
        """
        HE and HESH detonate on the outer surface.
        Damage is a flat fraction of max_health — independent of plate thickness.
        No residual penetration. No spall (surface blast, not internal fragmentation).
        """
        dmg        = min(self.max_health * self.config.he_damage_scale, self.health)
        new_health = max(0.0, self.health - dmg)
        return HitResult(
            residual_penetration = 0.0,
            plate_damage         = dmg,
            outcome              = Outcome.STOPPED,
            new_health           = new_health,
            spall                = SpallData.none(),
        )

    # ── Main entry point ──────────────────────────────────────

    def hit(
        self,
        P_in:      float,        # Incoming penetration value (mm RHAe)
        T:         AmmoType,     # Ammo type
        d:         Vec3,         # Direction of travel (need not be pre-normalized)
        hit_point: Vec3,         # World-space impact point (reserved for caller routing)
        caliber:   float,        # Shell diameter (mm), used for overmatch and spall
        shot_hash: int,          # Stable int identifying this shot (for reproducibility)
        roller:    RollProvider, # Injected RNG — no default, must be explicit
    ) -> HitResult:
        """
        Resolve a projectile impact against this plate.

        Order of operations:
          1. Back-face cull
          2. HE / HESH early-out
          3. Impact angle → effective thickness
          4. Multi-hit degradation  (sigmoid — holds then collapses)
          5. Overmatch
          6. Ricochet
          7. Penetration check (stopped)
          8. Residual + HEAT air-gap decay
          9. Plate damage + spall from energy absorption

        Returns HitResult (immutable). Does NOT mutate self.health.
        """
        if P_in < 0:
            raise ValueError(f"Penetration value cannot be negative: {P_in}")
        if caliber < 0:
            raise ValueError(f"Caliber cannot be negative: {caliber}")

        # 1. Back-face cull — plate is facing away, projectile cannot hit it.
        d      = _normalize(d)
        dot_dn = _dot(d, self.normal)
        if dot_dn >= 0.0:
            return HitResult(0.0, 0.0, Outcome.STOPPED, self.health, SpallData.none())

        # 2. HE / HESH: surface detonation, no penetration model.
        if T in (AmmoType.HE, AmmoType.HESH):
            return self._resolve_he_hesh()

        # 3. Impact angle → effective thickness.
        #    theta = angle between incoming ray and plate normal (0° = dead-on).
        #    Clamped to 85° to avoid t_eff blowup at grazing angles.
        theta         = math.degrees(math.acos(_clamp(abs(dot_dn), 0.0, 1.0)))
        theta_clamped = _clamp(theta, 0.0, 85.0)
        t_eff         = self.thickness / math.cos(math.radians(theta_clamped))

        # 4. Multi-hit degradation: damaged plate offers less resistance.
        #    Sigmoid centered at damage_ratio=0.5 — plate holds near full resistance
        #    until roughly half health, then falls sharply toward the floor set by
        #    degradation_factor. At zero health: t_eff *= (1 - degradation_factor * ~1.0).
        if self.health < self.max_health:
            damage_ratio = 1.0 - (self.health / self.max_health)
            x     = (damage_ratio - 0.5) * self.config.degradation_steepness
            s     = 1.0 / (1.0 + math.exp(-x))   # sigmoid: 0→1 as damage_ratio 0→1
            t_eff *= 1.0 - self.config.degradation_factor * s

        # 5. Overmatch: large-caliber shell partially ignores effective thickness.
        #    R = caliber / t_eff. Above threshold, t_eff is reduced proportionally,
        #    floored at overmatch_min_reduction.
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

        # 6. Ricochet — probability rises linearly past ricochet_angle threshold.
        #    Overmatch suppresses ricochet: a round that punches through angle can't skip off.
        theta_ric    = self.config.ricochet_angles.get(T, 60.0)
        ric_modifier = self.config.overmatch_ricochet_reduction if overmatch_applied else 1.0
        p_ric        = _clamp(
            (theta - theta_ric) / self.config.ricochet_angle_window, 0.0, 1.0
        ) * ric_modifier

        if roller.roll(self._ricochet_seed(shot_hash)) < p_ric:
            dmg        = min(self.config.surface_scuff_damage, self.health)
            new_health = max(0.0, self.health - dmg)
            return HitResult(0.0, dmg, Outcome.RICOCHET, new_health, SpallData.none())

        # 7. Penetration check: does the round have enough energy to push through?
        #    absorbed = P_in: energy the round spent against this plate.
        #    A pistol barely stresses tank armor; a near-miss APFSDS craters it.
        if P_in < t_eff:
            absorbed   = P_in
            dmg        = min(self._plate_damage_from_absorption(absorbed), self.health)
            new_health = max(0.0, self.health - dmg)
            spall      = self._compute_spall(P_in, t_eff, caliber, theta)
            return HitResult(0.0, dmg, Outcome.STOPPED, new_health, spall)

        # 8. Residual penetration after subtracting plate resistance.
        eta   = self.config.resistance_matrix[T][self.material]
        P_res = max(0.0, P_in - t_eff * eta)

        # HEAT jet decays exponentially across the air gap to the next plate.
        if T == AmmoType.HEAT and self.air_gap > 0.0 and P_res > 0.0:
            P_res *= math.exp(-self.air_gap / self.config.heat_jet_decay_length)

        # 9. Plate damage + spall.
        #    Energy absorbed = t_eff * η (work done on this plate by the penetrating round).
        #    A round that sailed through cleanly absorbed less than one that barely made it.
        absorbed   = t_eff * eta
        dmg        = min(self._plate_damage_from_absorption(absorbed), self.health)
        new_health = max(0.0, self.health - dmg)
        spall      = self._compute_spall(P_in, t_eff, caliber, theta)

        outcome = Outcome.PENETRATED if P_res > 0.0 else Outcome.STOPPED
        return HitResult(P_res, dmg, outcome, new_health, spall)