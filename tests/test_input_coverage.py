"""Every input to the algorithm is reachable, and binding, from every front end.

"Binding" is the load-bearing word. It is not enough for a knob to exist in the
config schema or take an argparse flag: the value has to arrive in the
`DivePlan` / `GasPlan` the planner is actually handed. The GUI in particular
used to *read* the rates and the ppO2 window from `dive_plan.json` and write
them back untouched — present in the file, invisible in the app, and impossible
to change there. That reads as support and is not.

So this enumerates `DivePlan` and `GasPlan` by reflection and, for each field,
sets a distinctive value through each of the three front ends and checks it
comes back out. A field added without being wired fails here — which is the
point: the coverage claim has to be checkable, not remembered (DECISIONS.md
#19).

The GUI half skips without Tk/matplotlib, like the other GUI suites.
"""

from __future__ import annotations

import contextlib
import dataclasses
import io
import unittest
from typing import ClassVar

from deco import buhlmann as b
from deco import cli
from deco import dive_config as dc

try:
    import tkinter as tk

    from deco import app
    _root = tk.Tk()
    _root.withdraw()
    _HAVE_GUI = True
except Exception:
    _HAVE_GUI = False
else:
    _root.destroy()


#: A distinctive value per plan field, different from the default so a knob
#: that is silently ignored cannot pass by coincidence.
PLAN_PROBE: dict[str, float] = {
    "descent_rate": 17.0, "ascent_rate": 7.0, "stop_interval": 2.0,
    "last_stop_depth": 6.0, "gf_low": 0.22, "gf_high": 0.77,
    "surface_p": 0.93, "msw_per_bar": 10.25, "p_h2o": 0.0567,
    "ppo2_deco": 1.55, "ppo2_bottom": 1.35, "ppo2_min": 0.19,
    "ppo2_switch_tol": 0.09, "min_stop_time": 0.5,
}
GAS_PROBE: dict[str, float] = {
    "sac": 17.5, "sac_deco": 13.5, "sac_emergency": 31.0,
    "problem_minutes": 2.5, "divers": 2,
}
#: Gas-plan fields that are switches rather than numbers. Probed with the
#: NON-default value, so a front end that hardcodes "emergency on" fails here:
#: the emergency block is a real input, not a constant (DECISIONS.md #28).
GAS_PROBE_BOOL: dict[str, bool] = {"emergency": False, "turn_pressure": False}
#: Gas-plan fields that are named choices.
GAS_PROBE_STR: dict[str, str] = {"turn_rule": "thirds"}
#: Plan fields that are not numbers. Probed by equality rather than a
#: tolerance, but held to exactly the same standard: set it through each front
#: end, check it arrives in the DivePlan.
PLAN_PROBE_STR: dict[str, str] = {"gas_switch_policy": "at-first-stop"}
#: Fields carried as gas-stack roles rather than scalars, checked separately.
GAS_STACK_FIELDS = {"travel_gases", "deco_gases"}
#: Nothing here at present. A field listed here would be one the planner
#: declares but never reads — which is exactly the trap this module exists to
#: prevent, so prefer deleting the field to listing it.
UNUSED_FIELDS: set[str] = set()

#: Defaults that deliberately differ between the library and the front ends.
#: GF-high is the only one: the library keeps Bühlmann's 0.80, while the config,
#: the CLI and the GUI agree with each other on 30/**70** (CLAUDE.md,
#: "Defaults"). Anything else that has to be listed here is drift, not a
#: decision — write the entry only after deciding it, never to make the test
#: pass.
DEFAULT_EXCEPTIONS: dict[str, dict[str, float]] = {
    "gf_high": {"library": 0.80, "front_ends": 0.70},
}


def _probe_config() -> dict:
    cfg = dc.default_config()
    cfg.update({
        "descent_rate": 17.0, "ascent_rate": 7.0, "stop_interval": 2.0,
        "last_stop_m": 6.0, "gf_low": 22, "gf_high": 77,
        "surface_p_bar": 0.93, "msw_per_bar": 10.25, "p_h2o_bar": 0.0567,
        "ppo2_deco": 1.55, "ppo2_bottom": 1.35, "ppo2_min": 0.19,
        "ppo2_switch_tol": 0.09, "min_stop_time": 0.5,
        "sac_normal": 17.5, "sac_deco": 13.5, "sac_emergency": 31.0,
        "emergency": False, "turn_pressure": False, "turn_rule": "thirds",
        "problem_minutes": 2.5, "divers": 2,
        "gas_switch_policy": "at-first-stop",
    })
    return cfg


CLI_ARGV = [
    "plan", "--depth", "30", "--time", "20", "--gas", "air",
    "--travel-gas", "35/25", "--deco-gas", "50",
    "--descent-rate", "17", "--ascent-rate", "7", "--stop-interval", "2",
    "--last-stop", "6", "--gf-low", "0.22", "--gf-high", "0.77",
    "--surface-p", "0.93", "--msw-per-bar", "10.25", "--p-h2o", "0.0567",
    "--ppo2-deco", "1.55", "--ppo2-bottom", "1.35", "--ppo2-min", "0.19",
    "--ppo2-switch-tol", "0.09", "--min-stop-time", "0.5",
    "--sac", "17.5", "--sac-deco", "13.5", "--sac-emergency", "31",
    "--no-emergency", "--no-turn-pressure", "--turn-rule", "thirds",
    "--problem-time", "2.5", "--divers", "2",
    "--gas-switch", "at-first-stop",
]


def _cli_args(argv: list[str]):
    """The parsed args for `argv`, captured out of the real parser."""
    captured = {}
    original = cli.cmd_plan

    def spy(args):
        captured["args"] = args
        return 0

    cli.cmd_plan = spy
    try:
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            cli.main(argv)
    finally:
        cli.cmd_plan = original
    return captured["args"]


def _cli_plans():
    """Run the real parser, then build the plan exactly as `cmd_plan` does."""
    args = _cli_args(CLI_ARGV)
    return cli._build_plan(args), cli._args_gas_context(args)[0]


class TestEveryFieldIsProbed(unittest.TestCase):
    """The guard on the guard: a new plan field must join a probe table, or the
    coverage tests below would silently stop covering the whole surface."""

    def test_no_plan_field_is_unaccounted_for(self):
        known = set(PLAN_PROBE) | set(PLAN_PROBE_STR) | GAS_STACK_FIELDS
        fields = {f.name for f in dataclasses.fields(b.DivePlan)}
        self.assertEqual(fields - known, set(),
                         "new DivePlan field(s): add a value to PLAN_PROBE and "
                         "wire them into the config, the CLI and the GUI")

    def test_no_gas_plan_field_is_unaccounted_for(self):
        known = (set(GAS_PROBE) | set(GAS_PROBE_BOOL) | set(GAS_PROBE_STR)
                 | UNUSED_FIELDS)
        fields = {f.name for f in dataclasses.fields(b.GasPlan)}
        self.assertEqual(fields - known, set(),
                         "new GasPlan field(s): add a value to GAS_PROBE and "
                         "wire them into the config, the CLI and the GUI")


def _default_plans():
    """The three no-input defaults: library, config, bare command line."""
    args = _cli_args(["plan", "--depth", "30", "--time", "20"])
    return (b.DivePlan(),
            dc.to_buhlmann(dc.default_config())[1],
            cli._build_plan(args))


class TestDefaultsAgree(unittest.TestCase):
    """The probes above prove a knob **binds**; this proves the knobs agree
    when nobody touches them.

    `PLAN_PROBE` deliberately uses values *different from the default* so an
    ignored knob cannot pass by coincidence — which makes it blind, by
    construction, to the defaults themselves. And every default is written out
    five to eight separate times: `DivePlan`'s field, `default_config()`,
    `to_buhlmann`'s `cfg.get(..., 1.4)` fallback, the argparse default, and the
    GUI's `_make_plan` / `_apply_config` / `_collect_config`. One copy drifting
    changes what gets planned with every flag left off, which is the common
    case and the hardest to notice.

    Only `DEFAULT_SAC` vs `sac_normal` was pinned before this
    (`test_report.py`). This is that check for the whole surface.
    """

    def test_plan_defaults_agree(self):
        lib, cfg, cmdline = _default_plans()
        for f in dataclasses.fields(b.DivePlan):
            if f.name in GAS_STACK_FIELDS:
                continue
            with self.subTest(f.name):
                if f.name in DEFAULT_EXCEPTIONS:
                    want = DEFAULT_EXCEPTIONS[f.name]
                    self.assertEqual(getattr(lib, f.name), want["library"])
                    self.assertEqual(getattr(cfg, f.name), want["front_ends"])
                    self.assertEqual(getattr(cmdline, f.name),
                                     want["front_ends"])
                    continue
                self.assertEqual(getattr(cfg, f.name), getattr(lib, f.name),
                                 "config default differs from the library's")
                self.assertEqual(getattr(cmdline, f.name), getattr(lib, f.name),
                                 "CLI default differs from the library's")

    def test_gas_plan_defaults_agree(self):
        """`GasPlan.sac` is required, so there is no library default to compare
        against — the config and the CLI are checked against each other, and
        `sac` itself against `report.DEFAULT_SAC` as before."""
        cfg_gp = dc.to_buhlmann(dc.default_config())[2]
        cli_gp = cli._args_gas_context(
            _cli_args(["plan", "--depth", "30", "--time", "20"]))[0]
        for f in dataclasses.fields(b.GasPlan):
            with self.subTest(f.name):
                self.assertEqual(getattr(cli_gp, f.name),
                                 getattr(cfg_gp, f.name))

    def test_the_exception_list_is_only_the_ones_we_chose(self):
        """A field may be listed as an exception only while it really differs.
        Left behind after the two are reconciled, an entry here would silently
        stop checking a field forever."""
        lib, cfg, _cmdline = _default_plans()
        for name in DEFAULT_EXCEPTIONS:
            with self.subTest(name):
                self.assertNotEqual(
                    getattr(lib, name), getattr(cfg, name),
                    f"{name} no longer differs — drop it from "
                    f"DEFAULT_EXCEPTIONS so it is checked like the rest")


class TestConfigBinds(unittest.TestCase):
    """The agentic surface: dive_plan.json is what an agent edits."""

    def setUp(self):
        self.plan, self.gas_plan = dc.to_buhlmann(_probe_config())[1:3]

    def test_plan_fields(self):
        for name, want in PLAN_PROBE.items():
            with self.subTest(name):
                self.assertAlmostEqual(getattr(self.plan, name), want, places=9)
        for name, text in PLAN_PROBE_STR.items():
            with self.subTest(name):
                self.assertEqual(getattr(self.plan, name), text)

    def test_gas_plan_fields(self):
        for name, want in GAS_PROBE.items():
            with self.subTest(name):
                self.assertAlmostEqual(getattr(self.gas_plan, name), want,
                                       places=9)
        for name, flag in GAS_PROBE_BOOL.items():
            with self.subTest(name):
                self.assertEqual(getattr(self.gas_plan, name), flag)
        for name, text in GAS_PROBE_STR.items():
            with self.subTest(name):
                self.assertEqual(getattr(self.gas_plan, name), text)

    def test_gas_stack_roles(self):
        cfg = _probe_config()
        cfg["gases"] = [
            {"role": "Bottom", "o2": 21, "he": 35},
            {"role": "Travel", "o2": 35, "he": 25},
            {"role": "Deco", "o2": 50, "he": 0},
        ]
        bottom, plan, _gp, _g = dc.to_buhlmann(cfg)
        self.assertEqual(bottom, b.Gas(0.21, 0.35))
        self.assertEqual(plan.travel_gases, (b.Gas(0.35, 0.25),))
        self.assertEqual(plan.deco_gases, (b.Gas(0.50),))

    def test_everything_survives_a_round_trip_through_json(self):
        import json
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.json")
            dc.save(_probe_config(), path)
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
            plan, gp = dc.to_buhlmann(dc.load(path))[1:3]
        for name, want in PLAN_PROBE.items():
            with self.subTest(name):
                self.assertAlmostEqual(getattr(plan, name), want, places=9)
        for name, want in GAS_PROBE.items():
            with self.subTest(f"GasPlan.{name}"):
                self.assertAlmostEqual(getattr(gp, name), want, places=9)
        for name, flag in GAS_PROBE_BOOL.items():
            with self.subTest(f"GasPlan.{name}"):
                self.assertEqual(getattr(gp, name), flag)
        for name, text in GAS_PROBE_STR.items():
            with self.subTest(f"GasPlan.{name}"):
                self.assertEqual(getattr(gp, name), text)
        for name, text in PLAN_PROBE_STR.items():
            with self.subTest(name):
                self.assertEqual(getattr(plan, name), text)
        # and the file is human/agent-editable: no field hidden behind a
        # derived key the schema does not document
        self.assertIn("p_h2o_bar", raw)
        self.assertIn("ppo2_switch_tol", raw)
        self.assertIn("gas_switch_policy", raw)


class TestCliBinds(unittest.TestCase):
    def setUp(self):
        self.plan, self.gas_plan = _cli_plans()

    def test_plan_fields(self):
        for name, want in PLAN_PROBE.items():
            with self.subTest(name):
                self.assertAlmostEqual(getattr(self.plan, name), want, places=9)
        for name, text in PLAN_PROBE_STR.items():
            with self.subTest(name):
                self.assertEqual(getattr(self.plan, name), text)

    def test_gas_plan_fields(self):
        for name, want in GAS_PROBE.items():
            with self.subTest(name):
                self.assertAlmostEqual(getattr(self.gas_plan, name), want,
                                       places=9)
        for name, flag in GAS_PROBE_BOOL.items():
            with self.subTest(name):
                self.assertEqual(getattr(self.gas_plan, name), flag)

    def test_gas_stack_roles(self):
        self.assertEqual(self.plan.travel_gases, (b.Gas(0.35, 0.25),))
        self.assertEqual(self.plan.deco_gases, (b.Gas(0.50),))

    def test_save_captures_every_field_for_the_agentic_side(self):
        """`--save` has to write what was planned, or the CLI and an agent
        editing the file disagree about the same dive."""
        captured = {}
        original = cli.cmd_plan
        cli.cmd_plan = lambda args: captured.setdefault("args", args) and 0
        try:
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                cli.main(CLI_ARGV)
        finally:
            cli.cmd_plan = original
        cfg = cli._config_from_args(captured["args"])
        plan, gp = dc.to_buhlmann(cfg)[1:3]
        for name, want in PLAN_PROBE.items():
            with self.subTest(name):
                self.assertAlmostEqual(getattr(plan, name), want, places=9)
        for name, want in GAS_PROBE.items():
            with self.subTest(f"GasPlan.{name}"):
                self.assertAlmostEqual(getattr(gp, name), want, places=9)
        for name, flag in GAS_PROBE_BOOL.items():
            with self.subTest(f"GasPlan.{name}"):
                self.assertEqual(getattr(gp, name), flag)


@unittest.skipUnless(_HAVE_GUI, "Tk/matplotlib GUI not available")
class TestGuiBinds(unittest.TestCase):
    """The one that used to be untrue: several of these were config
    passthrough with no widget at all."""

    #: plan field -> the GUI variable that drives it
    WIDGETS: ClassVar[dict[str, tuple[str, str]]] = {
        "descent_rate": ("descent_rate", "17"),
        "ascent_rate": ("ascent_rate", "7"),
        "stop_interval": ("stop_interval", "2"),
        "last_stop_depth": ("last_stop", "6"),
        "gf_low": ("gf_lo", "22"),
        "gf_high": ("gf_hi", "77"),
        "surface_p": ("surface_p", "0.93"),
        "msw_per_bar": ("msw_per_bar", "10.25"),
        "p_h2o": ("p_h2o", "0.0567"),
        "ppo2_deco": ("ppo2_deco", "1.55"),
        "ppo2_bottom": ("ppo2_bottom", "1.35"),
        "ppo2_min": ("ppo2_min", "0.19"),
        "ppo2_switch_tol": ("ppo2_switch_tol", "0.09"),
        "min_stop_time": ("min_stop_time", "0.5"),
    }
    #: Non-numeric plan fields and the widget variable behind each.
    STR_WIDGETS: ClassVar[dict[str, tuple[str, str]]] = {
        "gas_switch_policy": ("gas_switch_policy", "at-first-stop"),
    }
    GAS_WIDGETS: ClassVar[dict[str, tuple[str, str]]] = {
        "sac": ("sac", "17.5"), "sac_deco": ("sac_deco", "13.5"),
        "sac_emergency": ("sac_emergency", "31"),
        "problem_minutes": ("problem_min", "2.5"),
    }

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = app.DecoApp(self.root)

    def tearDown(self):
        self.root.destroy()

    def _set_everything(self):
        for _field, (var, value) in self.WIDGETS.items():
            getattr(self.app, var).set(value)
        for _field, (var, value) in self.STR_WIDGETS.items():
            getattr(self.app, var).set(value)
        for _field, (var, value) in self.GAS_WIDGETS.items():
            getattr(self.app, var).set(value)
        self.app.two_divers.set(True)
        for field, flag in GAS_PROBE_BOOL.items():
            getattr(self.app, field).set(flag)
        for field, text in GAS_PROBE_STR.items():
            getattr(self.app, field).set(text)

    def test_every_plan_field_has_a_widget_that_binds(self):
        self._set_everything()
        plan = self.app._make_plan()
        for name, want in PLAN_PROBE.items():
            with self.subTest(name):
                self.assertAlmostEqual(getattr(plan, name), want, places=9)
        for name, text in PLAN_PROBE_STR.items():
            with self.subTest(name):
                self.assertEqual(getattr(plan, name), text)

    def test_every_gas_plan_field_has_a_widget_that_binds(self):
        self._set_everything()
        gp = self.app._gas_plan()
        for name, want in GAS_PROBE.items():
            with self.subTest(name):
                self.assertAlmostEqual(getattr(gp, name), want, places=9)
        for name, flag in GAS_PROBE_BOOL.items():
            with self.subTest(name):
                self.assertEqual(getattr(gp, name), flag)
        for name, text in GAS_PROBE_STR.items():
            with self.subTest(name):
                self.assertEqual(getattr(gp, name), text)

    def test_the_widget_map_covers_every_field(self):
        """If a field gains a probe value but no GUI widget, say so here rather
        than letting the two tests above quietly test a shorter list."""
        self.assertEqual(set(PLAN_PROBE) - set(self.WIDGETS), set())
        self.assertEqual(set(GAS_PROBE) - set(self.GAS_WIDGETS) - {"divers"},
                         set())
        # the switches and choices have widgets of their own — checkbuttons
        # and a combobox, not spinboxes — named after the field they set
        for field in (*GAS_PROBE_BOOL, *GAS_PROBE_STR):
            self.assertTrue(hasattr(self.app, field), field)

    def test_everything_round_trips_through_the_config(self):
        self._set_everything()
        cfg = self.app._collect_config()
        plan, gp = dc.to_buhlmann(cfg)[1:3]
        for name, want in PLAN_PROBE.items():
            with self.subTest(name):
                self.assertAlmostEqual(getattr(plan, name), want, places=9)
        for name, want in GAS_PROBE.items():
            with self.subTest(f"GasPlan.{name}"):
                self.assertAlmostEqual(getattr(gp, name), want, places=9)
        for name, flag in GAS_PROBE_BOOL.items():
            with self.subTest(f"GasPlan.{name}"):
                self.assertEqual(getattr(gp, name), flag)
        # and reloading puts the same numbers back in the boxes
        self.app._apply_config(cfg)
        again = self.app._make_plan()
        for name, want in PLAN_PROBE.items():
            with self.subTest(f"reload {name}"):
                self.assertAlmostEqual(getattr(again, name), want, places=9)

    def test_gui_defaults_agree_with_the_config_and_the_cli(self):
        """The third copy of every default lives in the GUI — in the spinbox
        inits, in `_apply_config`'s `cfg.get(..., 1.4)` fallbacks and again in
        `_collect_config`.

        Fed `default_config()` directly rather than started from disk: a
        `DecoApp` built in a checkout loads the repo's real `dive_plan.json`,
        and a test that reads whatever dive the owner happens to be planning is
        a test of nothing.
        """
        self.app._apply_config(dc.default_config())
        cfg_plan = dc.to_buhlmann(dc.default_config())[1]
        gui_plan = self.app._make_plan()
        for f in dataclasses.fields(b.DivePlan):
            if f.name in GAS_STACK_FIELDS:
                continue
            with self.subTest(f.name):
                self.assertAlmostEqual(
                    float(getattr(gui_plan, f.name)),
                    float(getattr(cfg_plan, f.name)), places=6) \
                    if isinstance(getattr(cfg_plan, f.name), (int, float)) \
                    else self.assertEqual(getattr(gui_plan, f.name),
                                          getattr(cfg_plan, f.name))
        cfg_gp = dc.to_buhlmann(dc.default_config())[2]
        gui_gp = self.app._gas_plan()
        for f in dataclasses.fields(b.GasPlan):
            with self.subTest(f"GasPlan.{f.name}"):
                self.assertEqual(getattr(gui_gp, f.name),
                                 getattr(cfg_gp, f.name))

    def test_last_stop_switch_and_field_stay_in_step(self):
        """The '6 m' shorthand writes the free field, so the two can't disagree
        about the same dive."""
        self.app.last_stop6.set(True)
        self.assertEqual(self.app._make_plan().last_stop_depth, 6.0)
        self.app.last_stop6.set(False)
        self.assertEqual(self.app._make_plan().last_stop_depth, 3.0)
        # …and the free field can still express what the switch cannot
        self.app.last_stop.set("9")
        self.assertEqual(self.app._make_plan().last_stop_depth, 9.0)


if __name__ == "__main__":
    unittest.main()
