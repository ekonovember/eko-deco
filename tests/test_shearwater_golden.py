"""Pin eko-deco schedules to golden values from real planners.

Shearwater (Cloud Desktop / on-unit planner) and MultiDeco are closed source,
so unlike the Subsurface and Baker oracles they can't be compiled and driven
directly. Instead, tests/shearwater_golden.json holds profiles to be planned
manually in those tools; once a dive's "expected" schedule is transcribed the
test here compares eko-deco against it. Unfilled dives are reported as
skipped, so the suite doubles as a to-do list.

How to fill a fixture: see the "_readme" key in shearwater_golden.json.

Environment assumptions (match the planners' defaults): 10 msw/bar
(EN 13319 / salt), air = 21 % O2, surface ~1013 mbar — i.e. eko-deco's own
defaults; only GF, rates and gases are taken from the fixture.
"""

from __future__ import annotations

import json
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..")))

import buhlmann as b

FIXTURES = os.path.join(_HERE, "shearwater_golden.json")

STOP_TOL_DEFAULT = 2.0   # min per stop
TTS_TOL_DEFAULT = 3.0    # min


def _gas(d: dict) -> b.Gas:
    return b.Gas(d["o2"] / 100.0, d.get("he", 0) / 100.0)


def _schedule(dive: dict):
    plan = b.DivePlan(
        gf_low=dive["gf"][0] / 100.0, gf_high=dive["gf"][1] / 100.0,
        descent_rate=dive.get("descent_rate", 18.0),
        ascent_rate=dive.get("ascent_rate", 10.0),
        last_stop_depth=dive.get("last_stop_m", 3.0),
        deco_gases=tuple(_gas(g) for g in dive.get("deco_gases", [])))
    # match the source planner's water-vapour constant if it differs from
    # eko-deco's Buhlmann default (MultiDeco: Schreiner 0.0567)
    saved_p_h2o = b.P_H2O
    b.P_H2O = dive.get("p_h2o", saved_p_h2o)
    try:
        segs, _ = b.plan_dive(dive["depth_m"], dive["bottom_time_min"],
                              _gas(dive["bottom_gas"]), plan)
    finally:
        b.P_H2O = saved_p_h2o
    return ([(s.depth_start, s.duration) for s in segs if s.kind == "stop"],
            b.time_to_surface(segs))


class TestShearwaterGolden(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(FIXTURES) as f:
            cls.dives = json.load(f)["dives"]

    def test_golden_schedules(self):
        unfilled = 0
        for dive in self.dives:
            with self.subTest(dive["name"]):
                if not dive.get("expected"):
                    unfilled += 1
                    self.skipTest("no golden data yet — plan this profile in "
                                  "Shearwater Cloud / MultiDeco and fill "
                                  "'expected' in shearwater_golden.json")
                stops, tts = _schedule(dive)
                exp = dive["expected"]
                stop_tol = dive.get("stop_tol_min", STOP_TOL_DEFAULT)
                tts_tol = dive.get("tts_tol_min", TTS_TOL_DEFAULT)
                detail = (f"\n  eko:    {stops} TTS {tts:.1f}"
                          f"\n  golden: {exp['stops']} TTS {exp['tts_min']}"
                          f"  [{dive.get('source', 'unknown source')}]")
                self.assertLessEqual(abs(tts - exp["tts_min"]), tts_tol,
                                     msg="TTS" + detail)
                e = dict(stops)
                g = {float(d): float(t) for d, t in exp["stops"]}
                for depth in sorted(set(e) | set(g), reverse=True):
                    self.assertLessEqual(
                        abs(e.get(depth, 0.0) - g.get(depth, 0.0)), stop_tol,
                        msg=f"stop {depth} m" + detail)
        if unfilled == len(self.dives):
            self.skipTest(f"all {unfilled} golden fixtures still unfilled")


if __name__ == "__main__":
    unittest.main()
