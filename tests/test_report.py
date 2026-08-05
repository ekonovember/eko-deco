"""Tests for the shared report layer (report.py)."""
from __future__ import annotations

import math
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


class TestWetnotesRows(unittest.TestCase):
    """The printable runtime card's row format (report.wetnotes_rows).

    Verified against two real MultiDeco 4.24 exports — examples/scenario_1 and
    examples/scenario_2, whose schedules are pinned in shearwater_golden.json.
    """

    def _scenario_1(self):
        plan = b.DivePlan(gf_low=0.40, gf_high=0.85, descent_rate=8.0,
                          ascent_rate=9.0,
                          deco_gases=(b.Gas(0.50), b.Gas(1.0)))
        return b.plan_dive(32, 40, b.Gas(0.36), plan)[0]

    def test_stop_column_reconciles_with_the_run_column(self):
        """The property the format exists for: a diver adding the STOP column
        up lands on the printed runtime instead of a minute early.

        The clock runs bottom row → stop → stop. A gas-switch row is an
        annotation carrying the runtime of the switch, not a row the legs are
        measured from — that is what keeps the card, the GUI stop table and the
        cut table printing identical minutes (see `buhlmann.StopLeg`)."""
        for segs in (self._scenario_1(),
                     b.plan_dive(45, 25, b.AIR,
                                 b.DivePlan(deco_gases=(b.Gas(0.50),)))[0]):
            rows = rp.wetnotes_rows(segs)
            prev_run = 0
            for depth, stop, run, _gas in rows:
                if stop == "gas":               # annotation; clock unaffected
                    continue
                run_i = int(run)
                if stop != "-":
                    self.assertEqual(int(stop), run_i - prev_run,
                                     f"row {depth}: STOP {stop} != "
                                     f"{run_i} - {prev_run}")
                prev_run = run_i

    def test_scenario_1_matches_the_multideco_rows(self):
        rows = rp.wetnotes_rows(self._scenario_1())
        self.assertEqual([r[:3] for r in rows], [
            ["32 m", "-", "40"],     # bottom, leaving at runtime 40
            ["21 m", "gas", "41"],   # EAN50 switch on the way up (annotation)
            ["9 m", "3", "43"],      # MultiDeco: 9 m, leaves at (43)  — same
            ["6 m", "1", "44"],      # MultiDeco: 6 m 1:00, leaves at (44) — same
            ["3 m", "3", "47"],      # MultiDeco: 3 m 4:00, leaves at (48)
            ["surf", "-", "47"],
        ])

    def test_runs_are_truncated_not_rounded(self):
        """MultiDeco's convention, re-confirmed by both exports: the runtime
        cell is the floor, so a stop is never printed as finishing early."""
        rows = rp.wetnotes_rows(self._scenario_1())
        self.assertEqual(rows[-1][2], "47")     # true total runtime 47.56

    def test_gas_switch_without_a_stop_still_gets_a_row(self):
        rows = rp.wetnotes_rows(self._scenario_1())
        switch = [r for r in rows if r[1] == "gas"]
        self.assertEqual(len(switch), 1)
        self.assertEqual(switch[0][0], "21 m")
        self.assertEqual(switch[0][3], "EAN50")

    def test_no_deco_dive_is_bottom_then_surface(self):
        segs, _ = b.plan_dive(18, 30, b.AIR)
        rows = rp.wetnotes_rows(segs)
        self.assertEqual([r[0] for r in rows], ["18 m", "surf"])


class TestOneNotationEverywhere(unittest.TestCase):
    """Every view of one dive prints the same numbers for the same thing.

    The runtime card, the GUI's stop table and the contingency cut table are
    three renderings of one schedule, and they used to disagree: the card
    showed the *leg* (ascent to the stop plus the hold, per DECISIONS.md #17)
    while the other two showed the bare hold, so the same 3 m stop read as
    "4" on the card and "3" in the results table. All three now render
    `buhlmann.stop_legs`.
    """

    def _dive(self):
        plan = b.DivePlan(gf_low=0.40, gf_high=0.85, descent_rate=8.0,
                          ascent_rate=9.0,
                          deco_gases=(b.Gas(0.50), b.Gas(1.0)))
        return b.plan_dive(32, 40, b.Gas(0.36), plan)[0]

    def test_run_is_when_you_leave_the_stop(self):
        """The definition worth being sure of: `run` is the moment you leave,
        so it is the arrival runtime plus the hold — never the arrival."""
        segs = self._dive()
        run = 0.0
        arrivals, departures = [], []
        for s in segs:
            if s.kind == "stop" and s.duration > 0:
                arrivals.append(run)
                departures.append(run + s.duration)
            run += s.duration
        for leg, arrive, leave in zip(b.stop_legs(segs), arrivals, departures,
                                      strict=True):
            self.assertEqual(leg.run, rp.runtime_min(leave))
            self.assertNotEqual(leg.run, rp.runtime_min(arrive))
            self.assertAlmostEqual(leave - arrive, leg.hold, places=9)

    def test_card_and_stop_table_agree_stop_for_stop(self):
        segs = self._dive()
        card = {r[0]: (r[1], r[2]) for r in rp.wetnotes_rows(segs)
                if r[1] not in ("-", "gas")}
        table = {f"{leg.depth:.0f} m": (str(leg.leg), str(leg.run))
                 for leg in b.stop_legs(segs)}
        self.assertEqual(card, table)

    def test_cut_table_cell_uses_the_same_legs(self):
        segs = self._dive()
        cell = b.ContingencyCell(32.0, 40.0, segs).text()
        for leg in b.stop_legs(segs):
            self.assertIn(f"{leg.depth:g}:{leg.leg:g}", cell)

    def test_legs_sum_to_the_runtime_in_every_view(self):
        segs = self._dive()
        run_bottom = rp.runtime_min(b.total_runtime(segs)
                                    - b.time_to_surface(segs))
        legs = b.stop_legs(segs)
        self.assertEqual(run_bottom + sum(l.leg for l in legs), legs[-1].run)

    def test_tts_rounds_up_while_runtimes_truncate(self):
        """Deliberately different directions: a runtime is a clock reading, a
        TTS is a budget you must not underestimate."""
        segs = self._dive()
        tts = b.time_to_surface(segs)
        cell = b.ContingencyCell(32.0, 40.0, segs).text()
        self.assertIn(f"{math.ceil(tts - 1e-9):g}′", cell)
        self.assertLess(rp.runtime_min(b.total_runtime(segs)),
                        b.total_runtime(segs))
