"""Sanity checks for the Bühlmann implementation.

Run with: python -m pytest -q   (or)   python tests/test_buhlmann.py
"""
from __future__ import annotations

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import buhlmann as b


class TestConstants(unittest.TestCase):
    def test_compartment_counts(self):
        self.assertEqual(b.N_COMP, 16)
        for t in (b.N2_HALFTIME, b.N2_A, b.N2_B,
                  b.HE_HALFTIME, b.HE_A, b.HE_B):
            self.assertEqual(len(t), 16)

    def test_halftimes_monotonic(self):
        self.assertEqual(list(b.N2_HALFTIME), sorted(b.N2_HALFTIME))
        self.assertEqual(list(b.HE_HALFTIME), sorted(b.HE_HALFTIME))


class TestTissues(unittest.TestCase):
    def test_surface_saturation_air(self):
        t = b.Tissues.at_surface()
        expected = (b.P_ATM - b.P_H2O) * 0.79
        for p in t.pN2:
            self.assertAlmostEqual(p, expected, places=6)
        for p in t.pHe:
            self.assertEqual(p, 0.0)

    def test_haldane_equivalence(self):
        t = b.Tissues.at_surface()
        b.update_tissues(t, b.AIR, 4.0, 4.0, 100.0)
        p_insp = (4.0 - b.P_H2O) * 0.79
        self.assertAlmostEqual(t.pN2[0], p_insp, places=3)
        self.assertLess(t.pN2[-1], p_insp * 0.5)


class TestNDL(unittest.TestCase):
    def test_ndl_air(self):
        plan = b.DivePlan(gf_low=1.0, gf_high=1.0)
        cases = [(18, 56), (21, 37), (30, 17), (40, 7)]
        for depth, expected in cases:
            got = b.ndl(depth, b.AIR, plan)
            self.assertIsNotNone(got)
            self.assertLess(abs(got - expected), 6,
                            f"NDL {depth}m: got {got}, expected ~{expected}")

    def test_ndl_shrinks_with_depth(self):
        plan = b.DivePlan()
        prev = b.ndl(12, b.AIR, plan)
        for d in (15, 18, 21, 24, 27, 30, 33, 36):
            cur = b.ndl(d, b.AIR, plan)
            self.assertIsNotNone(cur)
            self.assertLessEqual(cur, prev)
            prev = cur


class TestPlan(unittest.TestCase):
    def test_shallow_air_dive_no_deco(self):
        segs, t = b.plan_dive(18, 30, b.AIR)
        self.assertFalse(any(s.kind == "stop" for s in segs))
        self.assertLessEqual(b.ceiling_depth(t, 0.80), 0.5)

    def test_deep_dive_requires_deco(self):
        segs, _ = b.plan_dive(45, 25, b.AIR)
        self.assertTrue(any(s.kind == "stop" for s in segs))

    def test_gas_switch_increases_fO2_with_depth(self):
        plan = b.DivePlan(deco_gases=(b.EAN50, b.O2))
        segs, _ = b.plan_dive(40, 30, b.AIR, plan)
        stops = [s for s in segs if s.kind == "stop"]
        for s in stops:
            if s.depth_start > 21.5:
                self.assertEqual(s.gas.fO2, 0.21)
            if s.depth_start <= 3:
                self.assertAlmostEqual(s.gas.fO2, 1.0)

    def test_gradient_factor_endpoints(self):
        p_stop = b.depth_to_p_amb(9.0)
        self.assertAlmostEqual(b.gf_at(p_stop, 0.3, 0.8, p_stop), 0.30)
        self.assertAlmostEqual(b.gf_at(b.P_ATM, 0.3, 0.8, p_stop), 0.80)


class TestCLI(unittest.TestCase):
    def test_parse_gas(self):
        from cli import parse_gas
        self.assertEqual(parse_gas("air").fO2, 0.21)
        self.assertEqual(parse_gas("ean32").fO2, 0.32)
        self.assertEqual(parse_gas("50").fO2, 0.50)
        g = parse_gas("21/35")
        self.assertAlmostEqual(g.fO2, 0.21)
        self.assertAlmostEqual(g.fHe, 0.35)
        self.assertAlmostEqual(g.fN2, 0.44)


class TestMultiGasTravel(unittest.TestCase):
    HYPOXIC = b.Gas(0.10, 0.70)   # 10/70 hypoxic trimix
    TRAVEL = b.Gas(0.21, 0.35)    # 21/35 travel/bottom-ish mix

    def test_travel_gas_used_when_bottom_gas_hypoxic_at_surface(self):
        plan = b.DivePlan(travel_gases=(self.TRAVEL,), deco_gases=(b.EAN50, b.O2))
        segs, _ = b.plan_dive(70, 20, self.HYPOXIC, plan)
        descents = [s for s in segs if s.kind == "descent"]
        self.assertAlmostEqual(descents[0].gas.fO2, self.TRAVEL.fO2)
        self.assertAlmostEqual(descents[0].gas.fHe, self.TRAVEL.fHe)
        self.assertTrue(any(s.gas.fHe == self.HYPOXIC.fHe for s in descents),
                        "bottom gas is never picked up on descent")

    def test_bottom_gas_switch_depth_is_its_min_depth(self):
        plan = b.DivePlan(travel_gases=(self.TRAVEL,))
        segs, _ = b.plan_dive(60, 15, self.HYPOXIC, plan)
        on_bottom = [s for s in segs
                     if s.kind == "descent" and s.gas.fHe == self.HYPOXIC.fHe]
        self.assertTrue(on_bottom)
        first = min(s.depth_start for s in on_bottom)
        self.assertAlmostEqual(first, self.HYPOXIC.min_depth(plan.ppo2_min), delta=0.5)

    def test_no_segment_is_breathed_hypoxic(self):
        plan = b.DivePlan(travel_gases=(self.TRAVEL,), deco_gases=(b.EAN50, b.O2))
        segs, _ = b.plan_dive(70, 25, self.HYPOXIC, plan)
        for s in segs:
            shallow = min(s.depth_start, s.depth_end)
            self.assertGreaterEqual(
                s.gas.ppo2(shallow), plan.ppo2_min - 1e-6,
                f"{s.gas!r} hypoxic on {s.kind} at {shallow:.1f} m")

    def test_no_segment_exceeds_deco_ppo2_ceiling(self):
        # switches snap to stop depths, so ppO2 may exceed ppo2_deco by at
        # most ppo2_switch_tol (O2 at the 6 m stop: 1.613 bar)
        plan = b.DivePlan(deco_gases=(b.EAN50, b.O2))
        segs, _ = b.plan_dive(45, 25, b.AIR, plan)
        for s in segs:
            deep = max(s.depth_start, s.depth_end)
            self.assertLessEqual(
                s.gas.ppo2(deep), plan.ppo2_deco + plan.ppo2_switch_tol + 1e-6,
                f"{s.gas!r} ppO2 too high on {s.kind} at {deep:.1f} m")

    def test_descent_stays_on_bottom_gas_when_normoxic(self):
        plan = b.DivePlan(travel_gases=(b.O2,))
        segs, _ = b.plan_dive(30, 20, b.EAN32, plan)
        descents = [s for s in segs if s.kind == "descent"]
        self.assertEqual(len(descents), 1)
        self.assertAlmostEqual(descents[0].gas.fO2, 0.32)

    def test_multiple_deco_gases_richest_used_shallowest(self):
        plan = b.DivePlan(deco_gases=(b.EAN50, b.O2))
        segs, _ = b.plan_dive(45, 25, b.AIR, plan)
        stops = [s for s in segs if s.kind == "stop"]
        shallowest = min(stops, key=lambda s: s.depth_start)
        self.assertAlmostEqual(shallowest.gas.fO2, 1.0)
        for s in stops:
            if s.gas.fO2 == 1.0:
                self.assertLessEqual(s.depth_start, plan.switch_depth(b.O2) + 1e-6)
            if s.gas.fO2 == 0.50:
                self.assertLessEqual(s.depth_start, plan.switch_depth(b.EAN50) + 1e-6)

    def test_switch_depths_snap_to_stops(self):
        plan = b.DivePlan()
        # O2: MOD 5.87 m at ppO2 1.6 -> standard 6 m stop (excess 0.013 bar)
        self.assertAlmostEqual(plan.switch_depth(b.O2), 6.0)
        # EAN50: MOD 21.87 m -> 21 m stop (nearest, no excess)
        self.assertAlmostEqual(plan.switch_depth(b.EAN50), 21.0)
        # a switch is never rounded deeper than ppo2_switch_tol allows
        tight = b.DivePlan(ppo2_switch_tol=0.001)
        self.assertAlmostEqual(tight.switch_depth(b.O2), 3.0)

    def test_min_depth_and_ppo2_helpers(self):
        self.assertAlmostEqual(self.HYPOXIC.min_depth(0.18),
                               (0.18 / 0.10 - b.P_ATM) * 10.0, places=6)
        self.assertEqual(b.AIR.min_depth(0.18), 0.0)
        self.assertAlmostEqual(b.O2.ppo2(0.0), b.P_ATM, places=6)


class TestTTSandRockBottom(unittest.TestCase):
    def test_tts_is_ascent_plus_stops(self):
        segs, _ = b.plan_dive(45, 25, b.AIR, b.DivePlan())
        manual = sum(s.duration for s in segs if s.kind in ("ascent", "stop"))
        self.assertAlmostEqual(b.time_to_surface(segs), manual)
        self.assertGreater(b.time_to_surface(segs), 0)

    def test_tts_no_deco_is_just_the_ascent(self):
        segs, _ = b.plan_dive(18, 20, b.AIR, b.DivePlan())
        self.assertFalse(any(s.kind == "stop" for s in segs))
        self.assertAlmostEqual(b.time_to_surface(segs), 18 / 10.0, places=6)

    def test_rock_bottom_scales_linearly_with_multiplier(self):
        gp1 = b.GasPlan(sac=20, sac_multiplier=1.0)
        gp2 = b.GasPlan(sac=20, sac_multiplier=2.0)
        self.assertAlmostEqual(b.rock_bottom_liters(30, gp2),
                               2 * b.rock_bottom_liters(30, gp1), places=6)

    def test_rock_bottom_grows_with_multiplier(self):
        lo = b.rock_bottom_liters(30, b.GasPlan(sac=20, sac_multiplier=1.5))
        hi = b.rock_bottom_liters(30, b.GasPlan(sac=20, sac_multiplier=3.0))
        self.assertGreater(hi, lo)

    def test_rock_bottom_is_problem_plus_direct_ascent(self):
        gp = b.GasPlan(sac=20, sac_multiplier=2.0, problem_minutes=2.0)
        emergency = 20 * 2.0                                # sac * multiplier
        problem = emergency * b.depth_to_p_amb(30) * 2.0
        p_avg = b.P_ATM + 15.0 / 10.0                       # mid-depth of 30 m
        ascent = emergency * p_avg * (30 / 10.0)
        self.assertAlmostEqual(b.rock_bottom_liters(30, gp, 10.0),
                               problem + ascent, places=6)

    def test_rock_bottom_grows_with_depth(self):
        gp = b.GasPlan(sac=20, sac_multiplier=2.0)
        self.assertGreater(b.rock_bottom_liters(45, gp),
                           b.rock_bottom_liters(30, gp))

    def test_rock_bottom_is_a_practical_reserve(self):
        # 45 m single-diver min gas on a 24 L twinset is a realistic reserve —
        # tens of bar, not the hundreds the old full-deco method produced.
        gp = b.GasPlan(sac=20, sac_multiplier=2.0)
        bar = b.rock_bottom_liters(45, gp) / 24.0
        self.assertGreater(bar, 15)
        self.assertLess(bar, 120)

    def test_segment_gas_liters_hand_calc_single_segment(self):
        seg = b.DiveSegment("bottom", 20, 20, 10.0, b.AIR)
        ata = b.depth_to_p_amb(20)
        self.assertAlmostEqual(b.segment_gas_liters([seg], 15),
                               15 * ata * 10.0, places=6)


class TestLastStopDepth(unittest.TestCase):
    """last_stop_depth=6 — the Shearwater/MultiDeco 'last stop 6 m' option."""

    def schedules(self, last_stop, depth=40, time=30):
        plan = b.DivePlan(gf_low=0.30, gf_high=0.80, last_stop_depth=last_stop)
        segs, _ = b.plan_dive(depth, time, b.AIR, plan)
        return ([(s.depth_start, s.duration) for s in segs if s.kind == "stop"],
                b.time_to_surface(segs))

    def test_no_stop_shallower_than_last_stop(self):
        stops, _ = self.schedules(6.0)
        self.assertTrue(stops)
        self.assertGreaterEqual(min(d for d, _t in stops), 6.0)

    def test_deeper_stops_unchanged(self):
        stops3, _ = self.schedules(3.0)
        stops6, _ = self.schedules(6.0)
        self.assertEqual([s for s in stops3 if s[0] > 6.0],
                         [s for s in stops6 if s[0] > 6.0])

    def test_shallow_deco_served_at_6m_takes_longer(self):
        # off-gassing at 6 m is slower than at 3 m, so folding the 3 m stop
        # into the 6 m stop must not shorten the schedule
        (stops3, tts3), (stops6, tts6) = self.schedules(3.0), self.schedules(6.0)
        self.assertGreater(dict(stops6)[6.0], dict(stops3)[6.0])
        self.assertGreaterEqual(tts6, tts3)

    def test_shallow_only_deco_collapses_to_single_6m_stop(self):
        # 21 m / 50 min air needs only 6 m + 3 m stops; with last stop 6 m the
        # whole obligation is served in one 6 m stop
        stops, _ = self.schedules(6.0, depth=21, time=50)
        self.assertEqual([d for d, _t in stops], [6.0])

    def test_default_is_unchanged(self):
        self.assertEqual(b.DivePlan().last_stop_depth, 3.0)


if __name__ == "__main__":
    unittest.main()
