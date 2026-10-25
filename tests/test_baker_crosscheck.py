"""Cross-check buhlmann.py against Erik Baker's original GFDECO Fortran code.

GFDECO (tests/baker_oracle/gfdeco.f, compiled on demand; module skips without
gfortran) is the published reference for the gradient-factor convention that
Shearwater, MultiDeco/V-Planner and most tech dive computers implement:

* first stop = ceiling at GF-low rounded up to the step size, deepened by his
  PROJECTED_ASCENT check until the ceiling on arrival is no deeper than it,
* GF slope anchored at that rounded first stop, static for the ascent,
* Schreiner-equation ramps, whole-minute stops,
* initial saturation (P_surf - P_H2O) * 0.79,
* sea level = 10.0 msw = 1.000 bar exactly ("based on 100000 Pa" per the
  source) — so the eko-deco side runs with surface_p=1.0.

eko-deco follows the same convention, so this suite pins the planner
behaviour. Baker's program uses the ZH-L16B nitrogen a-coefficients and a
water vapour pressure of 0.0567 bar (Rq 0.9), so those two constants are
patched onto buhlmann.py for the duration of this module (setUpModule /
tearDownModule) — the comparison validates the *planner*, the ZHL-16C tables
are pinned by tests/test_subsurface_crosscheck.py.

Reporting difference to be aware of: GFDECO clocks >= 1 minute at every stop
from the first stop down (its run times are rounded to whole minutes), while
eko-deco passes straight through stops that need no wait. Schedules are
therefore compared per-stop with a small tolerance plus total TTS; the GF
anchor is compared against eko-deco's computed (not reported) first stop.

Calibrated worst case over the matrix: per-stop 1 min, TTS 1.3 min.
"""

from __future__ import annotations

import os
import sys
import unittest
from typing import ClassVar

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from deco import buhlmann as b

try:
    import baker_deco as bd
    bd.ensure_built()
except Exception as exc:  # no gfortran — keep the core suite green
    raise unittest.SkipTest(f"Baker GFDECO oracle unavailable: {exc}") from exc

from baker_deco import BakerGas

# Baker's model constants (see baker_oracle/README.md)
ZHL16B_N2_A = (1.1696, 1.0000, 0.8618, 0.7562, 0.6667, 0.5600, 0.4947, 0.4500,
               0.4187, 0.3798, 0.3497, 0.3223, 0.2850, 0.2737, 0.2523, 0.2327)
BAKER_P_H2O = 0.0567

_saved = None


def setUpModule():
    """GFDECO is ZH-L16**B**, so its N2 'a' table is patched on for this module.
    The water-vapour pressure is NOT patched: it is a plan input now
    (DECISIONS.md #19), passed as p_h2o=BAKER_P_H2O wherever a plan is built
    here — a global only has to be patched when there is no parameter."""
    global _saved
    _saved = b.N2_A
    b.N2_A = ZHL16B_N2_A


def tearDownModule():
    b.N2_A = _saved


BAKER_SURFACE = 1.0  # bar; GFDECO msw mode: sea level = 10.0 msw


def eko_schedule(depth, time, gas, deco, gf, **plan_kw):
    plan_kw.setdefault("p_h2o", BAKER_P_H2O)
    plan = b.DivePlan(gf_low=gf[0], gf_high=gf[1], descent_rate=18.0,
                      surface_p=BAKER_SURFACE, deco_gases=tuple(deco), **plan_kw)
    segs, _ = b.plan_dive(depth, time, gas, plan,
                          start_tissues=b.Tissues.at_surface(
                              BAKER_SURFACE, b.AIR, plan.p_h2o))
    stops = [(s.depth_start, s.duration) for s in segs if s.kind == "stop"]
    return stops, b.time_to_surface(segs)


def eko_anchor(depth, time, gas, gf_low):
    """eko-deco's GF-low anchor: the first stop as the planner derives it when
    leaving the bottom — the rounded GF-low ceiling, deepened by the projected
    ascent (`buhlmann._first_stop_depth`, DECISIONS.md #36)."""
    plan = b.DivePlan(gf_low=gf_low, gf_high=max(gf_low, 0.85),
                      descent_rate=18.0, surface_p=BAKER_SURFACE,
                      p_h2o=BAKER_P_H2O)
    t = b.Tissues.at_surface(plan.surface_p, b.AIR, plan.p_h2o)
    p0 = b.depth_to_p_amb(0.0, plan.surface_p, plan.msw_per_bar)
    p_bot = b.depth_to_p_amb(depth, plan.surface_p, plan.msw_per_bar)
    t_desc = depth / plan.descent_rate
    b.update_tissues(t, gas, p0, p_bot, t_desc, plan.p_h2o)
    b.update_tissues(t, gas, p_bot, p_bot, max(0.0, time - t_desc), plan.p_h2o)
    return b._first_stop_depth(t, plan, gas, depth)


# name, depth, time, eko gas, eko deco gases, baker gases, (gf_low, gf_high)
CASES = [
    ("30m/40min EAN32 30/80", 30, 40, b.Gas(0.32), [],
     [BakerGas(0.32)], (0.30, 0.80)),
    ("40m/30min air 30/80", 40, 30, b.Gas(0.21), [],
     [BakerGas(0.21)], (0.30, 0.80)),
    ("40m/30min air 100/100", 40, 30, b.Gas(0.21), [],
     [BakerGas(0.21)], (1.00, 1.00)),
    ("40m/30min air 20/85", 40, 30, b.Gas(0.21), [],
     [BakerGas(0.21)], (0.20, 0.85)),
    ("45m/25min 21/35+50+O2 30/80", 45, 25, b.Gas(0.21, 0.35),
     [b.Gas(0.50), b.Gas(1.00)],
     [BakerGas(0.21, 0.35), BakerGas(0.50, 0, 21), BakerGas(1.00, 0, 6)],
     (0.30, 0.80)),
    ("51m/25min 18/45+50+O2 50/80", 51, 25, b.Gas(0.18, 0.45),
     [b.Gas(0.50), b.Gas(1.00)],
     [BakerGas(0.18, 0.45), BakerGas(0.50, 0, 21), BakerGas(1.00, 0, 6)],
     (0.50, 0.80)),
    ("60m/30min 15/55+50+O2 30/85", 60, 30, b.Gas(0.15, 0.55),
     [b.Gas(0.50), b.Gas(1.00)],
     [BakerGas(0.15, 0.55), BakerGas(0.50, 0, 21), BakerGas(1.00, 0, 6)],
     (0.30, 0.85)),
    # Short deep bounces: the GF-Low ceiling RISES during the ascent (the slow
    # compartments are still loading), so Baker's PROJECTED_ASCENT deepens the
    # first stop. Before eko-deco did the same, it stopped at 6 m and 9 m here
    # where GFDECO stops at 9 m and 12 m (DECISIONS.md #36).
    ("51m/5min air 30/70 bounce", 51, 5, b.Gas(0.21), [],
     [BakerGas(0.21)], (0.30, 0.70)),
    ("54m/5min air 20/85 bounce", 54, 5, b.Gas(0.21), [],
     [BakerGas(0.21)], (0.20, 0.85)),
]

# eko-deco now implements Baker's own stop discretisation — hold to the second,
# then pad the runtime to a whole minute, stopping at the rounded ceiling even
# where the ascent has already cleared it (DECISIONS.md #21). The result is that
# TTS matches GFDECO EXACTLY on every case below, so the tolerance that used to
# absorb the difference is gone.
#
# The old comment here read "covers GFDECO's >= 1 min pass-through stops": the
# behaviour was known and papered over with tolerance rather than implemented.
STOP_TOL = 1.0  # min per stop — GFDECO prints its STOP TIME column rounded UP
                # to whole minutes while ours is the true fractional hold, so a
                # sub-minute difference per stop is expected and is all that
                # remains (worst measured 0.90).
TTS_TOL = 0.05  # min — measured 0.00 across all seven cases.


class TestBakerSchedules(unittest.TestCase):
    def test_schedules(self):
        for name, depth, time, ge, dge, bg, gf in CASES:
            with self.subTest(name):
                eko_stops, eko_tts = eko_schedule(depth, time, ge, dge, gf)
                r = bd.plan(depth, time, bg, gf[0], gf[1])
                detail = f"\n  eko:   {eko_stops} TTS {eko_tts:.1f}" \
                         f"\n  baker: {r.stops} TTS {r.tts:.1f}"
                self.assertLessEqual(abs(eko_tts - r.tts), TTS_TOL,
                                     msg="TTS" + detail)
                e, s = dict(eko_stops), dict(r.stops)
                for stop in sorted(set(e) | set(s), reverse=True):
                    self.assertLessEqual(
                        abs(e.get(stop, 0.0) - s.get(stop, 0.0)), STOP_TOL,
                        msg=f"stop {stop} m" + detail)

    def test_gf_anchor_matches_baker_first_stop(self):
        """The rounded first stop that anchors the GF slope — the defining
        choice of the Baker/Shearwater convention. eko-deco's computed anchor
        must equal GFDECO's first stop. It used to be allowed one 3 m step of
        slack, because GFDECO deepens the first stop through its
        PROJECTED_ASCENT check and eko-deco did not; now it does, so the slack
        is gone (DECISIONS.md #36)."""
        for name, depth, time, ge, _dge, bg, gf in CASES:
            with self.subTest(name):
                r = bd.plan(depth, time, bg, gf[0], gf[1])
                if r.first_stop is None:
                    continue
                anchor = eko_anchor(depth, time, ge, gf[0])
                self.assertAlmostEqual(
                    anchor, r.first_stop, places=6,
                    msg=f"eko anchor {anchor} vs GFDECO first stop "
                        f"{r.first_stop}\n  baker: {r.stops}")

    def test_last_stop_6m_matches_baker_step_change(self):
        """eko-deco's last_stop_depth=6 vs GFDECO with a step-size change to
        6 m at 6 m depth — the two ways of expressing 'last stop at 6 m'.
        The 6 m stop carries the folded 3 m obligation in both engines."""
        eko_stops, eko_tts = eko_schedule(
            45, 25, b.Gas(0.21, 0.35), [b.Gas(0.50), b.Gas(1.00)],
            (0.30, 0.80), last_stop_depth=6.0)
        r = bd.plan(45, 25,
                    [BakerGas(0.21, 0.35), BakerGas(0.50, 0, 21),
                     BakerGas(1.00, 0, 6)],
                    0.30, 0.80, last_stop_step=6.0)
        detail = f"\n  eko:   {eko_stops}\n  baker: {r.stops}"
        self.assertEqual(min(d for d, _t in eko_stops), 6.0, msg=detail)
        self.assertEqual(min(d for d, _t in r.stops), 6.0, msg=detail)
        self.assertLessEqual(abs(dict(eko_stops)[6.0] - dict(r.stops)[6.0]),
                             STOP_TOL, msg="6 m stop" + detail)
        self.assertLessEqual(abs(eko_tts - r.tts), TTS_TOL, msg="TTS" + detail)

    def test_no_deco_dive_agrees(self):
        """A dive with no GF-low ceiling must produce no stops in either
        engine (Baker prints a 1 min stop for *any* positive ceiling because
        of whole-minute run-time rounding, so the profile must be cleanly
        inside the limit)."""
        eko_stops, _ = eko_schedule(12, 25, b.Gas(0.32), [], (0.30, 0.85))
        r = bd.plan(12, 25, [BakerGas(0.32)], 0.30, 0.85)
        self.assertEqual(eko_stops, [])
        self.assertEqual(r.stops, [])

    def test_marginal_deco_boundary_agrees(self):
        """Just past the no-deco limit both engines must see the same 3 m
        ceiling: eko's computed anchor is 3 m (its zero-wait stop is skipped
        in the report) and GFDECO clocks its minimum 1 min stop at 3 m."""
        anchor = eko_anchor(15, 20, b.Gas(0.32), 0.30)
        r = bd.plan(15, 20, [BakerGas(0.32)], 0.30, 0.85)
        self.assertEqual(anchor, 3.0)
        self.assertEqual(r.stops, [(3.0, 1.0)])


class TestBakerMultilevel(unittest.TestCase):
    """Multi-level profiles against GFDECO. Baker's program takes multi-level
    input natively (profile code 1 = ascent/descent, code 2 = constant depth
    keyed by Run_Time_End_of_Segment, each with its own mix — gfdeco.f:354), so
    eko-deco's `Level` maps onto it one-for-one with no reinterpretation. This
    is the real proof that multi-level planning is right, not just plausible.

    Held to the same tolerance as the square profiles (worst observed: 1 min
    per stop, 0.8 min TTS)."""

    # name, eko levels, eko bottom gas, eko deco gases,
    #       baker levels [(depth, runtime, mix#)], baker gases, gf
    CASES: ClassVar[list] = [
        ("45->30->18 air +EAN50",
         [b.Level(45, 25), b.Level(30, 40), b.Level(18, 55)],
         b.Gas(0.21), [b.Gas(0.50)],
         [(45, 25, 1), (30, 40, 1), (18, 55, 1)],
         [BakerGas(0.21), BakerGas(0.50, 0, 21)], (0.30, 0.80)),
        ("40->20 air +EAN50, GF35/75",
         [b.Level(40, 20), b.Level(20, 45)],
         b.Gas(0.21), [b.Gas(0.50)],
         [(40, 20, 1), (20, 45, 1)],
         [BakerGas(0.21), BakerGas(0.50, 0, 21)], (0.35, 0.75)),
        ("3-level trimix 51->36->21 +EAN50+O2",
         [b.Level(51, 20), b.Level(36, 35), b.Level(21, 45)],
         b.Gas(0.18, 0.45), [b.Gas(0.50), b.Gas(1.00)],
         [(51, 20, 1), (36, 35, 1), (21, 45, 1)],
         [BakerGas(0.18, 0.45), BakerGas(0.50, 0, 21), BakerGas(1.00, 0, 6)],
         (0.30, 0.80)),
        ("second level DEEPER: 30 -> 45",
         [b.Level(30, 15), b.Level(45, 30)],
         b.Gas(0.21), [b.Gas(0.50)],
         [(30, 15, 1), (45, 30, 1)],
         [BakerGas(0.21), BakerGas(0.50, 0, 21)], (0.30, 0.80)),
    ]

    def test_multilevel_schedules(self):
        for name, levels, ge, dge, blevels, bgases, gf in self.CASES:
            with self.subTest(name):
                plan = b.DivePlan(gf_low=gf[0], gf_high=gf[1], descent_rate=18.0,
                                  surface_p=BAKER_SURFACE, p_h2o=BAKER_P_H2O,
                                  deco_gases=tuple(dge))
                segs, _ = b.plan_multilevel(
                    levels, ge, plan,
                    start_tissues=b.Tissues.at_surface(BAKER_SURFACE, b.AIR,
                                                       BAKER_P_H2O))
                eko_stops = [(s.depth_start, s.duration) for s in segs
                             if s.kind == "stop"]
                eko_tts = b.time_to_surface(segs)
                r = bd.plan_levels(blevels, bgases, gf[0], gf[1])
                detail = (f"\n  eko:   {eko_stops} TTS {eko_tts:.1f}"
                          f"\n  baker: {r.stops} TTS {r.tts:.1f}")
                self.assertLessEqual(abs(eko_tts - r.tts), TTS_TOL,
                                     msg="TTS" + detail)
                e, s = dict(eko_stops), dict(r.stops)
                for stop in sorted(set(e) | set(s), reverse=True):
                    self.assertLessEqual(
                        abs(e.get(stop, 0.0) - s.get(stop, 0.0)), STOP_TOL,
                        msg=f"stop {stop} m" + detail)

    def test_multilevel_is_shorter_than_the_square_dive(self):
        """Sanity: spending the back half of the dive shallow must not produce
        more deco than staying deep for the whole runtime. Both engines agree."""
        plan = b.DivePlan(gf_low=0.30, gf_high=0.80, surface_p=BAKER_SURFACE,
                          p_h2o=BAKER_P_H2O, deco_gases=(b.Gas(0.50),))
        def tissues():
            return b.Tissues.at_surface(BAKER_SURFACE, b.AIR, BAKER_P_H2O)

        ml, _ = b.plan_multilevel([b.Level(45, 25), b.Level(18, 55)], b.Gas(0.21),
                                  plan, start_tissues=tissues())
        square, _ = b.plan_multilevel([b.Level(45, 55)], b.Gas(0.21), plan,
                                      start_tissues=tissues())
        self.assertLess(b.time_to_surface(ml), b.time_to_surface(square))

        r_ml = bd.plan_levels([(45, 25, 1), (18, 55, 1)],
                              [BakerGas(0.21), BakerGas(0.50, 0, 21)], 0.30, 0.80)
        r_sq = bd.plan_levels([(45, 55, 1)],
                              [BakerGas(0.21), BakerGas(0.50, 0, 21)], 0.30, 0.80)
        self.assertLess(r_ml.tts, r_sq.tts)


if __name__ == "__main__":
    unittest.main()
