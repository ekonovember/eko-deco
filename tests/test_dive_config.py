"""Sanity checks for dive_config (the shared JSON config)."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import dive_config as dc


class TestDiveConfig(unittest.TestCase):
    def test_default_has_required_keys(self):
        cfg = dc.default_config()
        for k in ("levels", "gf_low", "gf_high",
                  "sac_normal", "sac_multiplier", "gases"):
            self.assertIn(k, cfg)
        self.assertTrue(any(g["role"] == "Bottom" for g in cfg["gases"]))
        self.assertTrue(cfg["levels"])

    def test_save_load_roundtrip(self):
        cfg = dc.default_config()
        cfg["levels"] = [{"depth_m": 51, "runtime_min": 25, "gas": None}]
        cfg["gases"] = [
            {"role": "Bottom", "o2": 21, "he": 35, "tank_l": 24},
            {"role": "Travel", "o2": 35, "he": 25, "tank_l": 11},
            {"role": "Deco", "o2": 50, "he": 0, "tank_l": 11},
        ]
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "cfg.json")
            dc.save(cfg, path)
            back = dc.load(path)
        self.assertEqual(back["levels"][0]["depth_m"], 51)
        self.assertEqual(len(back["gases"]), 3)
        self.assertEqual(back["gases"][1]["role"], "Travel")
        self.assertEqual(back["gases"][0]["pressure_bar"], 232)   # default applied

    def test_gas_tuples_include_tank_and_pressure(self):
        _b, _p, _gp, gases = dc.to_buhlmann(dc.default_config())
        role, _gas, tank, pressure = gases[0]
        self.assertEqual(role, "Bottom")
        self.assertGreater(tank, 0)
        self.assertGreater(pressure, 0)

    def test_plan_params_round_trip_and_apply(self):
        cfg = dc.default_config()
        cfg["ascent_rate"] = 9.0
        cfg["ppo2_deco"] = 1.5
        cfg["problem_minutes"] = 2.0
        _b, plan, gp, _g = dc.to_buhlmann(cfg)
        self.assertAlmostEqual(plan.ascent_rate, 9.0)
        self.assertAlmostEqual(plan.ppo2_deco, 1.5)
        self.assertAlmostEqual(gp.problem_minutes, 2.0)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.json")
            dc.save(cfg, path)
            back = dc.load(path)
        self.assertEqual(back["ascent_rate"], 9.0)
        self.assertEqual(back["ppo2_deco"], 1.5)
        self.assertEqual(back["problem_minutes"], 2.0)

    def test_load_missing_returns_default(self):
        missing = os.path.join(tempfile.gettempdir(), "no_such_dive_xyz.json")
        self.assertEqual(dc.load(missing)["levels"],
                         dc.default_config()["levels"])

    def test_levels_round_trip_with_per_level_gas(self):
        cfg = dc.default_config()
        cfg["levels"] = [
            {"depth_m": 120, "runtime_min": 20, "gas": {"o2": 10, "he": 70}},
            {"depth_m": 45, "runtime_min": 40, "gas": None},
        ]
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.json")
            dc.save(cfg, path)
            back = dc.load(path)
        levels = dc.levels_of(back)
        self.assertEqual(len(levels), 2)
        self.assertAlmostEqual(levels[0].depth, 120)
        self.assertAlmostEqual(levels[0].runtime, 20)
        self.assertAlmostEqual(levels[0].gas.fHe, 0.70)
        self.assertIsNone(levels[1].gas)          # None = "auto"

    def test_empty_levels_never_leaves_the_planner_without_a_dive(self):
        # A config can arrive with no levels (an empty list written by a GUI
        # mid-edit, or a hand-edited file); it must fall back to a real dive
        # rather than persist a profile with nothing in it.
        for cfg in ({"levels": []}, {}):
            merged = dc._merged(cfg)
            self.assertTrue(merged["levels"])
            self.assertTrue(dc.levels_of(merged))

    def test_legacy_square_config_migrates_to_one_level(self):
        # Pre-multilevel configs: a single depth + bottom time, where the time
        # already meant "runtime at the end of the bottom" — so it carries over.
        cfg = dc._merged({"depth_m": 40, "bottom_time_min": 22})
        self.assertEqual(cfg["levels"],
                         [{"depth_m": 40.0, "runtime_min": 22.0, "gas": None}])
        self.assertNotIn("depth_m", cfg)
        self.assertNotIn("bottom_time_min", cfg)
        level = dc.levels_of(cfg)[0]
        self.assertAlmostEqual(level.depth, 40)
        self.assertAlmostEqual(level.runtime, 22)

    def test_to_buhlmann_maps_roles(self):
        cfg = {
            "depth_m": 60, "bottom_time_min": 20, "gf_low": 30, "gf_high": 70,
            "sac_normal": 20, "sac_multiplier": 2.0, "problem_minutes": 1,
            "gases": [
                {"role": "Bottom", "o2": 10, "he": 70, "tank_l": 24},
                {"role": "Travel", "o2": 35, "he": 25, "tank_l": 11},
                {"role": "Deco", "o2": 50, "he": 0, "tank_l": 11},
            ],
        }
        bottom, plan, gp, gases = dc.to_buhlmann(cfg)
        self.assertAlmostEqual(bottom.fO2, 0.10)
        self.assertAlmostEqual(bottom.fHe, 0.70)
        self.assertEqual(len(plan.travel_gases), 1)
        self.assertEqual(len(plan.deco_gases), 1)
        self.assertAlmostEqual(plan.gf_low, 0.30)
        self.assertAlmostEqual(plan.gf_high, 0.70)
        self.assertAlmostEqual(gp.sac_multiplier, 2.0)
        self.assertEqual(len(gases), 3)

    def test_sac_multiplier_maps_to_gasplan(self):
        cfg = dc.default_config()
        cfg["sac_multiplier"] = 1.5
        _b, _p, gp, _g = dc.to_buhlmann(cfg)
        self.assertAlmostEqual(gp.sac_multiplier, 1.5)

    def test_legacy_sac_stress_migrates_to_multiplier(self):
        # Old configs stored an absolute distress SAC and a solo flag.
        cfg = dc._merged({"sac_normal": 20, "sac_stress": 30, "solo": True})
        self.assertAlmostEqual(cfg["sac_multiplier"], 1.5)
        self.assertNotIn("sac_stress", cfg)
        self.assertNotIn("solo", cfg)

    def test_disabled_gas_is_left_out_of_the_plan(self):
        cfg = dc.default_config()
        cfg["gases"][1]["enabled"] = False       # the EAN50 deco stage
        _b, plan, _gp, gases = dc.to_buhlmann(cfg)
        self.assertEqual(len(plan.deco_gases), 0)
        self.assertEqual(len(gases), 1)

    def test_enabled_flag_round_trips(self):
        cfg = dc.default_config()
        cfg["gases"][1]["enabled"] = False
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.json")
            dc.save(cfg, path)
            back = dc.load(path)
        self.assertTrue(back["gases"][0]["enabled"])
        self.assertFalse(back["gases"][1]["enabled"])

    def test_invalid_role_coerced_to_deco(self):
        cfg = dc.default_config()
        cfg["gases"] = [{"role": "Nonsense", "o2": 32, "he": 0, "tank_l": 11}]
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.json")
            dc.save(cfg, path)
            back = dc.load(path)
        self.assertEqual(back["gases"][0]["role"], "Deco")


if __name__ == "__main__":
    unittest.main()
