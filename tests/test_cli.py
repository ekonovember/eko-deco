"""CLI boundary tests: argument validation and exit codes.

Run with: python -m unittest tests.test_cli
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import unittest

from deco import cli


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

    def test_negative_sac_rejected(self):
        code, _, _err = run_cli(["plan", "--depth", "30", "--time", "20",
                                 "--sac", "-20"])
        self.assertEqual(code, 2)

    def test_zero_divers_rejected(self):
        code, _, _err = run_cli(["plan", "--depth", "30", "--time", "20",
                                 "--sac", "18", "--divers", "0"])
        self.assertEqual(code, 2)

    def test_sac_multiplier_below_one_rejected(self):
        # validated by GasPlan, surfaced as a clean exit-2, not a traceback
        code, _, err = run_cli(["plan", "--depth", "30", "--time", "20",
                                "--sac", "18", "--sac-multiplier", "0.5"])
        self.assertEqual(code, 2)
        self.assertIn("multiplier", err)

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
