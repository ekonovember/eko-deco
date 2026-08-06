"""Sanity checks for dive_config (the shared JSON config)."""
from __future__ import annotations

import os
import tempfile
import unittest
from typing import ClassVar

from deco import buhlmann as b
from deco import dive_config as dc


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

    def test_levels_round_trip_drops_legacy_per_level_gas(self):
        cfg = dc.default_config()
        cfg["levels"] = [
            {"depth_m": 120, "runtime_min": 20, "gas": {"o2": 10, "he": 70}},
            {"depth_m": 45, "runtime_min": 40, "gas_id": 2},
        ]
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.json")
            dc.save(cfg, path)
            back = dc.load(path)
        # Levels are pure depth/time periods now: any legacy gas reference is
        # dropped, and the stack is untouched (no parked entries).
        for lvl in back["levels"]:
            self.assertEqual(set(lvl), {"depth_m", "runtime_min"})
        self.assertEqual(len(back["gases"]), 2)
        levels = dc.levels_of(back)
        self.assertEqual(len(levels), 2)
        self.assertAlmostEqual(levels[0].depth, 120)
        self.assertAlmostEqual(levels[0].runtime, 20)

    def test_legacy_start_min_is_dropped_on_load(self):
        """Levels are contiguous now — the transit is part of the runtime, as in
        every other planner. An old config carrying an arrival time still loads;
        the key is simply dropped rather than silently changing the profile."""
        cfg = dc.default_config()
        cfg["levels"] = [{"depth_m": 16, "runtime_min": 17, "start_min": 4}]
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.json")
            dc.save(cfg, path)
            back = dc.load(path)
        self.assertNotIn("start_min", back["levels"][0])
        self.assertEqual(back["levels"][0],
                         {"depth_m": 16.0, "runtime_min": 17.0})
        lv = dc.levels_of(back)[0]
        self.assertEqual((lv.depth, lv.runtime), (16.0, 17.0))

    def test_legacy_inline_gas_is_dropped_not_parked(self):
        cfg = dc._merged({
            "gases": [{"role": "Bottom", "o2": 21, "he": 0},
                      {"role": "Deco", "o2": 50, "he": 0}],
            "levels": [{"depth_m": 21, "runtime_min": 30,
                        "gas": {"o2": 50, "he": 0}}],
        })
        self.assertEqual(set(cfg["levels"][0]), {"depth_m", "runtime_min"})
        self.assertEqual(len(cfg["gases"]), 2)           # nothing parked

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
                         [{"depth_m": 40.0, "runtime_min": 22.0}])
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

    def test_contingency_defaults_and_roundtrip(self):
        cfg = dc.default_config()
        self.assertEqual(cfg["contingency"],
                         {"time_before": 1, "time_after": 1,
                          "depth_before": 1, "depth_after": 1})
        cfg["contingency"] = {"time_before": 0, "time_after": 2,
                              "depth_before": 1, "depth_after": 3}
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.json")
            dc.save(cfg, path)
            back = dc.load(path)
        self.assertEqual(back["contingency"],
                         {"time_before": 0, "time_after": 2,
                          "depth_before": 1, "depth_after": 3})
        self.assertEqual(dc.contingency_of(back), (0, 2, 1, 3))

    def test_contingency_partial_block_fills_defaults(self):
        # A hand-edited block naming one count must not clobber the others.
        cfg = dc._merged({"contingency": {"time_after": 3}})
        self.assertEqual(cfg["contingency"],
                         {"time_before": 1, "time_after": 3,
                          "depth_before": 1, "depth_after": 1})

    def test_contingency_missing_block_gets_defaults(self):
        self.assertEqual(dc.contingency_of({}), (1, 1, 1, 1))

    def test_contingency_negatives_clamp_to_zero(self):
        cfg = dc._merged({"contingency": {"time_before": -5, "time_after": -1,
                                          "depth_before": -2, "depth_after": -3}})
        self.assertEqual(cfg["contingency"],
                         {"time_before": 0, "time_after": 0,
                          "depth_before": 0, "depth_after": 0})

    def test_contingency_legacy_deltas_migrate_to_steps(self):
        # Old configs stored time +-DT min / depth +DD m deltas: DT becomes
        # round(DT/3) rows both ways, DD round(DD/3) deeper columns only.
        cfg = dc._merged({"contingency": {"time_delta_min": 5.0,
                                          "depth_delta_m": 3.0}})
        self.assertEqual(cfg["contingency"],
                         {"time_before": 2, "time_after": 2,
                          "depth_before": 0, "depth_after": 1})
        cfg = dc._merged({"contingency": {"time_delta_min": 0,
                                          "depth_delta_m": 6}})
        self.assertEqual(cfg["contingency"],
                         {"time_before": 0, "time_after": 0,
                          "depth_before": 0, "depth_after": 2})

    def test_invalid_role_coerced_to_deco(self):
        cfg = dc.default_config()
        cfg["gases"] = [{"role": "Nonsense", "o2": 32, "he": 0, "tank_l": 11}]
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.json")
            dc.save(cfg, path)
            back = dc.load(path)
        self.assertEqual(back["gases"][0]["role"], "Deco")

    def test_legacy_level_role_gas_is_dropped_on_migration(self):
        # The old "Level" role (a mix breathed only on a level that named it)
        # is gone: gas is automatic-by-role now, so such an entry is dropped.
        cfg = dc.normalize({
            "levels": [{"depth_m": 35, "runtime_min": 25, "gas_id": 2}],
            "gases": [
                {"role": "Bottom", "o2": 21, "he": 0, "tank_l": 24},
                {"role": "Level", "o2": 28, "he": 0, "tank_l": 11},
            ],
        })
        self.assertEqual([g["role"] for g in cfg["gases"]], ["Bottom"])
        _bottom, plan, _gp, gases = dc.to_buhlmann(cfg)
        self.assertEqual(plan.travel_gases, ())
        self.assertEqual(plan.deco_gases, ())
        self.assertNotIn("Level", [role for role, *_ in gases])

    def test_load_strict_raises_on_missing_and_invalid(self):
        with self.assertRaises(FileNotFoundError):
            dc.load("/no/such/dive_plan.json", strict=True)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "broken.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{not json")
            with self.assertRaises(ValueError):   # json.JSONDecodeError
                dc.load(path, strict=True)
            # lenient mode (the GUI) still falls back to the default config
            self.assertEqual(dc.load(path), dc.default_config())


if __name__ == "__main__":
    unittest.main()


class TestLoadBoundary(unittest.TestCase):
    """Strict/lenient contract for semantically corrupt (valid-JSON) configs."""

    CORRUPT = '{"levels": [{"depth_m": "oops", "runtime_min": 20}]}'

    def _write(self, d, text):
        path = os.path.join(d, "cfg.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def test_lenient_semantic_corruption_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = dc.load(self._write(d, self.CORRUPT))
        self.assertEqual(cfg, dc.default_config())

    def test_strict_semantic_corruption_raises_valueerror(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, self.CORRUPT)
            with self.assertRaises(ValueError):
                dc.load(path, strict=True)

    def test_lenient_non_dict_json_falls_back(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = dc.load(self._write(d, '[1, 2, 3]'))
        self.assertEqual(cfg, dc.default_config())

    def test_normalize_is_public_and_merges(self):
        cfg = dc.normalize({"gf_high": 85})
        self.assertEqual(cfg["gf_high"], 85)
        self.assertTrue(cfg["levels"])         # defaults filled in


class TestAtomicSave(unittest.TestCase):
    def test_save_leaves_no_temp_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "cfg.json")
            dc.save(dc.default_config(), path)
            self.assertEqual(os.listdir(d), ["cfg.json"])
            self.assertEqual(dc.load(path), dc.normalize(dc.default_config()))



class TestEnvironmentAndDecoSac(unittest.TestCase):
    """Water type / surface pressure / deco SAC: the settings the MultiDeco
    scenarios in examples/ needed and the config had no home for."""

    def test_defaults_are_sea_level_salt_and_one_sac(self):
        cfg = dc.default_config()
        self.assertEqual(cfg["msw_per_bar"], b.MSW_PER_BAR)
        self.assertEqual(cfg["surface_p_bar"], b.P_ATM)
        self.assertIsNone(cfg["sac_deco"])
        _bg, plan, gp, _g = dc.to_buhlmann(cfg)
        self.assertEqual(plan.msw_per_bar, b.MSW_PER_BAR)
        self.assertEqual(plan.surface_p, b.P_ATM)
        self.assertIsNone(gp.sac_deco)

    def test_fresh_water_and_altitude_round_trip_and_apply(self):
        cfg = dc.default_config()
        cfg["msw_per_bar"] = b.MSW_PER_BAR_FRESH
        cfg["surface_p_bar"] = 0.845
        cfg["sac_deco"] = 16.0
        _bg, plan, gp, _g = dc.to_buhlmann(cfg)
        self.assertAlmostEqual(plan.msw_per_bar, b.MSW_PER_BAR_FRESH)
        self.assertAlmostEqual(plan.surface_p, 0.845)
        self.assertAlmostEqual(gp.sac_deco, 16.0)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.json")
            dc.save(cfg, path)
            back = dc.load(path)
        self.assertAlmostEqual(back["msw_per_bar"], b.MSW_PER_BAR_FRESH)
        self.assertAlmostEqual(back["surface_p_bar"], 0.845)
        self.assertAlmostEqual(back["sac_deco"], 16.0)

    def test_config_without_the_new_keys_still_loads_as_sea_level_salt(self):
        """Every dive_plan.json written before these settings existed must
        keep planning exactly as it did — the environment is additive."""
        legacy = {"levels": [{"depth_m": 30, "runtime_min": 20}],
                  "gf_low": 30, "gf_high": 70, "sac_normal": 20}
        _bg, plan, gp, _g = dc.to_buhlmann(dc.normalize(legacy))
        self.assertEqual(plan.surface_p, b.P_ATM)
        self.assertEqual(plan.msw_per_bar, b.MSW_PER_BAR)
        self.assertIsNone(gp.sac_deco)


class TestNoGasIsRefused(unittest.TestCase):
    """A config with no usable gas must not quietly become a dive on Air.

    `{"gases": []}` used to fall back to the default stack, so the planner
    produced a schedule on Air with an EAN50 deco stage — neither of which
    appeared anywhere in the file the user was holding. Unticking every gas did
    the same. That is the failure mode DECISIONS.md #9 names ("silently
    planning a *different* dive than the one asked for is the worst possible
    failure mode"), arriving through a different door; #24 closes it.
    """

    BASE: ClassVar[dict] = {"levels": [{"depth_m": 40, "runtime_min": 25}]}

    def test_an_explicit_empty_list_stays_empty(self):
        cfg = dc.normalize({**self.BASE, "gases": []})
        self.assertEqual(cfg["gases"], [])
        with self.assertRaises(ValueError) as e:
            dc.to_buhlmann(cfg)
        self.assertIn("no gas", str(e.exception))

    def test_every_gas_disabled_is_refused_by_name(self):
        cfg = dc.normalize({**self.BASE, "gases": [
            {"role": "Bottom", "o2": 21, "he": 35, "tank_l": 24,
             "pressure_bar": 232, "enabled": False}]})
        with self.assertRaises(ValueError) as e:
            dc.to_buhlmann(cfg)
        self.assertIn("none enabled", str(e.exception))

    def test_an_absent_key_still_gets_the_defaults(self):
        """Only an *explicit* empty list is taken as given — a config that
        never mentions gases is a partial hand-edit, not a gasless dive."""
        cfg = dc.normalize(dict(self.BASE))
        self.assertTrue(cfg["gases"])
        bottom, _plan, _gp, gases = dc.to_buhlmann(cfg)
        self.assertTrue(gases)
        self.assertIsInstance(bottom, b.Gas)
