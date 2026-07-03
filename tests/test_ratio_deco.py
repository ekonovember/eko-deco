"""Sanity checks for the Ratio Deco utility (educational)."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import ratio_deco as rd


class TestStandardGases(unittest.TestCase):
    def test_bottom_gas_bands(self):
        cases = [(21, "EAN32"), (30, "EAN32"), (40, "30/30"), (45, "30/30"),
                 (55, "21/35"), (60, "21/35"), (70, "18/45"), (80, "15/55"),
                 (100, "12/65")]
        for depth, label in cases:
            self.assertEqual(rd.standard_bottom_gas(depth)[1], label,
                             f"{depth} m -> {label}")

    def test_bottom_gas_clamps_below_deepest(self):
        self.assertEqual(rd.standard_bottom_gas(150)[1], "12/65")

    def test_deco_gases_depend_on_depth(self):
        self.assertEqual([l for (_d, _g, l) in rd.standard_deco_gases(51)],
                         ["EAN50", "O2"])
        self.assertEqual([l for (_d, _g, l) in rd.standard_deco_gases(15)], ["O2"])
        self.assertEqual(rd.standard_deco_gases(4), [])

    def test_standard_dive_gases_adds_travel_only_when_hypoxic(self):
        _bottom, travel, _deco = rd.standard_dive_gases(51)   # 21/35 breathes at surface
        self.assertEqual(travel, ())
        _bottom, travel, _deco = rd.standard_dive_gases(90)   # 15/55 is hypoxic
        self.assertTrue(travel and abs(travel[0].fO2 - 0.32) < 1e-9)


class TestRatio(unittest.TestCase):
    def test_ratio_anchors(self):
        self.assertAlmostEqual(rd.ratio_at(46), 1.0, places=6)
        self.assertAlmostEqual(rd.ratio_at(67), 2.0, places=6)

    def test_ratio_midpoint_and_floor(self):
        self.assertAlmostEqual(rd.ratio_at(56.5), 1.5, places=2)
        self.assertEqual(rd.ratio_at(20), 0.0)

    def test_ratio_increases_with_depth(self):
        self.assertLess(rd.ratio_at(40), rd.ratio_at(50))
        self.assertLess(rd.ratio_at(50), rd.ratio_at(60))

    def test_first_stop_is_80pct_of_max_pressure(self):
        self.assertEqual(rd.first_stop_depth(51), 36.0)
        self.assertEqual(rd.first_stop_depth(75), 57.0)


class TestRatioDeco(unittest.TestCase):
    def test_min_deco_when_shallow(self):
        res = rd.ratio_deco(25, 30)
        self.assertTrue(res.min_deco)
        self.assertEqual(res.stops, [])
        self.assertEqual(res.total_deco_min, 0.0)

    def test_total_is_bottom_time_times_ratio(self):
        res = rd.ratio_deco(51, 25)
        self.assertAlmostEqual(res.total_deco_min, 25 * rd.ratio_at(51), places=6)

    def test_stops_structure_and_gases(self):
        res = rd.ratio_deco(51, 25)
        self.assertFalse(res.min_deco)
        self.assertEqual(res.first_stop_m, 36.0)
        last = res.stops[-1]
        self.assertEqual(last.depth_m, 6.0)
        self.assertEqual(last.gas, "O2")
        self.assertAlmostEqual(last.minutes, res.total_deco_min / 2.0, places=6)
        for s in res.stops:
            if s.depth_m > 21:
                self.assertEqual(s.gas, res.bottom_gas)
            elif s.depth_m <= 6:
                self.assertEqual(s.gas, "O2")
            else:
                self.assertEqual(s.gas, "EAN50")

    def test_gas_switch_minimum_stop_enforced(self):
        res = rd.ratio_deco(51, 25)
        stop21 = next(s for s in res.stops if abs(s.depth_m - 21) < 1e-9)
        self.assertGreaterEqual(stop21.minutes, 3.0)

    def test_scheduled_at_least_total(self):
        res = rd.ratio_deco(51, 25)
        self.assertGreaterEqual(res.scheduled_deco_min + 1e-6, res.total_deco_min)

    def test_deeper_or_longer_means_more_deco(self):
        self.assertGreater(rd.ratio_deco(60, 25).total_deco_min,
                           rd.ratio_deco(50, 25).total_deco_min)
        self.assertGreater(rd.ratio_deco(51, 40).total_deco_min,
                           rd.ratio_deco(51, 20).total_deco_min)

    def test_avg_depth_override_lowers_deco(self):
        deep = rd.ratio_deco(60, 25)
        shallow_avg = rd.ratio_deco(60, 25, avg_depth_m=45)
        self.assertLess(shallow_avg.total_deco_min, deep.total_deco_min)


if __name__ == "__main__":
    unittest.main()
