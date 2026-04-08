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
Dry test: plate=10.0mm, STEEL, P_in=9.0mm, PISTOL, cal=9.0mm
  Health |    t_eff  |    Outcome |  Damage  |      HP  | Spall Frags | Spall Vel
------------------------------------------------------------------------------------------
  100.0% |   10.00mm |    stopped |   43.2HP |  100.0HP |           2 |     80.0m/s [0]
   96.0% |    9.90mm |    stopped |   43.2HP |   96.0HP |           2 |     80.0m/s [1]
   92.0% |    9.87mm |    stopped |   43.2HP |   92.0HP |           2 |     80.0m/s [2]
   88.0% |    9.82mm |    stopped |   43.2HP |   88.0HP |           2 |     80.0m/s [3]
   84.0% |    9.75mm |    stopped |   43.2HP |   84.0HP |           2 |     80.0m/s [4]
   80.0% |    9.67mm |    stopped |   43.2HP |   80.0HP |           2 |     80.0m/s [5]
   76.0% |    9.56mm |    stopped |   43.2HP |   76.0HP |           2 |     80.0m/s [6]
   72.0% |    9.41mm |    stopped |   43.2HP |   72.0HP |           2 |     80.0m/s [7]
   68.0% |    9.23mm |    stopped |   43.2HP |   68.0HP |           2 |     80.0m/s [8]
   64.0% |    9.02mm |    stopped |   43.2HP |   64.0HP |           2 |     80.0m/s [9]
   60.0% |    8.76mm | penetrated |   42.0HP |   60.0HP |           3 |     80.0m/s [10]
   56.0% |    8.47mm | penetrated |   40.7HP |   56.0HP |           3 |     80.0m/s [11]
   52.0% |    8.16mm | penetrated |   39.2HP |   52.0HP |           3 |     80.0m/s [12]
   48.0% |    7.84mm | penetrated |   37.6HP |   48.0HP |           3 |     80.0m/s [13]
   44.0% |    7.53mm | penetrated |   36.1HP |   44.0HP |           3 |     80.0m/s [14]
   40.0% |    7.24mm | penetrated |   34.8HP |   40.0HP |           3 |     80.0m/s [15]
   36.0% |    6.98mm | penetrated |   33.5HP |   36.0HP |           3 |     80.0m/s [16]
   32.0% |    6.77mm | penetrated |   32.0HP |   32.0HP |           3 |     80.0m/s [17]
   28.0% |    6.59mm | penetrated |   28.0HP |   28.0HP |           4 |     80.0m/s [18]
   24.0% |    6.44mm | penetrated |   24.0HP |   24.0HP |           4 |     80.0m/s [19]
   20.0% |    6.33mm | penetrated |   20.0HP |   20.0HP |           4 |     80.0m/s [20]
   16.0% |    6.25mm | penetrated |   16.0HP |   16.0HP |           4 |     80.0m/s [21]
   12.0% |    6.18mm | penetrated |   12.0HP |   12.0HP |           4 |     80.0m/s [22]
    8.0% |    6.13mm | penetrated |    8.0HP |    8.0HP |           4 |     80.0m/s [23]
    4.0% |    6.10mm | penetrated |    4.0HP |    4.0HP |           4 |     80.0m/s [24]
    0.0% |    6.07mm | penetrated |    0.0HP |    0.0HP |           4 |     80.0m/s [25]
```

