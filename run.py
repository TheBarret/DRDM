"""
DRDM — Plate Unit Tests
Targets: plate.py revision 2

Run:  python -m pytest test_plate.py -v
  or: python test_plate.py
"""

import math
import time
import unittest

from plate import (
    AmmoType,
    Config,
    ConstantRoller,
    Material,
    Outcome,
    Plate,
    SeededRoller,
)

# ── Helpers ────────────────────────────────────────────────────────────────

def make_plate(
    thickness: float = 100.0,
    normal: tuple = (0.0, 0.0, 1.0),
    health: float = 100.0,
    max_health: float = None,
    material: Material = Material.STEEL,
    air_gap: float = 0.0,
    config: Config = None,
) -> Plate:
    return Plate(
        thickness=thickness,
        normal=normal,
        health=health,
        max_health=max_health if max_health is not None else health,
        material=material,
        air_gap=air_gap,
        config=config or Config(),
    )


def fire(
    plate: Plate,
    P_in: float = 200.0,
    T: AmmoType = AmmoType.AP,
    d: tuple = (0.0, 0.0, -1.0),
    caliber: float = 30.0,
    shot_hash: int = 1,
    roller=None,
):
    """Single shot helper. Defaults: AP, head-on, 30mm caliber."""
    return plate.hit(
        P_in=P_in,
        T=T,
        d=d,
        hit_point=(0.0, 0.0, 0.0),
        caliber=caliber,
        shot_hash=shot_hash,
        roller=roller or ConstantRoller(0.0),   # no ricochet by default
    )


def commit(plate: Plate, result) -> None:
    """Apply a HitResult to the plate (explicit commit pattern)."""
    plate.health = result.new_health


# ── Direction helpers ──────────────────────────────────────────────────────

def dir_at_angle(deg: float) -> tuple:
    """
    Unit vector traveling in -Z with a Y-axis lean of `deg` degrees.
    0°  → straight-on  (0, 0, -1)
    60° → angled       (0, sin60, -cos60)
    """
    r = math.radians(deg)
    return (0.0, math.sin(r), -math.cos(r))

# 1. API contract

class TestHitResultContract(unittest.TestCase):
    """hit() must return an immutable HitResult and never mutate the plate."""

    def test_returns_hit_result_fields(self):
        plate = make_plate()
        result = fire(plate)
        self.assertTrue(hasattr(result, "residual_penetration"))
        self.assertTrue(hasattr(result, "plate_damage"))
        self.assertTrue(hasattr(result, "outcome"))
        self.assertTrue(hasattr(result, "new_health"))

    def test_hit_does_not_mutate_health(self):
        plate = make_plate(health=100.0)
        original_health = plate.health
        fire(plate, P_in=500.0)          # would penetrate
        self.assertEqual(plate.health, original_health, 
                         "hit() must not mutate plate.health — caller must commit")

    def test_commit_applies_damage(self):
        plate = make_plate(health=100.0)
        result = fire(plate, P_in=500.0)
        commit(plate, result)
        self.assertLess(plate.health, 100.0)

    def test_hit_result_is_immutable(self):
        plate = make_plate()
        result = fire(plate)
        with self.assertRaises((AttributeError, TypeError)):
            result.plate_damage = 999.0   # frozen dataclass must reject this

    def test_new_health_never_negative(self):
        plate = make_plate(health=1.0)
        result = fire(plate, P_in=10000.0)
        self.assertGreaterEqual(result.new_health, 0.0)

    def test_residual_never_negative(self):
        plate = make_plate(thickness=500.0)
        result = fire(plate, P_in=50.0)
        self.assertGreaterEqual(result.residual_penetration, 0.0)

# 2. Back-face culling

class TestBackfaceCulling(unittest.TestCase):

    def test_shot_from_behind_is_ignored(self):
        plate = make_plate(normal=(0, 0, 1))
        result = fire(plate, d=(0, 0, 1))   # same direction as normal → behind
        self.assertEqual(result.outcome, Outcome.STOPPED)
        self.assertEqual(result.residual_penetration, 0.0)
        self.assertEqual(result.plate_damage, 0.0)
        self.assertEqual(result.new_health, plate.health)

    def test_perpendicular_shot_hits(self):
        plate = make_plate(normal=(0, 0, 1))
        result = fire(plate, d=(0, 0, -1), P_in=500.0)
        self.assertNotEqual(result.outcome, Outcome.STOPPED)

    def test_grazing_shot_from_behind_is_ignored(self):
        """dot > 0 even by epsilon → culled."""
        plate = make_plate(normal=(0, 0, 1))
        result = fire(plate, d=(0, 0.001, 0.999))  # slightly behind
        self.assertEqual(result.plate_damage, 0.0)

# 3. Geometry — effective thickness

class TestEffectiveThickness(unittest.TestCase):

    def test_head_on_100mm_stops_90mm_pen(self):
        plate = make_plate(thickness=100.0)
        result = fire(plate, P_in=90.0, T=AmmoType.AP)
        self.assertEqual(result.outcome, Outcome.STOPPED)
        self.assertEqual(result.residual_penetration, 0.0)

    def test_head_on_100mm_passes_110mm_pen(self):
        plate = make_plate(thickness=100.0)
        result = fire(plate, P_in=110.0, T=AmmoType.AP)
        self.assertEqual(result.outcome, Outcome.PENETRATED)
        self.assertGreater(result.residual_penetration, 0.0)

    def test_60deg_doubles_effective_thickness(self):
        """
        100mm plate at 60°: t_eff = 100/cos(60°) = 200mm.
        150mm pen → stopped. 250mm pen → penetrates.
        """
        plate = make_plate(thickness=100.0)
        d60 = dir_at_angle(60)

        result_stop = fire(plate, P_in=150.0, d=d60, T=AmmoType.AP)
        self.assertEqual(result_stop.outcome, Outcome.STOPPED,
                         "150mm pen should stop against 200mm effective armor")

        result_pen = fire(plate, P_in=250.0, d=d60, T=AmmoType.AP)
        self.assertEqual(result_pen.outcome, Outcome.PENETRATED,
                         "250mm pen should penetrate 200mm effective armor")

    def test_45deg_increases_effective_thickness(self):
        """t_eff at 45° ≈ 141mm. 130mm stops, 150mm penetrates."""
        plate = make_plate(thickness=100.0)
        d45 = dir_at_angle(45)

        self.assertEqual(fire(plate, P_in=130.0, d=d45).outcome, Outcome.STOPPED)
        self.assertEqual(fire(plate, P_in=150.0, d=d45).outcome, Outcome.PENETRATED)

    def test_85deg_clamp_prevents_infinite_t_eff(self):
        """Near-parallel shots should not produce infinite t_eff."""
        plate = make_plate(thickness=100.0)
        d84 = dir_at_angle(84)
        result = fire(plate, P_in=10000.0, d=d84)
        # Should resolve without error and produce a finite residual
        self.assertIsNotNone(result.outcome)
        self.assertTrue(math.isfinite(result.residual_penetration))

# 4. Ricochet

class TestRicochet(unittest.TestCase):

    def test_forced_ricochet_via_roller(self):
        """ConstantRoller(0.0) → roll always < p_ric when angle is above threshold → ricochet."""
        plate = make_plate(thickness=50.0)
        # AP threshold 68°; fire at 80° → p_ric > 0 → ConstantRoller(0.0) forces ricochet
        result = fire(plate, P_in=500.0, T=AmmoType.AP, d=dir_at_angle(80),
                      roller=ConstantRoller(0.0))
        self.assertEqual(result.outcome, Outcome.RICOCHET)
        self.assertEqual(result.residual_penetration, 0.0)

    def test_forced_no_ricochet_via_roller(self):
        """ConstantRoller(1.0) → roll always >= p_ric → never ricochet."""
        plate = make_plate(thickness=50.0)
        result = fire(plate, P_in=500.0, T=AmmoType.AP, d=dir_at_angle(80),
                      roller=ConstantRoller(1.0))
        self.assertNotEqual(result.outcome, Outcome.RICOCHET)

    def test_low_angle_never_ricochets(self):
        """30° is well below all ricochet thresholds — must never ricochet."""
        plate = make_plate(thickness=50.0)
        d30 = dir_at_angle(30)
        for i in range(50):
            result = fire(plate, P_in=500.0, T=AmmoType.AP, d=d30,
                          roller=SeededRoller(), shot_hash=i)
            self.assertNotEqual(result.outcome, Outcome.RICOCHET,
                                f"Unexpected ricochet on shot {i}")

    def test_ricochet_only_scuffs_plate(self):
        """A ricochet should deal surface_scuff_damage, not a full hit."""
        config = Config()
        plate = make_plate(thickness=50.0, config=config)
        result = fire(plate, P_in=500.0, T=AmmoType.AP, d=dir_at_angle(80),
                      roller=ConstantRoller(0.0))
        self.assertEqual(result.plate_damage, config.surface_scuff_damage)

    def test_apfsds_ricochets_less_than_ap_at_same_angle(self):
        """
        APFSDS threshold (72°) > AP threshold (68°) → lower p_ric at the same angle.
        Use SeededRoller over many shots and compare counts.
        """
        roller = SeededRoller()
        d75 = dir_at_angle(75)
        shots = 200

        def count_ricochets(ammo: AmmoType) -> int:
            count = 0
            for i in range(shots):
                plate = make_plate(thickness=50.0)
                result = fire(plate, P_in=500.0, T=ammo, d=d75,
                              roller=roller, shot_hash=i)
                if result.outcome == Outcome.RICOCHET:
                    count += 1
            return count

        ap_ric     = count_ricochets(AmmoType.AP)
        apfsds_ric = count_ricochets(AmmoType.APFSDS)
        self.assertGreater(ap_ric, apfsds_ric,
                           f"AP ({ap_ric}) should ricochet more than APFSDS ({apfsds_ric}) at 75°")

    def test_overmatch_suppresses_ricochet_probability(self):
        """
        Very large caliber vs thin plate → overmatch applied → ricochet modifier reduces p_ric.
        Same angle, same shot_hash: without overmatch more likely to ricochet.
        """
        d80 = dir_at_angle(80)
        roller = SeededRoller()
        shots = 100

        def count_ric(caliber: float) -> int:
            c = 0
            for i in range(shots):
                plate = make_plate(thickness=20.0)  # thin plate, overmatch with large caliber
                result = fire(plate, P_in=500.0, T=AmmoType.AP, d=d80,
                              caliber=caliber, roller=roller, shot_hash=i)
                if result.outcome == Outcome.RICOCHET:
                    c += 1
            return c

        small_cal_ric = count_ric(5.0)    # no overmatch
        large_cal_ric = count_ric(200.0)  # strong overmatch
        self.assertGreater(small_cal_ric, large_cal_ric,
                           "Overmatch should reduce ricochet count")

# 5. Penetration & residuals

class TestPenetrationResidual(unittest.TestCase):

    def test_residual_decreases_with_thicker_plate(self):
        """More armor → less residual."""
        roller = ConstantRoller(1.0)  # no ricochet
        r50  = fire(make_plate(thickness=50.0),  P_in=300.0, roller=roller)
        r100 = fire(make_plate(thickness=100.0), P_in=300.0, roller=roller)
        r150 = fire(make_plate(thickness=150.0), P_in=300.0, roller=roller)
        self.assertGreater(r50.residual_penetration, r100.residual_penetration)
        self.assertGreater(r100.residual_penetration, r150.residual_penetration)

    def test_subtractive_not_multiplicative(self):
        """
        Subtractive model: residual = P_in - t_eff * eta.
        Doubling P_in on the same plate should increase residual by roughly the same amount,
        not by a percentage — confirm the model isn't accidentally multiplicative.
        """
        roller = ConstantRoller(1.0)
        plate  = make_plate(thickness=100.0)
        r200   = fire(plate, P_in=200.0, roller=roller)
        r400   = fire(plate, P_in=400.0, roller=roller)
        delta  = r400.residual_penetration - r200.residual_penetration
        # Subtractive: delta should be ~200 (same as P_in delta)
        self.assertAlmostEqual(delta, 200.0, delta=10.0,
                               msg="Residual should increase linearly with P_in (subtractive model)")

    def test_stopped_shot_zero_residual(self):
        plate = make_plate(thickness=200.0)
        result = fire(plate, P_in=50.0, roller=ConstantRoller(1.0))
        self.assertEqual(result.outcome, Outcome.STOPPED)
        self.assertEqual(result.residual_penetration, 0.0)

    def test_penetrated_positive_residual(self):
        plate = make_plate(thickness=50.0)
        result = fire(plate, P_in=300.0, roller=ConstantRoller(1.0))
        self.assertEqual(result.outcome, Outcome.PENETRATED)
        self.assertGreater(result.residual_penetration, 0.0)

    def test_material_resistance_aluminum_easier(self):
        """Aluminum resists less → more residual than steel at same thickness."""
        roller = ConstantRoller(1.0)
        steel = fire(make_plate(thickness=100.0, material=Material.STEEL),
                     P_in=200.0, roller=roller)
        alum  = fire(make_plate(thickness=100.0, material=Material.ALUMINUM),
                     P_in=200.0, roller=roller)
        self.assertGreater(alum.residual_penetration, steel.residual_penetration)

    def test_material_resistance_composite_harder_than_steel_for_ap(self):
        """Composite η > steel η for AP → less residual."""
        roller = ConstantRoller(1.0)
        steel = fire(make_plate(thickness=100.0, material=Material.STEEL),
                     P_in=200.0, T=AmmoType.AP, roller=roller)
        comp  = fire(make_plate(thickness=100.0, material=Material.COMPOSITE),
                     P_in=200.0, T=AmmoType.AP, roller=roller)
        self.assertGreater(steel.residual_penetration, comp.residual_penetration)

# 6. Plate damage

class TestPlateDamage(unittest.TestCase):

    def test_penetration_deals_damage(self):
        plate = make_plate(thickness=50.0, health=100.0)
        result = fire(plate, P_in=300.0, roller=ConstantRoller(1.0))
        self.assertGreater(result.plate_damage, 0.0)
        self.assertLess(result.new_health, 100.0)

    def test_stop_deals_less_damage_than_penetration(self):
        """A stopped shot absorbs less energy → less damage."""
        roller = ConstantRoller(1.0)
        stopped    = fire(make_plate(thickness=200.0, health=100.0), P_in=50.0,  roller=roller)
        penetrated = fire(make_plate(thickness=50.0,  health=100.0), P_in=500.0, roller=roller)
        self.assertLess(stopped.plate_damage, penetrated.plate_damage)

    def test_damage_does_not_exceed_max_health(self):
        plate = make_plate(thickness=10.0, health=100.0)
        result = fire(plate, P_in=100000.0, roller=ConstantRoller(1.0))
        self.assertLessEqual(result.plate_damage, plate.max_health)

    def test_health_floor_is_zero(self):
        plate = make_plate(thickness=10.0, health=1.0)
        result = fire(plate, P_in=100000.0, roller=ConstantRoller(1.0))
        self.assertGreaterEqual(result.new_health, 0.0)

    def test_degraded_plate_offers_less_resistance(self):
        """Damaged plate → lower t_eff → higher residual on subsequent shots."""
        roller = ConstantRoller(1.0)
        P_in   = 150.0

        fresh   = make_plate(thickness=100.0, health=100.0, max_health=100.0)
        damaged = make_plate(thickness=100.0, health=10.0,  max_health=100.0)

        r_fresh   = fire(fresh,   P_in=P_in, roller=roller)
        r_damaged = fire(damaged, P_in=P_in, roller=roller)

        self.assertGreaterEqual(r_damaged.residual_penetration,
                                r_fresh.residual_penetration,
                                "Damaged plate should offer less resistance")


# 7. Overmatch

class TestOvermatch(unittest.TestCase):

    def test_overmatch_reduces_effective_thickness(self):
        """
        A very large caliber vs a thin plate should produce more residual
        than a small caliber at the same P_in (overmatch reduces t_eff).
        """
        roller = ConstantRoller(1.0)
        # 200mm caliber vs 20mm plate → R = 10 → strong overmatch
        large = fire(make_plate(thickness=20.0), P_in=100.0,
                     caliber=200.0, roller=roller)
        small = fire(make_plate(thickness=20.0), P_in=100.0,
                     caliber=5.0, roller=roller)
        self.assertGreater(large.residual_penetration, small.residual_penetration)

    def test_no_overmatch_below_threshold(self):
        """caliber/t_eff < 1.5 → no reduction, both shots should be identical."""
        roller = ConstantRoller(1.0)
        # caliber=10, t_eff≈100 → R=0.1 (well below 1.5)
        r1 = fire(make_plate(thickness=100.0), P_in=200.0, caliber=10.0,  roller=roller)
        r2 = fire(make_plate(thickness=100.0), P_in=200.0, caliber=100.0, roller=roller)
        # caliber=100, t_eff≈100 → R=1.0 (still below threshold)
        self.assertAlmostEqual(r1.residual_penetration, r2.residual_penetration, places=3)


# 8. Ammo-type specific

class TestAmmoTypes(unittest.TestCase):

    def test_he_always_stops(self):
        """HE detonates on surface — residual must always be 0."""
        plate = make_plate(thickness=5.0)  # even paper-thin plate
        result = fire(plate, P_in=9999.0, T=AmmoType.HE)
        self.assertEqual(result.residual_penetration, 0.0)
        self.assertEqual(result.outcome, Outcome.STOPPED)

    def test_hesh_always_stops(self):
        plate = make_plate(thickness=5.0)
        result = fire(plate, P_in=9999.0, T=AmmoType.HESH)
        self.assertEqual(result.residual_penetration, 0.0)
        self.assertEqual(result.outcome, Outcome.STOPPED)

    def test_he_deals_flat_damage(self):
        """HE damage = max_health * he_damage_scale regardless of P_in."""
        config = Config()
        plate  = make_plate(health=100.0, config=config)
        r1 = fire(plate, P_in=1.0,    T=AmmoType.HE)
        r2 = fire(plate, P_in=9999.0, T=AmmoType.HE)
        self.assertAlmostEqual(r1.plate_damage, r2.plate_damage, places=3,
                               msg="HE damage should not scale with P_in")
        self.assertAlmostEqual(r1.plate_damage,
                               plate.max_health * config.he_damage_scale, places=3)

    def test_heat_decays_across_air_gap(self):
        """HEAT residual should be lower with a large air gap than without."""
        roller = ConstantRoller(1.0)
        no_gap  = make_plate(thickness=50.0, air_gap=0.0)
        big_gap = make_plate(thickness=50.0, air_gap=1000.0)
        r_no  = fire(no_gap,  P_in=300.0, T=AmmoType.HEAT, roller=roller)
        r_gap = fire(big_gap, P_in=300.0, T=AmmoType.HEAT, roller=roller)
        self.assertGreater(r_no.residual_penetration, r_gap.residual_penetration,
                           "HEAT should lose energy across air gap")

    def test_heat_no_gap_unaffected(self):
        """air_gap=0 should not change HEAT residual."""
        roller = ConstantRoller(1.0)
        ap_result   = fire(make_plate(thickness=50.0, air_gap=0.0),
                           P_in=300.0, T=AmmoType.AP,   roller=roller)
        heat_result = fire(make_plate(thickness=50.0, air_gap=0.0),
                           P_in=300.0, T=AmmoType.HEAT, roller=roller)
        # With no gap HEAT and AP differ only by η — not checking equality,
        # just confirming HEAT still penetrates.
        self.assertGreater(heat_result.residual_penetration, 0.0)


# 9. RollProvider determinism

class TestRollProviderDeterminism(unittest.TestCase):

    def test_seeded_roller_same_seed_same_result(self):
        """Same shot_hash → same roll → same outcome every time."""
        plate   = make_plate(thickness=50.0)
        roller  = SeededRoller()
        d80     = dir_at_angle(80)
        results = [
            fire(plate, P_in=500.0, T=AmmoType.AP, d=d80,
                 shot_hash=42, roller=roller).outcome
            for _ in range(10)
        ]
        self.assertEqual(len(set(results)), 1,
                         "Same seed must always produce same outcome")

    def test_seeded_roller_different_seeds_vary(self):
        """Different seeds must produce meaningfully different roll values."""
        roller = SeededRoller()
        rolls  = [roller.roll(i) for i in range(50)]
        unique = len(set(round(r, 3) for r in rolls))
        self.assertGreater(unique, 40,
                           "SeededRoller should produce varied values across 50 seeds")
        # Also verify spread covers the [0,1) range reasonably
        self.assertLess(min(rolls), 0.2)
        self.assertGreater(max(rolls), 0.8)

    def test_constant_roller_zero_forces_ricochet_above_threshold(self):
        roller = ConstantRoller(0.0)
        plate  = make_plate(thickness=50.0)
        result = fire(plate, P_in=500.0, T=AmmoType.AP,
                      d=dir_at_angle(80), roller=roller)
        self.assertEqual(result.outcome, Outcome.RICOCHET)

    def test_constant_roller_one_prevents_ricochet(self):
        roller = ConstantRoller(1.0)
        plate  = make_plate(thickness=50.0)
        result = fire(plate, P_in=500.0, T=AmmoType.AP,
                      d=dir_at_angle(80), roller=roller)
        self.assertNotEqual(result.outcome, Outcome.RICOCHET)

# 10. Multi-hit sequence (commit pattern integration)

class TestMultiHitSequence(unittest.TestCase):

    def test_sequential_hits_degrade_plate(self):
        """Committing multiple penetrations should progressively lower health."""
        plate  = make_plate(thickness=100.0, health=100.0)
        roller = ConstantRoller(1.0)

        healths = [plate.health]
        for i in range(5):
            result = fire(plate, P_in=200.0, roller=roller, shot_hash=i)
            commit(plate, result)
            healths.append(plate.health)

        self.assertEqual(healths, sorted(healths, reverse=True),
                         "Health should be monotonically non-increasing")
        self.assertLess(healths[-1], healths[0],
                        "Health should have decreased after multiple hits")

    def test_degraded_plate_yields_higher_residual(self):
        """
        After several hits the plate is weaker, so the same shot should
        produce more residual than on the first hit.
        """
        plate  = make_plate(thickness=100.0, health=100.0)
        roller = ConstantRoller(1.0)

        # Wear the plate down
        for i in range(8):
            commit(plate, fire(plate, P_in=200.0, roller=roller, shot_hash=i))

        r_fresh = fire(make_plate(thickness=100.0, health=100.0),
                       P_in=150.0, roller=roller)
        r_worn  = fire(plate, P_in=150.0, roller=roller)

        self.assertGreaterEqual(r_worn.residual_penetration,
                                r_fresh.residual_penetration,
                                "Worn plate should offer less resistance")


# Performance benchmark

def run_benchmark(shots: int = 10_000) -> float:
    plate  = make_plate()
    roller = SeededRoller()
    start  = time.perf_counter()
    for i in range(shots):
        plate.hit(
            P_in=280.0, T=AmmoType.APFSDS, d=(0.0, 0.0, -1.0),
            hit_point=(0.0, 0.0, 0.0), caliber=120.0,
            shot_hash=i, roller=roller,
        )
    elapsed = time.perf_counter() - start
    rate    = shots / elapsed
    print(f"\nBenchmark: {shots:,} shots in {elapsed:.3f}s")
    print(f"  {rate:,.0f} shots/sec  ({elapsed * 1000 / shots:.4f} ms/shot)")
    return rate


if __name__ == "__main__":
    unittest.main(verbosity=2, exit=False)
    run_benchmark()