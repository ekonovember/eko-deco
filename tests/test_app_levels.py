"""GUI level-window (from → to) behaviour.

The Levels list shows each level as an explicit ``from → to`` runtime window
(minutes since the surface). Adjacent levels share a boundary, so the windows
are always contiguous and can never gap or overlap. These tests pin that
coupling. They need Tk + matplotlib (``app``); when either is missing — as on
the headless CI that runs the stdlib-only core — they skip, exactly like the
compiled cross-check oracles.
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

    def _froms(self):
        return [r["from"].get() for r in self.app.level_rows]

    def _tos(self):
        return [r["runtime"].get() for r in self.app.level_rows]

    def test_first_level_starts_at_the_beginning(self):
        self.assertEqual(self.app.level_rows[0]["from"].get(), "0")

    def test_windows_are_contiguous(self):
        tos = self._tos()
        self.assertEqual(self._froms(), ["0"] + tos[:-1])

    def test_editing_to_drags_the_next_from(self):
        self.app.level_rows[0]["runtime"].set("17")
        self.assertEqual(self.app.level_rows[1]["from"].get(), "17")

    def test_editing_from_drags_the_previous_to(self):
        self.app.level_rows[1]["from"].set("19")
        self.assertEqual(self.app.level_rows[0]["runtime"].get(), "19")

    def test_first_from_snaps_back_to_zero(self):
        self.app.level_rows[0]["from"].set("5")
        self.assertEqual(self.app.level_rows[0]["from"].get(), "0")

    def test_added_level_continues_from_the_last(self):
        last_to = self.app.level_rows[-1]["runtime"].get()
        self.app._add_level_row(20, 999, recompute=False)
        self.assertEqual(self.app.level_rows[-1]["from"].get(), last_to)

    def test_removing_a_level_re_derives_the_windows(self):
        while len(self.app.level_rows) < 2:
            self.app._add_level_row(20, 999, recompute=False)
        self.app._remove_level_row(self.app.level_rows[0])
        self.assertEqual(self.app.level_rows[0]["from"].get(), "0")


if __name__ == "__main__":
    unittest.main()
