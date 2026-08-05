"""The printed card carries the same numbers as the planner.

`cards/make_cards.py` is a layout engine outside the package: it computes
nothing and is fed numbers. That is exactly where a notation drifts — someone
reads the CLI's segment table, copies the *hold* into a cell, and the card is
quietly one ascent per stop out of step with the schedule it claims to be.

`table_from_plans` removes the transcription step by building the rows from
`deco plan --json`, and these tests pin that what lands in a cell is what
`buhlmann.stop_legs` says: the leg and the leave-at runtime.

Skips without matplotlib, like the other rendering suites.
"""

from __future__ import annotations

import json
import math
import os
import sys
import unittest

from deco import buhlmann as b
from deco import cli
from deco import report as rp

_CARDS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "cards")
try:
    sys.path.insert(0, _CARDS)
    import make_cards as mc
    _HAVE_CARDS = True
except Exception:                      # no matplotlib, or cards/ not present
    _HAVE_CARDS = False


def _plan_json(*extra: str) -> dict:
    """One `deco plan --json` result, through the real CLI."""
    import contextlib
    import io
    out = io.StringIO()
    argv = ["plan", "--json", "--depth", "45", "--time", "25",
            "--gas", "21/35", "--deco-gas", "50", "--deco-gas", "100",
            "--descent-rate", "8", "--ascent-rate", "9",
            "--gf-low", "0.30", "--gf-high", "0.70", *extra]
    with contextlib.redirect_stdout(out):
        code = cli.main(argv)
    assert code == 0
    return json.loads(out.getvalue())


@unittest.skipUnless(_HAVE_CARDS, "cards/make_cards.py (matplotlib) unavailable")
class TestCardMatchesThePlanner(unittest.TestCase):
    def setUp(self):
        self.plan = _plan_json()
        self.segs = b.plan_dive(
            45, 25, b.Gas(0.21, 0.35),
            b.DivePlan(gf_low=0.30, gf_high=0.70, descent_rate=8.0,
                       ascent_rate=9.0,
                       deco_gases=(b.Gas(0.50), b.Gas(1.0))))[0]

    def test_cells_are_the_leg_and_the_leave_at_runtime(self):
        """Every stop cell is `(leg, run)` from `buhlmann.stop_legs` — not the
        hold, which is the error this bridge exists to make impossible."""
        _title, rows = mc.table_from_plans("t", [self.plan])
        cells = {float(label): cellv[0]
                 for label, cellv, kind in rows if kind == "stop"}
        legs = b.stop_legs(self.segs)
        self.assertEqual(len(cells), len(legs))
        for leg in legs:
            with self.subTest(depth=leg.depth):
                self.assertEqual(cells[leg.depth], (leg.leg, leg.run))
                # and the hold really is a different number on some stop, so
                # this test would catch a regression to it
        self.assertNotEqual([l.leg for l in legs], [l.hold for l in legs])

    def test_card_agrees_with_the_wetnotes_card_and_the_cut_table(self):
        """All four renderings of one dive: CLI JSON, the card engine, the
        GUI's runtime card, and the contingency cut-table cell."""
        _title, rows = mc.table_from_plans("t", [self.plan])
        card = {float(label): cellv[0]
                for label, cellv, kind in rows if kind == "stop"}
        wet = {float(r[0][:-2]): (int(r[1]), int(r[2]))
               for r in rp.wetnotes_rows(self.segs)
               if r[1] not in ("-", "gas")}
        self.assertEqual(card, wet)
        cell = b.ContingencyCell(45.0, 25.0, self.segs).text()
        for depth, (leg, _run) in card.items():
            self.assertIn(f"{depth:g}:{leg:g}", cell)

    def test_surface_row_truncates_and_tts_rounds_up(self):
        _title, rows = mc.table_from_plans("t", [self.plan])
        by_kind = {kind: cellv for _l, cellv, kind in rows}
        self.assertEqual(by_kind["sum"][0],
                         rp.runtime_min(self.plan["total_runtime_min"]))
        self.assertEqual(by_kind["tts"][0],
                         math.ceil(self.plan["tts_min"] - 1e-9))
        # opposite directions on purpose (DECISIONS.md #17)
        self.assertLessEqual(by_kind["sum"][0], self.plan["total_runtime_min"])
        self.assertGreaterEqual(by_kind["tts"][0], self.plan["tts_min"])

    def test_a_depth_only_some_columns_reach_shows_a_dash(self):
        short, long_ = _plan_json("--time", "12"), _plan_json("--time", "35")
        # --time is repeated; argparse keeps the last, so these really differ
        _title, rows = mc.table_from_plans("t", [short, long_], mark=1)
        stops = [(label, cellv) for label, cellv, kind in rows if kind == "stop"]
        deepest = stops[0][1]
        self.assertIsNone(deepest[0], "shallow column should not reach it")
        self.assertIsNotNone(deepest[1])

    def test_gas_line_names_each_switch_once_at_its_depth(self):
        line = mc.gas_line(self.plan)
        self.assertTrue(line.startswith("Trimix 21/35"))
        self.assertEqual(line.count("EAN50"), 1, f"duplicate switch in {line!r}")
        self.assertEqual(line.count("O2"), 1, f"duplicate switch in {line!r}")
        # short enough for the title strip beside a second table
        self.assertLessEqual(len(line), 40, line)

    def test_a_real_seven_stop_schedule_still_fits_the_card(self):
        """The layout was drawn around three stops; a trimix dive has seven,
        and an overflowing table writes the TTS row over the summary — on the
        one artifact that goes underwater."""
        _title, rows = mc.table_from_plans("t", [self.plan])
        self.assertGreaterEqual(len([r for r in rows if r[2] == "stop"]), 6)
        size = mc.fit_size(len(rows))
        used = len(rows) * (size * 0.62 + 0.55)
        self.assertLessEqual(used, mc.TABLE_H + 1e-9)
        self.assertGreater(size, 3.6, "type would be too small to read wet")
        # a short card still gets the full design size, not a ballooned one
        self.assertEqual(mc.fit_size(6), mc.SIZE_MAX)


if __name__ == "__main__":
    unittest.main()
