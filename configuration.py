from enum import Enum
from dataclasses import dataclass, field

class AmmoType(Enum):
    AP     = 1
    APFSDS = 2
    HEAT   = 3
    HE     = 4
    HESH   = 5


class Material(Enum):
    STEEL     = "steel"
    ALUMINUM  = "aluminum"
    COMPOSITE = "composite"

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
    energy_to_hp_scale:   float = 0.8
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
    })
