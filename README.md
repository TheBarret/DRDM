# Directional Recursive Damage Model

A deterministic, performance-oriented damage propagation system using penetration values and subtractive residuals.  
No physics engine required  pure mathematics from first principles to derived semantics. 

# Features

| Component | Status | Notes |
|-----------|--------|-------|
| Penetration model | ✅ Complete | Physics-based, angle-aware |
| Degradation | ✅ Complete | Sigmoid curve, configurable |
| Ricochet | ✅ Complete | Angle + overmatch influence |
| Overmatch | ✅ Complete | Large calibers ignore thickness |
| HEAT/HESH | ✅ Complete | Surface detonation |
| Spalling | ✅ Complete | Caliber/angle/penetration aware |
| Deterministic RNG | ✅ Complete | Seed-based, reproducible |
| Validation | ✅ Complete | Post-init checks |


## Use Case

For small to medium games or simulations requiring a lightweight, quick-to-evaluate damage model on any actor (vehicle, structure, entity).  
The framework propagates and resolves damage with reasonable realism without real-time physics integration. 

## 1. Scope & Assumptions

A vehicle is modeled as a hierarchical assembly of armored plates (planar armor elements) and internal components.
A minimal vehicle resembles a minimal of six plates (front, back, top, bottom, left, right).  
The system resolves damage deterministically given only:

- Direction of impact
- Penetration force
- Ammunition type (AP, APFSDS, HE, HESH, HEAT)

### Impact Definition

| Parameter | Symbol | Description |
|-----------|--------|-------------|
| Penetration value | P (mm RHAe) | Capability at 0 degrees, standard ballistic measure |
| Ammunition type | T | AP, APFSDS, HE, HESH, or HEAT |
| Direction vector | d (unit) | Normalized travel direction |
| Impact point | P_hit (3D) | World-space coordinates |
| Caliber | C (mm) | Shell diameter |

**Core principle:** 
- Subtract armor thickness (scaled by material resistance) from penetration value.  
- No energy equations, no velocity integration.

## Unit System

| Quantity | Unit | Notes |
|----------|------|-------|
| P | mm RHAe | Penetration at 0 degrees |
| t | mm | Physical plate thickness |
| H | HP | Arbitrary; 100 HP ≈ failure after 2-3 penetrations |
| C | mm | Shell caliber for overmatch |
| Angles | degrees | Convert to radians only for trigonometric functions |

## Plate Definition

| Property | Symbol | Description |
|----------|--------|-------------|
| Thickness | t (mm) | Physical armor depth |
| Normal vector | n (unit) | Outward-facing direction |
| Health | H_p (HP) | Structural integrity |
| Material | m | Steel, aluminum, or composite |


## Early Testing

```text
python run.py
Pistol vs Car Door:
    AMMO        : PISTOL | P: 2mm | Cal: 9.0mm | Angle: 0°
    PLATE       : 1.0mm steel | Health: 50/50
    OUTCOME     : PENETRATED
    Residual    : 1.5mm
    Damage      : 14.4 HP
    New health  : 36 HP
Rifle AP vs Light Armor:
    AMMO        : RIFLE_BALL | P: 5mm | Cal: 5.56mm | Angle: 0°
    PLATE       : 8.0mm steel | Health: 100/100
    OUTCOME     : STOPPED
    Residual    : 0.0mm
    Damage      : 37.5 HP
    New health  : 62 HP
.50 cal vs APC Side (45°):
    AMMO        : HMGR_AP | P: 25mm | Cal: 12.7mm | Angle: 45°
    PLATE       : 25.0mm steel | Health: 150/150
    OUTCOME     : STOPPED
    Residual    : 0.0mm
    Damage      : 90.0 HP
    New health  : 60 HP
```

## Logic

Input: [`P_in`, `T`, `d`, `hit_point`, `caliber`, `shot_hash`, `roller`]:
```

                    │
                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. BACK-FACE CULL                                                           │
│    d = normalize(d)                                                         │
│    dot_dn = dot(d, normal)                                                  │
│    if dot_dn >= 0 → STOPPED (no damage, no residual)                        │
└─────────────────────────────────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 2. HE/HESH EARLY EXIT                                                       │
│    if T in (HE, HESH):                                                      │
│        damage = max_health * he_damage_scale                                │
│        → STOPPED (0 residual, fixed damage)                                 │
└─────────────────────────────────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 3. EFFECTIVE THICKNESS                                                      │
│    theta = acos(|dot_dn|) in degrees                                        │
│    theta_clamped = min(theta, 85°)                                          │
│    t_eff = thickness / cos(radians(theta_clamped))                          │
└─────────────────────────────────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 4. MULTI-HIT DEGRADATION                                                    │
│    if health < max_health:                                                  │
│        damage_ratio = 1 - (health / max_health)                             │
│        t_eff *= (1 - degradation_factor * damage_ratio)                     │
└─────────────────────────────────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 5. OVERMATCH                                                                │
│    if caliber > 0:                                                          │
│        R = caliber / t_eff                                                  │
│        if R > overmatch_threshold:                                          │
│            reduction = max(min_reduction, 1 - slope*(R - threshold))        │
│            t_eff *= reduction                                               │
│            overmatch_applied = True                                         │
└─────────────────────────────────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 6. RICOCHET                                                                 │
│    theta_ric = ricochet_angles[T]                                           │
│    p_ric = clamp((theta - theta_ric) / angle_window, 0, 1)                  │
│    if overmatch_applied:                                                    │
│        p_ric *= overmatch_ricochet_reduction                                │
│                                                                             │
│    if roller.roll(seed) < p_ric:                                            │
│        damage = surface_scuff_damage                                        │
│        → RICOCHET (0 residual, scuff damage)                                │
└─────────────────────────────────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 7. PENETRATION CHECK                                                        │
│    if P_in < t_eff:                                                         │
│        absorbed = min(P_in, t_eff)  # ← PROBLEM: absorbed = P_in always     │
│        damage = _plate_damage_from_absorption(absorbed)                     │
│        → STOPPED (0 residual, damage based on absorbed energy)              │
└─────────────────────────────────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 8. RESIDUAL & HEAT DECAY                                                    │
│    eta = resistance_matrix[T][material]                                     │
│    P_res = max(0, P_in - t_eff * eta)                                       │
│                                                                             │
│    if T == HEAT and air_gap > 0 and P_res > 0:                              │
│        P_res *= exp(-air_gap / heat_jet_decay_length)                       │
└─────────────────────────────────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 9. PLATE DAMAGE (PENETRATION CASE)                                          │
│    absorbed = t_eff * eta                                                   │
│    damage = _plate_damage_from_absorption(absorbed)                         │
│    → PENETRATED if P_res > 0 else STOPPED                                   │
└─────────────────────────────────────────────────────────────────────────────┘
```
