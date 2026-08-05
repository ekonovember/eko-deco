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

# The environment the exports print in ("Wysokość = 150m (s)" — (s) = słodka,
# fresh water). Backed out of the printed ppO2/ead: surface 0.9986..1.0059 bar
# and 10.327..10.378 m/bar were the only combinations that round to every
# printed figure, and 1.0 / 10 1/3 is the pair MultiDeco (Baker-derived) uses.
MD_SURFACE_P = 1.0
MD_MSW_PER_BAR = b.MSW_PER_BAR_FRESH
MD_P_H2O = 0.0567

EAN50, O2 = b.Gas(0.50), b.Gas(1.0)

# (label, bottom gas, GF, printed OTU, printed CNS%, printed density g/L)
SCENARIOS = {
    1: ("scenario_1", b.Gas(0.36), (0.40, 0.85), 78, 34.2, 5.0),
    2: ("scenario_2", b.Gas(0.28), (0.05, 0.50), 84, 33.8, 5.0),
}

# Every "N ppO2" the two exports print: (gas, depth_m, printed value).
PRINTED_PPO2 = [
    (b.Gas(0.36), 32, 1.47), (EAN50, 9, 0.94), (O2, 6, 1.58), (O2, 3, 1.29),
    (b.Gas(0.28), 32, 1.15), (EAN50, 18, 1.37), (EAN50, 15, 1.23),
    (EAN50, 12, 1.08),
]
# Every "N m ead" the two exports print: (gas, depth_m, printed value).
PRINTED_EAD = [
    (b.Gas(0.36), 32, 24), (EAN50, 9, 2), (b.Gas(0.28), 32, 28),
    (EAN50, 18, 8), (EAN50, 15, 6), (EAN50, 12, 4),
]

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


def _plan(scenario: int, decos=(EAN50, O2), **kw) -> list[b.DiveSegment]:
    """The scenario's 32 m / 40 min square dive. Defaults to eko-deco's own
    environment; pass surface_p / msw_per_bar for MultiDeco's display one."""
    _label, gas, gf, *_ = SCENARIOS[scenario]
    plan = b.DivePlan(gf_low=gf[0], gf_high=gf[1], descent_rate=8.0,
                      ascent_rate=9.0, deco_gases=tuple(decos), **kw)
    saved, b.P_H2O = b.P_H2O, MD_P_H2O
    try:
        return b.plan_dive(32, 40, gas, plan)[0]
    finally:
        b.P_H2O = saved


class TestPrintedEnvironment(unittest.TestCase):
    """Every ppO2 and ead the exports print, reproduced to the last digit."""

    def test_ppo2(self):
        for gas, depth, printed in PRINTED_PPO2:
            with self.subTest(gas=repr(gas), depth=depth):
                got = gas.ppo2(depth, MD_SURFACE_P, MD_MSW_PER_BAR)
                self.assertEqual(round(got, 2), printed)

    def test_ead(self):
        # MultiDeco labels this "ead": equivalent AIR depth, so N2 only —
        # not the O2-narcotic END eko-deco shows by default.
        for gas, depth, printed in PRINTED_EAD:
            with self.subTest(gas=repr(gas), depth=depth):
                got = gas.end(depth, MD_SURFACE_P, MD_MSW_PER_BAR,
                              o2_narcotic=False)
                self.assertEqual(round(got), printed)

    def test_sea_level_salt_would_not_match(self):
        """The point of the water/altitude settings: our defaults do NOT
        reproduce these figures, so a fresh-water plan has to be told so."""
        gas, depth, printed = PRINTED_PPO2[0]
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
                got_cns, got_otu = b.cns_otu(segs, MD_SURFACE_P, MD_MSW_PER_BAR)
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
        rep = rp.gas_report(segs, SCENARIOS[2][1], gp, [], deco_gases=(EAN50, O2))
        by_gas = {c.gas: c for c in rep.cylinders}
        self.assertLess(
            abs(by_gas[EAN50].liters - MD_LITERS[2]["OK"][EAN50])
            / MD_LITERS[2]["OK"][EAN50], 0.10)


class TestPrintingConventions(unittest.TestCase):
    def test_runtimes_are_truncated(self):
        """Both exports confirm report.runtime_min: MultiDeco prints (41) for
        a 41.22 min runtime and (42) for 42.56 — the floor, never a round."""
        self.assertEqual(rp.runtime_min(41.222), 41)
        self.assertEqual(rp.runtime_min(42.556), 42)
        self.assertEqual(rp.runtime_min(41.556), 41)

    def test_stop_time_includes_the_ascent_to_the_stop(self):
        """MultiDeco's segment time for a stop covers the ascent to it, which
        is why its runtimes stay whole minutes: scenario 2 leaves 12 m at 46
        and 9 m at 51, a 5 min printed leg made of a 0.33 min ascent and a
        4.67 min hold. eko-deco holds whole minutes and ascends on top, so the
        SAME schedule reads one ascent longer per stop — the wetnotes card
        prints the leg (see DECISIONS.md #17) precisely so the two agree."""
        segs = _plan(2)
        run = 40.0
        legs = {}
        pending = 0.0
        for s in segs:
            if s.kind in ("descent", "bottom"):
                continue
            run += s.duration
            if s.kind == "stop":
                legs[round(s.depth_start)] = (pending + s.duration, run)
                pending = 0.0
            else:
                pending += s.duration
        # MultiDeco: 9 m leg 5 min, leaving at runtime 51.
        leg, leave = legs[9]
        self.assertAlmostEqual(leg, 5.0 + 1 / 3, places=6)
        self.assertEqual(rp.runtime_min(leave), 51)


if __name__ == "__main__":
    unittest.main()
