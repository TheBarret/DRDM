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

# Graphs

<img width="1024" src="https://github.com/user-attachments/assets/c22362e3-2ecc-4af8-a694-49d8474a0b96" />
<img width="1024" src="https://github.com/user-attachments/assets/eb712859-8310-4363-b4c6-f6347f273c74" />

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
Dry test: plate=8.0mm, STEEL, P_in=5.56mm, RIFLE_BALL, cal=5.56mm
  Health |    t_eff  |    Outcome |  Damage  |      HP  | Spall Frags | Spall Vel
------------------------------------------------------------------------------------------
  100.0% |    8.00mm |    stopped |   41.7HP |   58.3HP |           0 |      0.0m/s
   97.5% |    7.93mm |    stopped |   41.7HP |   55.8HP |           2 |    240.2m/s
   95.0% |    7.91mm |    stopped |   41.7HP |   53.3HP |           2 |    240.5m/s
   92.5% |    7.90mm |    stopped |   41.7HP |   50.8HP |           2 |    240.8m/s
   90.0% |    7.87mm |    stopped |   41.7HP |   48.3HP |           2 |    241.2m/s
   87.5% |    7.85mm |    stopped |   41.7HP |   45.8HP |           2 |    241.7m/s
   85.0% |    7.82mm |    stopped |   41.7HP |   43.3HP |           2 |    242.3m/s
   82.5% |    7.78mm |    stopped |   41.7HP |   40.8HP |           2 |    243.0m/s
   80.0% |    7.73mm |    stopped |   41.7HP |   38.3HP |           2 |    243.8m/s
   77.5% |    7.68mm |    stopped |   41.7HP |   35.8HP |           2 |    244.8m/s
   75.0% |    7.62mm |    stopped |   41.7HP |   33.3HP |           2 |    246.0m/s
   72.5% |    7.55mm |    stopped |   41.7HP |   30.8HP |           2 |    247.4m/s
   70.0% |    7.46mm |    stopped |   41.7HP |   28.3HP |           2 |    249.0m/s
   67.5% |    7.37mm |    stopped |   41.7HP |   25.8HP |           2 |    250.9m/s
   65.0% |    7.26mm |    stopped |   41.7HP |   23.3HP |           2 |    253.2m/s
   62.5% |    7.14mm |    stopped |   41.7HP |   20.8HP |           2 |    255.8m/s
   60.0% |    7.01mm |    stopped |   41.7HP |   18.3HP |           2 |    258.7m/s
   57.5% |    6.87mm |    stopped |   41.7HP |   15.8HP |           2 |    262.0m/s
   55.0% |    6.72mm |    stopped |   41.7HP |   13.3HP |           2 |    265.6m/s
   52.5% |    6.56mm |    stopped |   41.7HP |   10.8HP |           2 |    269.5m/s
   50.0% |    6.40mm |    stopped |   41.7HP |    8.3HP |           2 |    273.8m/s
   47.5% |    6.24mm |    stopped |   41.7HP |    5.8HP |           2 |    278.2m/s
   45.0% |    6.08mm |    stopped |   41.7HP |    3.3HP |           2 |    282.8m/s
   42.5% |    5.93mm |    stopped |   41.7HP |    0.8HP |           2 |    287.4m/s
   40.0% |    5.79mm |    stopped |   40.0HP |    0.0HP |           2 |    292.0m/s
   37.5% |    5.66mm |    stopped |   37.5HP |    0.0HP |           2 |    296.4m/s
   35.0% |    5.54mm | penetrated |   35.0HP |    0.0HP |           3 |    300.7m/s
   32.5% |    5.43mm | penetrated |   32.5HP |    0.0HP |           3 |    304.7m/s
   30.0% |    5.34mm | penetrated |   30.0HP |    0.0HP |           3 |    308.3m/s
   27.5% |    5.25mm | penetrated |   27.5HP |    0.0HP |           3 |    311.7m/s
   25.0% |    5.18mm | penetrated |   25.0HP |    0.0HP |           3 |    314.6m/s
   22.5% |    5.12mm | penetrated |   22.5HP |    0.0HP |           3 |    317.2m/s
   20.0% |    5.07mm | penetrated |   20.0HP |    0.0HP |           3 |    319.5m/s
   17.5% |    5.02mm | penetrated |   17.5HP |    0.0HP |           3 |    321.5m/s
   15.0% |    4.98mm | penetrated |   15.0HP |    0.0HP |           3 |    323.1m/s
   12.5% |    4.95mm | penetrated |   12.5HP |    0.0HP |           3 |    324.6m/s
   10.0% |    4.93mm | penetrated |   10.0HP |    0.0HP |           3 |    325.8m/s
    7.5% |    4.90mm | penetrated |    7.5HP |    0.0HP |           3 |    326.8m/s
    5.0% |    4.89mm | penetrated |    5.0HP |    0.0HP |           3 |    327.6m/s
    2.5% |    4.87mm | penetrated |    2.5HP |    0.0HP |           3 |    328.3m/s
    0.0% |    4.86mm | penetrated |    0.0HP |    0.0HP |           3 |    328.9m/s
```

