"""The bottom-timer contingency matrix (`deco.contingency`).

The cut table a gauge diver carries against a computer failure: the planned
dive and its neighbours on a fixed 3 min × 3 m grid, each cell in the same
printed notation as the runtime card (`buhlmann.stop_legs`), so a cut table and
a plan for the same profile can never disagree.
"""

from __future__ import annotations

import math
import re
import unittest

from deco import buhlmann as b
from deco import contingency as c


class TestContingency(unittest.TestCase):
    PLAN = b.DivePlan(deco_gases=(b.EAN50,))

    def _stops(self, segs):
        return [(s.depth_start, s.duration) for s in segs if s.kind == "stop"]

    def test_grid_shape_and_variants(self):
        # Rows = bottom-time variants, columns = depth variants, 3 min x 3 m.
        grid = c.contingency_schedules([b.Level(40, 20)], b.AIR, self.PLAN)
        self.assertEqual([len(row) for row in grid], [3, 3, 3])
        self.assertEqual([[(c.depth, c.bottom_time) for c in row]
                          for row in grid],
                         [[(37, 17), (40, 17), (43, 17)],
                          [(37, 20), (40, 20), (43, 20)],
                          [(37, 23), (40, 23), (43, 23)]])

    def test_step_counts_extend_the_grid(self):
        grid = c.contingency_schedules([b.Level(40, 20)], b.AIR, self.PLAN,
                                       time_before=0, time_after=2,
                                       depth_before=0, depth_after=1)
        self.assertEqual([c.bottom_time for row in grid for c in row[:1]],
                         [20, 23, 26])
        self.assertEqual([c.depth for c in grid[0]], [40, 43])

    def test_plan_cell_matches_plan_dive(self):
        grid = c.contingency_schedules([b.Level(40, 20)], b.AIR, self.PLAN)
        segs, _ = b.plan_dive(40, 20, b.AIR, self.PLAN)
        cell = grid[1][1]                      # planned time x planned depth
        self.assertEqual(self._stops(cell.segments), self._stops(segs))
        self.assertAlmostEqual(b.time_to_surface(cell.segments),
                               b.time_to_surface(segs))

    def test_tts_monotone_in_time_and_depth(self):
        grid = c.contingency_schedules([b.Level(40, 25)], b.AIR, self.PLAN)
        for row in grid:                       # deeper column -> more deco
            tts = [b.time_to_surface(c.segments) for c in row]
            self.assertEqual(tts, sorted(tts))
        for col in range(3):                   # longer row -> more deco
            tts = [b.time_to_surface(row[col].segments) for row in grid]
            self.assertEqual(tts, sorted(tts))

    def test_no_deco_variant_is_a_normal_cell(self):
        grid = c.contingency_schedules([b.Level(18, 20)], b.AIR)
        short = grid[0][0]                     # shortest x shallowest
        self.assertIsNotNone(short.segments)
        self.assertFalse(any(s.kind == "stop" for s in short.segments))
        self.assertIn("no deco", short.text())

    def test_unplannable_cell_keeps_its_place(self):
        # T - 3 = 1 min < the descent to 45 m: the whole shortened row is
        # unplannable, but the grid stays rectangular (3x3) with n/a cells.
        grid = c.contingency_schedules([b.Level(45, 4)], b.AIR)
        self.assertEqual([len(row) for row in grid], [3, 3, 3])
        self.assertIsNone(grid[0][1].segments)
        self.assertEqual(grid[0][1].text(), "n/a")
        self.assertIsNotNone(grid[1][1].segments)

    def test_zero_counts_disable_directions(self):
        grid = c.contingency_schedules([b.Level(40, 20)], b.AIR,
                                       time_before=0, time_after=0,
                                       depth_before=0, depth_after=0)
        self.assertEqual([len(row) for row in grid], [1])
        self.assertEqual((grid[0][0].depth, grid[0][0].bottom_time), (40, 20))

    def test_nonpositive_variants_are_dropped(self):
        # 2 min - 3 min and 3 m - 3 m would be <= 0: those rows/columns vanish
        # instead of appearing as unplannable cells.
        grid = c.contingency_schedules([b.Level(3, 2)], b.AIR)
        self.assertEqual([c.bottom_time for row in grid for c in row[:1]],
                         [2, 5])
        self.assertEqual([c.depth for c in grid[0]], [3, 6])

    def test_cell_text_lists_stops_and_tts(self):
        grid = c.contingency_schedules([b.Level(40, 25)], b.AIR, self.PLAN)
        cell = grid[1][1]
        self.assertTrue(any(s.kind == "stop" for s in cell.segments))
        self.assertRegex(cell.text(), r"^(\d+:\d+ )*\d+:\d+ · \d+′$")
        tts = int(re.search(r"· (\d+)′$", cell.text()).group(1))
        self.assertEqual(tts, math.ceil(b.time_to_surface(cell.segments) - 1e-9))

    def test_multilevel_flattens_to_conservative_square(self):
        levels = [b.Level(45, 20), b.Level(30, 35), b.Level(18, 50)]
        grid = c.contingency_schedules(levels, b.AIR, self.PLAN)
        cell = grid[1][1]
        self.assertEqual(cell.depth, b.max_depth(levels))
        self.assertEqual(cell.bottom_time, levels[-1].runtime)
        real, _ = b.plan_multilevel(levels, b.AIR, self.PLAN)
        self.assertGreaterEqual(b.time_to_surface(cell.segments),
                                b.time_to_surface(real))



if __name__ == "__main__":
    unittest.main()
