"""Oxygen toxicity clocks (`deco.toxicity`): NOAA CNS % and Repex OTU.

Both are downstream analyses of a planned dive — they read a segment list and
integrate a published dose curve over it, touching no tissue compartment.
"""

from __future__ import annotations

import unittest

from deco import buhlmann as b
from deco import toxicity as tox


class TestOxygenToxicity(unittest.TestCase):
    @staticmethod
    def _flat(depth, minutes, gas):
        return [b.DiveSegment("bottom", depth, depth, minutes, gas)]

    def test_cns_100pct_after_45min_at_1_6_bar(self):
        depth = (1.6 - b.P_ATM) * 10.0                # ppO2 exactly 1.6 on O2
        cns, _ = tox.cns_otu(self._flat(depth, 45, b.O2))
        self.assertAlmostEqual(cns, 100.0, places=6)

    def test_cns_and_otu_at_1_bar(self):
        depth = (2.0 - b.P_ATM) * 10.0                # ppO2 1.0 on EAN50
        cns, otu = tox.cns_otu(self._flat(depth, 60, b.EAN50))
        self.assertAlmostEqual(cns, 20.0, places=6)   # 60 / 300 NOAA minutes
        self.assertAlmostEqual(otu, 60.0, places=6)   # rate is exactly 1 /min

    def test_no_dose_below_half_bar(self):
        cns, otu = tox.cns_otu(self._flat(10, 60, b.Gas(0.21, 0.60)))
        self.assertEqual((cns, otu), (0.0, 0.0))      # ppO2 0.42 < 0.5

    def test_deeper_is_worse(self):
        shallow = tox.cns_otu(self._flat(30, 30, b.EAN32))
        deep = tox.cns_otu(self._flat(40, 30, b.EAN32))
        self.assertGreater(deep[0], shallow[0])
        self.assertGreater(deep[1], shallow[1])



if __name__ == "__main__":
    unittest.main()


class TestSurfaceDecay(unittest.TestCase):
    """`cns_after_interval` — the CNS clock across a surface interval."""

    def test_one_halftime_halves_it(self):
        self.assertAlmostEqual(
            tox.cns_after_interval(80.0, tox.CNS_HALFTIME_MIN), 40.0, places=9)

    def test_no_interval_changes_nothing(self):
        for t in (0.0, -5.0):
            self.assertEqual(tox.cns_after_interval(42.0, t), 42.0)

    def test_decays_monotonically_and_never_below_zero(self):
        prev = 100.0
        for t in (10, 30, 60, 120, 600):
            now = tox.cns_after_interval(100.0, t)
            self.assertLess(now, prev)
            self.assertGreater(now, 0.0)
            prev = now


class TestReportingThresholds(unittest.TestCase):
    """The warning tiers are ordered and are the published limits."""

    def test_tiers_are_ordered(self):
        self.assertLess(tox.CNS_WARN_PCT, tox.CNS_LIMIT_PCT)

    def test_published_limits(self):
        self.assertEqual(tox.CNS_LIMIT_PCT, 100.0)   # NOAA single exposure
        self.assertEqual(tox.OTU_DAILY_LIMIT, 300.0)  # Repex daily dose
