from enum import Enum
from dataclasses import dataclass, field


class AmmoType(Enum):
    # Vehicle based
    AP     = 1      # Armor Piercing
    APFSDS = 2      # Armor Piercing, 
    HEAT   = 3      # High Explosive/Anti Tank
    HE     = 4
    HESH   = 5
    
    # Handheld based
    PISTOL     = 6   # 9mm, .45 ACP
    RIFLE_BALL = 7   # 5.56mm, 7.62mm FMJ
    RIFLE_AP   = 8   # M993, M995 armor piercing
    RIFLE_SLAP = 9   # Saboted light armor penetrator
    
    # Medium based
    HMGR_AP    = 10  # .50 cal, 14.5mm API
    GRENADE    = 11  # 40mm HEDP

class Material(Enum):
    STEEL     = "steel"
    ALUMINUM  = "aluminum"
    COMPOSITE = "composite"


# Penetration Reference (mm RHAe at 0°, point blank)
TYPICAL_PENETRATION = {
    # Small arms (handheld)
    AmmoType.PISTOL:     2,      # 9mm FMJ
    AmmoType.RIFLE_BALL: 5,      # 5.56mm M855
    AmmoType.RIFLE_AP:   12,     # 5.56mm M995
    AmmoType.RIFLE_SLAP: 18,     # 7.62mm SLAP
    AmmoType.HMGR_AP:    25,     # .50 cal M903
    AmmoType.GRENADE:    50,     # 40mm HEDP shaped charge
    
    # Vehicle cannon
    AmmoType.AP:         150,    # 105mm M392
    AmmoType.APFSDS:     450,    # 120mm M829A4
    AmmoType.HEAT:       350,    # 105mm HEAT
    AmmoType.HE:         30,     # Not penetration-based, but reference
    AmmoType.HESH:       25,     # Not penetration-based, but reference
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
    ricochet_angles: dict = field(default_factory=lambda: {
        AmmoType.AP:     68.0,
        AmmoType.APFSDS: 72.0,
        AmmoType.HEAT:   75.0,
        AmmoType.HE:     60.0,
        AmmoType.HESH:   60.0,
        AmmoType.PISTOL:     25.0,
        AmmoType.RIFLE_BALL: 30.0,
        AmmoType.RIFLE_AP:   40.0,
        AmmoType.RIFLE_SLAP: 55.0,
        AmmoType.HMGR_AP:    60.0,
        AmmoType.GRENADE:    20.0,
    })

    # ── Overmatch ──────────────────────────────────────────────
    overmatch_threshold:          float = 1.5
    overmatch_min_reduction:      float = 0.6
    overmatch_slope:              float = 0.2
    overmatch_ricochet_reduction: float = 0.5

    # ── HEAT spaced-armor decay ────────────────────────────────
    heat_jet_decay_length: float = 200.0

    # ── Plate damage ───────────────────────────────────────────
    # Energy scale: maps absorbed energy (mm·η) → HP.
    # Tune so one clean penetration of a 100mm steel plate ≈ 80 HP.
    # At t=100, η=1.0 → energy=100 → damage = 100 * 0.8 = 80 HP. ✓
    energy_to_hp_scale:   float = 0.6
    # Hardness denominator per material (mm·η units, treated as plate_max_energy basis).
    # Used in absorption ratio: absorbed / (thickness * hardness).
    material_hardness: dict = field(default_factory=lambda: {
        Material.STEEL:     1.0,
        Material.ALUMINUM:  0.5,
        Material.COMPOSITE: 0.85,
    })

    # ── Degradation ────────────────────────────────────────────
    degradation_factor: float = 0.4

    # ── HE / HESH surface detonation ──────────────────────────
    he_damage_scale:    float = 0.6   # fraction of max_health dealt on detonation
    surface_scuff_damage: float = 5.0

    # ── Resistance matrix  η(AmmoType, Material) ──────────────
    # Higher η → plate resists more → lower residual.
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
    })
