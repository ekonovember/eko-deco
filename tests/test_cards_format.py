"""The printed card carries the same numbers as the planner.

`deco.cards` is a layout engine: it computes nothing and is fed numbers. That
is exactly where a notation drifts — someone reads the CLI's segment table,
copies the *hold* into a cell, and the card is quietly one ascent per stop out
of step with the schedule it claims to be.

`rows_from_scenarios` removes the transcription step by building the rows from
`deco plan --json`, and these tests pin that what lands in a cell is what
`buhlmann.stop_legs` says: the leg and the leave-at runtime.

Skips without matplotlib, like the other rendering suites.
"""

from __future__ import annotations

import json
import unittest

from deco import buhlmann as b
from deco import cli
from deco import report as rp

try:
    from deco import cards as mc
    _HAVE_CARDS = True
except Exception:                      # no matplotlib
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


@unittest.skipUnless(_HAVE_CARDS, "deco.cards (matplotlib) unavailable")
class TestCardMatchesThePlanner(unittest.TestCase):
    """The card carries the planner's own numbers, in MultiDeco's compressed
    layout (`examples/scenario_2` — depth rows, scenario columns, `min (run)`
    cells, the bottom depth carrying only its runtime)."""

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
        rows = mc.rows_from_scenarios([self.plan])
        cells = {float(label): c[0] for label, c, _sw in rows[1:]}
        legs = b.stop_legs(self.segs)
        self.assertEqual(len(cells), len(legs))
        for leg in legs:
            with self.subTest(depth=leg.depth):
                self.assertEqual(cells[leg.depth], (leg.leg, leg.run))
        self.assertNotEqual([l.leg for l in legs], [l.hold for l in legs])

    def test_first_row_is_the_bottom_carrying_only_its_runtime(self):
        """MultiDeco prints `32  (40)`: you do not hold on the bottom, you
        leave it at that runtime."""
        label, cells, switch = mc.rows_from_scenarios([self.plan])[0]
        self.assertEqual(label, "45")
        self.assertIsNone(switch)
        leg, run = cells[0]
        self.assertIsNone(leg)
        self.assertEqual(run, rp.runtime_min(self.plan["total_runtime_min"]
                                             - self.plan["tts_min"]))
        self.assertEqual(mc.cell(cells[0]), f"({run})")

    def test_card_agrees_with_the_wetnotes_card_and_the_cut_table(self):
        """Four renderings of one dive: CLI JSON, the card engine, the GUI's
        runtime card, and the contingency cut-table cell."""
        rows = mc.rows_from_scenarios([self.plan])
        card = {float(label): c[0] for label, c, _sw in rows[1:]}
        wet = {float(r[0][:-2]): (int(r[1]), int(r[2]))
               for r in rp.wetnotes_rows(self.segs)
               if r[1] not in ("-", "gas")}
        self.assertEqual(card, wet)
        cell = b.ContingencyCell(45.0, 25.0, self.segs).text()
        for depth, (leg, _run) in card.items():
            self.assertIn(f"{depth:g}:{leg:g}", cell)

    def test_gas_switches_are_flagged_on_the_row_they_apply_to(self):
        rows = mc.rows_from_scenarios([self.plan])
        flagged = {label: sw for label, _c, sw in rows if sw}
        # 21 m is a pass-through stop now (Baker's padding, DECISIONS #21),
        # so EAN50 is first breathed on a stop row rather than mid-ascent.
        self.assertEqual(flagged, {"21": "EAN50", "6": "O2"})

    def test_brackets_hug_their_digits(self):
        """`(42)`, never `( 42)` — alignment comes from where the two fields
        are drawn, not from padding inside them."""
        self.assertEqual(mc.cell_fields((2, 42)), ("2", "(42)"))
        self.assertEqual(mc.cell_fields((33, 104)), ("33", "(104)"))
        self.assertEqual(mc.cell_fields((None, 40)), ("", "(40)"))
        self.assertEqual(mc.cell_fields(None), ("", "-"))

    def test_a_depth_only_some_columns_reach_shows_a_dash(self):
        short, long_ = _plan_json("--time", "12"), _plan_json("--time", "35")
        rows = mc.rows_from_scenarios([short, long_])
        deepest = rows[1][1]
        self.assertIsNone(deepest[0], "shallow column should not reach it")
        self.assertIsNotNone(deepest[1])
        self.assertEqual(mc.cell(deepest[0]), "-")

    def test_a_real_seven_stop_schedule_still_fits_the_card(self):
        """The layout was drawn around three stops; a trimix dive has seven,
        and an overflowing table writes rows over the summary — on the one
        artifact that goes underwater."""
        rows = mc.rows_from_scenarios([self.plan])
        self.assertGreaterEqual(len(rows), 7)
        size = mc.fit_size(len(rows) + 1)
        used = (len(rows) + 1) * (size * 0.62 + 0.55)
        self.assertLessEqual(used, mc.TABLE_H + 1e-9)
        self.assertGreater(size, 3.6, "type would be too small to read wet")

    def _spec(self, **kw):
        spec = {"tag": "T", "subtitle": "s", "columns": ["OK"],
                "rows": mc.rows_from_scenarios([self.plan]),
                "warnings": self.plan["warnings"],
                "extra": [], "summary": "x", "footer": "y", "accent": "#222"}
        spec.update(kw)
        return spec

    def test_it_renders(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "c.pdf"
            mc.save_card(self._spec(), out)
            self.assertTrue(out.exists() and out.stat().st_size > 0)

    def test_a_card_cannot_be_rendered_without_its_warnings(self):
        """The printed card carries no disclaimer, so the model's warnings are
        the only caveat on it (DECISIONS.md #4, #5). `warnings` is therefore a
        required spec key, not an optional one: a renderer that forgets it
        fails loudly instead of printing a schedule with nothing on it. Pass []
        when the plan really is clean.
        """
        import tempfile
        from pathlib import Path
        spec = self._spec()
        del spec["warnings"]
        with tempfile.TemporaryDirectory() as d, self.assertRaises(KeyError):
            mc.save_card(spec, Path(d) / "c.pdf")

    def test_the_planners_warnings_reach_the_card(self):
        """A dive the model complains about must print the complaint. 45 m on
        air is over the gas-density ceiling; the card says so, in the planner's
        own wording."""
        deep = _plan_json("--depth", "45", "--time", "25", "--gas", "air")
        self.assertTrue(deep["warnings"], "expected a density warning")
        self.assertTrue(any("density" in w for w in deep["warnings"]))


if __name__ == "__main__":
    unittest.main()
