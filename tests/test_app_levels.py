"""GUI Levels-list behaviour.

The Levels list is depth + cumulative runtime, nothing else: levels are
contiguous, so the transit to a level is part of that level's runtime (no
planner has an arrival time — MultiDeco rejects a level time that cannot cover
the descent/ascent). These tests pin that the rows persist exactly as typed and
never grow a third field again. They need Tk + matplotlib (``app``); when either
is missing — as on the headless CI that runs the stdlib-only core — they skip,
exactly like the compiled cross-check oracles.
"""

from __future__ import annotations

import unittest

try:
    import tkinter as tk

    from deco import app
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

    def test_level_rows_are_depth_and_runtime_only(self):
        # No "from"/arrival field: a row is exactly what gets planned and saved.
        self.app._add_level_row(20, 60, recompute=False)
        row = self.app.level_rows[-1]
        self.assertEqual(set(row) - {"widgets"}, {"depth", "runtime"})
        rl = self.app._row_levels()[-1]
        self.assertEqual((rl.depth, rl.runtime), (20.0, 60.0))
        self.assertFalse(hasattr(rl, "start"))

    def test_editing_one_row_does_not_drag_neighbours(self):
        self.app._add_level_row(20, 60, recompute=False)
        before = self.app.level_rows[0]["runtime"].get()
        self.app.level_rows[1]["runtime"].set("70")
        self.assertEqual(self.app.level_rows[0]["runtime"].get(), before)
        self.assertEqual(self.app.level_rows[1]["runtime"].get(), "70")

    def test_rows_round_trip_through_collect_config(self):
        self.app.level_rows[0]["depth"].set("26")
        self.app.level_rows[0]["runtime"].set("16")
        out = self.app._collect_config()
        self.assertEqual(out["levels"][0],
                         {"depth_m": 26.0, "runtime_min": 16.0})

    def test_a_blanked_field_keeps_the_level(self):
        # Persistence saves what was typed: a field cleared mid-edit must not
        # delete the row (see CLAUDE.md — _row_levels vs _levels).
        self.app._add_level_row(20, 60, recompute=False)
        n = len(self.app.level_rows)
        self.app.level_rows[-1]["runtime"].set("")
        self.assertEqual(len(self.app._row_levels()), n)
        self.assertEqual(len(self.app._levels()), n - 1)

    def test_contiguous_multilevel_plans(self):
        for row in list(self.app.level_rows[1:]):
            self.app._remove_level_row(row)
        self.app.level_rows[0]["depth"].set("26")
        self.app.level_rows[0]["runtime"].set("16")
        self.app._add_level_row(36, 33, recompute=False)
        self.app.recompute()
        self.assertTrue(self.app._plan_ok)
        # one bottom segment per level — never a repeated depth on the card
        from deco import buhlmann as b

        segs, _ = b.plan_multilevel(
            self.app._levels(), self.app._bottom_gas(), self.app._make_plan())
        self.assertEqual([s.depth_start for s in segs if s.kind == "bottom"],
                         [26.0, 36.0])


@unittest.skipUnless(_HAVE_GUI, "Tk/matplotlib GUI not available")
class TestEnvironmentAndDecoSacWidgets(unittest.TestCase):
    """Water type / altitude / surface pressure / deco SAC in the GUI. The
    stored truth is msw-per-bar and surface pressure; the dropdown and the
    altitude box only write them, so a hand-typed constant (MultiDeco's 1.0 bar
    surface, say) has to survive a save/load round trip untouched."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = app.DecoApp(self.root)

    def tearDown(self):
        self.root.destroy()

    def test_defaults_are_sea_level_salt_and_one_sac(self):
        from deco import buhlmann as b

        cfg = self.app._collect_config()
        self.assertEqual(cfg["msw_per_bar"], b.MSW_PER_BAR)
        self.assertEqual(cfg["surface_p_bar"], b.P_ATM)
        self.assertIsNone(cfg["sac_deco"])

    def test_water_dropdown_writes_msw_per_bar(self):
        from deco import buhlmann as b

        self.app.water.set("fresh")
        self.assertAlmostEqual(float(self.app.msw_per_bar.get()),
                               b.MSW_PER_BAR_FRESH, places=3)
        self.assertAlmostEqual(self.app._make_plan().msw_per_bar,
                               b.MSW_PER_BAR_FRESH, places=3)

    def test_altitude_writes_surface_pressure(self):
        from deco import buhlmann as b

        self.app.altitude.set("1500")
        self.assertAlmostEqual(float(self.app.surface_p.get()),
                               b.surface_p_at_altitude(1500), places=4)
        self.assertLess(self.app._make_plan().surface_p, b.P_ATM)

    def test_hand_typed_environment_round_trips(self):
        from deco import buhlmann as b

        self.app.msw_per_bar.set("10.33")
        self.app.surface_p.set("1")
        self.app.sac_deco.set("16")
        cfg = self.app._collect_config()
        self.assertAlmostEqual(cfg["msw_per_bar"], 10.33)
        self.assertEqual(cfg["surface_p_bar"], 1.0)
        self.assertEqual(cfg["sac_deco"], 16.0)
        self.app._apply_config(cfg)
        self.assertAlmostEqual(float(self.app.msw_per_bar.get()), 10.33)
        self.assertEqual(float(self.app.surface_p.get()), 1.0)
        self.assertEqual(float(self.app.sac_deco.get()), 16.0)
        # a value that is neither preset is labelled, not silently snapped
        self.assertEqual(self.app.water.get(), "custom")
        self.assertAlmostEqual(self.app._make_plan().msw_per_bar, 10.33)
        self.assertEqual(b.altitude_at_surface_p(1.0) > 0, True)

    def test_zero_deco_sac_means_one_rate(self):
        self.app.sac_deco.set("0")
        self.assertIsNone(self.app._gas_plan().sac_deco)
        self.app.sac_deco.set("12")
        self.assertEqual(self.app._gas_plan().sac_deco, 12.0)


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
