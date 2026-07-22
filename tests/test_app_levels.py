"""GUI level-window (from → to) behaviour.

The Levels list shows each level as a ``from → to`` runtime window (minutes
since the surface). ``from`` is the runtime the diver ARRIVES at the depth: it
is an independent, editable field. Left blank it means "auto" — arrive as soon
as the standard-rate descent/ascent allows (contiguous with the previous level,
the historical behaviour). Given a value it is carried as ``Level.start`` and
saved as ``start_min``. These tests pin that. They need Tk + matplotlib
(``app``); when either is missing — as on the headless CI that runs the
stdlib-only core — they skip, exactly like the compiled cross-check oracles.
"""

from __future__ import annotations

import unittest

try:
    import tkinter as tk
    import app
    _root = tk.Tk()
    _root.withdraw()
    _HAVE_GUI = True
except Exception:                       # no display, no tkinter, no matplotlib
    _HAVE_GUI = False
else:
    _root.destroy()


@unittest.skipUnless(_HAVE_GUI, "Tk/matplotlib GUI not available")
class TestLevelWindows(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = app.DecoApp(self.root)

    def tearDown(self):
        self.root.destroy()

    def test_from_defaults_to_blank_auto(self):
        # A freshly added level arrives automatically: its "from" is blank and
        # it plans as a contiguous level (Level.start is None).
        self.app._add_level_row(20, 60, recompute=False)
        self.assertEqual(self.app.level_rows[-1]["from"].get(), "")
        self.assertIsNone(self.app._row_levels()[-1].start)

    def test_explicit_from_becomes_level_start(self):
        self.app.level_rows[0]["from"].set("4")
        rl = self.app._row_levels()[0]
        self.assertEqual(rl.start, 4.0)
        lv = self.app._levels()[0]
        self.assertEqual(lv.start, 4.0)

    def test_editing_from_does_not_drag_neighbours(self):
        # Fields are independent now — no shared-boundary coupling.
        self.app._add_level_row(20, 60, recompute=False)
        before_prev_to = self.app.level_rows[0]["runtime"].get()
        self.app.level_rows[1]["from"].set("40")
        self.assertEqual(self.app.level_rows[0]["runtime"].get(), before_prev_to)
        self.assertEqual(self.app.level_rows[1]["from"].get(), "40")

    def test_first_level_may_carry_an_explicit_start(self):
        # A surface hold is allowed on the first level too.
        self.app.level_rows[0]["from"].set("3")
        self.assertEqual(self.app.level_rows[0]["from"].get(), "3")

    def test_start_round_trips_through_collect_config(self):
        self.app.level_rows[0]["from"].set("4")
        out = self.app._collect_config()
        self.assertEqual(out["levels"][0]["start_min"], 4.0)
        # a blank "from" is omitted (auto/contiguous), not saved as 0
        self.app.level_rows[0]["from"].set("")
        out = self.app._collect_config()
        self.assertNotIn("start_min", out["levels"][0])

    def test_explicit_first_level_start_still_plans(self):
        # "at 16 m from minute 4": a surface hold, then descent, then flat.
        for row in list(self.app.level_rows):
            if row is not self.app.level_rows[0]:
                self.app._remove_level_row(row)
        self.app.level_rows[0]["depth"].set("16")
        self.app.level_rows[0]["runtime"].set("17")
        self.app.level_rows[0]["from"].set("4")
        self.app.recompute()
        self.assertTrue(self.app._plan_ok)


@unittest.skipUnless(_HAVE_GUI, "Tk/matplotlib GUI not available")
class TestGeometryClamp(unittest.TestCase):
    """A window geometry saved on a monitor that is no longer attached — or that
    lands in a gap between vertically offset monitors — must be pulled onto a
    real screen, so its title bar is always reachable. Monitors are stubbed so
    the test is independent of the real layout."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self._orig = app._monitor_workareas
        # a three-monitor desktop: primary, a left screen at negative X whose top
        # is offset DOWN to y=115, and a right screen offset UP to y=-129 — so the
        # bounding box has gaps not covered by any monitor.
        app._monitor_workareas = lambda root: [
            (0, 0, 1920, 1032),        # primary
            (-1920, 115, 0, 1147),     # left, top offset to 115
            (1920, -129, 3456, 687),   # right, top offset to -129
        ]

    def tearDown(self):
        app._monitor_workareas = self._orig
        self.root.destroy()

    def test_offscreen_left_is_pulled_back(self):
        # Tk writes a negative-left position as "+-2557"; it must land on-screen.
        self.assertEqual(app.clamp_geometry(self.root, "1920x989+-2557+64"),
                         "1920x989+-1920+115")

    def test_titlebar_in_a_gap_snaps_to_the_monitor(self):
        # +-1920+64: on the left monitor's X but ABOVE its top (115) — a dead
        # zone. Must drop onto the left monitor's work area.
        self.assertEqual(app.clamp_geometry(self.root, "1920x989+-1920+64"),
                         "1920x989+-1920+115")

    def test_onscreen_is_untouched(self):
        self.assertEqual(app.clamp_geometry(self.root, "1200x800+100+100"),
                         "1200x800+100+100")

    def test_window_straddling_monitors_snaps_fully_onto_one(self):
        # a full-width window nudged to x=100 would spill onto the next monitor;
        # it is pulled fully onto the primary work area.
        self.assertEqual(app.clamp_geometry(self.root, "1920x989+100+100"),
                         "1920x989+0+43")

    def test_size_only_passes_through(self):
        self.assertEqual(app.clamp_geometry(self.root, "1500x900"), "1500x900")

    def test_oversized_is_capped_to_a_monitor(self):
        # snaps to the primary and is capped to its work area
        self.assertEqual(app.clamp_geometry(self.root, "99999x99999+100+100"),
                         "1920x1032+0+0")


if __name__ == "__main__":
    unittest.main()
