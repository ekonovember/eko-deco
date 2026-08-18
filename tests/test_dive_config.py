"""Sanity checks for dive_config (the shared JSON config)."""
from __future__ import annotations

import json
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
                  "sac_normal", "sac_emergency", "emergency", "gases"):
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
            "sac_normal": 20, "sac_emergency": 40.0, "problem_minutes": 1,
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
        self.assertAlmostEqual(gp.sac_emergency, 40.0)
        self.assertEqual(len(gases), 3)

    def test_sac_emergency_maps_to_gasplan(self):
        cfg = dc.default_config()
        cfg["sac_emergency"] = 30.0
        _b, _p, gp, _g = dc.to_buhlmann(cfg)
        self.assertAlmostEqual(gp.sac_emergency, 30.0)

    def test_emergency_flag_maps_to_gasplan(self):
        cfg = dc.default_config()
        self.assertTrue(dc.to_buhlmann(cfg)[2].emergency)
        cfg["emergency"] = False
        self.assertFalse(dc.to_buhlmann(cfg)[2].emergency)

    def test_legacy_sac_stress_migrates_to_an_absolute_rate(self):
        # Old configs stored an absolute distress SAC and a solo flag.
        cfg = dc._merged({"sac_normal": 20, "sac_stress": 30, "solo": True})
        self.assertAlmostEqual(cfg["sac_emergency"], 30.0)
        self.assertNotIn("sac_stress", cfg)
        self.assertNotIn("solo", cfg)

    def test_legacy_sac_multiplier_migrates_to_an_absolute_rate(self):
        # The middle form: a multiplier on the working SAC. Resolving it here
        # means a file written by the previous version plans identical litres.
        cfg = dc._merged({"sac_normal": 18, "sac_multiplier": 1.5})
        self.assertAlmostEqual(cfg["sac_emergency"], 27.0)
        self.assertNotIn("sac_multiplier", cfg)

    def test_a_config_naming_no_emergency_rate_keeps_the_old_default(self):
        # Twice the working SAC — what "multiplier 2.0" used to mean — rather
        # than the schema default, which knows nothing about this file's SAC.
        cfg = dc._merged({"sac_normal": 25})
        self.assertAlmostEqual(cfg["sac_emergency"], 50.0)

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

    def test_invalid_role_is_refused_not_coerced(self):
        """This used to coerce an unrecognised role to "Deco" — and was tested
        for it. A mistyped "Bottom" therefore left the dive with no bottom gas
        at all, which `to_buhlmann` then papered over by taking the first mix in
        the list, so a one-letter typo silently changed both the bottom gas and
        the deco stack. Refusing is what DECISIONS.md #9 asks for; #24 records
        the change."""
        with self.assertRaises(ValueError) as e:
            dc.normalize({"gases": [{"role": "Bottum", "o2": 32, "he": 0}]})
        self.assertIn("Bottum", str(e.exception))
        # and a hand-edited file carrying it fails the strict load the CLI uses
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.json")
            with open(path, "w") as f:
                json.dump({"levels": [{"depth_m": 40, "runtime_min": 25}],
                           "gases": [{"role": "Bottum", "o2": 32}]}, f)
            with self.assertRaises(ValueError):
                dc.load(path, strict=True)

    def test_a_mistyped_level_key_is_refused(self):
        """`{"depth": 40}` used to normalize to the DEFAULT 30 m — the typo'd
        key was simply absent, so the default filled in and the dive planned
        10 m shallower than the file said (#24)."""
        with self.assertRaises(ValueError) as e:
            dc.normalize({"levels": [{"depth": 40, "runtime_min": 25}]})
        self.assertIn("depth", str(e.exception))
        with self.assertRaises(ValueError):
            dc.normalize({"levels": [{"depth_m": 40}]})       # missing runtime

    def test_a_mistyped_top_level_key_is_refused(self):
        """The same rule as levels, gases and repeats — applied to the object
        that holds the GF, the SAC, the ppO2 window and the environment.

        `{"gf_hi": 95}` used to leave gf_high at 70 and plan a different dive,
        exit 0 (DECISIONS.md #29). The near-miss suggestion is part of the
        contract: with 27 valid keys, naming the one that was meant is what
        makes the error actionable."""
        with self.assertRaises(ValueError) as e:
            dc.normalize({"gf_hi": 95})
        self.assertIn("gf_hi", str(e.exception))
        self.assertIn("did you mean gf_high?", str(e.exception))
        # …and the strict load the CLI and the GUI both use refuses the file
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.json")
            with open(path, "w") as f:
                json.dump({"levels": [{"depth_m": 40, "runtime_min": 25}],
                           "ppo2_botom": 1.6}, f)
            with self.assertRaises(ValueError):
                dc.load(path, strict=True)

    def test_a_mistyped_key_cannot_be_laundered_through_a_save(self):
        """The worst part of the old behaviour was not the wrong plan, it was
        that `save()` wrote the typo back out: the file kept advertising a
        setting nothing honoured, so the evidence agreed with the mistake."""
        with self.assertRaises(ValueError):
            dc.save({"levels": [{"depth_m": 40, "runtime_min": 25}],
                     "gf_hi": 95}, os.devnull)

    def test_every_key_the_front_ends_write_is_a_known_key(self):
        """The strictness above is only safe because nothing we write trips it.
        A new config key added to one front end and not to `default_config()`
        would make the app refuse its own output on the next load."""
        known = set(dc.default_config()) | set(dc.LEGACY_KEYS)
        self.assertEqual(set(dc.default_config()) - known, set())
        # a saved round trip of the richest config we can build
        cfg = dc.default_config()
        cfg["repeats"] = [{"surface_interval_min": 45,
                           "levels": [{"depth_m": 22, "runtime_min": 35}]}]
        self.assertEqual(set(dc.normalize(cfg)) - known, set())

    def test_a_fraction_where_a_percentage_belongs_is_refused(self):
        """o2 0.32 is EAN32 typed as a fraction; taken literally it is a
        0.32 % hypoxic mix, and the planner would happily schedule it."""
        with self.assertRaises(ValueError) as e:
            dc.normalize({"gases": [{"role": "Bottom", "o2": 0.32}]})
        self.assertIn("percentage", str(e.exception))
        with self.assertRaises(ValueError):
            dc.normalize({"gases": [{"role": "Bottom", "o2": 21, "he": 90}]})

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


class TestRepetitiveDives(unittest.TestCase):
    """`repeats` is additive: every config written before it still means the
    single dive it always meant."""

    def test_a_config_without_repeats_is_one_dive(self):
        self.assertEqual(len(dc.series_of(dc.default_config())), 1)
        self.assertEqual(dc.series_of(dc.default_config())[0][0], 0.0)

    def test_series_of_orders_the_day(self):
        cfg = dc.default_config()
        cfg["levels"] = [{"depth_m": 30, "runtime_min": 25}]
        cfg["repeats"] = [
            {"surface_interval_min": 60, "levels": [{"depth_m": 24,
                                                     "runtime_min": 30}]},
            {"surface_interval_min": 90, "levels": [{"depth_m": 18,
                                                     "runtime_min": 40}]},
        ]
        series = dc.series_of(cfg)
        self.assertEqual([si for si, _ in series], [0.0, 60.0, 90.0])
        self.assertEqual([lv[0].depth for _, lv in series], [30, 24, 18])

    def test_a_repeat_without_a_surface_interval_is_refused(self):
        """Guessing one would invent residual nitrogen the file never stated."""
        cfg = dc.default_config()
        cfg["repeats"] = [{"levels": [{"depth_m": 20, "runtime_min": 30}]}]
        with self.assertRaises(ValueError):
            dc.normalize(cfg)

    def test_a_repeat_without_levels_is_refused(self):
        cfg = dc.default_config()
        cfg["repeats"] = [{"surface_interval_min": 60, "levels": []}]
        with self.assertRaises(ValueError):
            dc.normalize(cfg)

    def test_a_negative_surface_interval_is_refused(self):
        cfg = dc.default_config()
        cfg["repeats"] = [{"surface_interval_min": -5,
                           "levels": [{"depth_m": 20, "runtime_min": 30}]}]
        with self.assertRaises(ValueError):
            dc.normalize(cfg)

    def test_a_mistyped_repeat_key_is_refused_not_defaulted(self):
        """Same rule as levels and gases (#9, #24): a typo is a different dive."""
        cfg = dc.default_config()
        cfg["repeats"] = [{"surface_interval": 60,
                           "levels": [{"depth_m": 20, "runtime_min": 30}]}]
        with self.assertRaises(ValueError):
            dc.normalize(cfg)

    def test_repeats_survive_a_save_load_round_trip(self):
        import os
        import tempfile
        cfg = dc.default_config()
        cfg["repeats"] = [{"surface_interval_min": 45,
                           "levels": [{"depth_m": 22, "runtime_min": 35}]}]
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "series.json")
            dc.save(cfg, path)
            back = dc.load(path)
        self.assertEqual(len(dc.series_of(back)), 2)
        self.assertEqual(dc.series_of(back)[1][0], 45.0)
        self.assertEqual(dc.series_of(back)[1][1][0].depth, 22)
