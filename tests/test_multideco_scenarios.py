"""Cross-check against two real MultiDeco 4.24 plans (examples/scenario_*).

``tests/shearwater_golden.json`` pins the *schedules* of these two dives and
the six lost-gas columns that go with them. This module pins everything else
the exports print, which the golden fixture format has no room for:

* the environment. Both plans were made for FRESH water at 150 m altitude, and
  the printed ppO2 / ead values pin that display to **surface 1.0 bar +
  10.33 m/bar** — reproduced here exactly through the same settings a user
  reaches for (``--water fresh --surface-p 1.0``, or ``surface_p_bar`` /
  ``msw_per_bar`` in the config). Note the schedules do NOT follow those
  constants; see ``_scenario_provenance`` in the fixture file.
* the per-cylinder gas volumes, which reconcile with a single bottom RMV.
* two deliberate divergences worth failing on if they ever change silently:
  gas density (reference temperature) and MultiDeco's stop-time printing.

Both exports are transcribed inline rather than parsed: the files are a Polish
UI dump kept as evidence, not a data format.
"""

from __future__ import annotations

import unittest

from deco import buhlmann as b
from deco import report as rp
from deco import toxicity as tox

# The environment the exports print in ("Wysokość = 150m (s)" — (s) = słodka,
# fresh water). Backed out of the printed ppO2/ead: surface 0.9986..1.0059 bar
# and 10.327..10.378 m/bar were the only combinations that round to every
# printed figure, and 1.0 / 10 1/3 is the pair MultiDeco (Baker-derived) uses.
MD_SURFACE_P = 1.0
MD_MSW_PER_BAR = b.MSW_PER_BAR_FRESH
#: MultiDeco's water-vapour constant — and, since it is what every planner
#: these schedules are compared against uses, eko-deco's default too.
MD_P_H2O = b.P_H2O_SCHREINER

EAN50, O2 = b.Gas(0.50), b.Gas(1.0)

# (label, bottom gas, GF, printed OTU, printed CNS%, printed density g/L)
SCENARIOS = {
    1: ("scenario_1", b.Gas(0.36), (0.40, 0.85), 78, 34.2, 5.0),
    2: ("scenario_2", b.Gas(0.28), (0.05, 0.50), 84, 33.8, 5.0),
}

# Every "N ppO2" each export prints: {scenario: [(gas, depth_m, printed)]}.
# Kept PER SCENARIO on purpose. The two plans are different dives — different
# bottom mix (EAN36 vs EAN28) and very different conservatism (GF 40/85 vs
# 5/50) — so pooling their printed values into one list silently lets one
# dive's evidence stand in for the other's. It happens to be harmless here
# because both were planned at the same site, but that is a fact to state, not
# to rely on: see COMBINED_ENVIRONMENT_EVIDENCE below.
PRINTED_PPO2 = {
    1: [(b.Gas(0.36), 32, 1.47), (EAN50, 9, 0.94), (O2, 6, 1.58), (O2, 3, 1.29)],
    2: [(b.Gas(0.28), 32, 1.15), (EAN50, 18, 1.37), (EAN50, 15, 1.23),
        (EAN50, 12, 1.08), (EAN50, 9, 0.94), (O2, 6, 1.58), (O2, 3, 1.29)],
}
# Every "N m ead" each export prints. (Scenario 1 also prints 0 m ead for the
# two oxygen stops, which constrains nothing.)
PRINTED_EAD = {
    1: [(b.Gas(0.36), 32, 24), (EAN50, 9, 2)],
    2: [(b.Gas(0.28), 32, 28), (EAN50, 18, 8), (EAN50, 15, 6), (EAN50, 12, 4)],
}

#: Both exports print "Wysokość = 150m (s)" — the same site, same water. That,
#: and only that, is what licenses intersecting their two feasible environment
#: regions into a tighter one. Stated here so the combination is a claim about
#: the dives rather than an accident of sharing a list.
COMBINED_ENVIRONMENT_EVIDENCE = True

# MultiDeco's per-cylinder litres, per lost-gas column. The bottom-gas figure
# is identical in both scenarios because the bottom phase is identical.
MD_LITERS = {
    1: {"OK": {"bottom": 3206.7, EAN50: 90.9, O2: 113.4},
        "50": {"bottom": 3297.7, O2: 113.4},
        "100": {"bottom": 3206.7, EAN50: 248.2},
        "both": {"bottom": 3503.7}},
    2: {"OK": {"bottom": 3206.7, EAN50: 371.2, O2: 352.4},
        "50": {"bottom": 3801.1, O2: 401.2},
        "100": {"bottom": 3206.7, EAN50: 1023.6},
        "both": {"bottom": 4992.5}},
}
LOST = {"OK": (EAN50, O2), "50": (O2,), "100": (EAN50,), "both": ()}

#: RMV that reproduces MultiDeco's bottom-gas litres with eko-deco's default
#: (sea-level salt) accounting. The export does not record its RMV settings;
#: this is 3206.7 L divided by the bottom phase's litres-at-SAC-1.
MD_BOTTOM_RMV = 19.25


def _dive_plan(scenario: int, decos=(EAN50, O2), **kw) -> b.DivePlan:
    """The scenario's settings as a `DivePlan` — the export states the GF and
    both rates. Defaults to eko-deco's own environment; pass surface_p /
    msw_per_bar for MultiDeco's display one."""
    _label, _gas, gf, *_ = SCENARIOS[scenario]
    kw.setdefault("p_h2o", MD_P_H2O)
    return b.DivePlan(gf_low=gf[0], gf_high=gf[1], descent_rate=8.0,
                      ascent_rate=9.0, deco_gases=tuple(decos), **kw)


def _plan(scenario: int, decos=(EAN50, O2), **kw) -> list[b.DiveSegment]:
    """The scenario's 32 m / 40 min square dive."""
    return b.plan_dive(32, 40, SCENARIOS[scenario][1],
                       _dive_plan(scenario, decos, **kw))[0]


class TestPrintedEnvironment(unittest.TestCase):
    """Every ppO2 and ead the exports print, reproduced to the last digit."""

    def test_ppo2(self):
        for scenario, rows in PRINTED_PPO2.items():
            for gas, depth, printed in rows:
                with self.subTest(scenario=scenario, gas=repr(gas), depth=depth):
                    got = gas.ppo2(depth, MD_SURFACE_P, MD_MSW_PER_BAR)
                    self.assertEqual(round(got, 2), printed)

    def test_ead(self):
        # MultiDeco labels this "ead": equivalent AIR depth, so N2 only —
        # not the O2-narcotic END eko-deco shows by default.
        for scenario, rows in PRINTED_EAD.items():
            for gas, depth, printed in rows:
                with self.subTest(scenario=scenario, gas=repr(gas), depth=depth):
                    got = gas.end(depth, MD_SURFACE_P, MD_MSW_PER_BAR,
                                  o2_narcotic=False)
                    self.assertEqual(round(got), printed)

    def test_sea_level_salt_would_not_match(self):
        """The point of the water/altitude settings: our defaults do NOT
        reproduce these figures, so a fresh-water plan has to be told so."""
        gas, depth, printed = PRINTED_PPO2[1][0]
        self.assertNotEqual(round(gas.ppo2(depth), 2), printed)

    def test_environment_reaches_the_planner(self):
        plan = b.DivePlan(surface_p=MD_SURFACE_P, msw_per_bar=MD_MSW_PER_BAR)
        self.assertAlmostEqual(
            b.depth_to_p_amb(32, plan.surface_p, plan.msw_per_bar),
            1.0 + 32 / (31 / 3), places=9)


class TestPrintedTotals(unittest.TestCase):
    def test_cns_and_otu(self):
        """CNS/OTU within 10 % of the export (different integration steps)."""
        for n, (_label, _gas, _gf, otu, cns, _dens) in SCENARIOS.items():
            with self.subTest(scenario=n):
                segs = _plan(n, surface_p=MD_SURFACE_P,
                             msw_per_bar=MD_MSW_PER_BAR)
                got_cns, got_otu = tox.cns_otu(segs, MD_SURFACE_P, MD_MSW_PER_BAR)
                self.assertLess(abs(got_cns - cns) / cns, 0.10)
                self.assertLess(abs(got_otu - otu) / otu, 0.10)

    def test_density_diverges_by_reference_conditions(self):
        """Both exports print 5.0 g/L where we print ~5.3. That is not an
        error, it is a different reference state: MultiDeco reports density at
        about 20 °C per bar, eko-deco at 0 °C per atm — the convention behind
        Anthony & Mitchell's 5.2 / 6.2 g/L guidance and therefore behind our
        density ceiling, which is why ours is the one to keep. Both sides are
        reconstructed here so the gap can only move deliberately."""
        for n in SCENARIOS:
            with self.subTest(scenario=n):
                gas = SCENARIOS[n][1]
                p_amb = b.depth_to_p_amb(32, MD_SURFACE_P, MD_MSW_PER_BAR)
                molar_mass = (gas.fO2 * b.M_O2 + gas.fHe * b.M_HE
                              + gas.fN2 * b.M_N2)
                # MultiDeco: molar volume at 20 °C (24.055 L/mol), per bar.
                self.assertEqual(round(molar_mass / 24.055 * p_amb, 1), 5.0)
                # eko-deco: 0 °C (22.414 L/mol), per atm.
                ours = gas.density(32, MD_SURFACE_P, MD_MSW_PER_BAR)
                self.assertEqual(round(ours, 1), 5.3)


class TestGasVolumes(unittest.TestCase):
    def test_bottom_gas_reconciles_at_one_rmv(self):
        """MultiDeco's bottom-gas litres come out of our own accounting at a
        single RMV, in every lost-gas column of both dives. The columns differ
        only in how long the deco on back gas is, so this exercises the descent
        + bottom + ascent billing rather than one number.

        Tight (<= 1 %) wherever the bottom phase is all that is billed; looser
        (<= 5 %) on the columns that also bill a long back-gas deco, where our
        stop distribution differs from MultiDeco's by a minute or two and the
        error rides on that, not on the consumption model."""
        for n, cols in MD_LITERS.items():
            for col, want in cols.items():
                with self.subTest(scenario=n, lost=col):
                    segs = _plan(n, LOST[col])
                    gas = SCENARIOS[n][1]
                    got = b.segment_gas_liters(
                        [s for s in segs if s.gas == gas], MD_BOTTOM_RMV)
                    # "OK" and "100" still have a deco gas from the first
                    # switch on, so the back gas covers the bottom phase only.
                    tol = 0.01 if col in ("OK", "100") else 0.05
                    self.assertLess(abs(got - want["bottom"]) / want["bottom"],
                                    tol, f"{got:.0f} L vs MultiDeco "
                                         f"{want['bottom']:.0f} L")

    def test_deco_gas_needs_its_own_rmv(self):
        """The deco cylinders do NOT reconcile at the bottom RMV — MultiDeco
        billed them at roughly 16 L/min. That is what GasPlan.sac_deco is for;
        without it the deco figures are systematically ~20 % high."""
        segs = _plan(2)
        at_bottom_rmv = b.segment_gas_liters(
            [s for s in segs if s.gas == EAN50], MD_BOTTOM_RMV)
        self.assertGreater(at_bottom_rmv / MD_LITERS[2]["OK"][EAN50], 1.15)
        gp = b.GasPlan(sac=MD_BOTTOM_RMV, sac_deco=16.0)
        self.assertEqual(gp.sac_for(EAN50, (EAN50, O2)), 16.0)
        self.assertEqual(gp.sac_for(SCENARIOS[2][1], (EAN50, O2)),
                         MD_BOTTOM_RMV)
        rep = rp.gas_report(segs, SCENARIOS[2][1], gp, [], _dive_plan(2))
        by_gas = {c.gas: c for c in rep.cylinders}
        self.assertLess(
            abs(by_gas[EAN50].liters - MD_LITERS[2]["OK"][EAN50])
            / MD_LITERS[2]["OK"][EAN50], 0.10)


class TestDefaultsReproduceTheExports(unittest.TestCase):
    """At eko-deco's own defaults — sea-level salt water — a plan of these two
    dives lands on MultiDeco's runtime.

    That is the reason the defaults are what they are, and it is pinned as a
    *runtime*, not just as per-stop tolerances: the runtime is the number a
    diver compares against the plan in their pocket.

    Scenario 2 matches exactly; scenario 1 comes out one minute short because
    MultiDeco holds 3:40 at the 3 m stop where we hold 3:00. That is stop
    discretisation, not a model difference — we are 0.77 min under on one dive
    and 0.23 min over on the other, so there is no bias to correct — but it is
    asserted with its sign so a change in either direction is visible.
    """

    #: (scenario, MultiDeco's printed surface runtime, our expected runtime)
    CASES = ((1, 48, 47), (2, 66, 66))

    def test_surface_runtime(self):
        for scenario, multideco, ours in self.CASES:
            with self.subTest(scenario=scenario):
                segs = _plan(scenario)          # defaults: salt, sea level
                got = rp.runtime_min(b.total_runtime(segs))
                self.assertEqual(got, ours)
                self.assertLessEqual(abs(got - multideco), 1)

    def test_the_runtimes_match_stop_for_stop(self):
        """The number a diver actually flies: five of scenario 2's six stop
        runtimes are MultiDeco's exactly, and the sixth (12 m) is one minute
        out and re-synced by the next stop.

        Runtimes rather than stop lengths, deliberately. Adopting Baker's
        padding (DECISIONS.md #21) shifted a minute between the 12 m and 9 m
        legs while leaving every runtime from 9 m down on MultiDeco's — and it
        is the runtime, not the leg, that the card prints and the diver reads.
        """
        segs = _plan(2)
        runs = {round(l.depth): l.run for l in b.stop_legs(segs)}
        want = {18: 42, 15: 44, 12: 46, 9: 51, 6: 56, 3: 66}
        exact = [d for d in want if runs.get(d) == want[d]]
        self.assertEqual(sorted(exact, reverse=True), [18, 15, 9, 6, 3])
        self.assertEqual(runs[12], want[12] + 1)

    def test_what_the_fresh_water_environment_costs(self):
        """The trade the environment settings buy, quantified.

        Planning scenario 2 in the fresh water MultiDeco *prints* takes 2 min
        off the runtime — and with it the agreement with MultiDeco's own
        schedule. 150 m of altitude contributes nothing on its own: it does two
        opposing things (the tissues start *less* loaded, which shortens deco,
        while the surfacing target is lower, which lengthens it) and at that
        height they cancel. Only at real altitude does the second dominate —
        `test_buhlmann.TestEnvironment.test_altitude_lengthens_deco` pins that
        at 1500 m. Nor are they additive: together they come to -1, not -2,
        because a whole-minute runtime grid swallows the remainder.
        """
        alt150 = b.surface_p_at_altitude(150)
        for p_h2o in (b.P_H2O_BUHLMANN, MD_P_H2O):
            with self.subTest(p_h2o=p_h2o):
                base = b.total_runtime(_plan(2, p_h2o=p_h2o))
                fresh = b.total_runtime(
                    _plan(2, msw_per_bar=MD_MSW_PER_BAR, p_h2o=p_h2o))
                altitude = b.total_runtime(
                    _plan(2, surface_p=alt150, p_h2o=p_h2o))
                both = b.total_runtime(
                    _plan(2, surface_p=alt150, msw_per_bar=MD_MSW_PER_BAR,
                          p_h2o=p_h2o))
                self.assertAlmostEqual(fresh - base, -2.0, places=6)
                self.assertAlmostEqual(altitude - base, 0.0, places=6)
                self.assertAlmostEqual(both - base, -1.0, places=6)


class TestPrintingConventions(unittest.TestCase):
    def test_runtimes_are_truncated(self):
        """Both exports confirm report.runtime_min: MultiDeco prints (41) for
        a 41.22 min runtime and (42) for 42.56 — the floor, never a round."""
        self.assertEqual(rp.runtime_min(41.222), 41)
        self.assertEqual(rp.runtime_min(42.556), 42)
        self.assertEqual(rp.runtime_min(41.556), 41)

    def test_our_legs_are_whole_minutes_like_multidecos(self):
        """Since adopting Baker's runtime padding (DECISIONS.md #21) every leg
        — ascent to the stop plus the hold — is a whole number of minutes, and
        every stop runtime is an integer, exactly as MultiDeco prints them.

        Before, our holds were whole minutes with a fractional ascent on top,
        so the runtime drifted 0.33 min per stop and the two schedules could
        not be laid side by side. The holds are now the fractional part
        (0.44, 1.67, 2.67 …) and the *legs* are whole.
        """
        segs = _plan(2)
        legs = b.stop_legs(segs)
        for leg in legs:
            with self.subTest(depth=leg.depth):
                self.assertEqual(leg.leg, round(leg.leg))
                self.assertNotAlmostEqual(leg.hold, round(leg.hold), places=2)
        run = 40.0 + sum(l.leg for l in legs)
        self.assertEqual(legs[-1].run, run)


#: Every stop runtime both exports print, from their own "utrata gazu" (lost
#: gas) tables: {scenario: {column: {depth_m: printed runtime}}}. Columns are
#: MultiDeco's own — OK / lost EAN50 / lost O2 / both lost.
MD_RUNTIMES = {
    1: {"OK":   {9: 43, 6: 44, 3: 48},
        "-50":  {9: 43, 6: 44, 3: 48},
        "-O2":  {9: 43, 6: 44, 3: 50},
        "BOTH": {9: 43, 6: 45, 3: 52}},
    2: {"OK":   {18: 42, 15: 44, 12: 46, 9: 51, 6: 56, 3: 66},
        "-50":  {18: 43, 15: 45, 12: 49, 9: 57, 6: 63, 3: 74},
        "-O2":  {18: 42, 15: 44, 12: 46, 9: 51, 6: 59, 3: 79},
        "BOTH": {18: 43, 15: 45, 12: 49, 9: 57, 6: 72, 3: 108}},
}
#: Which deco gases each column still has.
MD_COLUMNS = {"OK": (EAN50, O2), "-50": (O2,), "-O2": (EAN50,), "BOTH": ()}
#: The cells where we do NOT print MultiDeco's runtime, and by how much.
#: 11 of 36; every other cell must agree exactly. See DECISIONS.md #23 — these
#: are recorded, not tolerated: closing one is a finding, opening a new one is
#: a regression, and neither may happen silently.
KNOWN_DELTAS = {
    # scenario 1: the last stop only. MultiDeco holds 3:40, we hold 3:00.
    (1, "OK", 3): -1, (1, "-O2", 3): -1, (1, "BOTH", 3): -1,
    # scenario 2: the 12 m row in every column — our ceiling is 5.4 mbar from
    # the 9 m step there, and decodaitengu puts our arithmetic within
    # 0.03 mbar, so the difference is MultiDeco's (unattributed: not a
    # compartment, see DECISIONS.md #23).
    (2, "OK", 12): +1, (2, "-50", 12): +1, (2, "-O2", 12): +1,
    (2, "BOTH", 12): +1,
    # scenario 2's two long lost-gas columns, where that row's minute is then
    # traded back over 20-45 min of extra deco on the last two stops.
    (2, "-O2", 6): +1, (2, "-O2", 3): -1,
    (2, "BOTH", 6): +1, (2, "BOTH", 3): -2,
}


class TestExportedRuntimeDeltas(unittest.TestCase):
    """Every stop runtime of both exports, all four lost-gas columns, against
    ours — 36 cells, of which **25 are identical** and 11 are the recorded
    deltas above.

    The golden fixture compares the same dives with a 2 min per-stop tolerance,
    which is the right shape for "did the schedule change materially" and the
    wrong one for this question: a one-minute drift, in either direction,
    passes it silently. Here the delta itself is the assertion, so agreement
    can only improve or regress *on purpose* (DECISIONS.md #18, #23).
    """

    def test_every_stop_runtime(self):
        for scenario, columns in MD_RUNTIMES.items():
            for column, printed in columns.items():
                segs = _plan(scenario, decos=MD_COLUMNS[column])
                runs = {round(l.depth): l.run for l in b.stop_legs(segs)}
                with self.subTest(scenario=scenario, column=column):
                    # no stop of ours that MultiDeco does not also print, and
                    # none of theirs missing: the delta map assumes one grid.
                    self.assertEqual(sorted(runs), sorted(printed))
                for depth, md in printed.items():
                    want = md + KNOWN_DELTAS.get((scenario, column, depth), 0)
                    with self.subTest(scenario=scenario, column=column,
                                      depth=depth):
                        self.assertEqual(runs[depth], want)

    def test_the_agreement_is_25_of_36(self):
        """The headline number, so it cannot quietly become 24."""
        cells = sum(len(c) for s in MD_RUNTIMES.values() for c in s.values())
        self.assertEqual(cells, 36)
        self.assertEqual(cells - len(KNOWN_DELTAS), 25)

    def test_the_two_dives_disagree_in_opposite_directions(self):
        """Why no bias is corrected: scenario 1 surfaces a minute early,
        scenario 2 a minute late at 12 m and level by 9 m. A single-signed
        error would be a constant to find; these are two mechanisms."""
        signs = {scenario: {d for (s, _c, _d), d in KNOWN_DELTAS.items()
                            if s == scenario}
                 for scenario in MD_RUNTIMES}
        self.assertEqual(signs[1], {-1})
        self.assertEqual(signs[2], {+1, -1, -2})


if __name__ == "__main__":
    unittest.main()
