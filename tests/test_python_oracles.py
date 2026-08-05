"""Cross-check against two independent **Python** implementations.

The compiled oracles pin us to Subsurface's C++ and Baker's Fortran. These add
`decotengu` and `decodaitengu` — see `tests/python_oracles.py` for what they
are and why they are pip test-dependencies rather than vendored code. Four
independent implementations is enough to tell "we have a bug" from "that tool
is the outlier", which is the question the MultiDeco comparison kept raising
and could not answer on its own.

Skips cleanly when they are not installed, exactly like the compiled oracles
skip without g++ / gfortran.
"""

from __future__ import annotations

import unittest
from typing import ClassVar

from deco import buhlmann as b
from tests import python_oracles as po

#: Both Python libraries use Bühlmann's 4.0 min "1a" first compartment; we,
#: Subsurface (`buehlmann_N2_t_halflife[] = { 5.0, ... }` in its deco.cpp) and
#: Baker's GFDECO (`Nitrogen_Half_Time(1)/5.0/`) use the 5.0 min "1b" variant.
#: Every other compartment is identical in all four. Aligning it is what lets
#: the ceiling comparison below isolate everything else.
LIB_COMPARTMENT_1 = (4.0, 1.2599, 0.5050)


class _AlignedCompartment1:
    """Patch our compartment 1 to the libraries' variant for one test."""

    def setUp(self):
        self._saved = (b.N2_HALFTIME, b.N2_A, b.N2_B)
        ht, a, bb = LIB_COMPARTMENT_1
        b.N2_HALFTIME = (ht, *self._saved[0][1:])
        b.N2_A = (a, *self._saved[1][1:])
        b.N2_B = (bb, *self._saved[2][1:])

    def tearDown(self):
        b.N2_HALFTIME, b.N2_A, b.N2_B = self._saved


@unittest.skipUnless(po.HAVE_DECOTENGU or po.HAVE_DECODAITENGU, po.SKIP_REASON)
class TestCoefficientTables(unittest.TestCase):
    """The cheapest cross-check there is: did four projects transcribe
    Bühlmann's tables the same way?"""

    def test_only_the_first_compartment_differs(self):
        tables = po.coefficients("n2")
        self.assertIn("eko-deco", tables)
        ours = tables["eko-deco"]
        for name, theirs in tables.items():
            if name == "eko-deco":
                continue
            for i in range(1, 16):          # compartments 2..16
                with self.subTest(lib=name, compartment=i + 1):
                    self.assertAlmostEqual(ours[0][i], theirs[0][i], places=6)
                    self.assertAlmostEqual(ours[1][i], theirs[1][i], places=6)
                    self.assertAlmostEqual(ours[2][i], theirs[2][i], places=6)

    def test_the_first_compartment_divergence_is_the_known_one(self):
        """Pinned rather than hidden. If a library ever changes its mind, or
        we change ours, this says so instead of a schedule quietly moving."""
        tables = po.coefficients("n2")
        self.assertEqual((b.N2_HALFTIME[0], b.N2_A[0], b.N2_B[0]),
                         (5.0, 1.1696, 0.5578), "ours is Bühlmann's 1b")
        for name, theirs in tables.items():
            if name == "eko-deco":
                continue
            with self.subTest(lib=name):
                got = (theirs[0][0], round(theirs[1][0], 4), round(theirs[2][0], 4))
                self.assertEqual(got, LIB_COMPARTMENT_1)

    def test_compartment_3_agrees_everywhere(self):
        """The one that controls the 12 m stop in examples/scenario_2, where we
        differ from MultiDeco. Every implementation here has the same a/b, so
        the coefficient is not the explanation."""
        for name, theirs in po.coefficients("n2").items():
            with self.subTest(lib=name):
                self.assertAlmostEqual(theirs[0][2], 12.5, places=6)
                self.assertAlmostEqual(theirs[1][2], 0.8618, places=6)
                self.assertAlmostEqual(theirs[2][2], 0.7222, places=6)


@unittest.skipUnless(po.HAVE_DECOTENGU or po.HAVE_DECODAITENGU, po.SKIP_REASON)
class TestHeliumTables(unittest.TestCase):
    """Helium diverges in two places, both pinned rather than smoothed over."""

    def test_first_compartment_matches_the_nitrogen_split(self):
        """Ours is 1.88 min (pairs with the 5.0 min N2 "1b"); both libraries
        use 1.51 (pairs with their 4.0 min "1a"). Same choice, consistently
        applied — not an independent error."""
        self.assertAlmostEqual(b.HE_HALFTIME[0], 1.88, places=6)
        for name, theirs in po.coefficients("he").items():
            if name == "eko-deco":
                continue
            with self.subTest(lib=name):
                self.assertAlmostEqual(theirs[0][0], 1.51, places=6)

    def test_we_match_decotengu_exactly_from_compartment_2(self):
        tables = po.coefficients("he")
        if "decotengu" not in tables:
            self.skipTest("decotengu not installed")
        ours, theirs = tables["eko-deco"], tables["decotengu"]
        for i in range(1, 16):
            with self.subTest(compartment=i + 1):
                self.assertAlmostEqual(ours[0][i], theirs[0][i], places=6)
                self.assertAlmostEqual(ours[1][i], theirs[1][i], places=6)
                self.assertAlmostEqual(ours[2][i], theirs[2][i], places=6)

    def test_decodaitengu_helium_diverges_on_the_slow_compartments(self):
        """A defect found by adding this oracle, not a tolerance question.

        decodaitengu's helium `a` tracks ours to the 4th decimal for the fast
        compartments and then walks away progressively: −0.011 at #10, −0.058
        at #12, **−0.162 at #16**. Bühlmann's published helium `a` values
        plateau around 0.51–0.53 for the slow tissues; theirs keep falling, as
        if generated from the a = 2·t½^(−1/3) formula rather than transcribed.

        Ours matches Subsurface's `buehlmann_He_a[]` and decotengu exactly, so
        three of four agree and it is theirs. Consequence: decodaitengu is used
        here as a **nitrogen** oracle only — a long trimix exposure that loads
        the slow compartments would be comparing against a different model.
        """
        tables = po.coefficients("he")
        if "decodaitengu" not in tables:
            self.skipTest("decodaitengu not installed")
        ours, theirs = tables["eko-deco"], tables["decodaitengu"]
        fast = max(abs(ours[1][i] - theirs[1][i]) for i in range(1, 8))
        slow = max(abs(ours[1][i] - theirs[1][i]) for i in range(9, 16))
        self.assertLess(fast, 2e-3, "fast compartments agree to ~0.001")
        self.assertGreater(slow, 0.1, "slow ones do not, by a lot")
        for i in range(1, 16):                      # b and half-times agree
            with self.subTest(compartment=i + 1):
                self.assertAlmostEqual(ours[0][i], theirs[0][i], places=6)
                self.assertAlmostEqual(ours[2][i], theirs[2][i], places=6)

    def test_we_match_subsurfaces_helium_table(self):
        """The tie-breaker, straight out of the vendored deco.cpp."""
        self.assertEqual(
            tuple(round(x, 4) for x in b.HE_A[9:]),
            (0.5545, 0.5333, 0.5189, 0.5181, 0.5176, 0.5172, 0.5119))


@unittest.skipUnless(po.HAVE_DECODAITENGU, po.SKIP_REASON)
class TestCeilingAgainstDecodaitengu(_AlignedCompartment1, unittest.TestCase):
    """Tissue loading + M-value ceiling against an independent Python model."""

    #: bar. Pure floating-point noise between two transcriptions of the same
    #: constants — 0.1 mbar is 1 mm of depth.
    TOL = 1e-4

    PROFILE: ClassVar[list] = [
        po.Segment(0, 32, 4.0, b.Gas(0.28)),
        po.Segment(32, 32, 36.0, b.Gas(0.28)),
        po.Segment(32, 21, 1.222, b.Gas(0.28)),
        po.Segment(21, 12, 1.0, b.Gas(0.50)),
    ]

    def _ours(self, segments, gf, p_h2o=0.0627):
        t = b.Tissues.at_surface(b.P_ATM, b.AIR, p_h2o)
        for s in segments:
            b.update_tissues(t, s.gas, b.depth_to_p_amb(s.depth_start),
                             b.depth_to_p_amb(s.depth_end), s.minutes, p_h2o)
        return b.ceiling(t, gf)

    def test_ceilings_match(self):
        for gf in (0.05, 0.275, 0.50, 0.85, 1.0):
            with self.subTest(gf=gf):
                ours = self._ours(self.PROFILE, gf)
                theirs = po.decodaitengu_ceiling(self.PROFILE, gf)
                self.assertAlmostEqual(ours, theirs, delta=self.TOL,
                                       msg=f"{(ours-theirs)*1000:+.4f} mbar")

    def test_nitrox_only_by_design(self):
        """decodaitengu is a nitrogen oracle here: its slow-compartment helium
        `a` values are a different model (see TestHeliumTables). Trimix is
        cross-checked against Subsurface and GFDECO instead, both of which
        share our table."""
        self.assertEqual(self.PROFILE[0].gas.fHe, 0.0)

    def test_the_multideco_gap_is_far_larger_than_this_noise(self):
        """The point of adding a third implementation.

        Our ceiling at the 12 m stop of `examples/scenario_2` is 5.4 mbar above
        MultiDeco's implied one — which is what makes that stop a minute longer
        for us. Independent implementations agree with each other to well under
        0.1 mbar, so 5.4 mbar is not transcription noise and not our arithmetic:
        MultiDeco is the outlier. That is a conclusion, not a guess, and it is
        why chasing that row by adjusting a coefficient would be wrong.
        """
        worst = max(
            abs(self._ours(self.PROFILE, gf)
                - po.decodaitengu_ceiling(self.PROFILE, gf))
            for gf in (0.05, 0.275, 0.50, 0.85, 1.0))
        self.assertLess(worst, 1e-4)
        self.assertGreater(0.0054 / max(worst, 1e-12), 50,
                           "the MultiDeco gap should dwarf implementation noise")


@unittest.skipUnless(po.HAVE_DECOTENGU, po.SKIP_REASON)
class TestSchedulesAgainstDecotengu(unittest.TestCase):
    """Whole schedules against decotengu's engine.

    It searches for the exact minimum stop time and rounds that up; we pad the
    runtime onto Baker's grid (DECISIONS.md #21). So the stop lists are not
    comparable minute-for-minute — what is comparable is the set of stop depths
    and the total, which is what a diver would notice.
    """

    CASES: ClassVar[list] = [
        ("32m/40min EAN28 5/50", 32, 40, b.Gas(0.28),
         (b.Gas(0.50), b.Gas(1.0)), (0.05, 0.50), 8.0, 9.0),
        ("32m/40min EAN36 40/85", 32, 40, b.Gas(0.36),
         (b.Gas(0.50), b.Gas(1.0)), (0.40, 0.85), 8.0, 9.0),
        ("45m/25min air 30/70", 45, 25, b.AIR, (b.Gas(0.50),),
         (0.30, 0.70), 18.0, 10.0),
    ]

    def _ours(self, depth, time, gas, deco, gf, dr, ar):
        plan = b.DivePlan(gf_low=gf[0], gf_high=gf[1], descent_rate=dr,
                          ascent_rate=ar, deco_gases=deco, p_h2o=0.0627)
        segs, _ = b.plan_dive(depth, time, gas, plan)
        return b.stop_legs(segs), b.time_to_surface(segs)

    def test_same_stop_depths(self):
        for name, depth, time, gas, deco, gf, dr, ar in self.CASES:
            with self.subTest(name):
                legs, _ = self._ours(depth, time, gas, deco, gf, dr, ar)
                theirs = po.decotengu_stops(depth, time, gas, deco,
                                            gf_low=gf[0], gf_high=gf[1],
                                            descent_rate=dr, ascent_rate=ar,
                                            p_h2o=0.0627)
                ours_d = {round(x.depth) for x in legs}
                theirs_d = {round(d) for d, _t in theirs}
                # our pass-through stops (DECISIONS #21) can add a depth
                # decotengu ascends straight through, never the reverse
                self.assertTrue(theirs_d <= ours_d,
                                f"ours {sorted(ours_d)} vs {sorted(theirs_d)}")
                self.assertLessEqual(len(ours_d - theirs_d), 1)

    def test_total_deco_is_close(self):
        """Totals within 6 min — two different discretisations of the same
        obligation. We pad runtimes onto Baker's grid and add pass-through
        stops; decotengu binary-searches the exact minimum and ascends through
        anything already cleared, so ours is consistently the longer."""
        for name, depth, time, gas, deco, gf, dr, ar in self.CASES:
            with self.subTest(name):
                legs, _tts = self._ours(depth, time, gas, deco, gf, dr, ar)
                theirs = po.decotengu_stops(depth, time, gas, deco,
                                            gf_low=gf[0], gf_high=gf[1],
                                            descent_rate=dr, ascent_rate=ar,
                                            p_h2o=0.0627)
                ours_stop = sum(x.hold for x in legs)
                theirs_stop = sum(t for _d, t in theirs)
                self.assertLess(abs(ours_stop - theirs_stop), 6.0,
                                f"ours {ours_stop:.1f} vs {theirs_stop:.1f}")


if __name__ == "__main__":
    unittest.main()
