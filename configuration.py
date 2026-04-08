from enum import Enum
from dataclasses import dataclass, field
from typing import Protocol, Tuple

# FNV-1a prime used for deterministic hash mixing.
# Shared here so SeededRoller and Plate._ricochet_seed stay in sync.
FNV_PRIME: int = 16777619

class AmmoType(Enum):
    # Vehicle based
    AP     = 1      # Armor Piercing
    APFSDS = 2      # Armor Piercing Fin-Stabilized Discarding Sabot
    HEAT   = 3      # High Explosive Anti-Tank (shaped charge)
    HE     = 4      # High Explosive
    HESH   = 5      # High Explosive Squash Head

    # Handheld based
    PISTOL     = 6   # 9mm, .45 ACP
    RIFLE_BALL = 7   # 5.56mm, 7.62mm FMJ
    RIFLE_AP   = 8   # M993, M995 armor piercing
    RIFLE_SLAP = 9   # Saboted light armor penetrator

    # Medium based
    HMGR_AP    = 10  # .50 cal, 14.5mm API
    GRENADE    = 11  # 40mm HEDP shaped charge — uses penetration path, not HE early-exit
    
    FRAGMENT     = 12  # Spall/debris: irregular, low-mass, no aerodynamic stability
    HEAT_JET     = 13  # HEAT cones jettison molten (copper) into segment
    EFP          = 14  # Explosively Formed Penetrator (distinct from HEAT: solid slug, longer standoff)

class Material(Enum):
    STEEL     = 1
    ALUMINUM  = 2
    COMPOSITE = 3


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
        value = (h & 0xFFFFFF) / 0x1000000
        return value


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

# ── SpallData ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SpallData:
    """
    Fragmentation/spalling result from a plate impact.
    Zero values indicate no meaningful spall event.

    Fields:
        fragment_count:     Number of fragments projected inward.
        max_velocity:       Fastest fragment velocity (m/s).
        cone_half_angle:    Half-angle of the fragment spread cone (degrees).
                            Wider at dead-normal impact, narrower at oblique.
        avg_fragment_mass:  Average fragment mass (grams).
        penetration_ratio:  P_in / t_eff — how hard the plate was stressed.
                            1.0 = exactly at threshold, >1 = overpenetration.
    """
    fragment_count:    int
    max_velocity:      float
    cone_half_angle:   float
    avg_fragment_mass: float
    penetration_ratio: float

    @staticmethod
    def none() -> "SpallData":
        """Canonical zero-spall sentinel. Use instead of constructing zeros manually."""
        return SpallData(0, 0.0, 0.0, 0.0, 0.0)

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

# ── Hit Chain ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class HitChain:
    """
    Result of a projectile traversing multiple plates/components.
    Immutable record of the complete penetration path.
    """
    results: Tuple[HitResult, ...]
    final_outcome: Outcome = field(init=False)
    total_damage: float = field(init=False)
    residual_penetration: float = field(init=False)
    
    def __post_init__(self):
        if not self.results:
            object.__setattr__(self, 'final_outcome', Outcome.STOPPED)
            object.__setattr__(self, 'total_damage', 0.0)
            object.__setattr__(self, 'residual_penetration', 0.0)
        else:
            last = self.results[-1]
            object.__setattr__(self, 'final_outcome', last.outcome)
            object.__setattr__(self, 'total_damage', sum(r.plate_damage for r in self.results))
            object.__setattr__(self, 'residual_penetration', last.residual_penetration)
    
    @property
    def penetrated(self) -> bool:
        return self.final_outcome == Outcome.PENETRATED
    
    @property
    def stopped(self) -> bool:
        return self.final_outcome in (Outcome.STOPPED, Outcome.RICOCHET, Outcome.SHATTERED)
    
    @property
    def total_spall_fragments(self) -> int:
        return sum(r.spall.fragment_count for r in self.results)


# ── Reference tables ──────────────────────────────────────────────────────

# Penetration Reference (mm RHAe at 0°, point blank)
TYPICAL_PENETRATION = {
    AmmoType.PISTOL:     2,
    AmmoType.RIFLE_BALL: 5,
    AmmoType.RIFLE_AP:   12,
    AmmoType.RIFLE_SLAP: 18,
    AmmoType.HMGR_AP:    25,
    AmmoType.GRENADE:    50,    # 40mm HEDP shaped charge
    AmmoType.AP:         150,   # 105mm M392
    AmmoType.APFSDS:     450,   # 120mm M829A4
    AmmoType.HEAT:       350,   # 105mm HEAT
    AmmoType.HE:         30,    # Not penetration-based; reference only
    AmmoType.HESH:       25,    # Not penetration-based; reference only
}

# Caliber Reference (mm)
TYPICAL_CALIBER = {
    AmmoType.PISTOL:     9.0,
    AmmoType.RIFLE_BALL: 5.56,
    AmmoType.RIFLE_AP:   5.56,
    AmmoType.RIFLE_SLAP: 7.62,
    AmmoType.HMGR_AP:    12.7,
    AmmoType.GRENADE:    40.0,
    AmmoType.AP:         105.0,
    AmmoType.APFSDS:     120.0,
    AmmoType.HEAT:       105.0,
    AmmoType.HE:         105.0,
    AmmoType.HESH:       105.0,
}


@dataclass(frozen=True)
class Config:

    # ── Ricochet ───────────────────────────────────────────────
    ricochet_angle_window: float = 12.0
    ricochet_seed: int = 2166136261
    ricochet_angles: dict = field(default_factory=lambda: {
        AmmoType.AP:         68.0,  # Armor Piercing
        AmmoType.APFSDS:     72.0,  # Armor-Piercing Fin-Stabilized Discarding Sabot
        AmmoType.HEAT:       75.0,  # HE + Anti-Tank
        AmmoType.HE:         60.0,  # HE
        AmmoType.HESH:       60.0,  # HE + energy transfer 
        AmmoType.PISTOL:     25.0,  # Pistol projectiles
        AmmoType.RIFLE_BALL: 30.0,  # Rifle
        AmmoType.RIFLE_AP:   40.0,  # Rifle + AP
        AmmoType.RIFLE_SLAP: 55.0,  # Rifle + Saboted Light Armor Penetrator
        AmmoType.HMGR_AP:    60.0,  # Similar to APFSDS but more volatile
        AmmoType.GRENADE:    20.0,  # HE + FRAGMENT
        AmmoType.FRAGMENT:   0.0,   # AmmoType to fragments mechanics (embed or shatter; never ricochet)
        AmmoType.HEAT_JET:   75.0,  # Inherit HEAT behavior, jettison of molten metals
        AmmoType.EFP:        70.0,  # TODO: Explosively Formed Penetrator
    })

    # ── Overmatch ──────────────────────────────────────────────
    overmatch_threshold:          float = 1.5
    overmatch_min_reduction:      float = 0.6
    overmatch_slope:              float = 0.2
    overmatch_ricochet_reduction: float = 0.5

    # ── HEAT spaced-armor decay length ────────────────────────────────
    heat_jet_decay_length: float = 200.0
    
    # ── EFP decay length ────────────────────────────────
    efp_decay_length: float = 400.0

    # ── Plate damage ───────────────────────────────────────────
    # Maps absorbed energy (mm·η) → HP fraction.
    # At t=100mm steel (η=1.0): energy=100 → damage = 100 * 0.6 * 1.0 = 60 HP
    energy_to_hp_scale: float = 0.6

    # Hardness denominator per material (used in absorption ratio)
    # absorbed / (thickness * hardness) → ratio clamped to [0, 2]
    material_hardness: dict = field(default_factory=lambda: {
        Material.STEEL:     1.0,
        Material.ALUMINUM:  0.5,
        Material.COMPOSITE: 0.85,
    })

    # ── Degradation ────────────────────────────────────────────
    # degradation_factor:    maximum t_eff reduction at zero health.
    #                        0.4 → a destroyed plate retains 60% effective thickness.
    # degradation_steepness: sharpness of the sigmoid knee.
    #   Low  (~4):  gradual, near-linear decay
    #   Mid  (~8):  plate holds until ~50% health, then drops
    #   High (~14): plate holds until late, then collapses sharply
    degradation_factor:    float = 0.4
    degradation_steepness: float = 8.0

    # ── HE / HESH surface detonation ──────────────────────────
    he_damage_scale:      float = 0.6   # fraction of max_health dealt on detonation
    surface_scuff_damage: float = 5.0   # HP dealt on ricochet graze

    # ── Spalling ──────────────────────────────────────────────
    # spall_threshold:      minimum P_in/t_eff ratio before any spall is generated.
    #                       0.7 → round must reach 70% of penetration threshold.
    # spall_base_cone:      fragment spread cone (degrees) at dead-normal impact (0°).
    #                       Narrows toward spall_min_cone as obliquity increases.
    # spall_min_cone:       cone floor at highly oblique impacts.
    # spall_base_velocity:  minimum fragment velocity (m/s).
    # spall_velocity_scale: additional velocity added at full penetration stress.
    # spall_base_mass:      fragment mass (grams) at 9mm reference caliber
    spall_threshold:         float = 0.7
    spall_base_cone:         float = 20.0
    spall_min_cone:          float = 5.0
    spall_base_velocity:     float = 200.0
    spall_velocity_scale:    float = 400.0
    spall_base_mass:         float = 0.1

    # ── Resistance matrix  η(AmmoType, Material) ──────────────
    # Higher η → plate resists more → lower residual penetration.
    # Formula: P_res = max(0, P_in - t_eff * η)
    resistance_matrix: dict = field(default_factory=lambda: {
        AmmoType.AP: {
            Material.STEEL: 1.0, Material.ALUMINUM: 0.5, Material.COMPOSITE: 1.1,
        },
        AmmoType.APFSDS: {
            Material.STEEL: 1.0, Material.ALUMINUM: 0.4, Material.COMPOSITE: 1.05,
        },
        AmmoType.HEAT: {
            Material.STEEL: 0.85, Material.ALUMINUM: 0.6, Material.COMPOSITE: 1.15,
        },
        AmmoType.HE: {
            Material.STEEL: 1.2, Material.ALUMINUM: 0.8, Material.COMPOSITE: 1.3,
        },
        AmmoType.HESH: {
            Material.STEEL: 1.2, Material.ALUMINUM: 0.8, Material.COMPOSITE: 1.3,
        },
        AmmoType.PISTOL: {
            Material.STEEL: 0.8, Material.ALUMINUM: 0.4, Material.COMPOSITE: 0.7,
        },
        AmmoType.RIFLE_BALL: {
            Material.STEEL: 0.9, Material.ALUMINUM: 0.5, Material.COMPOSITE: 0.8,
        },
        AmmoType.RIFLE_AP: {
            Material.STEEL: 1.0, Material.ALUMINUM: 0.5, Material.COMPOSITE: 1.0,
        },
        AmmoType.RIFLE_SLAP: {
            Material.STEEL: 0.95, Material.ALUMINUM: 0.4, Material.COMPOSITE: 1.1,
        },
        AmmoType.HMGR_AP: {
            Material.STEEL: 1.0, Material.ALUMINUM: 0.5, Material.COMPOSITE: 1.1,
        },
        AmmoType.GRENADE: {
            Material.STEEL: 0.5, Material.ALUMINUM: 0.3, Material.COMPOSITE: 0.6,
        },
        AmmoType.FRAGMENT: {
            Material.STEEL: 0.85, Material.ALUMINUM: 0.6, Material.COMPOSITE: 0.9
        },
        AmmoType.HEAT_JET: {  # only if you split HEAT
            Material.STEEL: 0.85, Material.ALUMINUM: 0.6, Material.COMPOSITE: 1.15
        },
        AmmoType.EFP: {
            Material.STEEL: 0.95, Material.ALUMINUM: 0.5, Material.COMPOSITE: 1.0
        },
    })