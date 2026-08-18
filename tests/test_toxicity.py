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
