"""Sanity checks for the Bühlmann implementation.

Run with: python -m pytest -q   (or)   python tests/test_buhlmann.py
"""
from __future__ import annotations

import math
import unittest
from typing import ClassVar

from deco import buhlmann as b


class TestConstants(unittest.TestCase):
    def test_compartment_counts(self):
        self.assertEqual(b.N_COMP, 16)
        for t in (b.N2_HALFTIME, b.N2_A, b.N2_B,
                  b.HE_HALFTIME, b.HE_A, b.HE_B):
            self.assertEqual(len(t), 16)

    def test_halftimes_monotonic(self):
        self.assertEqual(list(b.N2_HALFTIME), sorted(b.N2_HALFTIME))
        self.assertEqual(list(b.HE_HALFTIME), sorted(b.HE_HALFTIME))


class TestTissues(unittest.TestCase):
    def test_surface_saturation_air(self):
        t = b.Tissues.at_surface()
        expected = (b.P_ATM - b.P_H2O) * 0.79
        for p in t.pN2:
            self.assertAlmostEqual(p, expected, places=6)
        for p in t.pHe:
            self.assertEqual(p, 0.0)

    def test_haldane_equivalence(self):
        t = b.Tissues.at_surface()
        b.update_tissues(t, b.AIR, 4.0, 4.0, 100.0)
        p_insp = (4.0 - b.P_H2O) * 0.79
        self.assertAlmostEqual(t.pN2[0], p_insp, places=3)
        self.assertLess(t.pN2[-1], p_insp * 0.5)


class TestNDL(unittest.TestCase):
    def test_ndl_air(self):
        plan = b.DivePlan(gf_low=1.0, gf_high=1.0)
        cases = [(18, 56), (21, 37), (30, 17), (40, 7)]
        for depth, expected in cases:
            got = b.ndl(depth, b.AIR, plan)
            self.assertIsNotNone(got)
            self.assertLess(abs(got - expected), 6,
                            f"NDL {depth}m: got {got}, expected ~{expected}")

    def test_ndl_shrinks_with_depth(self):
        plan = b.DivePlan()
        prev = b.ndl(12, b.AIR, plan)
        for d in (15, 18, 21, 24, 27, 30, 33, 36):
            cur = b.ndl(d, b.AIR, plan)
            self.assertIsNotNone(cur)
            self.assertLessEqual(cur, prev)
            prev = cur


class TestPlan(unittest.TestCase):
    def test_shallow_air_dive_no_deco(self):
        segs, t = b.plan_dive(18, 30, b.AIR)
        self.assertFalse(any(s.kind == "stop" for s in segs))
        self.assertLessEqual(b.ceiling_depth(t, 0.80), 0.5)

    def test_deep_dive_requires_deco(self):
        segs, _ = b.plan_dive(45, 25, b.AIR)
        self.assertTrue(any(s.kind == "stop" for s in segs))

    def test_gas_switch_increases_fO2_with_depth(self):
        plan = b.DivePlan(deco_gases=(b.EAN50, b.O2))
        segs, _ = b.plan_dive(40, 30, b.AIR, plan)
        stops = [s for s in segs if s.kind == "stop"]
        for s in stops:
            if s.depth_start > 21.5:
                self.assertEqual(s.gas.fO2, 0.21)
            if s.depth_start <= 3:
                self.assertAlmostEqual(s.gas.fO2, 1.0)

    def test_gradient_factor_endpoints(self):
        p_stop = b.depth_to_p_amb(9.0)
        self.assertAlmostEqual(b.gf_at(p_stop, 0.3, 0.8, p_stop), 0.30)
        self.assertAlmostEqual(b.gf_at(b.P_ATM, 0.3, 0.8, p_stop), 0.80)


class TestCLI(unittest.TestCase):
    def test_parse_gas(self):
        from deco.cli import parse_gas
        self.assertEqual(parse_gas("air").fO2, 0.21)
        self.assertEqual(parse_gas("ean32").fO2, 0.32)
        self.assertEqual(parse_gas("50").fO2, 0.50)
        g = parse_gas("21/35")
        self.assertAlmostEqual(g.fO2, 0.21)
        self.assertAlmostEqual(g.fHe, 0.35)
        self.assertAlmostEqual(g.fN2, 0.44)

    def test_parse_level(self):
        from deco.cli import parse_level
        lv = parse_level("45:25")
        self.assertAlmostEqual(lv.depth, 45)
        self.assertAlmostEqual(lv.runtime, 25)
        lv = parse_level("120:20")
        self.assertAlmostEqual(lv.depth, 120)
        self.assertAlmostEqual(lv.runtime, 20)

    def test_parse_level_rejects_the_retired_start_window(self):
        """DEPTH:START-RUNTIME is gone: levels are contiguous, so the transit is
        part of the runtime (no planner has an arrival time). The old syntax
        must fail loudly rather than parse into something else."""
        from deco.cli import parse_level
        with self.assertRaises(ValueError):
            parse_level("16:4-17")

    def test_parse_level_rejects_junk(self):
        from deco.cli import parse_level
        for spec in ("45", "45:25:50", "45:25:50:9", "deep:25", "45:soon",
                     "16:soon-17", "16:4-late"):
            with self.assertRaises(ValueError, msg=spec):
                parse_level(spec)

    def test_parse_contingency(self):
        from deco.cli import parse_contingency
        none4 = (None, None, None, None)
        self.assertEqual(parse_contingency(""), none4)            # bare flag
        self.assertEqual(parse_contingency("2"), (2, None, None, None))
        self.assertEqual(parse_contingency("1:2:0:1"), (1, 2, 0, 1))
        self.assertEqual(parse_contingency(":2"), (None, 2, None, None))
        self.assertEqual(parse_contingency("::0:2"), (None, None, 0, 2))
        for spec in ("1:2:3:4:5", "soon", "-1", "1:-2", "1.5"):
            with self.assertRaises(ValueError, msg=spec):
                parse_contingency(spec)

    def test_plan_json_carries_warnings_and_toxicity(self):
        import contextlib
        import io
        import json

        from deco import cli
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli.main(["plan", "--depth", "70", "--time", "20",
                           "--gas", "air", "--json"])
        self.assertEqual(rc, 0)
        out = json.loads(buf.getvalue())
        self.assertNotIn("disclaimer", out)
        self.assertTrue(any("ppO2" in w for w in out["warnings"]))
        self.assertTrue(any("density" in w for w in out["warnings"]))
        self.assertGreater(out["cns_pct"], 0)
        self.assertGreater(out["otu"], 0)
        self.assertAlmostEqual(out["end_m"], 70.0, places=1)

    def test_plan_missing_config_is_an_error(self):
        import contextlib
        import io

        from deco import cli
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = cli.main(["plan", "/no/such/dive_plan.json"])
        self.assertEqual(rc, 2)
        self.assertIn("not found", err.getvalue())

    def test_plan_rejects_inverted_gradient_factors(self):
        import contextlib
        import io

        from deco import cli
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = cli.main(["plan", "--depth", "40", "--time", "20",
                           "--gas", "air", "--gf-low", "0.9",
                           "--gf-high", "0.4"])
        self.assertEqual(rc, 2)
        self.assertIn("gradient factors", err.getvalue())

    def test_plan_json_contingency_end_to_end(self):
        import contextlib
        import io
        import json

        from deco import cli
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli.main(["plan", "--depth", "40", "--time", "20",
                           "--gas", "air", "--deco-gas", "50",
                           "--contingency", "--json"])
        self.assertEqual(rc, 0)
        cont = json.loads(buf.getvalue())["contingency"]
        self.assertEqual(cont["time_step_min"], 3.0)
        self.assertEqual(cont["depth_step_m"], 3.0)
        self.assertEqual(cont["depths_m"], [37.0, 40.0, 43.0])
        self.assertEqual([r["bottom_time_min"] for r in cont["rows"]],
                         [17.0, 20.0, 23.0])
        for row in cont["rows"]:
            self.assertEqual([c["depth_m"] for c in row["cells"]],
                             [37.0, 40.0, 43.0])
            for c in row["cells"]:
                self.assertTrue(c["plannable"])
                self.assertIn("stops", c)
                self.assertIn("tts_min", c)


class TestMultiGasTravel(unittest.TestCase):
    HYPOXIC = b.Gas(0.10, 0.70)   # 10/70 hypoxic trimix
    TRAVEL = b.Gas(0.21, 0.35)    # 21/35 travel/bottom-ish mix

    def test_travel_gas_used_when_bottom_gas_hypoxic_at_surface(self):
        plan = b.DivePlan(travel_gases=(self.TRAVEL,), deco_gases=(b.EAN50, b.O2))
        segs, _ = b.plan_dive(70, 20, self.HYPOXIC, plan)
        descents = [s for s in segs if s.kind == "descent"]
        self.assertAlmostEqual(descents[0].gas.fO2, self.TRAVEL.fO2)
        self.assertAlmostEqual(descents[0].gas.fHe, self.TRAVEL.fHe)
        self.assertTrue(any(s.gas.fHe == self.HYPOXIC.fHe for s in descents),
                        "bottom gas is never picked up on descent")

    def test_bottom_gas_switch_depth_is_its_min_depth(self):
        plan = b.DivePlan(travel_gases=(self.TRAVEL,))
        segs, _ = b.plan_dive(60, 15, self.HYPOXIC, plan)
        on_bottom = [s for s in segs
                     if s.kind == "descent" and s.gas.fHe == self.HYPOXIC.fHe]
        self.assertTrue(on_bottom)
        first = min(s.depth_start for s in on_bottom)
        self.assertAlmostEqual(first, self.HYPOXIC.min_depth(plan.ppo2_min), delta=0.5)

    def test_no_segment_is_breathed_hypoxic(self):
        plan = b.DivePlan(travel_gases=(self.TRAVEL,), deco_gases=(b.EAN50, b.O2))
        segs, _ = b.plan_dive(70, 25, self.HYPOXIC, plan)
        for s in segs:
            shallow = min(s.depth_start, s.depth_end)
            self.assertGreaterEqual(
                s.gas.ppo2(shallow), plan.ppo2_min - 1e-6,
                f"{s.gas!r} hypoxic on {s.kind} at {shallow:.1f} m")

    def test_no_segment_exceeds_deco_ppo2_ceiling(self):
        # switches snap to stop depths, so ppO2 may exceed ppo2_deco by at
        # most ppo2_switch_tol (O2 at the 6 m stop: 1.613 bar)
        plan = b.DivePlan(deco_gases=(b.EAN50, b.O2))
        segs, _ = b.plan_dive(45, 25, b.AIR, plan)
        for s in segs:
            deep = max(s.depth_start, s.depth_end)
            self.assertLessEqual(
                s.gas.ppo2(deep), plan.ppo2_deco + plan.ppo2_switch_tol + 1e-6,
                f"{s.gas!r} ppO2 too high on {s.kind} at {deep:.1f} m")

    def test_descent_stays_on_bottom_gas_when_normoxic(self):
        plan = b.DivePlan(travel_gases=(b.O2,))
        segs, _ = b.plan_dive(30, 20, b.EAN32, plan)
        descents = [s for s in segs if s.kind == "descent"]
        self.assertEqual(len(descents), 1)
        self.assertAlmostEqual(descents[0].gas.fO2, 0.32)

    def test_multiple_deco_gases_richest_used_shallowest(self):
        plan = b.DivePlan(deco_gases=(b.EAN50, b.O2))
        segs, _ = b.plan_dive(45, 25, b.AIR, plan)
        stops = [s for s in segs if s.kind == "stop"]
        shallowest = min(stops, key=lambda s: s.depth_start)
        self.assertAlmostEqual(shallowest.gas.fO2, 1.0)
        for s in stops:
            if s.gas.fO2 == 1.0:
                self.assertLessEqual(s.depth_start, plan.switch_depth(b.O2) + 1e-6)
            if s.gas.fO2 == 0.50:
                self.assertLessEqual(s.depth_start, plan.switch_depth(b.EAN50) + 1e-6)

    def test_switch_depths_snap_to_stops(self):
        plan = b.DivePlan()
        # O2: MOD 5.87 m at ppO2 1.6 -> standard 6 m stop (excess 0.013 bar)
        self.assertAlmostEqual(plan.switch_depth(b.O2), 6.0)
        # EAN50: MOD 21.87 m -> 21 m stop (nearest, no excess)
        self.assertAlmostEqual(plan.switch_depth(b.EAN50), 21.0)
        # a switch is never rounded deeper than ppo2_switch_tol allows
        tight = b.DivePlan(ppo2_switch_tol=0.001)
        self.assertAlmostEqual(tight.switch_depth(b.O2), 3.0)

    def test_min_depth_and_ppo2_helpers(self):
        self.assertAlmostEqual(self.HYPOXIC.min_depth(0.18),
                               (0.18 / 0.10 - b.P_ATM) * 10.0, places=6)
        self.assertEqual(b.AIR.min_depth(0.18), 0.0)
        self.assertAlmostEqual(b.O2.ppo2(0.0), b.P_ATM, places=6)


#: The two plans the reserve tests plan their dives with. `emergency_gas_liters`
#: takes the DivePlan (it re-plans the dive truncated at each level to find the
#: worst moment, and bills at the plan's environment and deco stack), so these
#: must be the same objects the segments were planned with.
PLAIN = b.DivePlan()
DECO50 = b.DivePlan(deco_gases=(b.EAN50,))


class TestTTSandRockBottom(unittest.TestCase):
    def test_tts_is_ascent_plus_stops(self):
        segs, _ = b.plan_dive(45, 25, b.AIR, b.DivePlan())
        manual = sum(s.duration for s in segs if s.kind in ("ascent", "stop"))
        self.assertAlmostEqual(b.time_to_surface(segs), manual)
        self.assertGreater(b.time_to_surface(segs), 0)

    def test_tts_no_deco_is_just_the_ascent(self):
        segs, _ = b.plan_dive(18, 20, b.AIR, b.DivePlan())
        self.assertFalse(any(s.kind == "stop" for s in segs))
        self.assertAlmostEqual(b.time_to_surface(segs), 18 / 10.0, places=6)

    def test_rock_bottom_scales_linearly_with_multiplier(self):
        segs, _ = b.plan_dive(30, 20, b.AIR, b.DivePlan())
        gp1 = b.GasPlan(sac=20, sac_multiplier=1.0)
        gp2 = b.GasPlan(sac=20, sac_multiplier=2.0)
        self.assertAlmostEqual(b.rock_bottom_liters(segs, b.AIR, gp2, PLAIN),
                               2 * b.rock_bottom_liters(segs, b.AIR, gp1, PLAIN),
                               places=6)

    def test_rock_bottom_grows_with_multiplier(self):
        segs, _ = b.plan_dive(30, 20, b.AIR, b.DivePlan())
        lo = b.rock_bottom_liters(segs, b.AIR,
                                  b.GasPlan(sac=20, sac_multiplier=1.5), PLAIN)
        hi = b.rock_bottom_liters(segs, b.AIR,
                                  b.GasPlan(sac=20, sac_multiplier=3.0), PLAIN)
        self.assertGreater(hi, lo)

    def test_rock_bottom_is_problem_plus_real_ascent(self):
        # No-deco dive: rock bottom = problem at max depth + the real ascent,
        # all on the bottom gas at the emergency SAC (no switch, so no divers
        # split here).
        segs, _ = b.plan_dive(18, 20, b.AIR, b.DivePlan())
        gp = b.GasPlan(sac=20, sac_multiplier=2.0, problem_minutes=2.0)
        sac_e = 20 * 2.0
        be = b._bottom_phase_end(segs)
        ascent = b.segment_gas_liters(segs[be:], sac_e)
        problem = sac_e * b.depth_to_p_amb(18) * 2.0
        self.assertAlmostEqual(b.rock_bottom_liters(segs, b.AIR, gp, PLAIN),
                               problem + ascent, places=6)

    def test_rock_bottom_grows_with_depth(self):
        gp = b.GasPlan(sac=20, sac_multiplier=2.0)
        deep, _ = b.plan_dive(45, 20, b.AIR, b.DivePlan())
        shallow, _ = b.plan_dive(30, 20, b.AIR, b.DivePlan())
        self.assertGreater(b.rock_bottom_liters(deep, b.AIR, gp, PLAIN),
                           b.rock_bottom_liters(shallow, b.AIR, gp, PLAIN))

    def test_rock_bottom_is_a_practical_reserve(self):
        # 45 m single-diver min gas on a 24 L twinset is a realistic reserve —
        # tens of bar (back gas only to the first switch), not the hundreds the
        # old full-deco method produced.
        segs, _ = b.plan_dive(45, 25, b.AIR,
                              b.DivePlan(deco_gases=(b.EAN50,)))
        gp = b.GasPlan(sac=20, sac_multiplier=2.0)
        bar = b.rock_bottom_liters(segs, b.AIR, gp, DECO50) / 24.0
        self.assertGreater(bar, 15)
        self.assertLess(bar, 120)

    def test_segment_gas_liters_hand_calc_single_segment(self):
        seg = b.DiveSegment("bottom", 20, 20, 10.0, b.AIR)
        ata = b.depth_to_p_amb(20)
        self.assertAlmostEqual(b.segment_gas_liters([seg], 15),
                               15 * ata * 10.0, places=6)

    def test_emergency_gas_hand_calc(self):
        # Constructed profile: bottom phase on air, ascent + stop on EAN50.
        # Rock-bottom reserve: problem at max depth billed to the bottom gas +
        # the ascent/deco at SAC × multiplier. The gas already breathed on the
        # bottom is NOT part of the reserve.
        segs = [b.DiveSegment("descent", 0, 30, 2.0, b.AIR),
                b.DiveSegment("bottom", 30, 30, 18.0, b.AIR),
                b.DiveSegment("ascent", 30, 6, 2.4, b.EAN50),
                b.DiveSegment("stop", 6, 6, 5.0, b.EAN50)]
        gp = b.GasPlan(sac=20, sac_multiplier=1.5, problem_minutes=2.0)
        sac_e = 20 * 1.5
        air = sac_e * b.depth_to_p_amb(30) * 2.0            # problem only
        ean50 = b.segment_gas_liters(segs[2:], sac_e)
        self.assertAlmostEqual(b.emergency_gas_liters(segs, b.AIR, gp, PLAIN),
                               air, places=6)
        self.assertAlmostEqual(b.emergency_gas_liters(segs, b.EAN50, gp, PLAIN),
                               ean50, places=6)

    def test_emergency_reserve_is_ascent_only_at_base_sac(self):
        # multiplier 1 + no problem time = just the ascent/deco consumption of
        # each gas (the bottom phase is not part of the reserve).
        segs, _ = b.plan_dive(40, 25, b.AIR,
                              b.DivePlan(deco_gases=(b.EAN50,)))
        gp = b.GasPlan(sac=20, sac_multiplier=1.0, problem_minutes=0.0)
        be = b._bottom_phase_end(segs)
        for gas in (b.AIR, b.EAN50):
            self.assertAlmostEqual(
                b.emergency_gas_liters(segs, gas, gp, DECO50),
                b.segment_gas_liters([s for s in segs[be:] if s.gas == gas],
                                     20),
                places=6)

    def test_emergency_problem_minutes_bill_the_bottom_gas_only(self):
        segs, _ = b.plan_dive(40, 25, b.AIR,
                              b.DivePlan(deco_gases=(b.EAN50,)))
        gp0 = b.GasPlan(sac=20, sac_multiplier=2.0, problem_minutes=0.0)
        gp5 = b.GasPlan(sac=20, sac_multiplier=2.0, problem_minutes=5.0)
        self.assertAlmostEqual(b.emergency_gas_liters(segs, b.EAN50, gp5, DECO50),
                               b.emergency_gas_liters(segs, b.EAN50, gp0, DECO50),
                               places=6)
        self.assertAlmostEqual(b.emergency_gas_liters(segs, b.AIR, gp5, DECO50)
                               - b.emergency_gas_liters(segs, b.AIR, gp0, DECO50),
                               2.0 * 20 * b.depth_to_p_amb(40) * 5.0, places=6)

    def test_emergency_two_divers_share_until_the_first_switch(self):
        # Buddy out of gas: problem minutes + the ascent on the bottom gas
        # (up to the EAN50 switch) are doubled; the deco gas after the switch
        # is each diver's own, so its need does not change.
        segs, _ = b.plan_dive(40, 25, b.AIR,
                              b.DivePlan(deco_gases=(b.EAN50,)))
        gp1 = b.GasPlan(sac=20, sac_multiplier=2.0, problem_minutes=2.0,
                        divers=1)
        gp2 = b.GasPlan(sac=20, sac_multiplier=2.0, problem_minutes=2.0,
                        divers=2)
        self.assertAlmostEqual(b.emergency_gas_liters(segs, b.EAN50, gp2, DECO50),
                               b.emergency_gas_liters(segs, b.EAN50, gp1, DECO50),
                               places=6)
        be = b._bottom_phase_end(segs)
        shared = b.segment_gas_liters(
            [s for s in segs[be:] if s.gas == b.AIR], 40)
        problem = 40 * b.depth_to_p_amb(40) * 2.0
        self.assertAlmostEqual(b.emergency_gas_liters(segs, b.AIR, gp2, DECO50)
                               - b.emergency_gas_liters(segs, b.AIR, gp1, DECO50),
                               shared + problem, places=6)

    def test_emergency_two_divers_no_switch_shares_to_the_surface(self):
        segs, _ = b.plan_dive(40, 25, b.AIR, b.DivePlan())
        gp1 = b.GasPlan(sac=20, sac_multiplier=2.0, problem_minutes=0.0,
                        divers=1)
        gp2 = b.GasPlan(sac=20, sac_multiplier=2.0, problem_minutes=0.0,
                        divers=2)
        be = b._bottom_phase_end(segs)
        ascent_e = b.segment_gas_liters(segs[be:], 40)
        self.assertAlmostEqual(b.emergency_gas_liters(segs, b.AIR, gp2, PLAIN)
                               - b.emergency_gas_liters(segs, b.AIR, gp1, PLAIN),
                               ascent_e, places=6)

    def test_rock_bottom_scales_with_divers(self):
        segs, _ = b.plan_dive(30, 20, b.AIR, b.DivePlan())
        gp1 = b.GasPlan(sac=20, sac_multiplier=2.0, divers=1)
        gp2 = b.GasPlan(sac=20, sac_multiplier=2.0, divers=2)
        self.assertAlmostEqual(b.rock_bottom_liters(segs, b.AIR, gp2, PLAIN),
                               2 * b.rock_bottom_liters(segs, b.AIR, gp1, PLAIN),
                               places=6)

    def test_rock_bottom_equals_bottom_gas_emergency(self):
        # Rock bottom and the emergency column must always agree for the back
        # gas — the user-facing invariant the rock-bottom column relies on.
        plan = b.DivePlan(deco_gases=(b.EAN50, b.O2))
        segs, _ = b.plan_dive(45, 25, b.AIR, plan)
        gp = b.GasPlan(sac=18, sac_multiplier=1.8, problem_minutes=1.0)
        self.assertAlmostEqual(b.rock_bottom_liters(segs, b.AIR, gp, plan),
                               b.emergency_gas_liters(segs, b.AIR, gp, plan),
                               places=6)


class TestReserveWorstMoment(unittest.TestCase):
    """The reserve is taken at the worst level, not the last one.

    This was a documented approximation ("can UNDERSTATE the true worst case")
    for as long as multi-level dives have been supported, and it understated
    minimum gas by ~48 % on the profile below — 14 bar where the deep level
    needs 27. A safety number is the wrong place to keep an approximation whose
    error direction is optimistic (DECISIONS.md #7).
    """

    DEEP_FIRST: ClassVar[list] = [b.Level(45.0, 25.0),
                                  b.Level(18.0, 45.0)]

    def _plan(self):
        return b.DivePlan(deco_gases=(b.EAN50,))

    def test_deep_first_reserves_for_the_deep_level(self):
        plan = self._plan()
        segs, _ = b.plan_multilevel(list(self.DEEP_FIRST), b.AIR, plan)
        gp = b.GasPlan(sac=20, sac_multiplier=1.5, problem_minutes=2.0)
        got = b.rock_bottom_liters(segs, b.AIR, gp, plan)
        # what the dive truncated at the deep level actually needs
        deep, _ = b.plan_dive(45.0, 25.0, b.AIR, plan)
        want = b.rock_bottom_liters(deep, b.AIR, gp, plan)
        self.assertAlmostEqual(got, want, places=6)
        # and it is materially more than the last level would have asked for
        last_only = b._reserve_at(segs, b.AIR, gp, plan)
        self.assertGreater(got, last_only * 1.4)

    def test_a_square_dive_is_unchanged(self):
        """One level = one candidate moment, so nothing about the square-dive
        figure moves — the MultiDeco scenarios and the golden cards depend on
        that."""
        plan = self._plan()
        segs, _ = b.plan_dive(40.0, 25.0, b.AIR, plan)
        gp = b.GasPlan(sac=20, sac_multiplier=1.5, problem_minutes=2.0)
        self.assertAlmostEqual(b.rock_bottom_liters(segs, b.AIR, gp, plan),
                               b._reserve_at(segs, b.AIR, gp, plan), places=6)

    def test_shallow_first_is_the_last_level_anyway(self):
        """When the deepest level IS the last one, the worst moment is where it
        always was; the scan must not inflate it."""
        plan = self._plan()
        levels = [b.Level(18.0, 20.0), b.Level(45.0, 40.0)]
        segs, _ = b.plan_multilevel(levels, b.AIR, plan)
        gp = b.GasPlan(sac=20, sac_multiplier=1.5, problem_minutes=2.0)
        self.assertAlmostEqual(b.rock_bottom_liters(segs, b.AIR, gp, plan),
                               b._reserve_at(segs, b.AIR, gp, plan), places=6)

    def test_levels_of_round_trips_the_profile(self):
        plan = self._plan()
        segs, _ = b.plan_multilevel(list(self.DEEP_FIRST), b.AIR, plan)
        got = b.levels_of(segs)
        self.assertEqual([(l.depth, l.runtime) for l in got],
                         [(l.depth, l.runtime) for l in self.DEEP_FIRST])


class TestMultilevel(unittest.TestCase):
    """Multi-level profiles. `Level.runtime` is the runtime at the END of the
    level (cumulative, descent included) — the same meaning bottom_time has
    always had, which is what lets a single level reproduce a square dive."""

    PLAN = b.DivePlan(gf_low=0.30, gf_high=0.80, deco_gases=(b.EAN50, b.O2))

    def stops(self, segs):
        return [(s.depth_start, s.duration) for s in segs if s.kind == "stop"]

    def test_single_level_is_exactly_plan_dive(self):
        """The regression guard: plan_dive is plan_multilevel with one level, so
        a square dive must come out bit-for-bit identical."""
        square, t1 = b.plan_dive(45, 25, b.AIR, self.PLAN)
        one_level, t2 = b.plan_multilevel([b.Level(45, 25)], b.AIR, self.PLAN)
        self.assertEqual([s.as_dict() for s in square],
                         [s.as_dict() for s in one_level])
        self.assertEqual(t1.pN2, t2.pN2)
        self.assertEqual(t1.pHe, t2.pHe)

    def test_runtime_is_cumulative_and_includes_travel(self):
        levels = [b.Level(45, 25), b.Level(30, 40), b.Level(18, 55)]
        segs, _ = b.plan_multilevel(levels, b.AIR, self.PLAN)
        bottoms = [s for s in segs if s.kind == "bottom"]
        self.assertEqual([s.depth_start for s in bottoms], [45, 30, 18])
        # runtime at the end of the last level == its declared runtime
        bottom_end = 0.0
        for s in segs:
            bottom_end += s.duration
            if s is bottoms[-1]:
                break
        self.assertAlmostEqual(bottom_end, 55.0, places=6)
        # descent (2.5 min) is inside level 1's 25 min, not added to it
        self.assertAlmostEqual(bottoms[0].duration, 25.0 - 45 / 18.0, places=6)

    def test_levels_are_contiguous_transit_billed_to_the_runtime(self):
        """No arrival time: the transit to a level leaves the moment the
        previous level ends and its time comes out of that level's runtime —
        the MultiDeco/GFDECO/Subsurface convention. A 16 m level to runtime 17
        is 16/18 min of descent plus the remainder flat, with no hold at 0 m."""
        segs, _ = b.plan_multilevel([b.Level(16, 17)], b.AIR, self.PLAN)
        self.assertEqual(segs[0].kind, "descent")           # no surface hold
        self.assertAlmostEqual(segs[0].duration, 16 / 18.0, places=6)
        flat = segs[1]
        self.assertEqual((flat.kind, flat.depth_start), ("bottom", 16))
        self.assertAlmostEqual(flat.duration, 17 - 16 / 18.0, places=6)

    def test_no_duplicate_bottom_segment_at_the_same_depth(self):
        """Each level contributes exactly one bottom segment, so a schedule can
        never print the same depth twice in a row (what the retired arrival
        time used to cause)."""
        segs, _ = b.plan_multilevel([b.Level(26, 16), b.Level(36, 33)],
                                    b.EAN32, self.PLAN)
        depths = [s.depth_start for s in segs if s.kind == "bottom"]
        self.assertEqual(depths, [26, 36])

    def test_runtime_shorter_than_the_transit_is_rejected(self):
        """MultiDeco's "segment time … too short … for descent/ascent": a level
        whose runtime cannot cover the transit is an error, not a silent hold."""
        with self.assertRaises(ValueError):   # 16 m needs 0.9 min to reach
            b.plan_multilevel([b.Level(16, 0.5)], b.AIR, self.PLAN)

    def test_going_shallow_shortens_the_deco(self):
        deep, _ = b.plan_multilevel([b.Level(45, 55)], b.AIR, self.PLAN)
        multi, _ = b.plan_multilevel([b.Level(45, 25), b.Level(18, 55)],
                                     b.AIR, self.PLAN)
        self.assertLess(b.time_to_surface(multi), b.time_to_surface(deep))

    def test_tts_excludes_travel_between_levels(self):
        """Travel between levels is bottom time, not time-to-surface — it is an
        ascent segment, so a naive kind filter would wrongly count it."""
        levels = [b.Level(45, 25), b.Level(30, 40), b.Level(18, 55)]
        segs, _ = b.plan_multilevel(levels, b.AIR, self.PLAN)
        deco_only = sum(s.duration for s in segs
                        if s.kind in ("ascent", "stop")
                        and s.depth_start <= 18 + 1e-9)
        self.assertAlmostEqual(b.time_to_surface(segs), deco_only, places=6)

    def test_auto_level_breathes_the_bottom_gas_when_it_is_breathable(self):
        segs, _ = b.plan_multilevel([b.Level(40, 20), b.Level(20, 35)],
                                    b.EAN32, self.PLAN)
        for s in (s for s in segs if s.kind == "bottom"):
            self.assertAlmostEqual(s.gas.fO2, 0.32)

    def test_auto_level_picks_the_gas_relevant_at_that_depth(self):
        """'auto' is not 'the bottom gas' — it is the gas that is actually
        breathable there. A hypoxic bottom mix cannot be breathed on a shallow
        level, so the carried travel mix is used instead."""
        hypoxic, travel = b.Gas(0.10, 0.70), b.Gas(0.35, 0.25)
        plan = b.DivePlan(gf_low=0.30, gf_high=0.80,
                          travel_gases=(travel,), deco_gases=(b.EAN50,))
        segs, _ = b.plan_multilevel([b.Level(60, 20), b.Level(6, 40)],
                                    hypoxic, plan)
        levels = [s for s in segs if s.kind == "bottom"]
        self.assertAlmostEqual(levels[0].gas.fHe, 0.70)   # deep: the bottom mix
        self.assertAlmostEqual(levels[1].gas.fO2, 0.35)   # 6 m: 10/70 is hypoxic
        # and nothing is ever breathed outside the ppO2 window
        for s in segs:
            shallow = min(s.depth_start, s.depth_end)
            self.assertGreaterEqual(s.gas.ppo2(shallow), plan.ppo2_min - 1e-6,
                                    f"{s.gas!r} hypoxic at {shallow:.1f} m")

    def test_level_above_the_ceiling_is_flagged_but_still_planned(self):
        # 45 m for 30 min then straight to 6 m: the 6 m level is well above the
        # ceiling. The schedule is still produced; the level carries the ceiling.
        segs, _ = b.plan_multilevel([b.Level(45, 30), b.Level(6, 35)],
                                    b.AIR, self.PLAN)
        bad = b.ceiling_violations(segs)
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0].depth_start, 6)
        self.assertGreater(bad[0].ceiling_m, 6)
        self.assertTrue(self.stops(segs))          # still planned

    def test_legal_profile_has_no_ceiling_violation(self):
        segs, _ = b.plan_multilevel([b.Level(45, 25), b.Level(30, 40)],
                                    b.AIR, self.PLAN)
        self.assertEqual(b.ceiling_violations(segs), [])

    def test_max_and_average_depth(self):
        levels = [b.Level(45, 25), b.Level(18, 55)]
        segs, _ = b.plan_multilevel(levels, b.AIR, self.PLAN)
        self.assertEqual(b.max_depth(levels), 45)
        avg = b.average_depth(segs)
        self.assertLess(avg, 45)
        self.assertGreater(avg, 18)
        # a square dive's average depth is (nearly) its max depth
        square, _ = b.plan_multilevel([b.Level(45, 25)], b.AIR, self.PLAN)
        self.assertAlmostEqual(b.average_depth(square), 45, delta=3)

    def test_rejects_non_increasing_runtime(self):
        with self.assertRaises(ValueError):
            b.plan_multilevel([b.Level(45, 25), b.Level(30, 20)], b.AIR, self.PLAN)

    def test_rejects_runtime_before_arrival(self):
        with self.assertRaises(ValueError):    # 45 m takes 2.5 min to reach
            b.plan_multilevel([b.Level(45, 1)], b.AIR, self.PLAN)

    def test_rejects_empty_profile(self):
        with self.assertRaises(ValueError):
            b.plan_multilevel([], b.AIR, self.PLAN)


class TestLastStopDepth(unittest.TestCase):
    """last_stop_depth=6 — the Shearwater/MultiDeco 'last stop 6 m' option."""

    def schedules(self, last_stop, depth=40, time=30):
        plan = b.DivePlan(gf_low=0.30, gf_high=0.80, last_stop_depth=last_stop)
        segs, _ = b.plan_dive(depth, time, b.AIR, plan)
        return ([(s.depth_start, s.duration) for s in segs if s.kind == "stop"],
                b.time_to_surface(segs))

    def test_no_stop_shallower_than_last_stop(self):
        stops, _ = self.schedules(6.0)
        self.assertTrue(stops)
        self.assertGreaterEqual(min(d for d, _t in stops), 6.0)

    def test_deeper_stops_unchanged(self):
        stops3, _ = self.schedules(3.0)
        stops6, _ = self.schedules(6.0)
        self.assertEqual([s for s in stops3 if s[0] > 6.0],
                         [s for s in stops6 if s[0] > 6.0])

    def test_shallow_deco_served_at_6m_takes_longer(self):
        # off-gassing at 6 m is slower than at 3 m, so folding the 3 m stop
        # into the 6 m stop must not shorten the schedule
        (stops3, tts3), (stops6, tts6) = self.schedules(3.0), self.schedules(6.0)
        self.assertGreater(dict(stops6)[6.0], dict(stops3)[6.0])
        self.assertGreaterEqual(tts6, tts3)

    def test_shallow_only_deco_collapses_to_single_6m_stop(self):
        # 21 m / 50 min air: the obligation is served almost entirely at 6 m,
        # preceded by a sub-minute PASS-THROUGH stop at the rounded GF-low
        # ceiling (9 m). Baker's GFDECO does the same — it stops at that depth
        # and pads the runtime to a whole minute even where the ceiling has
        # already cleared (DECISIONS.md #21).
        stops, _ = self.schedules(6.0, depth=21, time=50)
        self.assertEqual([d for d, _t in stops], [9.0, 6.0])
        by_depth = dict(stops)
        self.assertLess(by_depth[9.0], 1.0, "9 m is a pass-through, not a hold")
        self.assertGreater(by_depth[6.0], 20.0, "the real obligation is at 6 m")

    def test_default_is_unchanged(self):
        self.assertEqual(b.DivePlan().last_stop_depth, 3.0)


class TestCeilingProfile(unittest.TestCase):
    PLAN = b.DivePlan(gf_low=0.30, gf_high=0.80,
                      deco_gases=(b.Gas(0.50), b.Gas(1.0)))

    def test_deco_free_dive_is_flat_zero(self):
        # 12 m / 10 min air never has a ceiling, even at GF-Low
        segs, _ = b.plan_dive(12, 10, b.AIR)
        for _t, c in b.ceiling_profile(segs, b.DivePlan()):
            self.assertEqual(c, 0.0)

    def test_time_axis_spans_the_dive(self):
        segs, _ = b.plan_dive(45, 25, b.AIR, self.PLAN)
        prof = b.ceiling_profile(segs, self.PLAN)
        times = [t for t, _c in prof]
        self.assertEqual(times[0], 0.0)
        self.assertEqual(times, sorted(times))
        self.assertAlmostEqual(times[-1], b.total_runtime(segs), places=6)

    def test_deco_dive_has_a_ceiling_and_clears_it(self):
        segs, _ = b.plan_dive(45, 25, b.AIR, self.PLAN)
        prof = b.ceiling_profile(segs, self.PLAN)
        self.assertGreater(max(c for _t, c in prof), 0.0)
        self.assertLessEqual(prof[-1][1], 0.01)   # surfaces clean at GF-High

    def test_anchor_matches_the_planned_first_stop(self):
        # the ceiling on leaving the bottom, rounded up like the planner does,
        # is the first stop — and no sample is ever deeper than that stop
        segs, _ = b.plan_dive(45, 25, b.AIR, self.PLAN)
        prof = b.ceiling_profile(segs, self.PLAN)
        first_stop = max(s.depth_start for s in segs if s.kind == "stop")
        bottom_t = sum(s.duration for s in segs[:b._bottom_phase_end(segs)])
        c_bottom = max(c for t, c in prof if t <= bottom_t + 1e-9)
        rounded = max(b._round_up_to_stop(c_bottom, self.PLAN.stop_interval),
                      self.PLAN.last_stop_depth)
        self.assertEqual(rounded, first_stop)
        self.assertLessEqual(max(c for _t, c in prof), first_stop + 1e-6)

    def test_trimix_multi_gas_smoke(self):
        plan = b.DivePlan(gf_low=0.30, gf_high=0.80,
                          travel_gases=(b.Gas(0.35, 0.25),),
                          deco_gases=(b.Gas(0.50), b.Gas(1.0)))
        segs, _ = b.plan_dive(60, 25, b.Gas(0.10, 0.70), plan)
        prof = b.ceiling_profile(segs, plan)
        self.assertTrue(all(math.isfinite(c) and 0.0 <= c <= 60.0
                            for _t, c in prof))


class TestContingency(unittest.TestCase):
    PLAN = b.DivePlan(deco_gases=(b.EAN50,))

    def _stops(self, segs):
        return [(s.depth_start, s.duration) for s in segs if s.kind == "stop"]

    def test_grid_shape_and_variants(self):
        # Rows = bottom-time variants, columns = depth variants, 3 min x 3 m.
        grid = b.contingency_schedules([b.Level(40, 20)], b.AIR, self.PLAN)
        self.assertEqual([len(row) for row in grid], [3, 3, 3])
        self.assertEqual([[(c.depth, c.bottom_time) for c in row]
                          for row in grid],
                         [[(37, 17), (40, 17), (43, 17)],
                          [(37, 20), (40, 20), (43, 20)],
                          [(37, 23), (40, 23), (43, 23)]])

    def test_step_counts_extend_the_grid(self):
        grid = b.contingency_schedules([b.Level(40, 20)], b.AIR, self.PLAN,
                                       time_before=0, time_after=2,
                                       depth_before=0, depth_after=1)
        self.assertEqual([c.bottom_time for row in grid for c in row[:1]],
                         [20, 23, 26])
        self.assertEqual([c.depth for c in grid[0]], [40, 43])

    def test_plan_cell_matches_plan_dive(self):
        grid = b.contingency_schedules([b.Level(40, 20)], b.AIR, self.PLAN)
        segs, _ = b.plan_dive(40, 20, b.AIR, self.PLAN)
        cell = grid[1][1]                      # planned time x planned depth
        self.assertEqual(self._stops(cell.segments), self._stops(segs))
        self.assertAlmostEqual(b.time_to_surface(cell.segments),
                               b.time_to_surface(segs))

    def test_tts_monotone_in_time_and_depth(self):
        grid = b.contingency_schedules([b.Level(40, 25)], b.AIR, self.PLAN)
        for row in grid:                       # deeper column -> more deco
            tts = [b.time_to_surface(c.segments) for c in row]
            self.assertEqual(tts, sorted(tts))
        for col in range(3):                   # longer row -> more deco
            tts = [b.time_to_surface(row[col].segments) for row in grid]
            self.assertEqual(tts, sorted(tts))

    def test_no_deco_variant_is_a_normal_cell(self):
        grid = b.contingency_schedules([b.Level(18, 20)], b.AIR)
        short = grid[0][0]                     # shortest x shallowest
        self.assertIsNotNone(short.segments)
        self.assertFalse(any(s.kind == "stop" for s in short.segments))
        self.assertIn("no deco", short.text())

    def test_unplannable_cell_keeps_its_place(self):
        # T - 3 = 1 min < the descent to 45 m: the whole shortened row is
        # unplannable, but the grid stays rectangular (3x3) with n/a cells.
        grid = b.contingency_schedules([b.Level(45, 4)], b.AIR)
        self.assertEqual([len(row) for row in grid], [3, 3, 3])
        self.assertIsNone(grid[0][1].segments)
        self.assertEqual(grid[0][1].text(), "n/a")
        self.assertIsNotNone(grid[1][1].segments)

    def test_zero_counts_disable_directions(self):
        grid = b.contingency_schedules([b.Level(40, 20)], b.AIR,
                                       time_before=0, time_after=0,
                                       depth_before=0, depth_after=0)
        self.assertEqual([len(row) for row in grid], [1])
        self.assertEqual((grid[0][0].depth, grid[0][0].bottom_time), (40, 20))

    def test_nonpositive_variants_are_dropped(self):
        # 2 min - 3 min and 3 m - 3 m would be <= 0: those rows/columns vanish
        # instead of appearing as unplannable cells.
        grid = b.contingency_schedules([b.Level(3, 2)], b.AIR)
        self.assertEqual([c.bottom_time for row in grid for c in row[:1]],
                         [2, 5])
        self.assertEqual([c.depth for c in grid[0]], [3, 6])

    def test_cell_text_lists_stops_and_tts(self):
        import re
        grid = b.contingency_schedules([b.Level(40, 25)], b.AIR, self.PLAN)
        cell = grid[1][1]
        self.assertTrue(any(s.kind == "stop" for s in cell.segments))
        self.assertRegex(cell.text(), r"^(\d+:\d+ )*\d+:\d+ · \d+′$")
        tts = int(re.search(r"· (\d+)′$", cell.text()).group(1))
        self.assertEqual(tts, math.ceil(b.time_to_surface(cell.segments) - 1e-9))

    def test_multilevel_flattens_to_conservative_square(self):
        levels = [b.Level(45, 20), b.Level(30, 35), b.Level(18, 50)]
        grid = b.contingency_schedules(levels, b.AIR, self.PLAN)
        cell = grid[1][1]
        self.assertEqual(cell.depth, b.max_depth(levels))
        self.assertEqual(cell.bottom_time, levels[-1].runtime)
        real, _ = b.plan_multilevel(levels, b.AIR, self.PLAN)
        self.assertGreaterEqual(b.time_to_surface(cell.segments),
                                b.time_to_surface(real))


class TestDivePlanValidation(unittest.TestCase):
    def test_gf_low_over_gf_high_rejected(self):
        with self.assertRaises(ValueError):
            b.DivePlan(gf_low=0.90, gf_high=0.40)

    def test_gf_out_of_range_rejected(self):
        for lo, hi in ((0.0, 0.7), (-0.1, 0.7), (0.3, 1.2)):
            with self.assertRaises(ValueError, msg=f"{lo}/{hi}"):
                b.DivePlan(gf_low=lo, gf_high=hi)

    def test_equal_and_full_gfs_are_valid(self):
        b.DivePlan(gf_low=0.85, gf_high=0.85)
        b.DivePlan(gf_low=1.0, gf_high=1.0)


class TestPpO2Violations(unittest.TestCase):
    def test_air_below_its_mod_is_flagged_hyperoxic(self):
        segs, _ = b.plan_dive(70, 20, b.AIR)          # ppO2 1.68 on the bottom
        viol = b.ppo2_violations(segs)
        highs = [v for v in viol if v.kind == "high"]
        self.assertTrue(highs)
        worst = max(highs, key=lambda v: v.ppo2)
        self.assertAlmostEqual(worst.ppo2, b.AIR.ppo2(70), places=6)
        self.assertAlmostEqual(worst.depth, 70.0)

    def test_hypoxic_mix_without_travel_gas_is_flagged(self):
        segs, _ = b.plan_dive(60, 15, b.Gas(0.10, 0.70))
        lows = [v for v in b.ppo2_violations(segs) if v.kind == "low"]
        self.assertTrue(lows)
        self.assertLess(min(v.ppo2 for v in lows), 0.18)

    def test_clean_multigas_dive_has_no_violations(self):
        plan = b.DivePlan(gf_low=0.30, gf_high=0.80,
                          deco_gases=(b.EAN50, b.O2))
        segs, _ = b.plan_multilevel([b.Level(45, 25)], b.Gas(0.21, 0.35), plan)
        self.assertEqual(b.ppo2_violations(segs, plan), [])

    def test_worst_dedupes_to_one_line_per_gas_and_kind(self):
        segs, _ = b.plan_dive(70, 20, b.AIR)          # descent AND bottom violate
        worst = b.worst_ppo2_violations(segs)
        self.assertEqual(len(worst), 1)
        self.assertAlmostEqual(worst[0].ppo2, b.AIR.ppo2(70), places=6)


class TestOxygenToxicity(unittest.TestCase):
    @staticmethod
    def _flat(depth, minutes, gas):
        return [b.DiveSegment("bottom", depth, depth, minutes, gas)]

    def test_cns_100pct_after_45min_at_1_6_bar(self):
        depth = (1.6 - b.P_ATM) * 10.0                # ppO2 exactly 1.6 on O2
        cns, _ = b.cns_otu(self._flat(depth, 45, b.O2))
        self.assertAlmostEqual(cns, 100.0, places=6)

    def test_cns_and_otu_at_1_bar(self):
        depth = (2.0 - b.P_ATM) * 10.0                # ppO2 1.0 on EAN50
        cns, otu = b.cns_otu(self._flat(depth, 60, b.EAN50))
        self.assertAlmostEqual(cns, 20.0, places=6)   # 60 / 300 NOAA minutes
        self.assertAlmostEqual(otu, 60.0, places=6)   # rate is exactly 1 /min

    def test_no_dose_below_half_bar(self):
        cns, otu = b.cns_otu(self._flat(10, 60, b.Gas(0.21, 0.60)))
        self.assertEqual((cns, otu), (0.0, 0.0))      # ppO2 0.42 < 0.5

    def test_deeper_is_worse(self):
        shallow = b.cns_otu(self._flat(30, 30, b.EAN32))
        deep = b.cns_otu(self._flat(40, 30, b.EAN32))
        self.assertGreater(deep[0], shallow[0])
        self.assertGreater(deep[1], shallow[1])


class TestGasEndDensity(unittest.TestCase):
    def test_end_o2_narcotic_hand_calc(self):
        g = b.Gas(0.21, 0.35)
        p_narc = b.depth_to_p_amb(45.0) * (1 - 0.35)
        self.assertAlmostEqual(g.end(45.0), (p_narc - b.P_ATM) * 10.0, places=6)

    def test_end_of_air_is_the_depth_itself(self):
        self.assertAlmostEqual(b.AIR.end(40.0), 40.0, places=6)

    def test_density_air_at_surface_about_1_3(self):
        self.assertAlmostEqual(b.AIR.density(0.0), 1.29, delta=0.02)

    def test_air_passes_6_2_g_l_around_39m(self):
        self.assertLess(b.AIR.density(38.0), b.DENSITY_MAX_G_L)
        self.assertGreater(b.AIR.density(40.0), b.DENSITY_MAX_G_L)

    def test_helium_thins_the_mix(self):
        self.assertLess(b.Gas(0.21, 0.35).density(45.0), b.AIR.density(45.0))


class TestDomainValidation(unittest.TestCase):
    """Invariants enforced at construction time (crash-free boundaries)."""

    def test_level_rejects_negative_depth(self):
        with self.assertRaises(ValueError):
            b.Level(-30.0, 20.0)

    def test_level_rejects_nonpositive_runtime(self):
        for rt in (0.0, -5.0):
            with self.assertRaises(ValueError):
                b.Level(30.0, rt)

    def test_level_surface_depth_allowed(self):
        b.Level(0.0, 5.0)                      # safety stop at the surface: fine

    def test_level_has_no_arrival_time(self):
        """Levels are depth + cumulative runtime, nothing else."""
        with self.assertRaises(TypeError):
            b.Level(16.0, 17.0, start=4.0)

    def test_plan_rejects_nonpositive_rates_and_intervals(self):
        for kw in ({"ascent_rate": 0.0}, {"descent_rate": 0.0},
                   {"stop_interval": 0.0}, {"ascent_rate": -10.0},
                   {"msw_per_bar": 0.0}, {"surface_p": 0.0}):
            with self.assertRaises(ValueError, msg=kw):
                b.DivePlan(**kw)

    def test_plan_rejects_negative_last_stop(self):
        with self.assertRaises(ValueError):
            b.DivePlan(last_stop_depth=-3.0)

    def test_plan_rejects_ppo2_ceiling_below_floor(self):
        with self.assertRaises(ValueError):
            b.DivePlan(ppo2_bottom=0.1)        # below ppo2_min 0.18
        with self.assertRaises(ValueError):
            b.DivePlan(ppo2_min=-0.1)

    def test_gasplan_rejects_nonsense_inputs(self):
        for kw in ({"sac": 0.0}, {"sac": -20.0},
                   {"sac": 20.0, "sac_multiplier": 0.5},
                   {"sac": 20.0, "problem_minutes": -1.0},
                   {"sac": 20.0, "divers": 0},
                   {"sac": 20.0, "sac_deco": 0.0}):
            with self.assertRaises(ValueError, msg=kw):
                b.GasPlan(**kw)

    def test_gasplan_accepts_sane_inputs(self):
        b.GasPlan(sac=20.0, sac_multiplier=1.0, problem_minutes=0.0,
                  divers=2, sac_deco=12.0)


class TestGasFractionClamp(unittest.TestCase):
    """fN2 never leaks a tiny negative value into the model (R2-L1)."""

    def test_fn2_never_negative(self):
        # A 79% helium mix: fO2 + fHe rounds to just over 1.0 in float.
        g = b.Gas(0.21, 0.79)
        self.assertGreaterEqual(g.fN2, 0.0)
        self.assertEqual(g.fN2, 0.0)

    def test_fn2_normal_mix(self):
        self.assertAlmostEqual(b.Gas(0.32).fN2, 0.68)


class TestNonePlanDefaults(unittest.TestCase):
    """Public functions build a fresh DivePlan when passed None, so no mutable
    default instance is shared across calls (R1-M1/R2-M6)."""

    def test_plan_multilevel_none_plan(self):
        segs, _ = b.plan_multilevel([b.Level(30.0, 20.0)], b.AIR)
        self.assertTrue(segs)

    def test_ndl_none_plan(self):
        self.assertIsInstance(b.ndl(30.0, b.AIR), (int, type(None)))

    def test_ceiling_profile_and_ppo2_none_plan(self):
        segs, _ = b.plan_dive(40.0, 20.0, b.AIR)
        self.assertTrue(b.ceiling_profile(segs))
        self.assertIsInstance(b.worst_ppo2_violations(segs), list)


class TestEnvironment(unittest.TestCase):
    """Water type and altitude: the constants a fresh-water or mountain dive
    needs, added for the MultiDeco scenarios in examples/."""

    def test_water_types(self):
        self.assertEqual(b.WATER_TYPES["salt"], 10.0)
        self.assertAlmostEqual(b.WATER_TYPES["fresh"], 31 / 3)
        # fresh water holds less pressure per metre, so the same depth is a
        # lower ambient pressure and a lower ppO2
        self.assertLess(b.depth_to_p_amb(30, msw_per_bar=b.MSW_PER_BAR_FRESH),
                        b.depth_to_p_amb(30, msw_per_bar=b.MSW_PER_BAR_SALT))

    def test_surface_p_at_altitude(self):
        self.assertEqual(b.surface_p_at_altitude(0), b.P_ATM)
        self.assertEqual(b.surface_p_at_altitude(-100), b.P_ATM)
        # standard atmosphere: ~0.899 bar at 1000 m, ~0.845 at 1500 m
        self.assertAlmostEqual(b.surface_p_at_altitude(1000), 0.8988, places=3)
        self.assertAlmostEqual(b.surface_p_at_altitude(1500), 0.8456, places=3)

    def test_altitude_round_trips_through_the_inverse(self):
        for m in (0, 150, 800, 1500, 3000):
            self.assertAlmostEqual(
                b.altitude_at_surface_p(b.surface_p_at_altitude(m)), m,
                places=6)
        self.assertEqual(b.altitude_at_surface_p(b.P_ATM + 0.02), 0.0)

    def test_altitude_lengthens_deco(self):
        plan_sea = b.DivePlan(deco_gases=(b.Gas(0.50),))
        plan_alt = b.DivePlan(deco_gases=(b.Gas(0.50),),
                              surface_p=b.surface_p_at_altitude(1500))
        sea, _ = b.plan_dive(40.0, 25.0, b.AIR, plan_sea)
        alt, _ = b.plan_dive(40.0, 25.0, b.AIR, plan_alt)
        self.assertGreater(b.time_to_surface(alt), b.time_to_surface(sea))

    def test_zero_or_negative_environment_rejected(self):
        with self.assertRaises(ValueError):
            b.DivePlan(surface_p=0.0)
        with self.assertRaises(ValueError):
            b.DivePlan(msw_per_bar=-1.0)


class TestDecoSac(unittest.TestCase):
    """GasPlan.sac_deco: a second consumption rate for the deco cylinders."""

    def test_defaults_to_one_rate(self):
        gp = b.GasPlan(sac=20.0)
        self.assertEqual(gp.sac_for(b.Gas(0.50), (b.Gas(0.50),)), 20.0)
        self.assertEqual(gp.sac_for(b.AIR, (b.Gas(0.50),)), 20.0)

    def test_applies_only_to_designated_deco_gases(self):
        gp = b.GasPlan(sac=20.0, sac_deco=12.0)
        self.assertEqual(gp.sac_for(b.Gas(0.50), (b.Gas(0.50),)), 12.0)
        self.assertEqual(gp.sac_for(b.AIR, (b.Gas(0.50),)), 20.0)
        # not in the plan's deco stack -> the bottom rate, whatever the mix
        self.assertEqual(gp.sac_for(b.Gas(0.50), ()), 20.0)

    def test_non_positive_deco_sac_rejected(self):
        with self.assertRaises(ValueError):
            b.GasPlan(sac=20.0, sac_deco=0.0)
        with self.assertRaises(ValueError):
            b.GasPlan(sac=20.0, sac_deco=-5.0)

    def test_reserve_follows_the_deco_rate(self):
        """The rock-bottom reserve on a deco gas is held at that gas's own
        emergency rate, so a lower deco SAC lowers the reserve too."""
        plan = b.DivePlan(deco_gases=(b.Gas(0.50),))
        segs, _ = b.plan_dive(40.0, 25.0, b.AIR, plan)
        one = b.emergency_gas_liters(segs, b.Gas(0.50), b.GasPlan(sac=20.0),
                                     plan)
        two = b.emergency_gas_liters(segs, b.Gas(0.50),
                                     b.GasPlan(sac=20.0, sac_deco=10.0), plan)
        self.assertAlmostEqual(two, one / 2.0, places=6)

    def test_rock_bottom_is_unaffected_by_the_deco_rate(self):
        """Rock bottom is back gas: it must not move when the deco SAC does."""
        plan = b.DivePlan(deco_gases=(b.Gas(0.50),))
        segs, _ = b.plan_dive(40.0, 25.0, b.AIR, plan)
        self.assertAlmostEqual(
            b.rock_bottom_liters(segs, b.AIR, b.GasPlan(sac=20.0), plan),
            b.rock_bottom_liters(segs, b.AIR,
                                 b.GasPlan(sac=20.0, sac_deco=10.0), plan),
            places=9)


class TestSurfaceGf(unittest.TestCase):
    """`surface_gf` inverts `ceiling` — so the two must agree by construction."""

    def test_it_is_the_gf_whose_ceiling_is_the_surface(self):
        """The defining property, checked against the forward function: at the
        returned GF the ceiling sits exactly at the surface pressure."""
        plan = b.DivePlan(deco_gases=(b.EAN50,))
        _segs, tissues = b.plan_dive(40.0, 30.0, b.AIR, plan)
        gf = b.surface_gf(tissues, plan.surface_p)
        self.assertAlmostEqual(b.ceiling(tissues, gf), plan.surface_p, places=9)

    def test_a_flown_schedule_surfaces_at_or_under_gf_high(self):
        """Baker's whole-minute padding means the diver reaches the surface with
        GF-High budget in hand, never past it."""
        for depth, time in ((45.0, 25.0), (30.0, 40.0), (21.0, 60.0)):
            plan = b.DivePlan(gf_low=0.30, gf_high=0.70,
                              deco_gases=(b.EAN50, b.O2))
            _segs, tissues = b.plan_dive(depth, time, b.AIR, plan)
            with self.subTest(depth=depth):
                self.assertLessEqual(b.surface_gf(tissues, plan.surface_p),
                                     plan.gf_high + 1e-9)

    def test_unloaded_tissues_are_not_supersaturated(self):
        plan = b.DivePlan()
        fresh = b.Tissues.at_surface(plan.surface_p, b.AIR, plan.p_h2o)
        self.assertEqual(b.surface_gf(fresh, plan.surface_p), 0.0)

    def test_it_is_returned_raw_above_one(self):
        """A violated ascent surfaces past its own M-value line. That is a
        warning, so it must not be clamped into looking legal."""
        plan = b.DivePlan()
        tissues = b.Tissues.at_surface(plan.surface_p, b.AIR, plan.p_h2o)
        p = b.depth_to_p_amb(50.0, plan.surface_p, plan.msw_per_bar)
        b.update_tissues(tissues, b.AIR, p, p, 60.0, plan.p_h2o)
        self.assertGreater(b.surface_gf(tissues, plan.surface_p), 1.0)


if __name__ == "__main__":
    unittest.main()


class TestGasSwitchPolicy(unittest.TestCase):
    """WHERE a deco gas is taken. The schedule must never get *shorter* for
    holding the switch back — that would mean the policy buys time, and it does
    not: it spends it (DECISIONS.md #25)."""

    @staticmethod
    def _plan(policy, **kw):
        return b.DivePlan(gf_low=0.30, gf_high=0.70,
                          deco_gases=(b.EAN50, b.O2),
                          gas_switch_policy=policy, **kw)

    def test_an_unknown_policy_is_refused(self):
        with self.assertRaises(ValueError):
            b.DivePlan(gas_switch_policy="whenever")

    def test_at_first_stop_moves_the_switch_up_to_the_first_stop(self):
        segs, _ = b.plan_dive(40.0, 20.0, b.AIR, self._plan("at-mod"))
        mod_switch = next(s.depth_start for s in segs if s.gas == b.EAN50)
        segs, _ = b.plan_dive(40.0, 20.0, b.AIR, self._plan("at-first-stop"))
        held = next(s.depth_start for s in segs if s.gas == b.EAN50)
        first_stop = max(s.depth_start for s in segs if s.kind == "stop")
        self.assertGreater(mod_switch, held)
        self.assertAlmostEqual(held, first_stop)

    def test_it_never_shortens_the_deco(self):
        """Swept, because the whole-minute stop grid hides the difference on
        most dives — a fine grid is what makes the effect visible at all."""
        for depth in range(21, 61, 3):
            for time in (15, 25, 35):
                fast = b.time_to_surface(b.plan_dive(
                    depth, time, b.AIR,
                    self._plan("at-mod", min_stop_time=0.1))[0])
                held = b.time_to_surface(b.plan_dive(
                    depth, time, b.AIR,
                    self._plan("at-first-stop", min_stop_time=0.1))[0])
                with self.subTest(depth=depth, time=time):
                    self.assertGreaterEqual(held, fast - 1e-9)

    def test_travel_and_bottom_gases_are_not_held_back(self):
        """The policy is about switches made on the way UP. A hypoxic diver
        still breathes the travel mix on the way down."""
        plan = b.DivePlan(gf_low=0.30, gf_high=0.70,
                          travel_gases=(b.Gas(0.35, 0.25),),
                          deco_gases=(b.EAN50,),
                          gas_switch_policy="at-first-stop")
        segs, _ = b.plan_dive(60.0, 20.0, b.Gas(0.10, 0.70), plan)
        descent = [s for s in segs if s.kind == "descent"]
        self.assertIn(b.Gas(0.35, 0.25), {s.gas for s in descent})

    def test_an_ndl_dive_has_no_first_stop_to_hold_to(self):
        """`first_stop=None` must fall back to at-MOD rather than suppress
        every switch all the way to the surface."""
        plan = self._plan("at-first-stop")
        segs, _ = b.plan_dive(18.0, 20.0, b.AIR, plan)
        self.assertEqual([s for s in segs if s.kind == "stop"], [])
        self.assertIn(b.O2, {s.gas for s in segs})


class TestBailoutSchedule(unittest.TestCase):
    """Losing the BOTTOM gas — the case the deco-gas scenarios cannot express."""

    def test_it_keeps_the_bottom_phase_and_reflies_only_the_ascent(self):
        plan = b.DivePlan(gf_low=0.30, gf_high=0.70, deco_gases=(b.EAN50,))
        segs, _ = b.plan_dive(21.0, 60.0, b.AIR, plan)
        out = b.bailout_schedule(segs, plan, b.AIR, (b.AIR,))
        assert out is not None
        bottom = [s for s in segs if s.kind in ("descent", "bottom")]
        self.assertEqual([(s.kind, s.duration) for s in out[:len(bottom)]],
                         [(s.kind, s.duration) for s in bottom])

    def test_the_ascent_no_longer_breathes_the_lost_gas(self):
        plan = b.DivePlan(gf_low=0.30, gf_high=0.70, deco_gases=(b.EAN50,))
        segs, _ = b.plan_dive(21.0, 60.0, b.AIR, plan)
        out = b.bailout_schedule(segs, plan, b.AIR, (b.AIR,))
        assert out is not None
        self.assertNotIn(b.AIR, {s.gas for s in out if s.kind == "stop"})

    def test_unsurvivable_returns_none_rather_than_a_schedule(self):
        """At 45 m with EAN50 (MOD 22 m) and O2 (MOD 6 m) there is nothing to
        breathe. A printed schedule here would be the most dangerous output the
        program could produce."""
        plan = b.DivePlan(gf_low=0.30, gf_high=0.70,
                          deco_gases=(b.EAN50, b.O2))
        gas = b.Gas(0.21, 0.35)
        segs, _ = b.plan_dive(45.0, 25.0, gas, plan)
        self.assertIsNone(b.bailout_schedule(segs, plan, gas, (gas,)))

    def test_losing_everything_is_none(self):
        plan = b.DivePlan(deco_gases=(b.EAN50,))
        segs, _ = b.plan_dive(21.0, 60.0, b.AIR, plan)
        self.assertIsNone(
            b.bailout_schedule(segs, plan, b.AIR, (b.AIR, b.EAN50)))


class TestTissuesAfter(unittest.TestCase):
    def test_replaying_a_plan_reproduces_the_planners_own_tissues(self):
        """The replay must be the same Schreiner step on the same profile, not
        a second model that merely agrees roughly."""
        plan = b.DivePlan(gf_low=0.30, gf_high=0.70, deco_gases=(b.EAN50, b.O2))
        segs, final = b.plan_dive(45.0, 25.0, b.Gas(0.21, 0.35), plan)
        replayed = b.tissues_after(segs, plan)
        for i in range(b.N_COMP):
            self.assertAlmostEqual(replayed.pN2[i], final.pN2[i], places=12)
            self.assertAlmostEqual(replayed.pHe[i], final.pHe[i], places=12)

    def test_it_starts_from_the_tissues_it_is_given(self):
        plan = b.DivePlan()
        loaded = b.Tissues.at_surface(plan.surface_p, b.AIR, plan.p_h2o)
        p = b.depth_to_p_amb(30.0, plan.surface_p, plan.msw_per_bar)
        b.update_tissues(loaded, b.AIR, p, p, 20.0, plan.p_h2o)
        segs, _ = b.plan_dive(20.0, 10.0, b.AIR, plan)
        self.assertGreater(b.tissues_after(segs, plan, loaded).pN2[5],
                           b.tissues_after(segs, plan).pN2[5])


class TestSurfaceInterval(unittest.TestCase):
    """Repetitive diving, with no tables and no pressure groups: the
    compartments carry the residual themselves."""

    @staticmethod
    def _repeat_tts(interval: float) -> float:
        plan = b.DivePlan(gf_low=0.30, gf_high=0.70, deco_gases=(b.EAN50,))
        _s1, t1 = b.plan_dive(30.0, 25.0, b.AIR, plan)
        segs, _ = b.plan_dive(30.0, 25.0, b.AIR, plan,
                              start_tissues=b.surface_interval(t1, interval,
                                                               plan))
        return b.time_to_surface(segs)

    def test_a_longer_interval_always_owes_less(self):
        tts = [self._repeat_tts(si) for si in (0, 15, 30, 60, 120, 240)]
        self.assertEqual(tts, sorted(tts, reverse=True))

    def test_a_long_enough_interval_converges_on_a_clean_dive(self):
        plan = b.DivePlan(gf_low=0.30, gf_high=0.70, deco_gases=(b.EAN50,))
        fresh = b.time_to_surface(b.plan_dive(30.0, 25.0, b.AIR, plan)[0])
        self.assertAlmostEqual(self._repeat_tts(24 * 60), fresh, places=6)

    def test_it_does_not_mutate_the_tissues_it_is_given(self):
        plan = b.DivePlan()
        _segs, t = b.plan_dive(30.0, 25.0, b.AIR, plan)
        before = list(t.pN2)
        b.surface_interval(t, 60.0, plan)
        self.assertEqual(t.pN2, before)

    def test_zero_minutes_changes_nothing(self):
        plan = b.DivePlan()
        _segs, t = b.plan_dive(30.0, 25.0, b.AIR, plan)
        self.assertEqual(b.surface_interval(t, 0.0, plan).pN2, t.pN2)

    def test_a_negative_interval_is_refused(self):
        with self.assertRaises(ValueError):
            b.surface_interval(b.Tissues.at_surface(), -1.0, b.DivePlan())

    def test_surface_oxygen_clears_nitrogen_faster_than_air(self):
        plan = b.DivePlan()
        _segs, t = b.plan_dive(30.0, 25.0, b.AIR, plan)
        on_air = b.surface_interval(t, 30.0, plan, b.AIR)
        on_o2 = b.surface_interval(t, 30.0, plan, b.O2)
        self.assertLess(sum(on_o2.pN2), sum(on_air.pN2))
