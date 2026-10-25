"""CLI boundary tests: argument validation and exit codes.

Run with: python -m unittest tests.test_cli
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from typing import ClassVar

from deco import buhlmann as b
from deco import cli
from deco import report as rp


def run_cli(argv):
    """(exit_code, stdout, stderr) for one CLI invocation. argparse errors
    raise SystemExit(2); cli returns int codes otherwise."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(argv)
        except SystemExit as e:
            code = e.code
    return code, out.getvalue(), err.getvalue()


class TestArgumentValidation(unittest.TestCase):
    def test_negative_depth_rejected(self):
        code, _, err = run_cli(["plan", "--depth", "-30", "--time", "20"])
        self.assertEqual(code, 2)
        self.assertIn("must be > 0", err)

    def test_zero_ascent_rate_rejected(self):
        code, _, err = run_cli(["plan", "--depth", "30", "--time", "20",
                                "--ascent-rate", "0"])
        self.assertEqual(code, 2)
        self.assertIn("must be > 0", err)

    def test_implausible_environment_rejected_cleanly(self):
        for flag, val, needle in (
                ("--p-h2o", "0.627", "p_h2o"),
                ("--surface-p", "1013", "surface_p"),
                ("--msw-per-bar", "1", "msw_per_bar"),
                ("--ascent-rate", "100", "ascent_rate")):
            code, _, err = run_cli(["plan", "--depth", "30", "--time", "20",
                                    flag, val])
            self.assertEqual(code, 2, msg=(flag, val))
            self.assertIn(needle, err)

    def test_negative_sac_rejected(self):
        code, _, _err = run_cli(["plan", "--depth", "30", "--time", "20",
                                 "--sac", "-20"])
        self.assertEqual(code, 2)

    def test_zero_divers_rejected(self):
        code, _, _err = run_cli(["plan", "--depth", "30", "--time", "20",
                                 "--sac", "18", "--divers", "0"])
        self.assertEqual(code, 2)

    def test_negative_emergency_sac_rejected(self):
        code, _, _err = run_cli(["plan", "--depth", "30", "--time", "20",
                                 "--sac", "18", "--sac-emergency", "-5"])
        self.assertEqual(code, 2)

    def test_negative_level_depth_rejected(self):
        code, _, _err = run_cli(["plan", "--level", "-30:20"])
        self.assertEqual(code, 2)

    def test_swapped_gfs_rejected(self):
        code, _, err = run_cli(["plan", "--depth", "30", "--time", "20",
                                "--gf-low", "0.9", "--gf-high", "0.3"])
        self.assertEqual(code, 2)
        self.assertIn("gradient factors", err)

    def test_gas_spec_extra_at_field_rejected(self):
        # 'air@24@232@99' silently dropped the 4th field before; now it errors.
        with self.assertRaises(ValueError):
            cli.parse_gas_spec("air@24@232@99")

    def test_a_fraction_typed_as_a_percentage_is_refused(self):
        # '--gas 0.32' planned a 0.32 % O2 mix labelled EAN0, and
        # '--deco-gas 1' a silent EAN1 with a 1590 m MOD; a config file has
        # refused the same typo since DECISIONS #9.
        for spec, hint in (("0.32", "32"), ("1", "100"), ("ean0.5", "50"),
                           ("0.21/0.35", "21")):
            with self.subTest(spec=spec):
                with self.assertRaises(ValueError) as cm:
                    cli.parse_gas(spec)
                self.assertIn(f"did you mean {hint}", str(cm.exception))

    def test_an_implausibly_lean_mix_is_refused(self):
        with self.assertRaises(ValueError):
            cli.parse_gas("3/80")

    def test_real_mixes_still_parse(self):
        for spec, fo2 in (("air", 0.21), ("o2", 1.0), ("100", 1.0),
                          ("ean32", 0.32), ("10/70", 0.10), ("5/90", 0.05)):
            with self.subTest(spec=spec):
                self.assertAlmostEqual(cli.parse_gas(spec).fO2, fo2)

    def test_the_cli_exits_2_on_a_fraction(self):
        for flag in ("--gas", "--deco-gas", "--travel-gas"):
            with self.subTest(flag=flag):
                code, _, err = run_cli(["plan", "--depth", "30", "--time", "20",
                                        flag, "0.5"])
                self.assertEqual(code, 2)
                self.assertIn("did you mean 50", err)

    def test_gas_spec_tank_and_pressure_ok(self):
        gas, tank, pressure = cli.parse_gas_spec("ean32@11@200")
        self.assertAlmostEqual(gas.fO2, 0.32)
        self.assertEqual((tank, pressure), (11.0, 200.0))


class TestHappyPath(unittest.TestCase):
    def test_plan_json_smoke(self):
        code, out, _ = run_cli(["plan", "--depth", "30", "--time", "25",
                                "--gas", "ean32", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertIn("segments", data)
        self.assertTrue(data["segments"])

    def test_ndl_json_smoke(self):
        code, out, _ = run_cli(["ndl", "--depth", "30", "--gas", "air",
                                "--json"])
        self.assertEqual(code, 0)
        self.assertIn("ndl_min", json.loads(out))


if __name__ == "__main__":
    unittest.main()


class TestSaveReloadRoundTrip(unittest.TestCase):
    """--save must write the clean schema (levels are pure depth/time periods,
    no per-level gas; gases carry no id) and a reload must reproduce the exact
    schedule."""

    def test_multilevel_round_trip_preserves_schedule(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "plan.json")
            code, out, _ = run_cli(["plan", "--level", "40:20", "--level",
                                    "21:35", "--gas", "air", "--deco-gas", "50",
                                    "--save", path, "--json"])
            self.assertEqual(code, 0)
            orig = json.loads(out)
            code, out, _ = run_cli(["plan", path, "--json"])
            self.assertEqual(code, 0)
            back = json.loads(out)
        self.assertEqual(orig["total_runtime_min"], back["total_runtime_min"])
        self.assertEqual([s["gas"] for s in orig["segments"]],
                         [s["gas"] for s in back["segments"]])

    def test_saved_config_has_clean_level_and_gas_schema(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "plan.json")
            code, _, _ = run_cli(["plan", "--level", "35:25",
                                  "--gas", "air", "--deco-gas", "50",
                                  "--save", path])
            self.assertEqual(code, 0)
            with open(path, encoding="utf-8") as fh:
                cfg = json.load(fh)
        for lvl in cfg["levels"]:
            self.assertEqual(set(lvl), {"depth_m", "runtime_min"})
        for g in cfg["gases"]:
            self.assertNotIn("id", g)
            self.assertIn(g["role"], ("Bottom", "Travel", "Deco"))


class TestEnvironmentFlags(unittest.TestCase):
    """--water / --msw-per-bar / --altitude / --surface-p / --sac-deco.

    These exist because two real MultiDeco plans (examples/scenario_1 and _2)
    are fresh-water dives at altitude and the CLI had no way to say so.
    """

    BASE: ClassVar[list[str]] = [
        "plan", "--depth", "32", "--time", "40", "--gas", "ean36",
        "--gf-low", "0.40", "--gf-high", "0.85", "--json"]

    def _plan(self, *extra):
        code, out, _ = run_cli([*self.BASE, *extra])
        self.assertEqual(code, 0)
        return json.loads(out)

    def test_defaults_are_sea_level_salt(self):
        got = self._plan()
        self.assertEqual(got["input"]["msw_per_bar"], b.MSW_PER_BAR)
        self.assertEqual(got["input"]["surface_p_bar"], b.P_ATM)

    def test_water_fresh_selects_the_fresh_constant(self):
        got = self._plan("--water", "fresh")
        self.assertAlmostEqual(got["input"]["msw_per_bar"], b.MSW_PER_BAR_FRESH)

    def test_explicit_msw_per_bar_wins_over_water(self):
        got = self._plan("--water", "fresh", "--msw-per-bar", "10.197")
        self.assertAlmostEqual(got["input"]["msw_per_bar"], 10.197)

    def test_altitude_sets_surface_pressure(self):
        got = self._plan("--altitude", "1500")
        self.assertAlmostEqual(got["input"]["surface_p_bar"],
                               b.surface_p_at_altitude(1500), places=9)
        self.assertLess(got["input"]["surface_p_bar"], b.P_ATM)

    def test_explicit_surface_p_wins_over_altitude(self):
        got = self._plan("--altitude", "1500", "--surface-p", "1.0")
        self.assertEqual(got["input"]["surface_p_bar"], 1.0)

    def test_altitude_lengthens_the_same_dive(self):
        """The whole point: less pressure overhead at the surface means the
        same loading sits closer to its ceiling, so deco gets longer."""
        sea = self._plan("--deco-gas", "50")
        alt = self._plan("--deco-gas", "50", "--altitude", "1500")
        self.assertGreater(alt["tts_min"], sea["tts_min"])

    def test_environment_reaches_the_reported_ppo2(self):
        """MultiDeco prints 1.47 ppO2 for EAN36 at 32 m in fresh water at
        1.0 bar; at our sea-level salt defaults the same gas reads 1.52."""
        fresh = self._plan("--water", "fresh", "--surface-p", "1.0")
        p = b.Gas(0.36).ppo2(32, fresh["input"]["surface_p_bar"],
                             fresh["input"]["msw_per_bar"])
        self.assertEqual(round(p, 2), 1.47)

    def test_environment_shows_in_the_text_header_only_when_it_differs(self):
        _c, plain, _e = run_cli(self.BASE[:-1])
        self.assertNotIn("Water:", plain)
        _c, fresh, _e = run_cli([*self.BASE[:-1], "--water", "fresh",
                                 "--altitude", "1500"])
        self.assertIn("Water: fresh", fresh)
        self.assertIn("1500 m altitude", fresh)

    def test_sac_deco_bills_the_deco_gas_separately(self):
        both = self._plan("--deco-gas", "50", "--sac", "20", "--sac-deco", "10")
        one = self._plan("--deco-gas", "50", "--sac", "20")
        by_gas = {c["gas"]: c for c in both["gas"]["cylinders"]}
        base = {c["gas"]: c for c in one["gas"]["cylinders"]}
        self.assertEqual(both["gas"]["sac_deco_l_min"], 10.0)
        # (the JSON rounds litres to 0.1, hence the delta)
        self.assertAlmostEqual(by_gas["EAN50"]["liters"],
                               base["EAN50"]["liters"] / 2.0, delta=0.1)
        # the bottom gas is untouched by the deco rate
        self.assertAlmostEqual(by_gas["EAN36"]["liters"],
                               base["EAN36"]["liters"], delta=0.1)

    def test_zero_sac_deco_rejected(self):
        code, _, _err = run_cli(["plan", "--depth", "30", "--time", "20",
                                 "--sac", "20", "--sac-deco", "0"])
        self.assertEqual(code, 2)

    def test_environment_and_sac_deco_survive_a_save_load_round_trip(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "plan.json")
            code, _, _ = run_cli(["plan", "--depth", "32", "--time", "40",
                                  "--gas", "ean36", "--deco-gas", "50",
                                  "--water", "fresh", "--altitude", "1500",
                                  "--sac", "20", "--sac-deco", "16",
                                  "--save", path])
            self.assertEqual(code, 0)
            with open(path, encoding="utf-8") as fh:
                cfg = json.load(fh)
            self.assertAlmostEqual(cfg["msw_per_bar"], b.MSW_PER_BAR_FRESH)
            self.assertAlmostEqual(cfg["surface_p_bar"],
                                   b.surface_p_at_altitude(1500))
            self.assertEqual(cfg["sac_deco"], 16.0)
            code, out, _ = run_cli(["plan", path, "--json"])
            self.assertEqual(code, 0)
            back = json.loads(out)
        self.assertAlmostEqual(back["input"]["msw_per_bar"], b.MSW_PER_BAR_FRESH)
        self.assertAlmostEqual(back["input"]["surface_p_bar"],
                               b.surface_p_at_altitude(1500))
        self.assertEqual(back["gas"]["sac_deco_l_min"], 16.0)


class TestPlanReadouts(unittest.TestCase):
    """SurfGF, the gas stack, EAD and the backup line reach the CLI's two
    projections. They are computed once in `report`, so this checks the wiring,
    not the arithmetic."""

    ARGV: ClassVar[list[str]] = [
        "plan", "--depth", "45", "--time", "25", "--gas", "21/35",
        "--deco-gas", "50", "--deco-gas", "100",
    ]

    def _json(self):
        code, out, _ = run_cli([*self.ARGV, "--json"])
        self.assertEqual(code, 0)
        return json.loads(out)

    def test_json_carries_the_new_keys(self):
        data = self._json()
        self.assertIn("surf_gf", data)
        self.assertIn("backup_line", data)
        self.assertEqual([r["gas"] for r in data["gas_stack"]],
                         ["Trimix 21/35", "EAN50", "O2"])
        self.assertTrue(all("ead_m" in s for s in data["stops"]))

    def test_surf_gf_is_a_fraction_within_gf_high(self):
        data = self._json()
        self.assertLessEqual(data["surf_gf"], 0.70 + 1e-9)
        self.assertGreater(data["surf_gf"], 0.0)

    def test_backup_line_agrees_with_the_stops(self):
        data = self._json()
        for stop in data["stops"]:
            self.assertIn(f"{stop['depth_m']:.0f}m/{stop['leg_min']:d}'",
                          data["backup_line"])

    def test_text_output_shows_them_too(self):
        code, out, _ = run_cli(self.ARGV)
        self.assertEqual(code, 0)
        self.assertIn("SurfGF", out)
        self.assertIn("Backup line:", out)
        self.assertIn("gas stack", out)


class TestGasEstimatesAreAlwaysThere(unittest.TestCase):
    """Gas is part of a plan, not an extra unlocked by remembering --sac.

    Before this, a `deco plan` without --sac printed a schedule and no litres
    at all — the one number a diver has to check against a cylinder was the
    easiest one to leave out (DECISIONS.md #28).
    """

    ARGV: ClassVar[list[str]] = [
        "plan", "--depth", "40", "--time", "25", "--gas", "air@24@232",
        "--deco-gas", "50@11@200",
    ]

    def _json(self, *extra):
        code, out, _ = run_cli([*self.ARGV, *extra, "--json"])
        self.assertEqual(code, 0)
        return json.loads(out)

    def test_no_sac_still_reports_gas_at_the_default_rate(self):
        data = self._json()
        self.assertEqual(data["gas"]["sac_normal_l_min"], rp.DEFAULT_SAC)
        self.assertTrue(data["gas"]["sac_assumed"])
        self.assertTrue(all(c["liters"] > 0 for c in data["gas"]["cylinders"]))

    def test_the_text_says_the_sac_was_assumed(self):
        code, out, _ = run_cli(self.ARGV)
        self.assertEqual(code, 0)
        self.assertIn(f"SAC {rp.DEFAULT_SAC:g} L/min assumed", out)
        code, given, _ = run_cli([*self.ARGV, "--sac", "18"])
        self.assertEqual(code, 0)
        self.assertNotIn("assumed", given)

    def test_a_given_sac_is_not_flagged_as_assumed(self):
        data = self._json("--sac", "18")
        self.assertEqual(data["gas"]["sac_normal_l_min"], 18.0)
        self.assertFalse(data["gas"]["sac_assumed"])


class TestEmergencyBlock(unittest.TestCase):
    """--emergency / --no-emergency, and what each shape prints."""

    ARGV: ClassVar[list[str]] = [
        "plan", "--depth", "40", "--time", "25", "--gas", "air@24@232",
        "--deco-gas", "50@11@200", "--sac", "20",
    ]

    def _json(self, *extra):
        code, out, _ = run_cli([*self.ARGV, *extra, "--json"])
        self.assertEqual(code, 0)
        return json.loads(out)

    def test_on_by_default(self):
        data = self._json()
        self.assertTrue(data["gas"]["emergency"])
        self.assertIn("rock_bottom_l", data["gas"])
        self.assertTrue(all("liters_emergency" in c
                            for c in data["gas"]["cylinders"]))

    def test_off_removes_the_keys_rather_than_zeroing_them(self):
        data = self._json("--no-emergency")
        self.assertFalse(data["gas"]["emergency"])
        self.assertNotIn("rock_bottom_l", data["gas"])
        self.assertNotIn("sac_emergency_l_min", data["gas"])
        for c in data["gas"]["cylinders"]:
            self.assertNotIn("liters_emergency", c)
            self.assertNotIn("bar_used_emergency", c)
            self.assertGreater(c["liters"], 0)      # the baseline stays

    def test_off_removes_it_from_the_text_too(self):
        code, on, _ = run_cli(self.ARGV)
        self.assertEqual(code, 0)
        self.assertIn("Rock bottom:", on)
        self.assertIn("emrg", on)
        code, off, _ = run_cli([*self.ARGV, "--no-emergency"])
        self.assertEqual(code, 0)
        self.assertNotIn("Rock bottom:", off)
        self.assertNotIn("emrg ", off)
        self.assertIn("emergency reserve off", off)

    def test_the_emergency_sac_is_absolute_and_defaults_to_twice_the_sac(self):
        self.assertEqual(self._json()["gas"]["sac_emergency_l_min"], 40.0)
        self.assertEqual(
            self._json("--sac-emergency", "30")["gas"]["sac_emergency_l_min"],
            30.0)

    def test_two_divers_raise_every_reserve(self):
        one = {c["gas"]: c for c in self._json()["gas"]["cylinders"]}
        two = {c["gas"]: c
               for c in self._json("--divers", "2")["gas"]["cylinders"]}
        for gas in ("Air", "EAN50"):
            reserve1 = one[gas]["liters_emergency"] - one[gas]["liters"]
            reserve2 = two[gas]["liters_emergency"] - two[gas]["liters"]
            self.assertAlmostEqual(reserve2, 2 * reserve1, delta=0.2, msg=gas)

    def test_the_turn_pressure_follows_its_own_rule(self):
        data = self._json()
        self.assertEqual(data["gas"]["turn_rule"], "rock-bottom")
        self.assertAlmostEqual(data["gas"]["turn_reserve_bar"],
                               data["gas"]["rock_bottom_bar"], delta=0.2)
        thirds = self._json("--turn-rule", "thirds")
        self.assertEqual(thirds["gas"]["turn_rule"], "thirds")
        self.assertAlmostEqual(thirds["gas"]["turn_pressure_bar"],
                               232.0 * 2 / 3, delta=0.1)

    def test_the_turn_pressure_can_be_dropped_on_its_own(self):
        data = self._json("--no-turn-pressure")
        self.assertNotIn("turn_pressure_bar", data["gas"])
        self.assertIn("rock_bottom_bar", data["gas"])     # the reserve stays
        code, out, _ = run_cli([*self.ARGV, "--no-turn-pressure"])
        self.assertEqual(code, 0)
        self.assertIn("Rock bottom:", out)
        self.assertNotIn("turn", out)

    def test_an_unknown_turn_rule_is_refused(self):
        code, _out, _err = run_cli([*self.ARGV, "--turn-rule", "halves"])
        self.assertEqual(code, 2)

    def test_thirds_under_the_reserve_is_said_out_loud(self):
        code, out, _ = run_cli([
            "plan", "--depth", "45", "--time", "20", "--gas", "21/35@12@200",
            "--deco-gas", "50@11@200", "--sac", "20", "--divers", "2",
            "--turn-rule", "thirds"])
        self.assertEqual(code, 0)
        self.assertIn("under the", out)

    def test_the_toggle_and_the_rate_survive_a_save_load_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "dive.json")
            code, _out, _err = run_cli([*self.ARGV, "--sac-emergency", "35",
                                        "--no-emergency", "--turn-rule",
                                        "thirds", "--save", path])
            self.assertEqual(code, 0)
            with open(path, encoding="utf-8") as fh:
                cfg = json.load(fh)
            self.assertEqual(cfg["sac_emergency"], 35.0)
            self.assertFalse(cfg["emergency"])
            self.assertEqual(cfg["turn_rule"], "thirds")
            code, out, _err = run_cli(["plan", path, "--json"])
            self.assertEqual(code, 0)
            self.assertFalse(json.loads(out)["gas"]["emergency"])


class TestDiveSeries(unittest.TestCase):
    """Repetitive dives from the CLI."""

    def test_a_series_plans_every_dive(self):
        code, out, _ = run_cli(["plan", "--dive", "30:25", "--dive", "30:25:60",
                                "--gas", "air", "--deco-gas", "50", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(len(data["dives"]), 2)
        self.assertIsNone(data["dives"][0]["surface_interval_min"])
        self.assertEqual(data["dives"][1]["surface_interval_min"], 60.0)

    def test_the_repeat_owes_more_deco_than_the_first_dive(self):
        code, out, _ = run_cli(["plan", "--dive", "30:25", "--dive", "30:25:30",
                                "--gas", "air", "--deco-gas", "50", "--json"])
        self.assertEqual(code, 0)
        first, second = json.loads(out)["dives"]
        self.assertGreater(second["tts_min"], first["tts_min"])

    def test_a_longer_surface_interval_owes_less(self):
        def tts(si):
            _c, out, _e = run_cli(["plan", "--dive", "30:25",
                                   "--dive", f"30:25:{si}", "--gas", "air",
                                   "--deco-gas", "50", "--json"])
            return json.loads(out)["dives"][1]["tts_min"]
        self.assertGreater(tts(15), tts(120))

    def test_a_single_dive_keeps_the_flat_json_shape(self):
        """Nothing that reads `deco plan --json` today should have to learn
        about series."""
        code, out, _ = run_cli(["plan", "--depth", "30", "--time", "25",
                                "--gas", "air", "--json"])
        self.assertEqual(code, 0)
        self.assertNotIn("dives", json.loads(out))

    def test_dive_index_selects_one(self):
        code, out, _ = run_cli(["plan", "--dive", "30:25", "--dive", "30:25:60",
                                "--gas", "air", "--dive-index", "2", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(len(data["dives"]), 1)
        self.assertEqual(data["dives"][0]["dive"], 2)

    def test_dive_index_outside_the_series_is_an_error(self):
        code, _out, err = run_cli(["plan", "--dive", "30:25", "--gas", "air",
                                   "--dive-index", "3"])
        self.assertEqual(code, 2)
        self.assertIn("outside the series", err)

    def test_dive_cannot_be_mixed_with_depth_time(self):
        code, _out, err = run_cli(["plan", "--dive", "30:25", "--depth", "30",
                                   "--time", "25", "--gas", "air"])
        self.assertEqual(code, 2)
        self.assertIn("cannot be combined", err)

    def test_the_first_dive_cannot_have_a_surface_interval(self):
        code, _out, err = run_cli(["plan", "--dive", "30:25:60", "--gas", "air"])
        self.assertEqual(code, 2)
        self.assertIn("nothing precedes it", err)

    def test_a_malformed_dive_spec_is_an_error(self):
        code, _out, err = run_cli(["plan", "--dive", "30", "--gas", "air"])
        self.assertEqual(code, 2)
        self.assertIn("DEPTH:RUNTIME", err)

    def test_a_series_round_trips_through_a_saved_config(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "series.json")
            code, out, _ = run_cli(["plan", "--dive", "30:25",
                                    "--dive", "24:30:90", "--gas", "air",
                                    "--sac", "20", "--save", path, "--json"])
            self.assertEqual(code, 0)
            direct = json.loads(out)["dives"]
            code, out, _ = run_cli(["plan", path, "--json"])
            self.assertEqual(code, 0)
            back = json.loads(out)["dives"]
        self.assertEqual([d["tts_min"] for d in back],
                         [d["tts_min"] for d in direct])


_DAY = ["plan", "--dive", "30:25", "--dive", "30:25:60",
        "--dive", "24:30:30", "--gas", "air", "--deco-gas", "50"]


class TestDayTotals(unittest.TestCase):
    """A repetitive series accumulates the oxygen clocks (DECISIONS.md #33)."""

    SERIES = _DAY

    def test_text_prints_a_day_total(self):
        code, out, _ = run_cli(self.SERIES)
        self.assertEqual(code, 0)
        self.assertIn("Day total over 3 dives", out)
        self.assertIn("daily", out)

    def test_json_carries_day_totals(self):
        code, out, _ = run_cli([*self.SERIES, "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        totals = data["day_totals"]
        self.assertAlmostEqual(totals["otu"],
                               round(sum(d["otu"] for d in data["dives"]), 1),
                               places=0)
        self.assertGreater(totals["cns_pct"],
                           max(d["cns_pct"] for d in data["dives"]))

    def test_a_single_dive_has_no_day_block(self):
        _code, out, _ = run_cli(["plan", "--depth", "30", "--time", "25",
                                "--gas", "air"])
        self.assertNotIn("Day total", out)
        _code, out, _ = run_cli(["plan", "--depth", "30", "--time", "25",
                                "--gas", "air", "--json"])
        self.assertNotIn("day_totals", json.loads(out))

    def test_one_dive_of_a_series_shows_only_that_dive(self):
        code, out, _ = run_cli([*self.SERIES, "--dive-index", "2"])
        self.assertEqual(code, 0)
        self.assertNotIn("Day total", out)


class TestSafetySurface(unittest.TestCase):
    """The warnings are the whole safety surface, so the CLI must print them."""

    def test_the_no_stop_overshoot_is_warned(self):
        code, out, _ = run_cli(["plan", "--depth", "66", "--time", "5",
                                "--gas", "air", "--gf-low", "0.85",
                                "--gf-high", "0.85"])
        self.assertEqual(code, 0)
        self.assertIn("ceiling left", out)
        self.assertIn("SurfGF 95% exceeds GF-High", out)

    def test_cns_over_the_limit_is_warned(self):
        _code, out, _ = run_cli(["plan", "--depth", "40", "--time", "60",
                                "--gas", "ean32", "--deco-gas", "100"])
        self.assertIn("over the NOAA single-exposure limit", out)

    def test_the_working_density_tier_is_warned(self):
        _code, out, _ = run_cli(["plan", "--depth", "32", "--time", "20",
                                "--gas", "air", "--deco-gas", "50"])
        self.assertIn("working limit", out)

    def test_lost_bottom_gas_states_the_finding_not_a_verdict(self):
        _code, out, _ = run_cli(["plan", "--depth", "30", "--time", "25",
                                "--gas", "ean32", "--deco-gas", "50"])
        self.assertIn("no schedule from depth", out)
        self.assertNotIn("NOT survivable", out)

    def test_a_deco_gas_used_as_travel_gas_is_noticed(self):
        _code, out, _ = run_cli(["plan", "--depth", "60", "--time", "20",
                                "--gas", "10/70", "--deco-gas", "50"])
        self.assertIn("used as travel gas", out)

    def test_notices_are_in_the_json(self):
        _code, out, _ = run_cli(["plan", "--depth", "60", "--time", "20",
                                "--gas", "10/70", "--deco-gas", "50", "--json"])
        self.assertTrue(json.loads(out)["notices"])

    def test_the_card_line_names_the_mix_at_each_switch(self):
        _code, out, _ = run_cli(["plan", "--depth", "45", "--time", "25",
                                "--gas", "21/35@24@232", "--deco-gas",
                                "50@11@200", "--deco-gas", "100@11@200",
                                "--sac", "18"])
        line = next(l for l in out.splitlines() if l.startswith("Stops as"))
        # the bar figures come off three different SPGs; each switch says which
        self.assertIn("EAN50", line)
        self.assertIn("O2", line)
