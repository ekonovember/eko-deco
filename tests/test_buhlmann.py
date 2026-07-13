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

    def test_parse_level(self):
        from cli import parse_level
        lv = parse_level("45:25")
        self.assertAlmostEqual(lv.depth, 45)
        self.assertAlmostEqual(lv.runtime, 25)
        self.assertIsNone(lv.gas)                 # no gas = "auto"
        lv = parse_level("120:20:10/70")
        self.assertAlmostEqual(lv.depth, 120)
        self.assertAlmostEqual(lv.runtime, 20)
        self.assertAlmostEqual(lv.gas.fHe, 0.70)
        self.assertAlmostEqual(parse_level("18:55:ean50").gas.fO2, 0.50)

    def test_parse_level_rejects_junk(self):
        from cli import parse_level
        for spec in ("45", "45:25:50:9", "deep:25", "45:soon"):
            with self.assertRaises(ValueError, msg=spec):
                parse_level(spec)


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


class TestMultilevel(unittest.TestCase):
    """Multi-level profiles. `Level.runtime` is the runtime at the END of the
    level (cumulative, descent included) — the same meaning bottom_time has
    always had, which is what lets a single level reproduce a square dive."""

    PLAN = b.DivePlan(gf_low=0.30, gf_high=0.80, deco_gases=(b.EAN50, b.O2))

    def stops(self, segs):
        return [(s.depth_start, s.duration) for s in segs if s.kind == "stop"]

    def test_single_level_is_exactly_plan_dive(self):
        """The regression guard: plan_dive is plan_multilevel with one level, so
        a square dive must come out bit-for-bit identical."""
        square, t1 = b.plan_dive(45, 25, b.AIR, self.PLAN)
        one_level, t2 = b.plan_multilevel([b.Level(45, 25)], b.AIR, self.PLAN)
        self.assertEqual([s.as_dict() for s in square],
                         [s.as_dict() for s in one_level])
        self.assertEqual(t1.pN2, t2.pN2)
        self.assertEqual(t1.pHe, t2.pHe)

    def test_runtime_is_cumulative_and_includes_travel(self):
        levels = [b.Level(45, 25), b.Level(30, 40), b.Level(18, 55)]
        segs, _ = b.plan_multilevel(levels, b.AIR, self.PLAN)
        bottoms = [s for s in segs if s.kind == "bottom"]
        self.assertEqual([s.depth_start for s in bottoms], [45, 30, 18])
        # runtime at the end of the last level == its declared runtime
        bottom_end = 0.0
        for s in segs:
            bottom_end += s.duration
            if s is bottoms[-1]:
                break
        self.assertAlmostEqual(bottom_end, 55.0, places=6)
        # descent (2.5 min) is inside level 1's 25 min, not added to it
        self.assertAlmostEqual(bottoms[0].duration, 25.0 - 45 / 18.0, places=6)

    def test_going_shallow_shortens_the_deco(self):
        deep, _ = b.plan_multilevel([b.Level(45, 55)], b.AIR, self.PLAN)
        multi, _ = b.plan_multilevel([b.Level(45, 25), b.Level(18, 55)],
                                     b.AIR, self.PLAN)
        self.assertLess(b.time_to_surface(multi), b.time_to_surface(deep))

    def test_tts_excludes_travel_between_levels(self):
        """Travel between levels is bottom time, not time-to-surface — it is an
        ascent segment, so a naive kind filter would wrongly count it."""
        levels = [b.Level(45, 25), b.Level(30, 40), b.Level(18, 55)]
        segs, _ = b.plan_multilevel(levels, b.AIR, self.PLAN)
        deco_only = sum(s.duration for s in segs
                        if s.kind in ("ascent", "stop")
                        and s.depth_start <= 18 + 1e-9)
        self.assertAlmostEqual(b.time_to_surface(segs), deco_only, places=6)

    def test_per_level_gas_is_breathed(self):
        levels = [b.Level(45, 25, b.Gas(0.21, 0.35)), b.Level(21, 40, b.EAN50)]
        segs, _ = b.plan_multilevel(levels, b.Gas(0.21, 0.35), self.PLAN)
        bottoms = [s for s in segs if s.kind == "bottom"]
        self.assertAlmostEqual(bottoms[0].gas.fHe, 0.35)
        self.assertAlmostEqual(bottoms[1].gas.fO2, 0.50)

    def test_named_level_gas_not_breathed_over_ppo2_on_the_travel_up(self):
        """Ascending to a shallow level on a rich named mix must not breathe it at
        the deep end of the travel: the switch waits for the mix's MOD. Regression
        for the chart showing EAN50 back at the bottom depth."""
        levels = [b.Level(36, 20, b.EAN32), b.Level(20, 30, b.EAN50)]
        segs, _ = b.plan_multilevel(levels, b.EAN32, self.PLAN)
        for s in segs:
            deep = max(s.depth_start, s.depth_end)
            self.assertLessEqual(
                s.gas.ppo2(deep),
                self.PLAN.ppo2_deco + self.PLAN.ppo2_switch_tol + 1e-6,
                f"{s.gas!r} over ppO2 at {deep:.1f} m")
        # the flat 20 m level is still the mix the user asked for
        bottoms = [s for s in segs if s.kind == "bottom"]
        self.assertAlmostEqual(bottoms[-1].gas.fO2, 0.50)
        # and EAN50 first appears no deeper than its switch depth
        first_ean50 = next(max(s.depth_start, s.depth_end)
                           for s in segs if s.gas == b.EAN50)
        self.assertLessEqual(first_ean50, self.PLAN.switch_depth(b.EAN50) + 1e-6)

    def test_auto_level_breathes_the_bottom_gas_when_it_is_breathable(self):
        segs, _ = b.plan_multilevel([b.Level(40, 20), b.Level(20, 35)],
                                    b.EAN32, self.PLAN)
        for s in (s for s in segs if s.kind == "bottom"):
            self.assertAlmostEqual(s.gas.fO2, 0.32)

    def test_auto_level_picks_the_gas_relevant_at_that_depth(self):
        """'auto' is not 'the bottom gas' — it is the gas that is actually
        breathable there. A hypoxic bottom mix cannot be breathed on a shallow
        level, so the carried travel mix is used instead."""
        hypoxic, travel = b.Gas(0.10, 0.70), b.Gas(0.35, 0.25)
        plan = b.DivePlan(gf_low=0.30, gf_high=0.80,
                          travel_gases=(travel,), deco_gases=(b.EAN50,))
        segs, _ = b.plan_multilevel([b.Level(60, 20), b.Level(6, 40)],
                                    hypoxic, plan)
        levels = [s for s in segs if s.kind == "bottom"]
        self.assertAlmostEqual(levels[0].gas.fHe, 0.70)   # deep: the bottom mix
        self.assertAlmostEqual(levels[1].gas.fO2, 0.35)   # 6 m: 10/70 is hypoxic
        # and nothing is ever breathed outside the ppO2 window
        for s in segs:
            shallow = min(s.depth_start, s.depth_end)
            self.assertGreaterEqual(s.gas.ppo2(shallow), plan.ppo2_min - 1e-6,
                                    f"{s.gas!r} hypoxic at {shallow:.1f} m")

    def test_level_gas_is_billed_to_its_own_cylinder(self):
        """Gas planning is segment-driven, so a level's gas has to show up in
        that gas's consumption — not the bottom gas's."""
        levels = [b.Level(40, 20), b.Level(21, 40, b.EAN50)]
        segs, _ = b.plan_multilevel(levels, b.AIR, self.PLAN)
        air = b.segment_gas_liters([s for s in segs if s.gas == b.AIR], 20)
        ean50 = b.segment_gas_liters([s for s in segs if s.gas == b.EAN50], 20)

        auto, _ = b.plan_multilevel([b.Level(40, 20), b.Level(21, 40)],
                                    b.AIR, self.PLAN)
        air_auto = b.segment_gas_liters([s for s in auto if s.gas == b.AIR], 20)
        ean50_auto = b.segment_gas_liters([s for s in auto if s.gas == b.EAN50], 20)

        # forcing the level onto EAN50 moves that level's litres off the back gas
        self.assertLess(air, air_auto)
        self.assertGreater(ean50, ean50_auto)

    def test_level_above_the_ceiling_is_flagged_but_still_planned(self):
        # 45 m for 30 min then straight to 6 m: the 6 m level is well above the
        # ceiling. The schedule is still produced; the level carries the ceiling.
        segs, _ = b.plan_multilevel([b.Level(45, 30), b.Level(6, 35)],
                                    b.AIR, self.PLAN)
        bad = b.ceiling_violations(segs)
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0].depth_start, 6)
        self.assertGreater(bad[0].ceiling_m, 6)
        self.assertTrue(self.stops(segs))          # still planned

    def test_legal_profile_has_no_ceiling_violation(self):
        segs, _ = b.plan_multilevel([b.Level(45, 25), b.Level(30, 40)],
                                    b.AIR, self.PLAN)
        self.assertEqual(b.ceiling_violations(segs), [])

    def test_max_and_average_depth(self):
        levels = [b.Level(45, 25), b.Level(18, 55)]
        segs, _ = b.plan_multilevel(levels, b.AIR, self.PLAN)
        self.assertEqual(b.max_depth(levels), 45)
        avg = b.average_depth(segs)
        self.assertLess(avg, 45)
        self.assertGreater(avg, 18)
        # a square dive's average depth is (nearly) its max depth
        square, _ = b.plan_multilevel([b.Level(45, 25)], b.AIR, self.PLAN)
        self.assertAlmostEqual(b.average_depth(square), 45, delta=3)

    def test_rejects_non_increasing_runtime(self):
        with self.assertRaises(ValueError):
            b.plan_multilevel([b.Level(45, 25), b.Level(30, 20)], b.AIR, self.PLAN)

    def test_rejects_runtime_before_arrival(self):
        with self.assertRaises(ValueError):    # 45 m takes 2.5 min to reach
            b.plan_multilevel([b.Level(45, 1)], b.AIR, self.PLAN)

    def test_rejects_empty_profile(self):
        with self.assertRaises(ValueError):
            b.plan_multilevel([], b.AIR, self.PLAN)


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


class TestCeilingProfile(unittest.TestCase):
    PLAN = b.DivePlan(gf_low=0.30, gf_high=0.80,
                      deco_gases=(b.Gas(0.50), b.Gas(1.0)))

    def test_deco_free_dive_is_flat_zero(self):
        # 12 m / 10 min air never has a ceiling, even at GF-Low
        segs, _ = b.plan_dive(12, 10, b.AIR)
        for _t, c in b.ceiling_profile(segs, b.DivePlan()):
            self.assertEqual(c, 0.0)

    def test_time_axis_spans_the_dive(self):
        segs, _ = b.plan_dive(45, 25, b.AIR, self.PLAN)
        prof = b.ceiling_profile(segs, self.PLAN)
        times = [t for t, _c in prof]
        self.assertEqual(times[0], 0.0)
        self.assertEqual(times, sorted(times))
        self.assertAlmostEqual(times[-1], b.total_runtime(segs), places=6)

    def test_deco_dive_has_a_ceiling_and_clears_it(self):
        segs, _ = b.plan_dive(45, 25, b.AIR, self.PLAN)
        prof = b.ceiling_profile(segs, self.PLAN)
        self.assertGreater(max(c for _t, c in prof), 0.0)
        self.assertLessEqual(prof[-1][1], 0.01)   # surfaces clean at GF-High

    def test_anchor_matches_the_planned_first_stop(self):
        # the ceiling on leaving the bottom, rounded up like the planner does,
        # is the first stop — and no sample is ever deeper than that stop
        segs, _ = b.plan_dive(45, 25, b.AIR, self.PLAN)
        prof = b.ceiling_profile(segs, self.PLAN)
        first_stop = max(s.depth_start for s in segs if s.kind == "stop")
        bottom_t = sum(s.duration for s in segs[:b._bottom_phase_end(segs)])
        c_bottom = max(c for t, c in prof if t <= bottom_t + 1e-9)
        rounded = max(b._round_up_to_stop(c_bottom, self.PLAN.stop_interval),
                      self.PLAN.last_stop_depth)
        self.assertEqual(rounded, first_stop)
        self.assertLessEqual(max(c for _t, c in prof), first_stop + 1e-6)

    def test_trimix_multi_gas_smoke(self):
        plan = b.DivePlan(gf_low=0.30, gf_high=0.80,
                          travel_gases=(b.Gas(0.35, 0.25),),
                          deco_gases=(b.Gas(0.50), b.Gas(1.0)))
        segs, _ = b.plan_dive(60, 25, b.Gas(0.10, 0.70), plan)
        prof = b.ceiling_profile(segs, plan)
        self.assertTrue(all(math.isfinite(c) and 0.0 <= c <= 60.0
                            for _t, c in prof))


if __name__ == "__main__":
    unittest.main()
