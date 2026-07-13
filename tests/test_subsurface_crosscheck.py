"""Cross-check buhlmann.py against Subsurface's native deco.cpp.

The oracle is the real, unmodified Subsurface model code (GPL-2.0, pinned
commit in subsurface_oracle/upstream/UPSTREAM.txt) compiled on demand to
subsurface_oracle/libsubsurface_deco.so and driven through subsurface_deco.py.
Needs g++; the whole module skips itself if the library can't be built.

Run:  python -m unittest tests.test_subsurface_crosscheck -v
      (or the usual: python -m unittest discover -s tests)

Alignment: Subsurface and eko-deco disagree on a few environmental constants,
so the eko-deco side is configured to Subsurface's values — surface pressure
1013 mbar (1_atm), salinity-based depth conversion (sea water 9.8968 m/bar),
air fed as Gas(0.209) (O2_IN_AIR = 209 permille), and initial tissue N2 from
fN2 = 0.781 (N2_IN_AIR = 781). The one structural difference left is the
GF-low anchor: eko-deco fixes it at the rounded first stop when leaving the
bottom, Subsurface tracks the smooth deepest GF-low ceiling dynamically with
a surface+1 bar floor. That bounds the schedule-level tolerances below (and
is why the GF 20/85 case gets a wider one); everything at tissue/ceiling
level agrees to machine precision.
"""

from __future__ import annotations

import math
import os
import random
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..")))
sys.path.insert(0, _HERE)

import buhlmann as b

try:
    import subsurface_deco as sd
    sd.lib()
except Exception as exc:  # no g++ / build failure — keep the core suite green
    raise unittest.SkipTest(f"subsurface oracle unavailable: {exc}")

from subsurface_deco import SubsurfaceDeco, Gas

SEA = sd.SEAWATER_SALINITY
FRESH = sd.FRESHWATER_SALINITY

EKO_AIR, SRF_AIR = b.Gas(0.209), Gas(209)

# (eko gas, oracle gas) pairs used across the tests, incl. hypoxic + He-heavy
GAS_PAIRS = [
    (EKO_AIR, SRF_AIR),
    (b.Gas(0.32), Gas(320)),
    (b.Gas(0.36), Gas(360)),
    (b.Gas(0.50), Gas(500)),
    (b.Gas(1.00), Gas(1000)),
    (b.Gas(0.21, 0.35), Gas(210, 350)),
    (b.Gas(0.18, 0.45), Gas(180, 450)),
    (b.Gas(0.10, 0.70), Gas(100, 700)),
    (b.Gas(0.35, 0.25), Gas(350, 250)),
]


def surface_bar(surface_mbar: int = 1013) -> float:
    return surface_mbar / 1000.0


def msw_per_bar(salinity: int = SEA) -> float:
    return 1.0 / (salinity * 0.981 / 1e5)


def surface_tissues(surface_mbar: int = 1013) -> b.Tissues:
    """eko-deco tissues saturated like Subsurface's clear_deco (fN2 = 0.781)."""
    p = (surface_bar(surface_mbar) - b.P_H2O) * 0.781
    return b.Tissues(pN2=[p] * 16, pHe=[0.0] * 16)


def eko_plan(gf, deco=(), surface_mbar=1013, salinity=SEA, **kw) -> b.DivePlan:
    return b.DivePlan(gf_low=gf[0] / 100, gf_high=gf[1] / 100,
                      descent_rate=18.0, surface_p=surface_bar(surface_mbar),
                      msw_per_bar=msw_per_bar(salinity),
                      deco_gases=tuple(deco), **kw)


class TestTissueLoading(unittest.TestCase):
    """add_segment vs update_tissues. Flat segments are analytically exact in
    both engines, so agreement validates half-times, the water-vapour constant
    and the exponential update in one go. Calibrated headroom: observed error
    stays below ~1e-10 bar; asserted at 1e-8."""

    def assert_tissues(self, t: b.Tissues, oracle: SubsurfaceDeco,
                       delta: float = 1e-8, msg: str = "") -> None:
        n2, he = oracle.tissues()
        for i in range(16):
            self.assertAlmostEqual(t.pN2[i], n2[i], delta=delta,
                                   msg=f"{msg} N2 compartment {i}")
            self.assertAlmostEqual(t.pHe[i], he[i], delta=delta,
                                   msg=f"{msg} He compartment {i}")

    def run_flat_profile(self, legs) -> None:
        t = surface_tissues()
        d = SubsurfaceDeco()
        for depth, (ge, gs), minutes in legs:
            amb = d.depth_to_bar(depth)
            b.update_tissues(t, ge, amb, amb, float(minutes))
            d.add_segment(amb, gs, int(minutes * 60))
        self.assert_tissues(t, d)

    def test_flat_air(self):
        self.run_flat_profile([(40.0, GAS_PAIRS[0], 30)])

    def test_flat_trimix_with_gas_switches(self):
        self.run_flat_profile([(45.0, GAS_PAIRS[5], 20),
                               (21.0, GAS_PAIRS[3], 5),
                               (6.0, GAS_PAIRS[4], 10)])

    def test_pure_o2_offgasses_everything(self):
        """On 100% O2 the inspired inert pressure is zero for both gases —
        exercises the p_insp = 0 washout path."""
        self.run_flat_profile([(30.0, GAS_PAIRS[0], 25),
                               (6.0, GAS_PAIRS[4], 30)])

    def test_deep_heliox_saturation(self):
        self.run_flat_profile([(100.0, GAS_PAIRS[7], 60)])

    def test_surface_desaturation(self):
        """12 h at the surface after a loaded dive — long off-gassing arc."""
        self.run_flat_profile([(40.0, GAS_PAIRS[0], 30),
                               (0.0, GAS_PAIRS[0], 12 * 60)])

    def test_fuzz_random_flat_profiles(self):
        """30 seeded random multi-level profiles over the full gas pool."""
        rng = random.Random(42)
        for trial in range(30):
            legs = [(rng.uniform(0.0, 80.0), rng.choice(GAS_PAIRS),
                     rng.randint(1, 30)) for _ in range(rng.randint(2, 8))]
            with self.subTest(trial=trial, legs=legs):
                self.run_flat_profile(legs)

    def test_ramps_all_rates(self):
        """eko integrates depth changes with Schreiner's equation, Subsurface
        gets 1 s constant-pressure slices — observed gap ≤ ~1.2e-3 bar."""
        for rate in (3.0, 9.0, 18.0, 30.0):
            with self.subTest(rate=rate):
                t = surface_tissues()
                d = SubsurfaceDeco()
                ge, gs = GAS_PAIRS[5]
                b.update_tissues(t, ge, d.depth_to_bar(0.0),
                                 d.depth_to_bar(60.0), 60.0 / rate)
                d.add_ramp(0.0, 60.0, rate, gs)
                self.assert_tissues(t, d, delta=5e-3, msg=f"rate {rate}")

    def test_v_profile_round_trip(self):
        """Descent + bottom + ascent, mixed integration methods."""
        t = surface_tissues()
        d = SubsurfaceDeco()
        ge, gs = GAS_PAIRS[0]
        p0, p40 = d.depth_to_bar(0.0), d.depth_to_bar(40.0)
        b.update_tissues(t, ge, p0, p40, 40 / 18.0)
        b.update_tissues(t, ge, p40, p40, 20.0)
        b.update_tissues(t, ge, p40, p0, 40 / 10.0)
        d.add_ramp(0.0, 40.0, 18.0, gs)
        d.add_flat(40.0, gs, 20 * 60)
        d.add_ramp(40.0, 0.0, 10.0, gs)
        self.assert_tissues(t, d, delta=5e-3)


class TestCeiling(unittest.TestCase):
    """Baker M-value ceiling: eko's ceiling() closed form vs Subsurface's
    tissue_tolerance_calc with gf_low == gf_high (which collapses the GF
    interpolation). Also proves the ZHL-16C a/b tables are identical.
    Observed agreement: machine epsilon; asserted at 1e-9."""

    GFS = (0.20, 0.35, 0.50, 0.75, 0.90, 1.00)

    def test_fuzzed_tissue_states(self):
        rng = random.Random(7)
        for trial in range(20):
            t = surface_tissues()
            d = SubsurfaceDeco()
            for _ in range(rng.randint(1, 6)):
                amb = d.depth_to_bar(rng.uniform(0.0, 80.0))
                ge, gs = rng.choice(GAS_PAIRS)
                b.update_tissues(t, ge, amb, amb, float(rng.randint(1, 40)))
            for gf in self.GFS:
                with self.subTest(trial=trial, gf=gf):
                    o = SubsurfaceDeco(gf_low=int(gf * 100),
                                       gf_high=int(gf * 100))
                    o.set_tissues(t.pN2, t.pHe)
                    self.assertAlmostEqual(b.ceiling(t, gf), o.tolerance_bar(),
                                           delta=1e-9)

    def test_ceiling_depth_and_stop_rounding(self):
        t = surface_tissues()
        d = SubsurfaceDeco()
        amb = d.depth_to_bar(45.0)
        b.update_tissues(t, b.Gas(0.21, 0.35), amb, amb, 25.0)
        for gf in (0.30, 0.80):
            with self.subTest(gf=gf):
                o = SubsurfaceDeco(gf_low=int(gf * 100), gf_high=int(gf * 100))
                o.set_tissues(t.pN2, t.pHe)
                eko_m = b.ceiling_depth(t, gf, surface_bar(), msw_per_bar())
                self.assertAlmostEqual(eko_m, o.ceiling_m(smooth=True), delta=0.01)
                self.assertAlmostEqual(b._round_up_to_stop(eko_m, 3.0),
                                       o.ceiling_m(smooth=False), delta=1e-9)


class TestGradientFactorInterpolation(unittest.TestCase):
    """eko's gf_at vs Subsurface's get_gf: algebraically the same line between
    (first stop, GF-low) and (surface, GF-high), including the GF-low clamp
    below the anchor. Observed agreement: machine epsilon."""

    def test_gf_line(self):
        for gf_low, gf_high in ((10, 95), (30, 80), (50, 80), (85, 85)):
            for anchor_depth in (6.0, 12.0, 18.0, 33.0, 48.0):
                d = SubsurfaceDeco(gf_low=gf_low, gf_high=gf_high)
                p_first = d.depth_to_bar(anchor_depth)
                d.gf_low_pressure_this_dive = p_first
                surf = surface_bar()
                for i in range(121):  # surface … 20 % below the anchor
                    p = surf + (i / 100.0) * (p_first - surf)
                    with self.subTest(gf=(gf_low, gf_high),
                                      anchor=anchor_depth, p_amb=round(p, 4)):
                        self.assertAlmostEqual(
                            b.gf_at(p, gf_low / 100, gf_high / 100, p_first, surf),
                            d.gf_at(p), delta=1e-9)


class TestNDL(unittest.TestCase):
    def test_ndl_pure_buhlmann_sweep(self):
        """GF 100/100 disables the GF machinery in both engines; NDLs must
        match to the minute across gases and depths. Very long NDLs cross the
        ceiling threshold on a nearly flat trajectory, where Subsurface's
        deco_allowed_depth quantizes to whole mbar — allow ±1 min there."""
        plan = eko_plan((100, 100))
        d = SubsurfaceDeco(gf_low=100, gf_high=100)
        for ge, gs in (GAS_PAIRS[0], GAS_PAIRS[1], GAS_PAIRS[2]):
            for depth in range(12, 45, 3):
                if gs.fo2 * d.depth_to_bar(depth) > 1.6:  # skip hyperoxic
                    continue
                with self.subTest(gas=repr(gs), depth=depth):
                    e = b.ndl(depth, ge, plan, start_tissues=surface_tissues())
                    s = d.ndl_min(depth, gs)
                    if e is None or s is None or min(e, s) >= 100:
                        self.assertLessEqual(abs((e or 600) - (s or 600)), 1)
                    else:
                        self.assertEqual(e, s)

    def test_ndl_with_gradient_factors(self):
        """With GF active the engines differ in the no-deco regime: Subsurface
        pins the GF-low anchor at least 1 bar below the surface
        (gf_low_position_min), eko applies pure GF-high. Within 1 min."""
        for gf in ((30, 80), (40, 85)):
            plan = eko_plan(gf)
            d = SubsurfaceDeco(gf_low=gf[0], gf_high=gf[1])
            for depth in (15, 18, 21, 27, 30, 36, 40):
                with self.subTest(gf=gf, depth=depth):
                    e = b.ndl(depth, EKO_AIR, plan,
                              start_tissues=surface_tissues())
                    s = d.ndl_min(depth, SRF_AIR)
                    self.assertLessEqual(abs(e - s), 1,
                                         msg=f"eko {e}, subsurface {s}")

    def test_ndl_at_altitude(self):
        """900 mbar surface (≈1000 m), acclimatized — exercises surface
        pressure handling end to end."""
        plan = eko_plan((100, 100), surface_mbar=900)
        d = SubsurfaceDeco(gf_low=100, gf_high=100, surface_mbar=900)
        for depth in (15, 21, 30):
            with self.subTest(depth=depth):
                e = b.ndl(depth, EKO_AIR, plan,
                          start_tissues=surface_tissues(900))
                s = d.ndl_min(depth, SRF_AIR)
                self.assertEqual(e, s)


class TestSchedules(unittest.TestCase):
    """Full deco schedules across depth/gas/GF/environment. Remaining gaps
    come from the documented GF-anchor difference plus Schreiner-vs-sliced
    ascents; calibrated bounds below (worst observed: stop Δ2 min, TTS Δ6 min
    on the GF 20/85 case — very low GF-low amplifies the anchor difference)."""

    # name, depth, time, eko gas, eko deco, srf gas, srf deco, gf,
    #   surface_mbar, salinity, tts_tol
    CASES = [
        ("18m/60min air 30/80", 18, 60, EKO_AIR, [], SRF_AIR, [], (30, 80), 1013, SEA, 4.0),
        ("24m/45min air 40/85", 24, 45, EKO_AIR, [], SRF_AIR, [], (40, 85), 1013, SEA, 4.0),
        ("30m/40min EAN32 30/80", 30, 40, b.Gas(0.32), [], Gas(320), [], (30, 80), 1013, SEA, 4.0),
        ("30m/40min EAN32 85/85", 30, 40, b.Gas(0.32), [], Gas(320), [], (85, 85), 1013, SEA, 4.0),
        ("40m/30min air 20/85", 40, 30, EKO_AIR, [], SRF_AIR, [], (20, 85), 1013, SEA, 7.0),
        ("40m/30min air 30/70", 40, 30, EKO_AIR, [], SRF_AIR, [], (30, 70), 1013, SEA, 4.0),
        ("40m/30min air 100/100", 40, 30, EKO_AIR, [], SRF_AIR, [], (100, 100), 1013, SEA, 4.0),
        ("40m/30min air+O2 30/80", 40, 30, EKO_AIR, [b.Gas(1.0)], SRF_AIR, [Gas(1000)], (30, 80), 1013, SEA, 4.0),
        ("45m/25min 21/35+50+O2 30/80", 45, 25, b.Gas(0.21, 0.35),
         [b.Gas(0.5), b.Gas(1.0)], Gas(210, 350), [Gas(500), Gas(1000)], (30, 80), 1013, SEA, 4.0),
        ("51m/25min 18/45+50+O2 50/80", 51, 25, b.Gas(0.18, 0.45),
         [b.Gas(0.5), b.Gas(1.0)], Gas(180, 450), [Gas(500), Gas(1000)], (50, 80), 1013, SEA, 4.0),
        ("60m/20min 18/45+50+O2 30/80", 60, 20, b.Gas(0.18, 0.45),
         [b.Gas(0.5), b.Gas(1.0)], Gas(180, 450), [Gas(500), Gas(1000)], (30, 80), 1013, SEA, 4.0),
        ("60m/30min 15/55+50+O2 30/85", 60, 30, b.Gas(0.15, 0.55),
         [b.Gas(0.5), b.Gas(1.0)], Gas(150, 550), [Gas(500), Gas(1000)], (30, 85), 1013, SEA, 4.0),
        ("altitude 900mbar 30m/30min air 30/80", 30, 30, EKO_AIR, [], SRF_AIR, [], (30, 80), 900, SEA, 4.0),
        ("fresh water 36m/30min EAN32 30/80", 36, 30, b.Gas(0.32), [], Gas(320), [], (30, 80), 1013, FRESH, 4.0),
    ]

    STOP_TOL = 2.0  # minutes, per stop depth

    @staticmethod
    def schedules(case):
        (name, depth, time, ge, dge, gs, dgs, gf, smb, sal, _) = case
        plan = eko_plan(gf, dge, surface_mbar=smb, salinity=sal)
        segs, _ = b.plan_dive(depth, time, ge, plan,
                              start_tissues=surface_tissues(smb))
        eko_stops = [(s.depth_start, s.duration) for s in segs if s.kind == "stop"]
        eko_tts = b.time_to_surface(segs)
        o = SubsurfaceDeco(gf_low=gf[0], gf_high=gf[1],
                           surface_mbar=smb, salinity=sal)
        stops, srf_tts = o.plan(depth, time, gs, deco_gases=dgs)
        return eko_stops, eko_tts, [(s.depth_m, s.minutes) for s in stops], srf_tts

    def test_schedules(self):
        for case in self.CASES:
            with self.subTest(case[0]):
                eko_stops, eko_tts, srf_stops, srf_tts = self.schedules(case)
                detail = f"\n  eko:        {eko_stops}\n  subsurface: {srf_stops}"
                self.assertLessEqual(abs(eko_tts - srf_tts), case[-1],
                                     msg=f"TTS eko {eko_tts} vs subsurface {srf_tts}{detail}")
                e, s = dict(eko_stops), dict(srf_stops)
                for stop in sorted(set(e) | set(s), reverse=True):
                    self.assertLessEqual(
                        abs(e.get(stop, 0.0) - s.get(stop, 0.0)), self.STOP_TOL,
                        msg=f"stop {stop} m{detail}")

    def test_first_stop_within_one_step(self):
        """Deepest stop within one 3 m interval — guards the first-stop /
        GF-low anchoring behaviour (where third-party implementations have
        been seen to diverge by 6+ m)."""
        for case in self.CASES:
            with self.subTest(case[0]):
                eko_stops, _, srf_stops, _ = self.schedules(case)
                if not eko_stops and not srf_stops:
                    continue
                self.assertTrue(eko_stops and srf_stops,
                                msg=f"one engine sees no deco: eko {eko_stops}, "
                                    f"subsurface {srf_stops}")
                self.assertLessEqual(abs(eko_stops[0][0] - srf_stops[0][0]), 3.0)


class TestMultilevel(unittest.TestCase):
    """Multi-level profiles against the native Subsurface model. The schedule
    loop is ours on both sides, so this pins the *tissue* consequences of the
    level-by-level profile (Baker's oracle pins the planner convention)."""

    # name, eko levels, oracle levels [(depth, runtime, gas|None)], gf
    CASES = [
        ("45->30->18 air +EAN50",
         [b.Level(45, 25), b.Level(30, 40), b.Level(18, 55)],
         [(45, 25, None), (30, 40, None), (18, 55, None)], (30, 80)),
        ("60->40->20 trimix +EAN50+O2",
         [b.Level(60, 20), b.Level(40, 35), b.Level(20, 50)],
         [(60, 20, None), (40, 35, None), (20, 50, None)], (30, 85)),
        ("second level deeper: 30 -> 45",
         [b.Level(30, 15), b.Level(45, 30)],
         [(30, 15, None), (45, 30, None)], (30, 80)),
    ]

    def test_multilevel_schedules(self):
        for name, levels, srf_levels, gf in self.CASES:
            with self.subTest(name):
                trimix = "trimix" in name
                ge = b.Gas(0.18, 0.45) if trimix else EKO_AIR
                gs = Gas(180, 450) if trimix else SRF_AIR
                dge = [b.Gas(0.50), b.Gas(1.00)] if trimix else [b.Gas(0.50)]
                dgs = [Gas(500), Gas(1000)] if trimix else [Gas(500)]

                plan = eko_plan(gf, dge)
                segs, _ = b.plan_multilevel(levels, ge, plan,
                                            start_tissues=surface_tissues())
                eko_stops = [(s.depth_start, s.duration) for s in segs
                             if s.kind == "stop"]
                eko_tts = b.time_to_surface(segs)

                d = SubsurfaceDeco(gf_low=gf[0], gf_high=gf[1])
                stops, srf_tts = d.plan_levels(srf_levels, gs, deco_gases=dgs)
                srf_stops = [(s.depth_m, s.minutes) for s in stops]

                detail = (f"\n  eko:        {eko_stops} TTS {eko_tts:.1f}"
                          f"\n  subsurface: {srf_stops} TTS {srf_tts:.1f}")
                self.assertLessEqual(abs(eko_tts - srf_tts), 4.0,
                                     msg="TTS" + detail)
                e, s = dict(eko_stops), dict(srf_stops)
                for stop in sorted(set(e) | set(s), reverse=True):
                    self.assertLessEqual(
                        abs(e.get(stop, 0.0) - s.get(stop, 0.0)), 2.0,
                        msg=f"stop {stop} m" + detail)

    def test_tissue_state_after_the_levels(self):
        """The whole point of multi-level: the tissue loading left behind by a
        level-by-level bottom phase must match the reference model. Both engines
        are driven through the same profile with the deco ascent left off, so
        only the ramp discretization separates them (observed ≤ 2e-3 bar)."""
        levels = [b.Level(45, 25), b.Level(30, 40), b.Level(18, 55)]
        surf, mpb = surface_bar(), msw_per_bar()

        eko = surface_tissues()
        oracle = SubsurfaceDeco(gf_low=30, gf_high=80)
        oracle.clear()
        run = depth = 0.0
        for lv in levels:
            rate = 18.0 if lv.depth > depth else 10.0
            travel = abs(lv.depth - depth) / rate
            b.update_tissues(eko, EKO_AIR, b.depth_to_p_amb(depth, surf, mpb),
                             b.depth_to_p_amb(lv.depth, surf, mpb), travel)
            oracle.add_ramp(depth, lv.depth, rate, SRF_AIR)

            flat = lv.runtime - (run + travel)
            p = b.depth_to_p_amb(lv.depth, surf, mpb)
            b.update_tissues(eko, EKO_AIR, p, p, flat)
            oracle.add_flat(lv.depth, SRF_AIR, int(round(flat * 60)))
            run, depth = lv.runtime, lv.depth

        n2, he = oracle.tissues()
        for i in range(16):
            self.assertAlmostEqual(eko.pN2[i], n2[i], delta=5e-3,
                                   msg=f"N2 compartment {i} after the levels")
            self.assertAlmostEqual(eko.pHe[i], he[i], delta=5e-3,
                                   msg=f"He compartment {i} after the levels")


class TestRepetitiveDive(unittest.TestCase):
    """Two dives with a 45 min surface interval; the second carries residual
    loading into deco. Compares the second schedule and the final tissue
    state (ramp discretization accumulates over two dives: observed ≤7e-3)."""

    def test_second_dive_schedule_and_tissues(self):
        plan = eko_plan((30, 80))
        segs, t = b.plan_dive(30, 30, EKO_AIR, plan,
                              start_tissues=surface_tissues())
        b.update_tissues(t, EKO_AIR, surface_bar(), surface_bar(), 45.0)
        segs2, t2 = b.plan_dive(30, 25, EKO_AIR, plan, start_tissues=t)
        eko_stops = [(s.depth_start, s.duration) for s in segs2 if s.kind == "stop"]
        eko_tts = b.time_to_surface(segs2)

        o = SubsurfaceDeco(gf_low=30, gf_high=80)
        o.plan(30, 30, SRF_AIR)
        o.add_flat(0.0, SRF_AIR, 45 * 60)
        stops, srf_tts = o.plan(30, 25, SRF_AIR, from_current=True)
        srf_stops = [(s.depth_m, s.minutes) for s in stops]

        self.assertTrue(eko_stops and srf_stops,
                        msg="expected deco on the repetitive dive")
        self.assertLessEqual(abs(eko_tts - srf_tts), 2.0,
                             msg=f"eko {eko_stops}, subsurface {srf_stops}")
        e, s = dict(eko_stops), dict(srf_stops)
        for stop in sorted(set(e) | set(s), reverse=True):
            self.assertLessEqual(abs(e.get(stop, 0.0) - s.get(stop, 0.0)), 2.0)
        n2, he = o.tissues()
        for i in range(16):
            self.assertAlmostEqual(t2.pN2[i], n2[i], delta=2e-2)
            self.assertAlmostEqual(t2.pHe[i], he[i], delta=2e-2)


if __name__ == "__main__":
    unittest.main()
