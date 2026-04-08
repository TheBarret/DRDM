"""
Directional Recursive Damage Model (DRDM)
Plate Component
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Tuple

from utilities import Vec3

from configuration import (Config,
                           RollProvider, SeededRoller, ConstantRoller,
                           AmmoType, Material, SpallData,
                           Outcome, HitChain, HitResult,
                           FNV_PRIME,
                           )

DEFAULT_CONFIG = Config()
VERBOSE = False

# ── Constants ──────────────────────────────────────────────────────────────

# Maximum obliquity angle (degrees) before t_eff is capped.
# cos(85°) ≈ 0.087 — beyond this the sec(θ) multiplier explodes unphysically.
_MAX_OBLIQUITY_DEG: float = 85.0

# Shatter fires when caliber/t_eff exceeds this ratio.
# Moved here from a bare 3.0 literal in hit() so it is visible and tweakable.
_SHATTER_RATIO: float = 3.0

# Energy budget for a shattered round (must sum ≤ 1.0).
#   ABSORBED  — fraction of P_in treated as work done on the plate.
#   SPALL_PIN — fraction of P_in forwarded to _compute_spall as fragment energy.
#   RESIDUAL  — fraction of P_in that leaks through as fragment penetration.
# These only activate when caliber/t_eff > _SHATTER_RATIO **and** P_in >= t_eff
# (the round had enough energy to reach the far side).  A stopped round that
# merely shatters yields zero residual.
_SHATTER_ABSORBED : float = 0.50
_SHATTER_SPALL_PIN: float = 0.30
_SHATTER_RESIDUAL : float = 0.20   # 0.50 + 0.30 + 0.20 = 1.00 — energy conserved

# Per-type spall multipliers kept as named constants rather than inline literals.
_FRAGMENT_THRESHOLD_MULT: float = 0.50   # lower spall threshold for already-broken rounds
_FRAGMENT_FRAG_MULT     : float = 1.50   # more fragments from a shattered round
_FRAGMENT_VEL_SCALE     : float = 0.60   # fragments are slower (energy lost shattering)
_FRAGMENT_MASS_SCALE    : float = 0.50   # fragments are lighter

_PISTOL_MAX_FRAGS       : int   = 3      # hard cap — pistols barely spall
_PISTOL_VEL_MULT        : float = 0.30   # pistol spall velocity multiplier
_PISTOL_VEL_CAP         : float = 80.0   # m/s absolute ceiling for pistol spall
_PISTOL_MASS_MULT       : float = 2.00   # pistol bullet is heavier, so bigger chunks

# Caliber breakpoints used in fragment-count tiers (mm).
# Mirrors TYPICAL_CALIBER reference values in configuration.py.
_CAL_SMALL_MAX : float = 10.0    # ≤ 10 mm  → small-arms tier (ref: 9 mm)
_CAL_MEDIUM_MAX: float = 20.0    # ≤ 20 mm  → medium-bore tier (ref: 12.7 mm)
_CAL_SMALL_REF : float =  9.0
_CAL_MEDIUM_REF: float = 12.7
_CAL_LARGE_REF : float = 100.0

# Fragment count ceilings per tier (before frag_multiplier and pistol cap).
_FRAGS_SMALL : int = 5
_FRAGS_MEDIUM: int = 15
_FRAGS_LARGE : int = 50

# Normal-unit-length tolerance used in __post_init__.
_NORMAL_UNIT_TOL: float = 1e-3

# ── Vector helpers ─────────────────────────────────────────────────────────

def _dot(a: Vec3, b: Vec3) -> float:
    return a.dot(b)


def _normalize(v: Vec3) -> Vec3:
    return v.normalize() if v.length() > 1e-8 else Vec3.zero()


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def debug(msg: str) -> None:
    if VERBOSE:
        print(msg)


# ── Debug sweep ───────────────────────────────────────────────────────────

def dry_test(plate: "Plate", P_in: float, T: AmmoType, caliber: float, steps: int = 10) -> None:
    """
    Print how the same round performs as plate health degrades from 100% to 0%.
    t_eff shown is the display-only approximation at 0° with no overmatch —
    the actual value used inside hit() also accounts for angle and overmatch.
    """
    roller = ConstantRoller(0.0)
    d         = Vec3(0.0, 0.0, -1.0)   # dead normal, 0° impact
    hit_point = Vec3.zero()
    cfg       = plate.config

    print(f"\nDry test: plate={plate.thickness}mm, {plate.material.name}, "
          f"P_in={P_in}mm, {T.name}, cal={caliber}mm")
    print(f"{'Health':>8} | {'t_eff':>8}  | {'Outcome':>10} | "
          f"{'Damage':>7}  | {'HP':>7}  | {'Spall Frags':>11} | {'Spall Vel':>9}")
    print("-" * 90)

    for i in range(steps + 1):
        health_frac = 1.0 - (i / steps)
        hp          = health_frac * plate.max_health

        p = Plate(
            thickness=plate.thickness,
            normal=plate.normal,
            health=hp,
            max_health=plate.max_health,
            material=plate.material,
            air_gap=plate.air_gap,
            config=cfg,
        )
        result = p.hit(P_in, T, d, hit_point, caliber, 0, roller)

        # Display-only t_eff: degradation only, 0°, no overmatch.
        t_eff = plate.thickness
        if hp < plate.max_health:
            damage_ratio = 1.0 - health_frac
            x     = (damage_ratio - 0.5) * cfg.degradation_steepness
            s     = 1.0 / (1.0 + math.exp(-x))
            t_eff *= 1.0 - cfg.degradation_factor * s

        if not VERBOSE:
            print(f"{health_frac*100:7.1f}% | {t_eff:7.2f}mm | "
                  f"{result.outcome.value:>10} | {result.plate_damage:6.1f}HP | "
                  f"{hp:6.1f}HP | {result.spall.fragment_count:11d} | "
                  f"{result.spall.max_velocity:8.1f}m/s [{i}]")


# ── Plate ─────────────────────────────────────────────────────────────────

@dataclass
class Plate:
    """
    A single armored plate.

    Immutable in all logic — hit() returns a HitResult and never mutates self.
    Caller is responsible for committing: plate.health = result.new_health
    """
    thickness:  float
    normal:     Vec3
    health:     float
    max_health: float    = 100.0
    material:   Material = Material.STEEL
    air_gap:    float    = 0.0
    config:     Config   = field(default_factory=lambda: DEFAULT_CONFIG, repr=False)
    position:   Vec3     = field(default_factory=Vec3.zero)

    # 2D bounds on the plate plane (infinite by default).
    bounds_u: Tuple[float, float] = field(default=(-1e6, 1e6), repr=False)
    bounds_v: Tuple[float, float] = field(default=(-1e6, 1e6), repr=False)

    def __post_init__(self) -> None:
        if self.thickness <= 0:
            raise ValueError(f"Plate thickness must be > 0, got {self.thickness}")
        if self.max_health <= 0:
            raise ValueError(f"Plate max_health must be > 0, got {self.max_health}")
        if not (0.0 <= self.health <= self.max_health):
            raise ValueError(f"Plate health {self.health} outside [0, {self.max_health}]")

        # Ensure normal is a unit vector.
        norm_mag = Vec3(self.normal[0], self.normal[1], self.normal[2]).length()
        if abs(norm_mag - 1.0) > _NORMAL_UNIT_TOL:
            object.__setattr__(self, 'normal', self.normal.normalize())

    # ── Private helpers ────────────────────────────────────────────────────

    def _ricochet_seed(self, shot_hash: int) -> int:
        """
        Deterministic per-plate, per-shot seed.
        FNV-1a mix of shot_hash, thickness (×100, integer), and material ordinal.
        Uses the shared FNV_PRIME constant — immune to PYTHONHASHSEED.
        """
        t_int = int(self.thickness * 100) & 0xFFFF
        m_int = self.material.value & 0xFFFF
        h     = self.config.ricochet_seed
        for word in (shot_hash & 0xFFFFFFFF, t_int, m_int):
            h = ((h ^ word) * FNV_PRIME) & 0xFFFFFFFF
        return h

    def _plate_max_energy(self) -> float:
        """
        Rated absorption capacity of this plate (mm·η units).
        = thickness × material hardness coefficient.
        Denominator in the energy→damage ratio.
        """
        return self.thickness * self.config.material_hardness[self.material]

    def _plate_damage_from_absorption(self, absorbed_energy: float) -> float:
        """
        Convert absorbed energy to HP damage.

        ratio = absorbed / rated_capacity, clamped to [0, 2].
        damage = max_health × energy_to_hp_scale × ratio, clamped to [0, max_health].

        With the default energy_to_hp_scale = 0.6 the maximum reachable damage
        is max_health × 0.6 × 2 = 1.2 × max_health, which is then clamped to
        max_health — so a single hit can destroy a plate but never exceed it.
        The ratio ceiling of 2.0 is only meaningful when energy_to_hp_scale > 0.5;
        below that the outer clamp is always hit first.
        """
        ratio = _clamp(absorbed_energy / self._plate_max_energy(), 0.0, 2.0)
        return _clamp(self.max_health * self.config.energy_to_hp_scale * ratio,
                      0.0, self.max_health)

    # ── Spalling ───────────────────────────────────────────────────────────

    def _compute_spall(self, P_in: float, t_eff: float, caliber: float,
                       theta: float, T: AmmoType) -> SpallData:
        """
        Derive fragmentation data from the impact geometry.

        Called for both stopped near-penetrations and full penetrations.
        P_in here is the energy proxy forwarded by the caller — for a shattered
        round this is already scaled to _SHATTER_SPALL_PIN × original P_in.

        Physics rationale
        -----------------
        - Dead-normal (0°): maximum transfer → widest cone, most fragments.
        - Oblique (high θ): energy deflected → narrower cone, fewer fragments.
        - penetration_ratio (P_in / t_eff) drives count and velocity.
        - caliber drives count ceiling and fragment mass.
        - FRAGMENT rounds spall more easily but are slower and lighter.
        - PISTOL rounds have a hard cap on count and velocity.
        """
        cfg = self.config
        penetration_ratio = P_in / t_eff if t_eff > 0.0 else 0.0

        # FRAGMENT type has a lower energy threshold (already broken).
        threshold = (cfg.spall_threshold * _FRAGMENT_THRESHOLD_MULT
                     if T == AmmoType.FRAGMENT else cfg.spall_threshold)

        if penetration_ratio < threshold:
            return SpallData.none()

        is_pistol = (T == AmmoType.PISTOL)

        # ── Fragment count ceiling (scales with caliber tier) ──────────────
        frag_mult = _FRAGMENT_FRAG_MULT if T == AmmoType.FRAGMENT else 1.0

        if caliber <= _CAL_SMALL_MAX:
            max_frags = int(_FRAGS_SMALL  * (caliber / _CAL_SMALL_REF)  * frag_mult)
        elif caliber <= _CAL_MEDIUM_MAX:
            max_frags = int(_FRAGS_MEDIUM * (caliber / _CAL_MEDIUM_REF) * frag_mult)
        else:
            max_frags = int(_FRAGS_LARGE  * (caliber / _CAL_LARGE_REF)  * frag_mult)

        if is_pistol:
            max_frags = min(max_frags, _PISTOL_MAX_FRAGS)

        max_frags = max(1, max_frags)

        # Obliquity factor: 1.0 at 0°, approaches 0 at 90°.
        obliquity_factor = math.cos(math.radians(_clamp(theta, 0.0, 89.0)))

        fragment_count = int(_clamp(
            int(max_frags * penetration_ratio * obliquity_factor),
            0, max_frags * 2,
        ))

        if fragment_count == 0:
            return SpallData.none()

        # ── Velocity ──────────────────────────────────────────────────────
        vel_scale = _FRAGMENT_VEL_SCALE if T == AmmoType.FRAGMENT else 1.0
        if is_pistol:
            vel_scale *= _PISTOL_VEL_MULT

        caliber_vel_factor = _clamp(caliber / 20.0, 0.5, 2.0)
        max_velocity = ((cfg.spall_base_velocity
                         + cfg.spall_velocity_scale * penetration_ratio)
                        * caliber_vel_factor * vel_scale)

        if is_pistol:
            max_velocity = min(max_velocity, _PISTOL_VEL_CAP)

        # ── Cone ──────────────────────────────────────────────────────────
        cone_half_angle = _clamp(
            cfg.spall_base_cone * obliquity_factor
            + cfg.spall_min_cone * (1.0 - obliquity_factor),
            cfg.spall_min_cone, cfg.spall_base_cone,
        )

        # ── Fragment mass ─────────────────────────────────────────────────
        mass_scale = _FRAGMENT_MASS_SCALE if T == AmmoType.FRAGMENT else 1.0
        if is_pistol:
            mass_scale *= _PISTOL_MASS_MULT

        avg_fragment_mass = (cfg.spall_base_mass
                             * (caliber / _CAL_SMALL_REF)
                             * penetration_ratio
                             * mass_scale)

        return SpallData(
            fragment_count    = fragment_count,
            max_velocity      = round(max_velocity, 1),
            cone_half_angle   = round(cone_half_angle, 1),
            avg_fragment_mass = round(avg_fragment_mass, 3),
            penetration_ratio = round(penetration_ratio, 3),
        )

    # ── HE / HESH ──────────────────────────────────────────────────────────

    def _resolve_he_hesh(self) -> HitResult:
        """
        HE and HESH detonate on the outer surface.
        Damage is a flat fraction of max_health — independent of plate thickness.
        No residual penetration, no internal spall.
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

    # ── Primary hit resolver ───────────────────────────────────────────────

    def hit(
        self,
        P_in:      float,         # Incoming penetration value (mm RHAe)
        T:         AmmoType,      # Ammo type
        d:         Vec3,          # Direction of travel (need not be pre-normalised)
        hit_point: Vec3,          # World-space impact point (used by caller for routing)
        caliber:   float,         # Shell diameter (mm) — overmatch and spall sizing
        shot_hash: int,           # Stable int identifying this shot (reproducibility)
        roller:    RollProvider,  # Injected RNG — no default, must be explicit
    ) -> HitResult:
        """
        Resolve a projectile impact against this plate.

        Order of operations
        -------------------
          1.  Back-face cull
          2.  HE / HESH early-out
          3.  Impact angle → effective thickness (t_eff)
          4.  Multi-hit degradation  (sigmoid — plate holds then collapses)
          5.  Overmatch              (large caliber partially ignores t_eff)
          6.  Ricochet               (skipped for FRAGMENT)
          7.  Shatter check          (caliber/t_eff > _SHATTER_RATIO,
                                      only if round had energy to reach far face)
          8.  Penetration check      (P_in < t_eff → STOPPED)
          9.  Residual + air-gap decay (HEAT / HEAT_JET / EFP)
          10. Plate damage + spall

        Returns HitResult (immutable).  Does NOT mutate self.health.
        """
        if P_in < 0:
            raise ValueError(f"Penetration value cannot be negative: {P_in}")
        if caliber < 0:
            raise ValueError(f"Caliber cannot be negative: {caliber}")

        # ── 1. Back-face cull ─────────────────────────────────────────────
        d      = _normalize(d)
        dot_dn = _dot(d, self.normal)
        if dot_dn >= 0.0:
            return HitResult(0.0, 0.0, Outcome.STOPPED, self.health, SpallData.none())

        # ── 2. HE / HESH: surface detonation ─────────────────────────────
        if T in (AmmoType.HE, AmmoType.HESH):
            return self._resolve_he_hesh()

        # ── 3. Impact angle → effective thickness ─────────────────────────
        # theta is clamped to _MAX_OBLIQUITY_DEG to prevent sec(θ) from
        # growing unboundedly as the angle approaches 90°.
        theta         = math.degrees(math.acos(_clamp(abs(dot_dn), 0.0, 1.0)))
        theta_clamped = _clamp(theta, 0.0, _MAX_OBLIQUITY_DEG)
        t_eff         = self.thickness / math.cos(math.radians(theta_clamped))

        # ── 4. Multi-hit degradation ──────────────────────────────────────
        if self.health < self.max_health:
            damage_ratio = 1.0 - (self.health / self.max_health)
            x     = (damage_ratio - 0.5) * self.config.degradation_steepness
            s     = 1.0 / (1.0 + math.exp(-x))
            t_eff *= 1.0 - self.config.degradation_factor * s

        # ── 5. Overmatch ──────────────────────────────────────────────────
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

        # ── 6. Ricochet ───────────────────────────────────────────────────
        # FRAGMENT is already tumbling/irregular — it embeds or shatters, never ricochets.
        if T != AmmoType.FRAGMENT:
            theta_ric    = self.config.ricochet_angles.get(T, 60.0)
            ric_modifier = self.config.overmatch_ricochet_reduction if overmatch_applied else 1.0
            p_ric        = _clamp(
                (theta - theta_ric) / self.config.ricochet_angle_window, 0.0, 1.0
            ) * ric_modifier

            if roller.roll(self._ricochet_seed(shot_hash)) < p_ric:
                dmg        = min(self.config.surface_scuff_damage, self.health)
                new_health = max(0.0, self.health - dmg)
                return HitResult(0.0, dmg, Outcome.RICOCHET, new_health, SpallData.none())

        # ── 7. Shatter check ──────────────────────────────────────────────
        # Applies only to solid-shot kinetic types; shaped-charge jets and
        # pre-fragmented rounds have different disintegration physics.
        # Crucially: residual penetration is only non-zero when the round had
        # enough energy to reach the far face (P_in >= t_eff).  A round that
        # is both too weak to penetrate AND wide enough to shatter still
        # deposits fragments inside the plate rather than leaking through.
        _shatter_excluded = (
            AmmoType.HEAT, AmmoType.HEAT_JET, AmmoType.EFP,
            AmmoType.FRAGMENT, AmmoType.HE, AmmoType.HESH,
        )
        if T not in _shatter_excluded and caliber / t_eff > _SHATTER_RATIO:
            dmg        = min(self._plate_damage_from_absorption(P_in * _SHATTER_ABSORBED),
                             self.health)
            new_health = max(0.0, self.health - dmg)
            spall      = self._compute_spall(P_in * _SHATTER_SPALL_PIN, t_eff,
                                             caliber, theta, AmmoType.FRAGMENT)
            # Residual only non-zero when the round had energy to exit.
            residual = (P_in * _SHATTER_RESIDUAL) if P_in >= t_eff else 0.0
            return HitResult(
                residual_penetration = residual,
                plate_damage         = dmg,
                outcome              = Outcome.SHATTERED,
                new_health           = new_health,
                spall                = spall,
            )

        # ── 8. Penetration check ──────────────────────────────────────────
        eta = self.config.resistance_matrix[T][self.material]
        if P_in < t_eff:
            # Round stopped. Absorbed energy = P_in × η (material-scaled).
            # Using P_in directly (rather than the t_eff·η·work_fraction form)
            # ensures that a thicker plate stopping the same round deals the
            # same damage proportionally — the round brought P_in of energy
            # regardless of plate geometry.
            absorbed   = P_in * eta
            dmg        = min(self._plate_damage_from_absorption(absorbed), self.health)
            new_health = max(0.0, self.health - dmg)
            spall      = self._compute_spall(P_in, t_eff, caliber, theta, T)
            return HitResult(0.0, dmg, Outcome.STOPPED, new_health, spall)

        # ── 9. Residual + air-gap decay ───────────────────────────────────
        P_res = max(0.0, P_in - t_eff * eta)

        if self.air_gap > 0.0 and P_res > 0.0:
            if T in (AmmoType.HEAT, AmmoType.HEAT_JET):
                P_res *= math.exp(-self.air_gap / self.config.heat_jet_decay_length)
            elif T == AmmoType.EFP:
                P_res *= math.exp(-self.air_gap / self.config.efp_decay_length)

        # ── 10. Plate damage + spall ──────────────────────────────────────
        absorbed   = t_eff * eta
        dmg        = min(self._plate_damage_from_absorption(absorbed), self.health)
        new_health = max(0.0, self.health - dmg)
        spall      = self._compute_spall(P_in, t_eff, caliber, theta, T)

        outcome = Outcome.PENETRATED if P_res > 0.0 else Outcome.STOPPED
        return HitResult(P_res, dmg, outcome, new_health, spall)

    # ── Geometry helpers ───────────────────────────────────────────────────

    def get_local_basis(self) -> Tuple[Vec3, Vec3]:
        """
        Return orthonormal basis vectors (U, V) spanning the plate plane.
        Both are perpendicular to self.normal and to each other.
        """
        ref = Vec3.up()
        if abs(self.normal.dot(ref)) > 0.99:
            ref = Vec3.forward()

        u = self.normal.cross(ref).normalize()
        v = self.normal.cross(u).normalize()
        return u, v

    def point_in_bounds(self, point: Vec3, epsilon: float = 1e-6) -> bool:
        """
        Return True when *point* (on the plate plane) lies within bounds_u/bounds_v.
        """
        u, v   = self.get_local_basis()
        local  = point - self.position
        u_coord = local.dot(u)
        v_coord = local.dot(v)

        return (self.bounds_u[0] - epsilon <= u_coord <= self.bounds_u[1] + epsilon and
                self.bounds_v[0] - epsilon <= v_coord <= self.bounds_v[1] + epsilon)


# ── Chassis Component Base ─────────────────────────────────────────────────

@dataclass(frozen=True)
class Chassis:
    """
    Collection of plates forming a complete armor envelope.
    Resolves hits through multiple layers in sequence using ray casting.

    The chassis defines a 3D bounding volume; plates are processed in order
    of hit distance along the projectile ray.
    """
    plates:     Tuple[Plate, ...]
    bounds_min: Vec3 = field(default=(-1.0, -1.0, -1.0))
    bounds_max: Vec3 = field(default=(1.0, 1.0, 1.0))

    def __post_init__(self) -> None:
        if any(mn >= mx for mn, mx in zip(self.bounds_min, self.bounds_max)):
            raise ValueError(f"Invalid bounds: min={self.bounds_min}, max={self.bounds_max}")

    def _ray_intersects_aabb(self, origin: Vec3, direction: Vec3) -> Tuple[bool, float, float]:
        """
        Ray-AABB intersection (slab method).
        Returns (hit, t_min, t_max) where t is distance along the ray.
        """
        t_min = float('-inf')
        t_max = float('inf')

        for i in range(3):
            if abs(direction[i]) < 1e-8:
                if origin[i] < self.bounds_min[i] or origin[i] > self.bounds_max[i]:
                    return False, 0.0, 0.0
            else:
                inv_d = 1.0 / direction[i]
                t1    = (self.bounds_min[i] - origin[i]) * inv_d
                t2    = (self.bounds_max[i] - origin[i]) * inv_d
                if t1 > t2:
                    t1, t2 = t2, t1
                t_min = max(t_min, t1)
                t_max = min(t_max, t2)
                if t_min > t_max:
                    return False, 0.0, 0.0

        return True, max(0.0, t_min), t_max

    def _ray_plane_intersection(self, origin: Vec3, direction: Vec3,
                                plate: Plate) -> Tuple[bool, float, Vec3]:
        """
        Ray-plane intersection for a given plate.
        Returns (hit, t, hit_point) where t is distance along the ray.
        Uses plate.position as the plane anchor point.
        """
        denom = _dot(direction, plate.normal)
        if abs(denom) < 1e-8:
            return False, float('inf'), Vec3.zero()

        offset = plate.position - origin
        t      = _dot(offset, plate.normal) / denom

        if t < 0:
            return False, float('inf'), Vec3.zero()

        hit_point = origin + direction * t
        return True, t, hit_point

    def _get_hit_plates(self, origin: Vec3, direction: Vec3) -> list:
        """
        Return all (distance, plate, hit_point) tuples for plates the ray
        intersects, sorted nearest-first.
        """
        hits_bounds, t_min, t_max = self._ray_intersects_aabb(origin, direction)
        if not hits_bounds:
            return []

        hits = []
        for plate in self.plates:
            ok, t, hit_point = self._ray_plane_intersection(origin, direction, plate)
            if ok and t_min <= t <= t_max:
                hits.append((t, plate, hit_point))

        hits.sort(key=lambda x: x[0])
        return hits

    def resolve(
        self,
        origin:    Vec3,
        direction: Vec3,
        P_in:      float,
        T:         AmmoType,
        caliber:   float,
        shot_hash: int,
        roller:    RollProvider,
    ) -> HitChain:
        """
        Process a projectile through all hit plates in ray-cast order.

        Args:
            origin:    World-space ray origin (e.g. shooter position).
            direction: Shot direction (need not be unit length).
            P_in:      Initial penetration value (mm RHAe).
            T:         Ammo type.
            caliber:   Projectile diameter (mm).
            shot_hash: Deterministic seed for this shot.
            roller:    RNG provider.
        """
        d           = _normalize(direction)
        hit_plates  = self._get_hit_plates(origin, d)
        results     = []
        current_P   = P_in
        current_hash = shot_hash

        for i, (_distance, plate, hit_point) in enumerate(hit_plates):
            result = plate.hit(current_P, T, d, hit_point, caliber, current_hash, roller)
            results.append(result)

            if result.outcome != Outcome.PENETRATED:
                break

            current_P    = result.residual_penetration
            current_hash = ((current_hash ^ (i + 1)) * FNV_PRIME) & 0xFFFFFFFF

        return HitChain(tuple(results))


# ── Hardware Component Base ────────────────────────────────────────────────
# TODO
#   Hardware is a scaffolding class for critical in-game internals:
#   controls, electronics, conduits, engines, compartments, fuel cells, etc.
#   Destroyed hardware can indirectly disable game mechanics —
#   e.g. a vehicle without a working engine cannot drive.

class Hardware:
    def __init__(self, name: str, health: float, max_health: float,
                 armor_protection: float = 0.0, critical: bool = False):
        self.name       = name
        self.health     = health
        self.max_health = max_health
        self.armor      = armor_protection   # mm RHAe of internal shielding
        self.critical   = critical
        self.destroyed  = False