"""
DRDM Calibration Suite
======================
Each test targets one specific step in Plate.hit() and verifies
the output against a value computed by hand from Config constants.

Not a fuzzer — every expected value is derived manually and documented
so you can re-derive it yourself if the config changes.

Run:
    python calibrate.py
"""

import math
import sys
from dataclasses import dataclass
from typing import Callable

from configuration import Config, AmmoType, Material
from components import Plate, Outcome, ConstantRoller

# ── Harness ────────────────────────────────────────────────────────────────

PASS = 0
FAIL = 0

@dataclass
class Result:
    name:    str
    ok:      bool
    detail:  str


def check(name: str, condition: bool, detail: str = "") -> Result:
    global PASS, FAIL
    tag = "PASS" if condition else "FAIL"
    if condition:
        PASS += 1
    else:
        FAIL += 1
    r = Result(name, condition, detail)
    status = f"  [{tag}] {name}"
    if not condition:
        status += f"\n         {detail}"
    print(status)
    return r


def approx(a: float, b: float, tol: float = 0.01) -> bool:
    """Absolute tolerance comparison."""
    return abs(a - b) <= tol


def section(title: str):
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")


# ── Plate factory ──────────────────────────────────────────────────────────

def make_plate(
    thickness: float,
    material:  Material = Material.STEEL,
    health:    float    = 100.0,
    max_hp:    float    = 100.0,
    air_gap:   float    = 0.0,
    config:    Config   = None,
) -> Plate:
    return Plate(
        thickness  = thickness,
        normal     = (0.0, 0.0, 1.0),   # faces +Z
        health     = health,
        max_health = max_hp,
        material   = material,
        air_gap    = air_gap,
        config     = config or Config(),
    )


NEVER_RICOCHET = ConstantRoller(0.0)
ALWAYS_RICOCHET = ConstantRoller(1.0)

D_NORMAL  = (0.0, 0.0, -1.0)   # dead-normal, 0°
HIT_POINT = (0.0, 0.0, 0.0)


def fire(plate: Plate, P_in: float, T: AmmoType, caliber: float,
         direction=D_NORMAL, roller=NEVER_RICOCHET, shot_hash: int = 0):
    return plate.hit(P_in, T, direction, HIT_POINT, caliber, shot_hash, roller)


# ══════════════════════════════════════════════════════════════════════════
# 1. BACK-FACE CULL  (step 1)
# ══════════════════════════════════════════════════════════════════════════

def test_backface_cull():
    section("1 · Back-face cull")
    cfg   = Config()
    plate = make_plate(20.0, config=cfg)

    # Shot traveling +Z hits the back of a +Z-normal plate — should be ignored.
    behind = (0.0, 0.0, 1.0)
    r = fire(plate, 150.0, AmmoType.APFSDS, 120.0, direction=behind)
    check("back-face shot: outcome is STOPPED",
          r.outcome == Outcome.STOPPED)
    check("back-face shot: no damage",
          r.plate_damage == 0.0 and r.new_health == plate.health)
    check("back-face shot: no residual",
          r.residual_penetration == 0.0)

    # Glancing shot (45°) still hits the front face.
    glance = (0.0, 0.707, -0.707)   # 45° elevation, still approaching front
    r2 = fire(plate, 9.0, AmmoType.PISTOL, 9.0, direction=glance)
    check("45° glance: outcome is not a back-face cull (damage > 0)",
          r2.plate_damage > 0.0)


# ══════════════════════════════════════════════════════════════════════════
# 2. HE / HESH EARLY-OUT  (step 2)
# ══════════════════════════════════════════════════════════════════════════

def test_he_hesh():
    section("2 · HE / HESH surface detonation")
    cfg   = Config()
    plate = make_plate(50.0, config=cfg)

    # HE damage = min(max_health * he_damage_scale, health) = 100 * 0.6 = 60
    expected_dmg = plate.max_health * cfg.he_damage_scale   # 60.0

    for T in (AmmoType.HE, AmmoType.HESH):
        r = fire(plate, 300.0, T, 105.0)
        check(f"{T.name}: outcome is STOPPED (surface det.)",
              r.outcome == Outcome.STOPPED)
        check(f"{T.name}: damage = {expected_dmg:.1f} HP",
              approx(r.plate_damage, expected_dmg),
              f"got {r.plate_damage}")
        check(f"{T.name}: no residual penetration",
              r.residual_penetration == 0.0)
        check(f"{T.name}: no spall (surface blast)",
              r.spall.fragment_count == 0)

    # HE on a half-health plate: clamped to remaining HP
    half = make_plate(50.0, health=40.0, config=cfg)
    r3 = fire(half, 300.0, AmmoType.HE, 105.0)
    check("HE on 40 HP plate: damage clamped to 40 HP",
          approx(r3.plate_damage, 40.0),
          f"got {r3.plate_damage}")
    check("HE on 40 HP plate: new_health = 0",
          r3.new_health == 0.0)


# ══════════════════════════════════════════════════════════════════════════
# 3. EFFECTIVE THICKNESS — ANGLE  (step 3)
# ══════════════════════════════════════════════════════════════════════════

def test_effective_thickness():
    section("3 · Effective thickness from impact angle")

    # At 60° from normal: t_eff = t / cos(60°) = t / 0.5 = 2t
    # IMPORTANT: caliber must be small enough to avoid triggering overmatch or shatter.
    # shatter_threshold = caliber/t_eff > 3.0 — use caliber=9mm (pistol-scale) to stay clear.
    # overmatch threshold = caliber/t_eff > 1.5 — 9/40 = 0.225, safe.
    cfg       = Config()
    thickness = 20.0
    plate     = make_plate(thickness, config=cfg)

    cos60 = 0.5
    sin60 = math.sqrt(3) / 2
    d_60  = (sin60, 0.0, -cos60)

    t_eff_expected = thickness / cos60   # 40.0mm

    # P_in=39.5 < 40.0 → must stop.
    # Use HEAT_JET: ricochet_angle=75° (> 60°, so no ricochet at 60°),
    # excluded from shatter check, caliber=40mm: 40/40=1.0 < overmatch threshold.
    r_stop = fire(plate, t_eff_expected - 0.5, AmmoType.HEAT_JET, 40.0, direction=d_60)
    check("60° angle: P_in=39.5 vs t_eff=40.0 → STOPPED",
          r_stop.outcome == Outcome.STOPPED,
          f"got {r_stop.outcome}")

    # P_in=40.5 > 40.0 → must penetrate
    r_pen = fire(plate, t_eff_expected + 0.5, AmmoType.HEAT_JET, 40.0, direction=d_60)
    check("60° angle: P_in=40.5 vs t_eff=40.0 → PENETRATED",
          r_pen.outcome == Outcome.PENETRATED,
          f"got {r_pen.outcome}")

    # At 0°: t_eff = thickness. P_in just below → stopped.
    # Use small caliber again: 5.56/20 = 0.278, no overmatch or shatter.
    r_normal = fire(plate, thickness - 0.1, AmmoType.RIFLE_AP, 5.56)
    check("0° angle: P_in just below thickness → STOPPED",
          r_normal.outcome == Outcome.STOPPED,
          f"got {r_normal.outcome}")


# ══════════════════════════════════════════════════════════════════════════
# 4. MULTI-HIT DEGRADATION  (step 4)
# ══════════════════════════════════════════════════════════════════════════

def test_degradation():
    section("4 · Multi-hit degradation (sigmoid)")
    cfg = Config()
    # degradation_factor=0.4, steepness=8.0
    # At 100% health: no degradation applied → t_eff = thickness
    # At 0% health:
    #   damage_ratio = 1.0
    #   x = (1.0 - 0.5) * 8.0 = 4.0
    #   s = 1 / (1 + exp(-4)) ≈ 0.9820
    #   t_eff = thickness * (1 - 0.4 * 0.9820) = thickness * 0.6072 ≈ 18.2mm
    #
    # NOTE: use RIFLE_AP (5.56mm caliber) throughout.
    #   caliber/t_eff is always < 3.0 (shatter) and < 1.5 (overmatch) for a 30mm plate.
    #   This keeps the shatter and overmatch steps from interfering with degradation checks.

    thickness  = 30.0
    full_plate = make_plate(thickness, health=100.0, config=cfg)
    dead_plate = make_plate(thickness, health=0.01,  max_hp=100.0, config=cfg)

    # At full health: no degradation. P_in just below thickness must stop.
    r_full = fire(full_plate, thickness - 0.1, AmmoType.RIFLE_AP, 5.56)
    check("full health: t_eff = thickness, P_in just below → STOPPED",
          r_full.outcome == Outcome.STOPPED,
          f"got {r_full.outcome}")

    # At near-zero health: t_eff ≈ 30 * 0.607 ≈ 18.2mm → P_in=20 penetrates
    r_dead = fire(dead_plate, 20.0, AmmoType.RIFLE_AP, 5.56)
    check("near-zero health: degraded t_eff ≈ 18.2mm, P_in=20 → PENETRATED",
          r_dead.outcome == Outcome.PENETRATED,
          f"got {r_dead.outcome}")

    # Sigmoid midpoint: at 50% health, damage_ratio=0.5
    # x = (0.5-0.5)*8 = 0, s = 0.5
    # t_eff = 30 * (1 - 0.4*0.5) = 30 * 0.8 = 24.0
    half_plate = make_plate(thickness, health=50.0, config=cfg)
    r_half_stop = fire(half_plate, 23.0, AmmoType.RIFLE_AP, 5.56)
    r_half_pen  = fire(half_plate, 25.0, AmmoType.RIFLE_AP, 5.56)
    check("50% health: P_in=23 < t_eff≈24 → STOPPED",
          r_half_stop.outcome == Outcome.STOPPED,
          f"got {r_half_stop.outcome}")
    check("50% health: P_in=25 > t_eff≈24 → PENETRATED",
          r_half_pen.outcome == Outcome.PENETRATED,
          f"got {r_half_pen.outcome}")


# ══════════════════════════════════════════════════════════════════════════
# 5. OVERMATCH  (step 5)
# ══════════════════════════════════════════════════════════════════════════

def test_overmatch():
    section("5 · Overmatch")
    # overmatch_threshold=1.5, min_reduction=0.6, slope=0.2
    # A 120mm shell against a 50mm plate: R = 120/50 = 2.4 > 1.5
    # reduction = max(0.6, 1.0 - 0.2 * (2.4 - 1.5)) = max(0.6, 1.0 - 0.18) = max(0.6, 0.82) = 0.82
    # t_eff after overmatch = 50 * 0.82 = 41.0mm
    cfg   = Config()
    plate = make_plate(50.0, config=cfg)

    # Without overmatch: P_in=45 < t_eff=50 → STOPPED
    r_no_om = fire(plate, 45.0, AmmoType.APFSDS, 10.0)   # 10mm caliber: R=10/50=0.2, no overmatch
    check("no overmatch (small caliber): P_in=45 < t_eff=50 → STOPPED",
          r_no_om.outcome == Outcome.STOPPED,
          f"got {r_no_om.outcome}")

    # With overmatch: t_eff reduces to ~41mm → P_in=45 now penetrates
    r_om = fire(plate, 45.0, AmmoType.APFSDS, 120.0)
    check("overmatch (120mm vs 50mm plate): P_in=45 > t_eff≈41 → PENETRATED",
          r_om.outcome == Outcome.PENETRATED,
          f"got {r_om.outcome}")

    # Extreme overmatch — reduction floored at min_reduction=0.6
    # R = 300/50 = 6.0 → reduction = max(0.6, 1.0 - 0.2*(6.0-1.5)) = max(0.6, 0.1) = 0.6
    # t_eff = 50 * 0.6 = 30.0
    # HOWEVER: caliber/t_eff = 300/30 = 10.0 > shatter_threshold=3.0 and ammo is APFSDS
    # so this triggers SHATTER, not clean PENETRATED. Outcome is SHATTERED with P_res>0.
    r_extreme = fire(plate, 31.0, AmmoType.APFSDS, 300.0)
    check("extreme overmatch + shatter: outcome is SHATTERED (caliber/t_eff >> 3.0)",
          r_extreme.outcome == Outcome.SHATTERED,
          f"got {r_extreme.outcome}")
    check("shattered round still carries residual (20% of P_in = 6.2)",
          approx(r_extreme.residual_penetration, 31.0 * 0.2, tol=0.5),
          f"got {r_extreme.residual_penetration:.2f}")


# ══════════════════════════════════════════════════════════════════════════
# 6. RICOCHET  (step 6)
# ══════════════════════════════════════════════════════════════════════════

def test_ricochet():
    section("6 · Ricochet")
    cfg = Config()
    # AP ricochet_angle = 68°, window = 12°
    # At theta=80°: p_ric = (80-68)/12 = 1.0 (certain ricochet with roller≥1.0)
    # At theta=60°: p_ric = (60-68)/12 = negative → clamped to 0.0 (never ricochet)

    # direction for theta≈80°: dot(d,n) = -cos(80°) ≈ -0.1736
    # d = (sin80, 0, -cos80) = (0.9848, 0, -0.1736)
    d_80 = (math.sin(math.radians(80)), 0.0, -math.cos(math.radians(80)))
    d_60 = (math.sin(math.radians(60)), 0.0, -math.cos(math.radians(60)))

    plate = make_plate(30.0, config=cfg)

    # Certain ricochet at 80° — ricochet condition is roller < p_ric (strict less-than).
    # p_ric=1.0, so roller must be < 1.0. Use 0.99.
    r_ric = fire(plate, 200.0, AmmoType.AP, 105.0, direction=d_80, roller=ConstantRoller(0.99))
    check("AP at 80°: roller=0.99 < p_ric=1.0 → RICOCHET",
          r_ric.outcome == Outcome.RICOCHET,
          f"got {r_ric.outcome}")
    check("ricochet: residual_penetration = 0",
          r_ric.residual_penetration == 0.0)
    check("ricochet: small scuff damage only (≤ surface_scuff_damage=5.0)",
          r_ric.plate_damage <= cfg.surface_scuff_damage,
          f"got {r_ric.plate_damage}")

    # Never ricochet at 60° (below threshold) even with ALWAYS_RICOCHET roller
    r_no_ric = fire(plate, 200.0, AmmoType.AP, 105.0, direction=d_60, roller=ALWAYS_RICOCHET)
    check("AP at 60°: below ricochet threshold → not RICOCHET",
          r_no_ric.outcome != Outcome.RICOCHET,
          f"got {r_no_ric.outcome}")

    # FRAGMENT never ricochets regardless of angle or roller
    r_frag = fire(plate, 30.0, AmmoType.FRAGMENT, 10.0, direction=d_80, roller=ALWAYS_RICOCHET)
    check("FRAGMENT at 80°: ricochet step skipped → not RICOCHET",
          r_frag.outcome != Outcome.RICOCHET,
          f"got {r_frag.outcome}")


# ══════════════════════════════════════════════════════════════════════════
# 7. PENETRATION RESIDUAL  (step 9)
# ══════════════════════════════════════════════════════════════════════════

def test_residual_penetration():
    section("7 · Residual penetration (η matrix)")
    cfg = Config()

    # To isolate the η matrix we need caliber small enough to avoid overmatch AND shatter.
    # overmatch: caliber/t_eff > 1.5 → with t=20mm, caliber must be < 30mm
    # shatter:   caliber/t_eff > 3.0 → with t=20mm, caliber must be < 60mm
    # Use caliber=5.56mm (RIFLE_AP) — 5.56/20 = 0.278, both steps skipped.

    # RIFLE_AP vs STEEL: η = 1.0  → P_res = 50 - 20*1.0 = 30.0
    plate = make_plate(20.0, Material.STEEL, config=cfg)
    r = fire(plate, 50.0, AmmoType.RIFLE_AP, 5.56)
    check("RIFLE_AP/STEEL: P_res = 50 - 20*1.0 = 30.0",
          approx(r.residual_penetration, 30.0, tol=0.5),
          f"got {r.residual_penetration:.2f}")

    # RIFLE_AP vs COMPOSITE: η = 1.0 → P_res = 50 - 20*1.0 = 30.0
    plate_c = make_plate(20.0, Material.COMPOSITE, config=cfg)
    r_c = fire(plate_c, 50.0, AmmoType.RIFLE_AP, 5.56)
    eta_c = cfg.resistance_matrix[AmmoType.RIFLE_AP][Material.COMPOSITE]  # 1.0
    expected_c = max(0.0, 50.0 - 20.0 * eta_c)
    check(f"RIFLE_AP/COMPOSITE: P_res = 50 - 20*{eta_c} = {expected_c:.1f}",
          approx(r_c.residual_penetration, expected_c, tol=0.5),
          f"got {r_c.residual_penetration:.2f}")

    # RIFLE_SLAP vs COMPOSITE: η = 1.1 → P_res = 50 - 20*1.1 = 28.0
    # caliber=7.62mm: 7.62/20 = 0.381, no overmatch or shatter
    eta_slap = cfg.resistance_matrix[AmmoType.RIFLE_SLAP][Material.COMPOSITE]  # 1.1
    expected_slap = max(0.0, 50.0 - 20.0 * eta_slap)
    r_slap = fire(plate_c, 50.0, AmmoType.RIFLE_SLAP, 7.62)
    check(f"RIFLE_SLAP/COMPOSITE: P_res = 50 - 20*{eta_slap} = {expected_slap:.1f}",
          approx(r_slap.residual_penetration, expected_slap, tol=0.5),
          f"got {r_slap.residual_penetration:.2f}")

    # Barely penetrates: P_in = t_eff + epsilon → P_res ≈ epsilon * η
    plate2 = make_plate(20.0, Material.STEEL, config=cfg)
    eta_rif = cfg.resistance_matrix[AmmoType.RIFLE_AP][Material.STEEL]  # 1.0
    r_barely = fire(plate2, 20.1, AmmoType.RIFLE_AP, 5.56)
    check("barely penetrates: P_res ≈ 0.1",
          approx(r_barely.residual_penetration, 0.1, tol=0.15),
          f"got {r_barely.residual_penetration:.3f}")
    check("barely penetrates: outcome PENETRATED",
          r_barely.outcome == Outcome.PENETRATED,
          f"got {r_barely.outcome}")

    # P_in exactly equals t_eff: fully absorbed, stopped
    r_exact = fire(plate2, 20.0, AmmoType.RIFLE_AP, 5.56)
    check("P_in == t_eff: STOPPED, P_res=0",
          r_exact.outcome == Outcome.STOPPED and r_exact.residual_penetration == 0.0,
          f"outcome={r_exact.outcome}, P_res={r_exact.residual_penetration}")


# ══════════════════════════════════════════════════════════════════════════
# 8. PLATE DAMAGE  (step 10)
# ══════════════════════════════════════════════════════════════════════════

def test_plate_damage():
    section("8 · Plate damage from absorption")
    cfg = Config()
    # energy_to_hp_scale=0.6, material_hardness[STEEL]=1.0
    # _plate_max_energy = thickness * hardness = 10.0 * 1.0 = 10.0
    # Stopped shot: absorbed = P_in = 9.0
    # ratio = 9/10 = 0.9 → damage = 100 * 0.6 * 0.9 = 54.0

    plate = make_plate(10.0, Material.STEEL, health=100.0, config=cfg)
    r = fire(plate, 9.0, AmmoType.PISTOL, 9.0)
    check("stopped: damage = max_hp * 0.6 * (P_in/t_max) = 54.0 HP",
          approx(r.plate_damage, 54.0),
          f"got {r.plate_damage}")

    # Aluminum: hardness=0.5, max_energy = 10*0.5 = 5.0
    # P_in=4 stopped: ratio=4/5=0.8 → damage = 100*0.6*0.8 = 48.0
    plate_al = make_plate(10.0, Material.ALUMINUM, health=100.0, config=cfg)
    r_al = fire(plate_al, 4.0, AmmoType.PISTOL, 9.0)
    check("ALUMINUM stopped: damage = 100*0.6*(4/5) = 48.0 HP",
          approx(r_al.plate_damage, 48.0),
          f"got {r_al.plate_damage}")

    # Overkill: ratio > 1 → clamped to 2.0 → max damage = 100*0.6*2 = 120 → clamped to 100
    plate2 = make_plate(5.0, Material.STEEL, health=100.0, config=cfg)
    r_ok = fire(plate2, 500.0, AmmoType.APFSDS, 120.0)
    check("overkill: damage clamped to max_health (100 HP)",
          approx(r_ok.plate_damage, 100.0),
          f"got {r_ok.plate_damage}")

    # Damage can never exceed current health
    plate3 = make_plate(10.0, Material.STEEL, health=10.0, max_hp=100.0, config=cfg)
    r_low = fire(plate3, 9.0, AmmoType.PISTOL, 9.0)
    check("damage clamped to current health (10 HP)",
          approx(r_low.plate_damage, 10.0) and r_low.new_health == 0.0,
          f"damage={r_low.plate_damage}, new_health={r_low.new_health}")


# ══════════════════════════════════════════════════════════════════════════
# 9. SPALL THRESHOLD AND FRAGMENT COUNT
# ══════════════════════════════════════════════════════════════════════════

def test_spall():
    section("9 · Spall generation")
    cfg = Config()  # spall_threshold=0.7

    # penetration_ratio = P_in / t_eff
    # At 0°, t_eff = thickness. For a stopped shot, P_in < t_eff.
    # Below threshold (0.7): ratio = 0.5 → no spall
    plate = make_plate(20.0, config=cfg)
    r_low = fire(plate, 10.0, AmmoType.AP, 105.0)   # ratio = 10/20 = 0.5
    check("ratio=0.5 < threshold=0.7: no spall",
          r_low.spall.fragment_count == 0,
          f"got {r_low.spall.fragment_count} frags")

    # Above threshold: ratio = 0.8 → spall expected
    r_high = fire(plate, 16.0, AmmoType.AP, 105.0)   # ratio = 16/20 = 0.8
    check("ratio=0.8 > threshold=0.7: spall generated",
          r_high.spall.fragment_count > 0,
          f"got {r_high.spall.fragment_count} frags")

    # FRAGMENT type: threshold halved to 0.35 — produces spall at lower ratios
    r_frag = fire(plate, 8.0, AmmoType.FRAGMENT, 10.0)   # ratio=0.4, normally below threshold
    check("FRAGMENT: halved threshold → spall at ratio=0.4",
          r_frag.spall.fragment_count > 0,
          f"got {r_frag.spall.fragment_count} frags")

    # Pistol hard cap: max 3 fragments
    plate_thin = make_plate(5.0, config=cfg)
    r_pist = fire(plate_thin, 4.5, AmmoType.PISTOL, 9.0)   # ratio=0.9 → above threshold
    check("PISTOL: fragment count hard-capped at 3",
          r_pist.spall.fragment_count <= 3,
          f"got {r_pist.spall.fragment_count} frags")

    # Pistol velocity hard cap: ≤ 80 m/s
    check("PISTOL: max_velocity ≤ 80 m/s",
          r_pist.spall.max_velocity <= 80.0,
          f"got {r_pist.spall.max_velocity}")

    # Dead-normal (0°) should produce wider cone than oblique (45°)
    d_45 = (math.sin(math.radians(45)), 0.0, -math.cos(math.radians(45)))
    plate2 = make_plate(30.0, config=cfg)
    r_0   = fire(plate2, 25.0, AmmoType.HMGR_AP, 12.7)
    r_45  = fire(plate2, 25.0, AmmoType.HMGR_AP, 12.7, direction=d_45)
    check("dead-normal cone > oblique cone (wider at 0°)",
          r_0.spall.cone_half_angle >= r_45.spall.cone_half_angle,
          f"0°={r_0.spall.cone_half_angle}° vs 45°={r_45.spall.cone_half_angle}°")


# ══════════════════════════════════════════════════════════════════════════
# 10. HEAT / EFP AIR-GAP DECAY  (step 9, shaped charges)
# ══════════════════════════════════════════════════════════════════════════

def test_air_gap_decay():
    section("10 · HEAT / EFP air-gap decay")
    cfg = Config()
    # heat_jet_decay_length = 200mm, efp_decay_length = 400mm
    #
    # IMPORTANT: use a thick plate so overmatch doesn't silently change t_eff.
    # overmatch triggers when caliber/t_eff > 1.5.
    # For HEAT (105mm caliber): t_eff must be > 70mm to avoid overmatch.
    # Use thickness=100mm, P_in=150 to guarantee penetration even after full decay.
    #
    # HEAT/STEEL η=0.85:
    # no-gap:  P_res = 150 - 100*0.85 = 65.0
    # gap=200: P_res = 65.0 * exp(-200/200) = 65.0 * exp(-1) ≈ 23.91

    plate_no_gap = make_plate(100.0, Material.STEEL, air_gap=0.0, config=cfg)
    r_no_gap = fire(plate_no_gap, 150.0, AmmoType.HEAT, 105.0)
    eta_heat = cfg.resistance_matrix[AmmoType.HEAT][Material.STEEL]
    expected_no_gap = 150.0 - 100.0 * eta_heat   # 65.0
    check(f"HEAT, no air gap: P_res = 150 - 100*{eta_heat} = {expected_no_gap:.1f}",
          approx(r_no_gap.residual_penetration, expected_no_gap, tol=0.5),
          f"got {r_no_gap.residual_penetration:.2f}")

    plate_gap = make_plate(100.0, Material.STEEL, air_gap=200.0, config=cfg)
    r_gap = fire(plate_gap, 150.0, AmmoType.HEAT, 105.0)
    expected_gap = expected_no_gap * math.exp(-1)   # ≈ 23.91
    check(f"HEAT, air_gap=200mm: P_res ≈ {expected_gap:.2f} (×exp(-1))",
          approx(r_gap.residual_penetration, expected_gap, tol=1.0),
          f"got {r_gap.residual_penetration:.2f}")

    # EFP decays slower (decay_length=400mm):
    # EFP/STEEL η=0.95: base P_res = 150 - 100*0.95 = 55.0
    # after 200mm gap: 55.0 * exp(-200/400) = 55.0 * exp(-0.5) ≈ 33.35
    eta_efp = cfg.resistance_matrix[AmmoType.EFP][Material.STEEL]
    base_efp = 150.0 - 100.0 * eta_efp
    expected_efp = base_efp * math.exp(-200.0 / cfg.efp_decay_length)
    plate_efp = make_plate(100.0, Material.STEEL, air_gap=200.0, config=cfg)
    r_efp = fire(plate_efp, 150.0, AmmoType.EFP, 120.0)
    check(f"EFP, air_gap=200mm: P_res ≈ {expected_efp:.2f}",
          approx(r_efp.residual_penetration, expected_efp, tol=1.0),
          f"got {r_efp.residual_penetration:.2f}")

    # AP is NOT decayed by air gap.
    # RIFLE_AP/STEEL η=1.0, caliber=5.56mm: no overmatch on 100mm plate.
    # P_res = 150 - 100*1.0 = 50.0, unaffected by gap.
    eta_ap = cfg.resistance_matrix[AmmoType.RIFLE_AP][Material.STEEL]
    base_ap = 150.0 - 100.0 * eta_ap
    plate_ap = make_plate(100.0, Material.STEEL, air_gap=200.0, config=cfg)
    r_ap = fire(plate_ap, 150.0, AmmoType.RIFLE_AP, 5.56)
    check(f"RIFLE_AP: air gap has no effect on residual (expect {base_ap:.1f})",
          approx(r_ap.residual_penetration, base_ap, tol=0.5),
          f"got {r_ap.residual_penetration:.2f}")


# ══════════════════════════════════════════════════════════════════════════
# 11. MULTI-HIT SEQUENCE (state accumulation)
# ══════════════════════════════════════════════════════════════════════════

def test_multi_hit_sequence():
    section("11 · Multi-hit sequence (state commit)")
    cfg   = Config()
    plate = make_plate(20.0, Material.STEEL, health=100.0, config=cfg)
    # P_in=18 < t_eff=20 → always stopped at full health.
    # Each hit: absorbed=18, max_energy=20, ratio=0.9, damage=100*0.6*0.9=54 HP → 100→46
    # After hit 1: health=46. t_eff now slightly degraded.
    # P_in=18 should still be stopped (t_eff still above 18 at ~46% health).

    r1 = fire(plate, 18.0, AmmoType.AP, 10.0)
    check("hit 1: STOPPED, damage=54",
          r1.outcome == Outcome.STOPPED and approx(r1.plate_damage, 54.0),
          f"outcome={r1.outcome}, dmg={r1.plate_damage}")
    plate.health = r1.new_health   # commit → health=46

    # After hit 1: health=46, damage_ratio=0.54
    # x=(0.54-0.5)*8=0.32, s≈0.579, t_eff=20*(1-0.4*0.579)=15.37mm
    # P_in=18 > 15.37 → PENETRATED (degradation curve has already crossed threshold)
    r2 = fire(plate, 18.0, AmmoType.AP, 10.0)
    check("hit 2: plate degraded to t_eff≈15.4mm, P_in=18 now PENETRATES",
          r2.outcome == Outcome.PENETRATED,
          f"got {r2.outcome} at health={plate.health}")
    plate.health = r2.new_health

    # Use P_in=14 to show plate still stops lighter rounds at moderate damage
    plate_mod = make_plate(20.0, Material.STEEL, health=46.0, config=cfg)
    r_light = fire(plate_mod, 14.0, AmmoType.AP, 10.0)
    check("hit 2 (light round P_in=14): still STOPPED vs t_eff≈15.4mm",
          r_light.outcome == Outcome.STOPPED,
          f"got {r_light.outcome}")

    # Deplete health further to force penetration
    plate.health = 5.0   # near-destroyed
    r_pen = fire(plate, 18.0, AmmoType.AP, 10.0)
    check("near-destroyed plate: P_in=18 eventually penetrates",
          r_pen.outcome == Outcome.PENETRATED,
          f"got {r_pen.outcome} at health={plate.health}")

    # After health=0: damage must be 0, no further HP loss
    plate.health = r_pen.new_health
    r_zero = fire(plate, 18.0, AmmoType.AP, 10.0)
    check("destroyed plate (0 HP): damage=0, health stays 0",
          r_zero.plate_damage == 0.0 and r_zero.new_health == 0.0,
          f"damage={r_zero.plate_damage}, health={r_zero.new_health}")


# ══════════════════════════════════════════════════════════════════════════
# 12. CONTRACT: HitResult invariants
# ══════════════════════════════════════════════════════════════════════════

def test_hit_result_contracts():
    section("12 · HitResult contracts (all ammo / all materials)")
    cfg   = Config()
    AMMOS = [AmmoType.AP, AmmoType.APFSDS, AmmoType.HEAT, AmmoType.HE,
             AmmoType.HESH, AmmoType.PISTOL, AmmoType.RIFLE_BALL,
             AmmoType.RIFLE_AP, AmmoType.HMGR_AP, AmmoType.GRENADE,
             AmmoType.FRAGMENT, AmmoType.HEAT_JET, AmmoType.EFP]
    MATS  = [Material.STEEL, Material.ALUMINUM, Material.COMPOSITE]

    from configuration import TYPICAL_PENETRATION, TYPICAL_CALIBER

    violations = []
    for T in AMMOS:
        P_in   = TYPICAL_PENETRATION.get(T, 30.0)
        caliber = TYPICAL_CALIBER.get(T, 20.0)
        for M in MATS:
            plate = make_plate(15.0, M, health=100.0, config=cfg)
            r = fire(plate, P_in, T, caliber)

            if r.new_health < 0.0 or r.new_health > plate.max_health:
                violations.append(f"{T.name}/{M.name}: new_health={r.new_health:.2f} out of range")
            if r.plate_damage < 0.0:
                violations.append(f"{T.name}/{M.name}: plate_damage={r.plate_damage:.2f} negative")
            if r.residual_penetration < 0.0:
                violations.append(f"{T.name}/{M.name}: residual={r.residual_penetration:.2f} negative")
            if r.outcome == Outcome.PENETRATED and r.residual_penetration == 0.0:
                violations.append(f"{T.name}/{M.name}: PENETRATED but residual=0")
            if r.outcome == Outcome.STOPPED and r.residual_penetration > 0.0:
                violations.append(f"{T.name}/{M.name}: STOPPED but residual>0")
            if not math.isclose(r.new_health, plate.health - r.plate_damage, abs_tol=0.01):
                violations.append(f"{T.name}/{M.name}: new_health != health - damage")

    check("all ammo×material combos: HitResult invariants hold",
          len(violations) == 0,
          "\n         " + "\n         ".join(violations) if violations else "")


# ── Runner ─────────────────────────────────────────────────────────────────

def run_all():
    print("\nDRDM Calibration")
    print("=" * 60)

    test_backface_cull()
    test_he_hesh()
    test_effective_thickness()
    test_degradation()
    test_overmatch()
    test_ricochet()
    test_residual_penetration()
    test_plate_damage()
    test_spall()
    test_air_gap_decay()
    test_multi_hit_sequence()
    test_hit_result_contracts()

    print(f"\n{'=' * 60}")
    total = PASS + FAIL
    print(f"  {PASS}/{total} passed  |  {FAIL} failed")
    print(f"{'=' * 60}\n")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    run_all()