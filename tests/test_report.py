"""Tests for the shared report layer (report.py)."""
from __future__ import annotations

import unittest

from deco import buhlmann as b
from deco import report as rp


class TestAggregateBanks(unittest.TestCase):
    def test_same_mix_cylinders_merge_volume_weighted(self):
        banks = rp.aggregate_banks([
            ("Bottom", b.AIR, 12.0, 232.0),
            ("Bottom", b.AIR, 12.0, 200.0),
        ])
        self.assertEqual(len(banks), 1)
        self.assertEqual(banks[0].tank_l, 24.0)
        self.assertAlmostEqual(banks[0].pressure_bar, 216.0)

    def test_near_mixes_with_same_label_do_not_merge(self):
        # Gas(0.206) and Gas(0.214) both display as EAN21 — display labels
        # must never be computational identity (review finding M2/R2-M1).
        g1, g2 = b.Gas(0.206), b.Gas(0.214)
        self.assertEqual(repr(g1), repr(g2))
        banks = rp.aggregate_banks([("Bottom", g1, 12.0, 232.0),
                                    ("Deco", g2, 11.0, 200.0)])
        self.assertEqual(len(banks), 2)
        self.assertEqual({bk.tank_l for bk in banks}, {12.0, 11.0})


class TestGasReport(unittest.TestCase):
    def _result(self, **gp_kw):
        gp = b.GasPlan(sac=20.0, **gp_kw)
        gases = [("Bottom", b.AIR, 24.0, 232.0),
                 ("Deco", b.EAN50, 11.0, 200.0)]
        plan = b.DivePlan(deco_gases=(b.EAN50,))
        return rp.compute_plan_result([b.Level(40.0, 25.0)], b.AIR, plan,
                                      gp, gases)

    def test_cylinders_in_first_breathed_order(self):
        res = self._result()
        self.assertEqual([c.gas for c in res.gas.cylinders],
                         [b.AIR, b.EAN50])
        self.assertEqual(res.gas.cylinders[0].role, "Bottom")

    def test_need_and_reserve_positive(self):
        res = self._result()
        for c in res.gas.cylinders:
            self.assertGreater(c.liters, 0)
            # Emergency total carries a reserve on top of the normal need.
            self.assertGreater(c.liters_emergency, c.liters)
        # Rock bottom is the back gas's reserve = its emergency total minus need.
        c0 = res.gas.cylinders[0]
        self.assertGreater(res.gas.rock_bottom_l, 0)
        self.assertAlmostEqual(res.gas.rock_bottom_l,
                               c0.liters_emergency - c0.liters, places=6)
        self.assertIsNotNone(res.gas.rock_bottom_bar)
        self.assertIsNotNone(res.gas.turn_pressure_bar)

    def test_emergency_total_is_need_plus_reserve(self):
        res = self._result(sac_multiplier=1.8, problem_minutes=2.0)
        segs = res.segments
        gp = res.gas.plan
        for c in res.gas.cylinders:
            need = b.segment_gas_liters(
                [s for s in segs if s.gas == c.gas], gp.sac)
            reserve = b.emergency_gas_liters(segs, c.gas, gp)
            self.assertAlmostEqual(c.liters_emergency, need + reserve, places=6)

    def test_short_flag_on_undersized_tank(self):
        gp = b.GasPlan(sac=25.0)
        gases = [("Bottom", b.AIR, 10.0, 100.0)]
        res = rp.compute_plan_result([b.Level(30.0, 60.0)], b.AIR,
                                     b.DivePlan(), gp, gases)
        self.assertTrue(res.gas.cylinders[0].short)

    def test_no_gasplan_means_no_gas_report(self):
        res = rp.compute_plan_result([b.Level(30.0, 20.0)], b.AIR,
                                     b.DivePlan())
        self.assertIsNone(res.gas)


class TestWarnings(unittest.TestCase):
    def test_air_below_mod_warns_high_ppo2_and_density(self):
        res = rp.compute_plan_result([b.Level(70.0, 15.0)], b.AIR,
                                     b.DivePlan())
        text = "\n".join(res.warnings)
        self.assertIn("ppO2", text)
        self.assertIn("over the", text)
        self.assertIn("g/L", text)

    def test_clean_dive_has_no_warnings(self):
        res = rp.compute_plan_result([b.Level(30.0, 20.0)], b.AIR,
                                     b.DivePlan())
        self.assertEqual(res.warnings, [])


class TestRuntimeConvention(unittest.TestCase):
    """`runtime_min` renders a runtime the way a schedule shows it. The values
    below are transcribed from a real MultiDeco 4.26 plan export (one row per
    segment, true runtime → the integer MultiDeco prints in parentheses): every
    row is the floor, never a round. Both front ends render runtimes through
    this helper, so the cards cannot drift from the planner the schedules are
    cross-checked against."""

    def test_matches_the_multideco_export(self):
        for true_run, shown in [(1.611, 1), (41.000, 41), (43.875, 43),
                                (44.008, 44), (50.440, 50), (50.870, 50)]:
            self.assertEqual(rp.runtime_min(true_run), shown,
                             msg=f"{true_run} min")

    def test_truncates_rather_than_rounds(self):
        # .5 and .9 both stay on the minute already reached — a round() here
        # would advance the runtime past a stop the diver has not finished.
        self.assertEqual(rp.runtime_min(34.5), 34)
        self.assertEqual(rp.runtime_min(39.9), 39)

    def test_exact_minutes_survive_float_error(self):
        # A runtime that is exactly 33 must never print 32 because the segment
        # durations summed to 32.999999999999996.
        self.assertEqual(rp.runtime_min(33.0), 33)
        self.assertEqual(rp.runtime_min(32.999999999999996), 33)


class TestPlanResult(unittest.TestCase):
    def test_contingency_grid_attached_when_requested(self):
        res = rp.compute_plan_result([b.Level(40.0, 25.0)], b.AIR,
                                     b.DivePlan(), contingency=(1, 1, 1, 1))
        self.assertIsNotNone(res.contingency)
        self.assertEqual(len(res.contingency), 3)      # -1, planned, +1 rows

    def test_totals_are_consistent(self):
        res = rp.compute_plan_result([b.Level(40.0, 25.0)], b.AIR,
                                     b.DivePlan())
        self.assertAlmostEqual(res.total_runtime_min,
                               b.total_runtime(res.segments))
        self.assertLess(res.tts_min, res.total_runtime_min)
        self.assertEqual(res.max_depth_m, 40.0)


if __name__ == "__main__":
    unittest.main()
