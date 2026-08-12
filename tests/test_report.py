"""Tests for the shared report layer (report.py)."""
from __future__ import annotations

import math
import unittest
from typing import ClassVar

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
        res = self._result(sac_emergency=36.0, problem_minutes=2.0)
        segs = res.segments
        gp = res.gas.plan
        for c in res.gas.cylinders:
            need = b.segment_gas_liters(
                [s for s in segs if s.gas == c.gas], gp.sac)
            reserve = b.emergency_gas_liters(segs, c.gas, gp, res.plan)
            self.assertAlmostEqual(c.liters_emergency, need + reserve, places=6)

    def test_the_baseline_sac_default_matches_the_config_schema(self):
        """One baseline rate across the front ends: a CLI run with no --sac and
        a first-launch GUI must plan the same litres."""
        from deco import dive_config as dc

        self.assertAlmostEqual(rp.DEFAULT_SAC,
                               dc.default_config()["sac_normal"])

    def test_emergency_off_reports_nothing_rather_than_zero(self):
        """The whole emergency block drops out — as None, never as 0.0. A zero
        reserve is a claim ("this dive needs none"); None is the truth ("not
        asked for"). DECISIONS.md #28."""
        res = self._result(emergency=False)
        self.assertFalse(res.gas.emergency)
        self.assertIsNone(res.gas.rock_bottom_l)
        self.assertIsNone(res.gas.rock_bottom_bar)
        self.assertIsNone(res.gas.turn_pressure_bar)
        for c in res.gas.cylinders:
            self.assertIsNone(c.liters_emergency)
            self.assertIsNone(c.bar_used_emergency)
            self.assertIsNone(c.bar_left_emergency)
            self.assertFalse(c.short_emergency)
            # …while the baseline accounting is untouched.
            self.assertGreater(c.liters, 0)
            self.assertIsNotNone(c.bar_used)

    def test_the_toggle_changes_nothing_else(self):
        """Turning the emergency block off must not move a planned litre."""
        on, off = self._result(), self._result(emergency=False)
        self.assertEqual([c.liters for c in on.gas.cylinders],
                         [c.liters for c in off.gas.cylinders])

    def test_two_divers_double_every_reserve_including_the_stage(self):
        """The scenario the emergency block exists for: a buddy out of gas
        breathes off the twinset to the switch and off the stage after it, so
        both reserves double (DECISIONS.md #28)."""
        one = self._result(sac_emergency=30.0, divers=1)
        two = self._result(sac_emergency=30.0, divers=2)
        for c1, c2 in zip(one.gas.cylinders, two.gas.cylinders, strict=True):
            reserve1 = c1.liters_emergency - c1.liters
            reserve2 = c2.liters_emergency - c2.liters
            self.assertGreater(reserve1, 0, msg=repr(c1.gas))
            self.assertAlmostEqual(reserve2, 2 * reserve1, places=6,
                                   msg=repr(c1.gas))

    def test_turn_pressure_can_be_hidden(self):
        self.assertIsNotNone(self._result().gas.turn_pressure_bar)
        off = self._result(turn_pressure=False)
        self.assertIsNone(off.gas.turn_pressure_bar)
        self.assertIsNone(off.gas.turn_reserve_bar)
        # …and the reserve itself is untouched: hiding the turn pressure is a
        # display choice, not a change of plan.
        self.assertAlmostEqual(off.gas.rock_bottom_l,
                               self._result().gas.rock_bottom_l, places=9)

    def test_the_emergency_switch_takes_the_turn_pressure_with_it(self):
        self.assertIsNone(self._result(emergency=False).gas.turn_pressure_bar)

    def test_rock_bottom_rule_surfaces_exactly_on_the_reserve(self):
        rep = self._result().gas
        self.assertAlmostEqual(rep.turn_reserve_bar, rep.rock_bottom_bar,
                               places=6)
        self.assertFalse(rep.turn_below_rock_bottom)

    def test_thirds_is_two_thirds_of_the_fill_whatever_the_profile(self):
        shallow = rp.compute_plan_result(
            [b.Level(18.0, 30.0)], b.AIR, b.DivePlan(),
            b.GasPlan(sac=20.0, turn_rule="thirds"),
            [("Bottom", b.AIR, 24.0, 232.0)])
        deep = self._result(turn_rule="thirds")
        for res in (shallow, deep):
            self.assertAlmostEqual(res.gas.turn_pressure_bar, 232.0 * 2 / 3,
                                   places=6)
            self.assertAlmostEqual(res.gas.turn_reserve_bar, 232.0 / 3,
                                   places=6)

    def test_thirds_is_flagged_when_a_third_does_not_cover_rock_bottom(self):
        """A rule of thumb that knows nothing about the profile can leave the
        team surfacing on less than minimum gas — 45 m for two divers on a
        single 12 L. Saying so is why both numbers are computed."""
        gp = b.GasPlan(sac=20.0, divers=2, turn_rule="thirds")
        res = rp.compute_plan_result(
            [b.Level(45.0, 20.0)], b.AIR, b.DivePlan(deco_gases=(b.EAN50,)),
            gp, [("Bottom", b.AIR, 12.0, 200.0),
                 ("Deco", b.EAN50, 11.0, 200.0)])
        self.assertTrue(res.gas.turn_below_rock_bottom)
        self.assertLess(res.gas.turn_reserve_bar, res.gas.rock_bottom_bar)

    def test_an_unknown_turn_rule_is_refused(self):
        with self.assertRaises(ValueError):
            b.GasPlan(sac=20.0, turn_rule="halves")

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


class TestGasReportTakesTheWholePlan(unittest.TestCase):
    """`gas_report` bills at `plan.surface_p` / `plan.msw_per_bar` and treats
    `plan.deco_gases` as the deco stack.

    Those three used to be optional parameters defaulting to sea-level salt
    water and an empty stack, and the GUI omitted all three (DECISIONS.md #24).
    Passing the plan is now the only way to call it, so the same omission would
    be a TypeError rather than a wrong number on a printed card.
    """

    EAN50 = b.Gas(0.50)

    def _dive(self, **kw):
        plan = b.DivePlan(deco_gases=(self.EAN50,), **kw)
        segs, _ = b.plan_dive(40, 25, b.AIR, plan)
        return segs, plan

    def _liters(self, rep):
        return {c.gas: c.liters for c in rep.cylinders}

    def test_deco_sac_bills_the_deco_cylinder(self):
        segs, plan = self._dive()
        gases = [("Bottom", b.AIR, 24.0, 232.0), ("Deco", self.EAN50, 11.0, 200.0)]
        one = rp.gas_report(segs, b.AIR, b.GasPlan(sac=20.0), gases, plan)
        two = rp.gas_report(segs, b.AIR,
                            b.GasPlan(sac=20.0, sac_deco=12.0), gases, plan)
        # The bottom gas is billed the same either way; only the deco mix moves,
        # and it moves by exactly the ratio of the two rates.
        self.assertAlmostEqual(self._liters(one)[b.AIR],
                               self._liters(two)[b.AIR], places=6)
        self.assertAlmostEqual(self._liters(two)[self.EAN50],
                               self._liters(one)[self.EAN50] * 12.0 / 20.0,
                               places=6)

    def test_the_environment_reaches_every_litre(self):
        """Fresh water at altitude is thinner gas per metre: the same schedule
        must not be billed at sea-level salt."""
        gases = [("Bottom", b.AIR, 24.0, 232.0), ("Deco", self.EAN50, 11.0, 200.0)]
        sea_segs, sea_plan = self._dive()
        alt_segs, alt_plan = self._dive(
            surface_p=b.surface_p_at_altitude(1500),
            msw_per_bar=b.MSW_PER_BAR_FRESH)
        gp = b.GasPlan(sac=20.0)
        sea = rp.gas_report(sea_segs, b.AIR, gp, gases, sea_plan)
        alt = rp.gas_report(alt_segs, b.AIR, gp, gases, alt_plan)
        self.assertLess(self._liters(alt)[b.AIR], self._liters(sea)[b.AIR])
        self.assertLess(alt.rock_bottom_l, sea.rock_bottom_l)

    def test_the_plan_is_required(self):
        segs, _plan = self._dive()
        with self.assertRaises(TypeError):
            rp.gas_report(segs, b.AIR, b.GasPlan(sac=20.0), [])  # type: ignore[call-arg]


class TestBackupLine(unittest.TestCase):
    """The one-line schedule is built from `stop_legs`, so it must agree with
    the card that comes off the same source."""

    @staticmethod
    def _dive():
        plan = b.DivePlan(gf_low=0.30, gf_high=0.70,
                          deco_gases=(b.EAN50, b.O2))
        segs, _ = b.plan_dive(45.0, 25.0, b.Gas(0.21, 0.35), plan)
        return segs

    def test_every_leg_matches_the_card(self):
        segs = self._dive()
        line = rp.backup_line(segs)
        for leg in b.stop_legs(segs):
            self.assertIn(f"{leg.depth:.0f}m/{leg.leg:d}'", line)

    def test_it_ends_at_the_truncated_total_runtime(self):
        segs = self._dive()
        run = rp.runtime_min(b.total_runtime(segs))
        self.assertTrue(rp.backup_line(segs).endswith(f"surf {run:d}"))

    def test_a_mix_is_named_only_where_it_changes(self):
        """A slate line repeating the mix on every row is unreadable; the
        switch is the thing worth writing down."""
        line = rp.backup_line(self._dive())
        self.assertEqual(line.count("EAN50"), 1)
        self.assertEqual(line.count("O2"), 1)

    def test_no_deco_dive_is_bottom_then_surface(self):
        segs, _ = b.plan_dive(18.0, 20.0, b.AIR, b.DivePlan())
        self.assertEqual(rp.backup_line(segs).count("->"), 1)


class TestGasStackTable(unittest.TestCase):
    def test_each_mix_is_quoted_at_its_own_mod(self):
        """Quoting the stack at the bottom depth would report a deco mix at a
        depth it is never switched to — the whole point of the table."""
        plan = b.DivePlan(deco_gases=(b.EAN50, b.O2))
        rows = rp.gas_stack_table(plan, b.AIR)
        by_gas = {r.gas: r for r in rows}
        self.assertAlmostEqual(
            by_gas[b.EAN50].mod_m,
            b.EAN50.mod(plan.ppo2_deco, plan.surface_p, plan.msw_per_bar))
        # the bottom gas is judged against the working ceiling, not the deco one
        self.assertAlmostEqual(
            by_gas[b.AIR].mod_m,
            b.AIR.mod(plan.ppo2_bottom, plan.surface_p, plan.msw_per_bar))

    def test_ead_is_the_n2_only_convention(self):
        plan = b.DivePlan(deco_gases=(b.EAN50,))
        row = next(r for r in rp.gas_stack_table(plan, b.AIR) if r.gas == b.EAN50)
        self.assertAlmostEqual(row.ead_m, b.EAN50.end(
            row.mod_m, plan.surface_p, plan.msw_per_bar, o2_narcotic=False))
        self.assertLess(row.ead_m, row.end_m)   # O2 narcotic is the deeper one

    def test_a_mix_listed_twice_appears_once(self):
        plan = b.DivePlan(travel_gases=(b.EAN50,), deco_gases=(b.EAN50, b.O2))
        rows = rp.gas_stack_table(plan, b.AIR)
        self.assertEqual(len(rows), 3)
        self.assertEqual([r.role for r in rows], ["Bottom", "Travel", "Deco"])

    def test_the_environment_reaches_the_table(self):
        """Altitude moves MOD and density; a stack table that ignored it would
        contradict the density warning beside it (DECISIONS #24)."""
        sea = rp.gas_stack_table(b.DivePlan(), b.AIR)[0]
        alt = rp.gas_stack_table(
            b.DivePlan(surface_p=b.surface_p_at_altitude(2000)), b.AIR)[0]
        self.assertGreater(alt.mod_m, sea.mod_m)


class TestPlanResultCarriesTheNewFigures(unittest.TestCase):
    def test_surf_gf_matches_the_model(self):
        plan = b.DivePlan(deco_gases=(b.EAN50,))
        res = rp.compute_plan_result([b.Level(40.0, 25.0)], b.AIR, plan)
        self.assertAlmostEqual(res.surf_gf,
                               b.surface_gf(res.tissues, plan.surface_p))

    def test_surface_ceiling_and_surf_gf_are_different_questions(self):
        """One is a depth left over, the other the budget spent. A dive that
        surfaces clean still spends most of its GF-High."""
        plan = b.DivePlan(gf_low=0.30, gf_high=0.70, deco_gases=(b.EAN50,))
        res = rp.compute_plan_result([b.Level(40.0, 25.0)], b.AIR, plan)
        self.assertAlmostEqual(res.surface_ceiling_m, 0.0, places=6)
        self.assertGreater(res.surf_gf, 0.3)


class TestLegPressures(unittest.TestCase):
    """The bar column an SPG gets checked against."""

    GASES: ClassVar[list] = [
        ("Bottom", b.AIR, 24.0, 232.0),
        ("Deco", b.EAN50, 11.0, 200.0),
    ]

    @staticmethod
    def _dive():
        plan = b.DivePlan(gf_low=0.30, gf_high=0.70, deco_gases=(b.EAN50,))
        segs, _ = b.plan_dive(40.0, 25.0, b.AIR, plan)
        return segs, plan

    def test_one_entry_per_stop_leg(self):
        """Index alignment with `stop_legs` is the whole contract — every
        renderer zips the two together."""
        segs, plan = self._dive()
        bars = rp.leg_pressures(segs, b.GasPlan(sac=20.0), self.GASES, plan)
        self.assertEqual(len(bars), len(b.stop_legs(segs)))

    def test_pressure_falls_monotonically_within_one_cylinder(self):
        segs, plan = self._dive()
        bars = rp.leg_pressures(segs, b.GasPlan(sac=20.0), self.GASES, plan)
        per_gas: dict = {}
        for leg, bar in zip(b.stop_legs(segs), bars, strict=True):
            if bar is None:
                continue
            if leg.gas in per_gas:
                self.assertLess(bar, per_gas[leg.gas])
            per_gas[leg.gas] = bar

    def test_the_last_stop_agrees_with_the_gas_report(self):
        """Same litres, same SAC, same environment — the card's final pressure
        and the GAS card's `bar_left` are one number seen twice."""
        segs, plan = self._dive()
        gp = b.GasPlan(sac=20.0, sac_deco=15.0)
        bars = rp.leg_pressures(segs, gp, self.GASES, plan)
        rep = rp.gas_report(segs, b.AIR, gp, self.GASES, plan)
        deco = next(c for c in rep.cylinders if c.gas == b.EAN50)
        last = [bar for leg, bar in zip(b.stop_legs(segs), bars, strict=True)
                if leg.gas == b.EAN50][-1]
        # The card stops at the last stop; the report bills the final ascent
        # too, so the report must be the lower of the two.
        assert deco.bar_left is not None
        self.assertLess(deco.bar_left, last)
        self.assertAlmostEqual(deco.bar_left, last, delta=5.0)

    def test_a_deco_cylinder_is_billed_at_the_deco_sac(self):
        segs, plan = self._dive()
        one = rp.leg_pressures(segs, b.GasPlan(sac=20.0), self.GASES, plan)
        two = rp.leg_pressures(segs, b.GasPlan(sac=20.0, sac_deco=10.0),
                               self.GASES, plan)
        legs = b.stop_legs(segs)
        deco = [i for i, leg in enumerate(legs) if leg.gas == b.EAN50]
        self.assertTrue(deco)
        for i in deco:
            self.assertGreater(two[i], one[i])   # slower breathing, more left

    def test_a_mix_with_no_cylinder_reads_none(self):
        segs, plan = self._dive()
        bars = rp.leg_pressures(segs, b.GasPlan(sac=20.0),
                                [("Bottom", b.AIR, 24.0, 232.0)], plan)
        legs = b.stop_legs(segs)
        for leg, bar in zip(legs, bars, strict=True):
            if leg.gas == b.EAN50:
                self.assertIsNone(bar)

    def test_no_gas_plan_means_no_pressures(self):
        segs, plan = self._dive()
        bars = rp.leg_pressures(segs, None, self.GASES, plan)
        self.assertEqual(bars, [None] * len(b.stop_legs(segs)))

    def test_wetnotes_rows_gain_the_column_only_when_asked(self):
        segs, plan = self._dive()
        bars = rp.leg_pressures(segs, b.GasPlan(sac=20.0), self.GASES, plan)
        self.assertTrue(all(len(r) == 4 for r in rp.wetnotes_rows(segs)))
        with_bar = rp.wetnotes_rows(segs, bars)
        self.assertTrue(all(len(r) == 5 for r in with_bar))
        # the surface row has no hold, so no gauge reading
        self.assertEqual(with_bar[-1][4], "")
