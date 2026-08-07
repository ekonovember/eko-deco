"""The constant/variable divergence harness (tests/planner_diff.py).

Two jobs, both regression guards rather than illustrations:

* the registry stays **complete** — adding a constant to `buhlmann` without
  registering it fails here, so "every possible difference" is a checkable
  claim and not a promise someone has to remember to keep;
* the divergence set for the bundled MultiDeco exports is **pinned** — a new
  difference between us and those plans turns into a failing test naming the
  constant, instead of a schedule that is quietly a minute out.
"""

from __future__ import annotations

import unittest

from deco import buhlmann as b
from tests import planner_diff as pd
from tests import test_multideco_scenarios as md

DEFAULT_ENV = (b.P_ATM, b.MSW_PER_BAR)
MD_ENV = (md.MD_SURFACE_P, md.MD_MSW_PER_BAR)

#: True in BOTH configurations, so it is a property of the two planners rather
#: than of how we chose to configure ours: MultiDeco reports gas density at a
#: different reference state (~20 C per bar vs our 0 C per atm, the convention
#: behind the Anthony & Mitchell limits our ceiling uses). The molar masses ride
#: along because a printed density only identifies the mass/volume ratio.
DIVERGES_ALWAYS = {
    "MOLAR_VOLUME", "M_O2", "M_N2", "M_HE", "density reference",
}

#: Planned at eko-deco's sea-level salt defaults the schedule agrees, but the
#: printed pressures do not — the environment and, through ppO2, the oxygen
#: exposure.
DIVERGES_AT_OUR_DEFAULTS = DIVERGES_ALWAYS | {
    "P_ATM", "MSW_PER_BAR", "DivePlan.surface_p", "DivePlan.msw_per_bar",
    "_CNS_RATE", "OTU_THRESHOLD_PPO2", "OTU_EXPONENT",
}

#: Planned in the environment MultiDeco's own printout implies, the pressures
#: match and the SCHEDULE stops matching — by 31 % of scenario 1's TTS and 21 %
#: of scenario 2's, against 6 % for both at our defaults. (Relative, because
#: the two are different dives: 8 minutes of deco against 26, so "minutes out"
#: is not comparable between them.) Everything the schedule jointly constrains
#: is therefore flagged. This is the evidence for DECISIONS.md #15's caveat: MultiDeco
#: appears to apply water type and altitude to what it displays but not to its
#: model, so no single configuration reproduces both halves of the export.
DIVERGES_AT_MULTIDECOS_ENVIRONMENT = DIVERGES_ALWAYS | {
    "N_COMP", "N2_A", "N2_B", "N2_HALFTIME", "HE_A", "HE_B", "HE_HALFTIME",
    "P_H2O", "P_H2O_BUHLMANN", "P_H2O_SCHREINER", "PLANNER_PROFILES",
    "DivePlan.p_h2o", "DivePlan.min_stop_time",
    "GF anchor", "DivePlan.last_stop_depth",
    "DivePlan.stop_interval",
    "DivePlan.ppo2_deco", "DivePlan.ppo2_switch_tol",
    # WHERE a deco gas is taken moves the schedule, so the schedule evidence
    # constrains it jointly with everything else here — it cannot be told apart
    # from the rest of the group by a printed plan alone. MultiDeco switches at
    # MOD, as we do by default, so this is a joint flag and not a real
    # disagreement about the policy (DECISIONS.md #25).
    "DivePlan.gas_switch_policy",
    "runtime rounding", "stop-time printing", "first-stop padding",
}


def _findings(scenario: int, env: tuple[float, float]) -> list[pd.Finding]:
    surface_p, msw_per_bar = env
    ev = pd.multideco_evidence(scenario, surface_p=surface_p,
                               msw_per_bar=msw_per_bar)
    return pd.compare(ev, surface_p=surface_p, msw_per_bar=msw_per_bar)


def _by_verdict(findings, verdict) -> set[str]:
    return {f.tunable.name for f in findings if f.verdict == verdict}


class TestRegistryCompleteness(unittest.TestCase):
    def test_no_gaps(self):
        """Every module constant and every DivePlan/GasPlan field is
        registered. This is the whole basis for claiming the harness can see
        all possible differences: it cannot detect a divergence in something
        it does not know exists."""
        gaps = pd.registry_gaps()
        self.assertEqual(gaps, [], f"unregistered tunables: {gaps} — add them "
                                   "to planner_diff.registry() with the "
                                   "observables that could pin them")

    def test_entries_are_well_formed(self):
        seen = set()
        for t in pd.registry():
            with self.subTest(t.name):
                self.assertNotIn(t.name, seen, "duplicate registry entry")
                seen.add(t.name)
                self.assertIn(t.where, ("module", "DivePlan", "GasPlan",
                                        "convention"))
                self.assertIn(t.exposure, ("setting", "library-only",
                                           "hardcoded"))
                for kind in t.pinned_by:
                    self.assertIn(kind, (pd.PPO2, pd.EAD, pd.DENSITY,
                                         pd.SCHEDULE, pd.OXTOX, pd.VOLUMES,
                                         pd.STATED))

    def test_the_environment_pair_is_the_only_separately_identifiable_model_input(self):
        """A sanity check on the harness's own premise: printed pressures pin
        the environment on its own, while the tissue constants are only ever
        joint with the schedule. If this ever changes, the JOINT_OK verdicts
        below are understating what the evidence could prove."""
        by_name = {t.name: t for t in pd.registry()}
        self.assertTrue(by_name["DivePlan.surface_p"].identifiable_alone)
        self.assertTrue(by_name["DivePlan.msw_per_bar"].identifiable_alone)
        for name in ("N2_A", "N2_B", "N2_HALFTIME", "HE_A", "HE_B", "P_H2O"):
            self.assertFalse(by_name[name].identifiable_alone, name)


class TestNoFalseReassurance(unittest.TestCase):
    """The failure mode worth engineering against: reporting agreement where
    there is simply no evidence."""

    def test_empty_evidence_makes_everything_undetermined(self):
        findings = pd.compare(pd.Evidence())
        self.assertEqual(len(findings), len(pd.registry()))
        self.assertEqual(_by_verdict(findings, pd.UNDETERMINED),
                         {f.tunable.name for f in findings})

    def test_a_dive_that_never_breathes_air_says_nothing_about_air(self):
        findings = _findings(1, MD_ENV)
        air = next(f for f in findings if f.tunable.name == "AIR")
        self.assertEqual(air.verdict, pd.UNDETERMINED)

    def test_contradictory_pressures_are_reported_not_swallowed(self):
        """If no (surface, metres-per-bar) pair explains every printed ppO2,
        something other than the environment differs — a rounding rule or the
        formula itself. That must surface, not silently widen the box."""
        ev = pd.Evidence(ppo2=((b.Gas(0.36), 32, 1.47),
                               (b.Gas(0.36), 32, 1.60)))   # same point, two values
        box = pd.infer_environment(ev)
        self.assertTrue(box.empty)
        verdicts = {f.tunable.name: f.verdict for f in pd.compare(ev)}
        self.assertEqual(verdicts["DivePlan.surface_p"], pd.DIVERGES)
        self.assertEqual(verdicts["DivePlan.msw_per_bar"], pd.DIVERGES)


class TestEnvironmentInference(unittest.TestCase):
    """The harness reproduces, mechanically, the manual scan that found the
    fresh-water/1.0-bar environment in the first place."""

    def test_brackets_multidecos_environment(self):
        ev = pd.multideco_evidence(1, surface_p=md.MD_SURFACE_P,
                                   msw_per_bar=md.MD_MSW_PER_BAR)
        box = pd.infer_environment(ev)
        self.assertFalse(box.empty)
        self.assertTrue(box.contains(md.MD_SURFACE_P, md.MD_MSW_PER_BAR))
        # and it excludes our sea-level salt defaults — the original bug
        self.assertFalse(box.contains(b.P_ATM, b.MSW_PER_BAR))
        assert box.msw_per_bar and box.surface_p
        self.assertGreater(box.msw_per_bar[0], 10.2)
        self.assertLess(box.surface_p[0], 1.01)

    def test_water_preset_is_identified_by_name(self):
        findings = _findings(1, MD_ENV)
        water = next(f for f in findings if f.tunable.name == "WATER_TYPES")
        self.assertEqual(water.verdict, pd.MATCH)
        self.assertIn("fresh", water.detail)


class TestKnownDivergences(unittest.TestCase):
    def _assert_set(self, scenario, env, want):
        findings = _findings(scenario, env)
        got = _by_verdict(findings, pd.DIVERGES)
        self.assertEqual(
            got, want,
            "\n".join([f"divergence set changed (added {got - want}, "
                       f"gone {want - got}):"]
                      + [str(f) for f in findings if f.verdict == pd.DIVERGES]))

    def test_pinned_at_our_defaults(self):
        for scenario in (1, 2):
            with self.subTest(scenario=scenario):
                self._assert_set(scenario, DEFAULT_ENV,
                                 DIVERGES_AT_OUR_DEFAULTS)

    def test_pinned_at_multidecos_own_environment(self):
        for scenario in (1, 2):
            with self.subTest(scenario=scenario):
                self._assert_set(scenario, MD_ENV,
                                 DIVERGES_AT_MULTIDECOS_ENVIRONMENT)

    def test_no_configuration_reproduces_both_halves_of_the_export(self):
        """The headline finding, and the reason DECISIONS.md #15 carries a
        caveat instead of a fix: set the environment MultiDeco prints and its
        schedule stops matching; keep the one its schedule implies and its
        printed pressures stop matching. That is a property of MultiDeco, not
        a bug of ours — but it must stay visible, because the tempting
        "improvement" is to chase one half and silently lose the other."""
        for scenario in (1, 2):
            with self.subTest(scenario=scenario):
                at_default = _by_verdict(_findings(scenario, DEFAULT_ENV),
                                         pd.DIVERGES)
                at_md = _by_verdict(_findings(scenario, MD_ENV), pd.DIVERGES)
                # environment wrong at our defaults…
                self.assertIn("DivePlan.surface_p", at_default)
                self.assertNotIn("DivePlan.surface_p", at_md)
                # …schedule wrong at theirs
                self.assertIn("P_H2O", at_md)
                self.assertNotIn("P_H2O", at_default)
                # and neither is clean
                self.assertTrue(at_default and at_md)

    def test_the_environment_matches_once_it_is_set(self):
        for scenario in (1, 2):
            with self.subTest(scenario=scenario):
                matched = _by_verdict(_findings(scenario, MD_ENV), pd.MATCH)
                self.assertLessEqual(
                    {"DivePlan.surface_p", "DivePlan.msw_per_bar",
                     "MSW_PER_BAR_FRESH", "WATER_TYPES"}, matched)

    def test_defaults_would_have_caught_the_original_bug(self):
        """Planned at sea-level salt water — the only thing eko-deco could do
        before this work — the harness flags the environment outright. That is
        the regression this whole module exists to make automatic."""
        for scenario in (1, 2):
            with self.subTest(scenario=scenario):
                got = _by_verdict(_findings(scenario, DEFAULT_ENV), pd.DIVERGES)
                self.assertIn("DivePlan.surface_p", got)
                self.assertIn("DivePlan.msw_per_bar", got)
                # …and the knock-on effect on oxygen exposure
                self.assertIn("_CNS_RATE", got)

    def test_stated_settings_are_not_reported_as_defects(self):
        """GF and the rates differ from our defaults on every export; they are
        inputs to pass, not divergences, and must not drown the real ones."""
        findings = _findings(1, MD_ENV)
        self.assertEqual(
            _by_verdict(findings, pd.SETTING),
            {"DivePlan.gf_low", "DivePlan.gf_high",
             "DivePlan.descent_rate", "DivePlan.ascent_rate"})

    def test_report_renders(self):
        text = pd.format_report(_findings(1, MD_ENV), "smoke")
        self.assertIn("DIVERGES", text)
        self.assertIn("density reference", text)


if __name__ == "__main__":
    unittest.main()


class TestEvidenceIsPerDive(unittest.TestCase):
    """The two exports are different dives — EAN36 at GF 40/85 against EAN28 at
    GF 5/50 — and the harness must keep their evidence apart. Pooling them once
    looked harmless (both were planned at the same site, so the pooled region
    was just the intersection) but it credited each dive's conclusion to the
    other's data, and would be silently wrong for two exports from different
    sites."""

    def test_a_scenarios_evidence_holds_only_its_own_mixes(self):
        for scenario, own, foreign in ((1, b.Gas(0.36), b.Gas(0.28)),
                                       (2, b.Gas(0.28), b.Gas(0.36))):
            with self.subTest(scenario=scenario):
                ev = pd.multideco_evidence(scenario, surface_p=MD_ENV[0],
                                           msw_per_bar=MD_ENV[1])
                mixes = {g for g, _d, _p in ev.ppo2}
                self.assertIn(own, mixes)
                self.assertNotIn(foreign, mixes,
                                 "the other dive's bottom mix leaked in")
                self.assertLessEqual(mixes, set(ev.gases_used))

    def test_each_dive_pins_the_environment_on_its_own(self):
        """Neither dive is carrying the other: each one's printed pressures
        alone bracket MultiDeco's environment and exclude our defaults."""
        for scenario in (1, 2):
            with self.subTest(scenario=scenario):
                ev = pd.multideco_evidence(scenario, surface_p=MD_ENV[0],
                                           msw_per_bar=MD_ENV[1])
                box = pd.infer_environment(ev)
                self.assertTrue(box.contains(*MD_ENV))
                self.assertFalse(box.contains(b.P_ATM, b.MSW_PER_BAR))

    def test_combining_them_is_a_stated_claim_and_tightens_the_answer(self):
        """Both exports print the same site, which is what licenses an
        intersection; it is narrower than either dive alone."""
        self.assertTrue(md.COMBINED_ENVIRONMENT_EVIDENCE)
        boxes = [pd.infer_environment(
            pd.multideco_evidence(s, surface_p=MD_ENV[0], msw_per_bar=MD_ENV[1]))
            for s in (1, 2)]
        both = pd.intersect(*boxes)
        self.assertTrue(both.contains(*MD_ENV))
        assert both.msw_per_bar
        for one in boxes:
            assert one.msw_per_bar
            self.assertGreaterEqual(both.msw_per_bar[0], one.msw_per_bar[0])
            self.assertLessEqual(both.msw_per_bar[1], one.msw_per_bar[1])


class TestScheduleErrorIsComparableAcrossDives(unittest.TestCase):
    """A single absolute tolerance is not comparable across dives of different
    length: scenario 2 decompresses for 26 minutes against scenario 1's 8, so
    "minutes out" penalises it for being longer."""

    def test_relative_error_is_small_on_both_dives(self):
        """Both dives agree with MultiDeco to under a tenth of their own deco,
        which is the comparable statement across an 8-minute ascent and a
        26-minute one.

        They are no longer the *same* fraction. Under the old whole-minute
        stop logic both came out at 5.6 %, which looked like a law and was a
        coincidence; adopting Baker's padding (DECISIONS.md #21) took scenario
        2 from +0.22 min to -0.01 min against MultiDeco and scenario 1 from
        -0.78 to -1.01. Pinned per dive rather than as an equality, so a real
        drift on either one is visible instead of being averaged away."""
        rel = {}
        for scenario in (1, 2):
            ev = pd.multideco_evidence(scenario, surface_p=DEFAULT_ENV[0],
                                       msw_per_bar=DEFAULT_ENV[1])
            rel[scenario] = ev.schedule.tts_relative
        self.assertAlmostEqual(rel[1], 0.083, delta=0.01)
        self.assertAlmostEqual(rel[2], 0.064, delta=0.01)
        self.assertLess(max(rel.values()), 0.10)

    def test_absolute_and_relative_must_both_pass(self):
        tight = pd.ScheduleDelta(0.0, 5.0, 10.0, 1.0, 9.0, 0.10)
        self.assertFalse(tight.agrees, "20 % of TTS should fail on relative")
        loose = pd.ScheduleDelta(0.0, 5.0, 500.0, 1.0, 1.0, 0.10)
        self.assertFalse(loose.agrees, "5 min > 1 min should fail on absolute")
        self.assertTrue(pd.ScheduleDelta(0.5, 0.5, 30.0, 1.0, 1.0, 0.10).agrees)
