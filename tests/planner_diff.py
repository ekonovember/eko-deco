"""Systematic constant/variable divergence detection against a reference planner.

The MultiDeco cross-check in `test_multideco_scenarios.py` grew out of a manual
parameter hunt: the exports printed a ppO2 we could not reproduce, and only a
by-hand scan showed why (fresh water at 1.0 bar). That hunt is exactly the kind
of thing that should not depend on someone thinking to do it. This module makes
it mechanical, and answers two questions a future export should answer without
new detective work:

1. **What could possibly differ?** `registry()` lists every model constant and
   every planner setting eko-deco has. `registry_gaps()` introspects the
   package and fails if anything is missing from it, so a new constant cannot
   be added without becoming visible here.
2. **What does the evidence actually pin?** `compare()` returns one `Finding`
   per tunable with an explicit verdict, including — the important part —
   `UNDETERMINED` for constants the export says nothing about. "We found no
   difference" and "the evidence cannot show a difference" are not the same
   claim, and conflating them is how a divergence survives a cross-check.

Identifiability is the organising idea. A printed ppO2 inverts cleanly to a
region of (surface pressure, metres per bar). A printed *schedule* does not
invert at all: it is a joint function of the halftimes, the a/b coefficients,
the water-vapour pressure, the GF convention and the environment together, so
the honest verdict for those is `JOINT_OK` — the group reproduces the export
within tolerance, no single member is separately identified.

Run it against the bundled exports for a report::

    python -m tests.planner_diff
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from deco import buhlmann as b

# ---------------------------------------------------------------------------
# 1. What could possibly differ
# ---------------------------------------------------------------------------

#: Verdicts a tunable can get. Ordered worst-first for reporting.
DIVERGES = "DIVERGES"          # identifiable from the evidence, and different
UNDETERMINED = "UNDETERMINED"  # nothing in the evidence constrains it
SETTING = "SETTING"            # the export states a value; ours is only a
                               # default, so this is "pass it", not a defect
JOINT_OK = "JOINT_OK"          # only identifiable as part of a group; group agrees
MATCH = "MATCH"                # identifiable, and equal
VERDICT_ORDER = (DIVERGES, UNDETERMINED, SETTING, JOINT_OK, MATCH)

#: Observable kinds an export can carry. A tunable declares which of these can
#: constrain it; a tunable pinned by none of the supplied observables is
#: reported UNDETERMINED rather than quietly assumed fine.
PPO2 = "ppo2"            # a printed partial pressure at (gas, depth)
EAD = "ead"              # a printed equivalent air/narcotic depth
DENSITY = "density"      # a printed gas density
SCHEDULE = "schedule"    # stop depths and times, runtimes, TTS
OXTOX = "oxtox"          # printed CNS % and OTU
VOLUMES = "volumes"      # printed per-cylinder gas litres
STATED = "stated"        # the export prints the setting outright (GF, rates)


@dataclass(frozen=True)
class Tunable:
    """One thing that could differ between eko-deco and another planner."""
    name: str
    value: object
    where: str          # "module" | "DivePlan" | "GasPlan" | "convention"
    exposure: str       # "setting" | "library-only" | "hardcoded"
    pinned_by: tuple[str, ...]
    note: str = ""

    @property
    def identifiable_alone(self) -> bool:
        """True when some observable pins this one on its own. The model
        constants are all False: only the schedule touches them, and the
        schedule is a joint function of all of them at once."""
        return bool(set(self.pinned_by) - {SCHEDULE})


def _v(name: str) -> object:
    return getattr(b, name)


def registry() -> list[Tunable]:
    """Every model constant and planner setting, with what could pin it."""
    env = (PPO2, EAD, DENSITY, SCHEDULE, OXTOX, VOLUMES)
    out: list[Tunable] = [
        # --- environment: the only model inputs a printed pressure inverts to
        Tunable("P_ATM", _v("P_ATM"), "module", "setting", env,
                "default surface pressure; DivePlan.surface_p overrides"),
        Tunable("MSW_PER_BAR", _v("MSW_PER_BAR"), "module", "setting", env,
                "default metres per bar; DivePlan.msw_per_bar overrides"),
        Tunable("MSW_PER_BAR_SALT", _v("MSW_PER_BAR_SALT"), "module", "setting",
                env, "--water salt preset"),
        Tunable("MSW_PER_BAR_FRESH", _v("MSW_PER_BAR_FRESH"), "module",
                "setting", env, "--water fresh preset"),
        Tunable("WATER_TYPES", _v("WATER_TYPES"), "module", "setting", env,
                "the preset table itself"),
        Tunable("PLANNER_PROFILES", _v("PLANNER_PROFILES"), "module", "setting",
                (SCHEDULE, PPO2, EAD), "named constant sets per reference "
                "planner; --planner selects one"),

        # --- tissue model: jointly constrained by the schedule, never alone
        Tunable("N_COMP", _v("N_COMP"), "module", "hardcoded", (SCHEDULE,)),
        Tunable("N2_HALFTIME", _v("N2_HALFTIME"), "module", "hardcoded",
                (SCHEDULE,), "ZHL-16C"),
        Tunable("N2_A", _v("N2_A"), "module", "hardcoded", (SCHEDULE,),
                "ZHL-16C; the B-set differs and is what GFDECO uses"),
        Tunable("N2_B", _v("N2_B"), "module", "hardcoded", (SCHEDULE,)),
        Tunable("HE_HALFTIME", _v("HE_HALFTIME"), "module", "hardcoded",
                (SCHEDULE,)),
        Tunable("HE_A", _v("HE_A"), "module", "hardcoded", (SCHEDULE,)),
        Tunable("HE_B", _v("HE_B"), "module", "hardcoded", (SCHEDULE,)),
        Tunable("P_H2O", _v("P_H2O"), "module", "setting", (SCHEDULE,),
                "default = Schreiner 0.0567 (MultiDeco/Shearwater/GFDECO); "
                "DivePlan.p_h2o overrides"),
        Tunable("P_H2O_BUHLMANN", _v("P_H2O_BUHLMANN"), "module", "setting",
                (SCHEDULE,), "Buhlmann's own; what Subsurface uses"),
        Tunable("P_H2O_SCHREINER", _v("P_H2O_SCHREINER"), "module", "setting",
                (SCHEDULE,), "the default"),

        # --- gas physics
        Tunable("MOLAR_VOLUME", _v("MOLAR_VOLUME"), "module", "hardcoded",
                (DENSITY,), "22.414 L/mol = 0 C, 1 atm"),
        Tunable("M_O2", _v("M_O2"), "module", "hardcoded", (DENSITY,)),
        Tunable("M_N2", _v("M_N2"), "module", "hardcoded", (DENSITY,)),
        Tunable("M_HE", _v("M_HE"), "module", "hardcoded", (DENSITY,)),
        Tunable("DENSITY_MAX_G_L", _v("DENSITY_MAX_G_L"), "module", "hardcoded",
                (), "our warning threshold; a planner need not have one"),

        # --- oxygen toxicity
        Tunable("_CNS_RATE", _v("_CNS_RATE"), "module", "hardcoded", (OXTOX,),
                "NOAA single-exposure table"),
        Tunable("OTU_THRESHOLD_PPO2", _v("OTU_THRESHOLD_PPO2"), "module",
                "hardcoded", (OXTOX,)),
        Tunable("OTU_EXPONENT", _v("OTU_EXPONENT"), "module", "hardcoded",
                (OXTOX,), "Repex / Hamilton"),

        # --- cut-table grid
        Tunable("CONTINGENCY_TIME_STEP", _v("CONTINGENCY_TIME_STEP"), "module",
                "setting", (), "our cut table; not a shared quantity"),
        Tunable("CONTINGENCY_DEPTH_STEP", _v("CONTINGENCY_DEPTH_STEP"), "module",
                "setting", ()),

        # --- standard mixes: AIR's composition is a real cross-planner variable
        Tunable("AIR", _v("AIR"), "module", "hardcoded", (PPO2, EAD, SCHEDULE),
                "21/79 here; Subsurface uses 20.9/79.1"),
        Tunable("EAN32", _v("EAN32"), "module", "hardcoded", ()),
        Tunable("EAN50", _v("EAN50"), "module", "hardcoded", ()),
        Tunable("O2", _v("O2"), "module", "hardcoded", ()),

        # --- conventions: not numbers, but they change printed output
        Tunable("runtime rounding", "floor", "convention", "hardcoded",
                (SCHEDULE,), "report.runtime_min; MultiDeco floors too"),
        Tunable("stop-time printing", "leg (ascent + hold)", "convention",
                "hardcoded", (SCHEDULE,),
                "report.wetnotes_rows, DECISIONS #17"),
        Tunable("first-stop padding", "none (we truncate instead)",
                "convention", "hardcoded", (SCHEDULE,),
                "MultiDeco pads the first stop to a whole runtime minute"),
        Tunable("GF anchor", "static, rounded first stop", "convention",
                "hardcoded", (SCHEDULE,),
                "Baker/Shearwater/MultiDeco; Subsurface anchors dynamically"),
        Tunable("narcotic convention", "O2 narcotic (END)", "convention",
                "hardcoded", (EAD,),
                "Gas.end o2_narcotic=True; MultiDeco prints N2-only 'ead'"),
        Tunable("density reference", "0 C per atm", "convention", "hardcoded",
                (DENSITY,), "MultiDeco prints ~20 C per bar"),
        Tunable("consumption billing", "mean depth per segment", "convention",
                "hardcoded", (VOLUMES,)),
    ]
    for f in dataclasses.fields(b.DivePlan):
        out.append(Tunable(f"DivePlan.{f.name}", f.default, "DivePlan",
                           "setting", _PLAN_PINS.get(f.name, (SCHEDULE,))))
    for f in dataclasses.fields(b.GasPlan):
        out.append(Tunable(f"GasPlan.{f.name}", f.default, "GasPlan", "setting",
                           _GAS_PINS.get(f.name, (VOLUMES,))))
    return out


_PLAN_PINS = {
    "descent_rate": (SCHEDULE, STATED), "ascent_rate": (SCHEDULE, STATED),
    "gf_low": (SCHEDULE, STATED), "gf_high": (SCHEDULE, STATED),
    "surface_p": (PPO2, EAD, DENSITY, SCHEDULE, OXTOX, VOLUMES),
    "msw_per_bar": (PPO2, EAD, DENSITY, SCHEDULE, OXTOX, VOLUMES),
    "ppo2_deco": (SCHEDULE,), "ppo2_bottom": (), "ppo2_min": (),
    "min_stop_time": (SCHEDULE,),
    "ppo2_switch_tol": (SCHEDULE,),
    # Holding a switch to the first stop lengthens the deco, so the schedule is
    # what pins it — jointly, like every other model constant.
    "gas_switch_policy": (SCHEDULE,),
    "travel_gases": (STATED,), "deco_gases": (STATED,),
}
_GAS_PINS = {
    "sac": (VOLUMES,), "sac_deco": (VOLUMES,), "sac_multiplier": (),
    "problem_minutes": (), "divers": (),
}


def registry_gaps() -> list[str]:
    """Names the registry is missing — the guard that makes "all possible
    differences" a checkable claim rather than a hope.

    Walks the module for constants (UPPER_CASE names bound to numbers, tuples,
    dicts or `Gas` values) and every `DivePlan` / `GasPlan` field, and returns
    whatever is not registered. A test asserts this is empty, so adding a
    constant without registering it fails the suite."""
    known = {t.name for t in registry()}
    gaps = []
    for name in dir(b):
        if name.startswith("__") or name.upper() != name:
            continue
        val = getattr(b, name)
        if (isinstance(val, (int, float, tuple, dict, b.Gas))
                and not callable(val) and name not in known):
            gaps.append(name)
    for cls in (b.DivePlan, b.GasPlan):
        for f in dataclasses.fields(cls):
            if f"{cls.__name__}.{f.name}" not in known:
                gaps.append(f"{cls.__name__}.{f.name}")
    return sorted(gaps)


# ---------------------------------------------------------------------------
# 2. What the evidence pins
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ScheduleDelta:
    """How far our schedule is from the export's, absolutely and relative to
    that dive's own decompression.

    Both, because a single absolute tolerance is not comparable across dives.
    These two exports are different dives by nature — EAN36 at GF 40/85 against
    EAN28 at GF 5/50, so 8 minutes of deco against 26 — and judging both by
    "minutes out" quietly penalises the longer one for being longer. Relative
    to each dive's own TTS the two agree to the *same* fraction, which is the
    stronger statement and the one that survives comparing unlike dives.
    """
    worst_stop_min: float
    tts_min: float
    tts_reference_min: float     # the export's own TTS, for the relative term
    stop_tol_min: float
    tts_tol_min: float
    tts_rel_tol: float = 0.10

    @property
    def tts_relative(self) -> float:
        return self.tts_min / self.tts_reference_min if self.tts_reference_min else 0.0

    @property
    def agrees(self) -> bool:
        return (self.worst_stop_min <= self.stop_tol_min
                and self.tts_min <= self.tts_tol_min
                and self.tts_relative <= self.tts_rel_tol)

    def describe(self) -> str:
        return (f"{self.worst_stop_min:.2g} min/stop, {self.tts_min:.2g} min TTS "
                f"({self.tts_relative * 100:.0f} % of this dive's "
                f"{self.tts_reference_min:.0f} min)")


@dataclass(frozen=True)
class Evidence:
    """What a reference export actually prints, per observable kind.

    Anything left empty simply is not evidence: the tunables it would have
    constrained come back UNDETERMINED.
    """
    #: (gas, depth_m, printed ppO2) — printed to 2 decimals
    ppo2: tuple[tuple[b.Gas, float, float], ...] = ()
    #: (gas, depth_m, printed ead/END, o2_narcotic) — printed to the metre
    ead: tuple[tuple[b.Gas, float, float, bool], ...] = ()
    #: (gas, depth_m, printed density g/L)
    density: tuple[tuple[b.Gas, float, float], ...] = ()
    #: schedule disagreement; None when the export carries no schedule
    schedule: ScheduleDelta | None = None
    #: (printed CNS %, printed OTU, ours, ours, relative tolerance)
    oxtox: tuple[float, float, float, float, float] | None = None
    #: (printed litres, our litres at SAC 1, relative tolerance) per cylinder
    volumes: tuple[tuple[str, float, float, float], ...] = ()
    #: settings the export prints outright: {tunable name: value}
    stated: dict[str, object] = field(default_factory=dict)
    #: the mixes actually breathed on this dive. A standard-mix constant the
    #: dive never touches is UNDETERMINED, not "agrees" — a dive on nitrox says
    #: nothing about whether we and the planner agree on what AIR is.
    gases_used: tuple[b.Gas, ...] = ()

    def kinds(self) -> set[str]:
        """The observable kinds this evidence actually carries."""
        got = set()
        if self.ppo2:
            got.add(PPO2)
        if self.ead:
            got.add(EAD)
        if self.density:
            got.add(DENSITY)
        if self.schedule is not None:
            got.add(SCHEDULE)
        if self.oxtox is not None:
            got.add(OXTOX)
        if self.volumes:
            got.add(VOLUMES)
        if self.stated:
            got.add(STATED)
        return got


@dataclass(frozen=True)
class Box:
    """The feasible interval for the environment pair, or empty."""
    surface_p: tuple[float, float] | None
    msw_per_bar: tuple[float, float] | None

    @property
    def empty(self) -> bool:
        return self.surface_p is None or self.msw_per_bar is None

    def contains(self, surface_p: float, msw_per_bar: float) -> bool:
        if self.empty:
            return False
        assert self.surface_p and self.msw_per_bar
        return (self.surface_p[0] - 1e-9 <= surface_p <= self.surface_p[1] + 1e-9
                and self.msw_per_bar[0] - 1e-9 <= msw_per_bar
                <= self.msw_per_bar[1] + 1e-9)


def infer_environment(ev: Evidence, *,
                      surface_range: tuple[float, float] = (0.80, 1.10),
                      msw_range: tuple[float, float] = (9.0, 11.5),
                      steps: int = 240) -> Box:
    """Bound (surface pressure, metres per bar) from the printed pressures.

    A grid search, deliberately: the printed values are *rounded*, so the
    feasible set is a region, not a point, and the honest answer is its extent.
    An empty box means no (surface, msw) pair reproduces every printed figure —
    which is itself a finding, and means something other than the environment
    differs (a rounding rule, or the formula).
    """
    lo_s, hi_s = surface_range
    lo_m, hi_m = msw_range
    ok_s: list[float] = []
    ok_m: list[float] = []
    for i in range(steps + 1):
        surface_p = lo_s + (hi_s - lo_s) * i / steps
        for j in range(steps + 1):
            mpb = lo_m + (hi_m - lo_m) * j / steps
            if _fits(ev, surface_p, mpb):
                ok_s.append(surface_p)
                ok_m.append(mpb)
    if not ok_s:
        return Box(None, None)
    return Box((min(ok_s), max(ok_s)), (min(ok_m), max(ok_m)))


def _fits(ev: Evidence, surface_p: float, msw_per_bar: float) -> bool:
    for gas, depth, printed in ev.ppo2:
        if abs(round(gas.ppo2(depth, surface_p, msw_per_bar), 2) - printed) > 1e-9:
            return False
    for gas, depth, printed, o2_narcotic in ev.ead:
        got = gas.end(depth, surface_p, msw_per_bar, o2_narcotic=o2_narcotic)
        if abs(round(got) - printed) > 1e-9:
            return False
    return True


def intersect(*boxes: Box) -> Box:
    """Intersect feasible environment regions from several exports.

    Only legitimate when the exports really were planned at the same site —
    combining two dives' evidence tightens the answer, but if they were made
    at different altitudes or in different water the intersection is a
    fabrication. Callers must assert the shared-site claim, not assume it
    (`test_multideco_scenarios.COMBINED_ENVIRONMENT_EVIDENCE`)."""
    lo_s = max((bx.surface_p[0] for bx in boxes if bx.surface_p), default=None)
    hi_s = min((bx.surface_p[1] for bx in boxes if bx.surface_p), default=None)
    lo_m = max((bx.msw_per_bar[0] for bx in boxes if bx.msw_per_bar), default=None)
    hi_m = min((bx.msw_per_bar[1] for bx in boxes if bx.msw_per_bar), default=None)
    if None in (lo_s, hi_s, lo_m, hi_m) or lo_s > hi_s or lo_m > hi_m:
        return Box(None, None)
    return Box((lo_s, hi_s), (lo_m, hi_m))


def infer_density_molar_volume(ev: Evidence, surface_p: float,
                               msw_per_bar: float) -> tuple[float, float] | None:
    """The molar volume (L/mol) implied by the printed densities, as an
    interval from their rounding. Ours is `MOLAR_VOLUME` per *atm*; a planner
    referencing a bar or a different temperature lands elsewhere, which is a
    reference-state difference rather than a physics one."""
    lo, hi = 0.0, math.inf
    for gas, depth, printed in ev.density:
        p_amb = b.depth_to_p_amb(depth, surface_p, msw_per_bar)
        molar_mass = gas.fO2 * b.M_O2 + gas.fHe * b.M_HE + gas.fN2 * b.M_N2
        # printed is rounded to 0.1 g/L: density in [printed-0.05, +0.05]
        for bound, dens in ((printed + 0.05, "lo"), (printed - 0.05, "hi")):
            if bound <= 0:
                continue
            v = molar_mass * p_amb / bound
            lo, hi = (max(lo, v), hi) if dens == "lo" else (lo, min(hi, v))
    return (lo, hi) if ev.density and lo <= hi else None


@dataclass(frozen=True)
class Finding:
    tunable: Tunable
    verdict: str
    detail: str

    def __str__(self) -> str:
        return f"{self.verdict:<12} {self.tunable.name:<28} {self.detail}"


def compare(ev: Evidence, *, surface_p: float = b.P_ATM,
            msw_per_bar: float = b.MSW_PER_BAR) -> list[Finding]:
    """One `Finding` per tunable, given what the export shows.

    `surface_p` / `msw_per_bar` are the settings *we* planned the comparison
    with, so a fresh-water export compared at fresh-water settings reports
    MATCH while the same export compared at our defaults reports DIVERGES —
    which is the point: the verdict is about a specific configuration, not
    about the library in the abstract.
    """
    have = ev.kinds()
    box = infer_environment(ev) if (ev.ppo2 or ev.ead) else Box(None, None)
    findings: list[Finding] = []
    for t in registry():
        pins = set(t.pinned_by) & have
        if not pins:
            findings.append(Finding(t, UNDETERMINED,
                                    "no observable in this export constrains it"))
            continue
        findings.append(_judge(t, ev, pins, box, surface_p, msw_per_bar))
    findings.sort(key=lambda f: (VERDICT_ORDER.index(f.verdict), f.tunable.name))
    return findings


def _judge(t: Tunable, ev: Evidence, pins: set[str], box: Box,
           surface_p: float, msw_per_bar: float) -> Finding:
    name = t.name
    # A standard mix the dive never breathes is not evidence about that mix.
    if name in ("AIR", "EAN32", "EAN50", "O2") and t.value not in ev.gases_used:
        return Finding(t, UNDETERMINED, "this dive never breathes it")
    # settings the export prints outright
    if STATED in pins and name in ev.stated:
        want = ev.stated[name]
        ok = want == t.value or (
            isinstance(want, (int, float)) and isinstance(t.value, (int, float))
            and abs(float(want) - float(t.value)) < 1e-9)
        # A stated setting that differs from our default is not a defect —
        # it just has to be passed. Keeping it out of DIVERGES is what stops
        # the report crying wolf over four rates on every single export.
        return Finding(t, MATCH if ok else SETTING,
                       f"export states {want!r}, our default {t.value!r}"
                       + ("" if ok else " — pass it explicitly"))
    # the environment pair, inverted from the printed pressures
    env_names = ("P_ATM", "DivePlan.surface_p", "MSW_PER_BAR",
                 "DivePlan.msw_per_bar", "MSW_PER_BAR_SALT",
                 "MSW_PER_BAR_FRESH", "WATER_TYPES")
    if name in env_names and (PPO2 in pins or EAD in pins):
        if box.empty:
            return Finding(t, DIVERGES,
                           "no surface/metres-per-bar pair reproduces every "
                           "printed pressure — the formula or rounding differs")
        assert box.surface_p and box.msw_per_bar
        # The presets are not what the dive was planned with — the useful
        # question for them is "does this export's water match one of ours?"
        if name in ("MSW_PER_BAR_SALT", "MSW_PER_BAR_FRESH"):
            lo, hi = box.msw_per_bar
            mine = float(t.value)                    # type: ignore[arg-type]
            covered = any(lo <= v <= hi for v in b.WATER_TYPES.values())
            if lo <= mine <= hi:
                return Finding(t, MATCH,
                               f"preset {mine:.5g} is the export's water "
                               f"({lo:.5g}..{hi:.5g})")
            # Some *other* preset matching is fine: a fresh-water export says
            # nothing about whether our salt constant is right.
            return Finding(t, JOINT_OK if covered else DIVERGES,
                           f"preset {mine:.5g} is not this export's water "
                           f"({lo:.5g}..{hi:.5g})"
                           + ("; another preset is" if covered else
                              "; no preset is"))
        if name == "WATER_TYPES":
            lo, hi = box.msw_per_bar
            hits = [n for n, v in b.WATER_TYPES.items() if lo <= v <= hi]
            return Finding(t, MATCH if hits else DIVERGES,
                           f"export's water matches preset(s) {hits}"
                           if hits else
                           f"no preset lands in {lo:.5g}..{hi:.5g} — "
                           "the export uses a water type we have no name for")
        is_surface = "surface_p" in name or name == "P_ATM"
        used = surface_p if is_surface else msw_per_bar
        rng = box.surface_p if is_surface else box.msw_per_bar
        inside = box.contains(surface_p, msw_per_bar)
        return Finding(t, MATCH if inside else DIVERGES,
                       f"planned with {used:.5g}; export implies "
                       f"{rng[0]:.5g}..{rng[1]:.5g}")
    if name in ("M_O2", "M_N2", "M_HE") and DENSITY in pins:
        # A printed density fixes molar_mass / molar_volume as a ratio; the
        # three molar masses are textbook and never the suspect, so report them
        # as joint with the reference state rather than pretending to identify
        # each one.
        got = infer_density_molar_volume(ev, surface_p, msw_per_bar)
        ours = b.MOLAR_VOLUME * b.P_ATM
        ok = bool(got) and got[0] <= ours <= got[1]
        return Finding(t, JOINT_OK if ok else DIVERGES,
                       "only the molar-mass / molar-volume ratio is identified; "
                       + ("it agrees" if ok else
                          "it does not — see MOLAR_VOLUME"))
    if name == "MOLAR_VOLUME" and DENSITY in pins:
        got = infer_density_molar_volume(ev, surface_p, msw_per_bar)
        if got is None:
            return Finding(t, UNDETERMINED, "printed density not invertible")
        ours = b.MOLAR_VOLUME * b.P_ATM      # our reference: per atm, not per bar
        ok = got[0] <= ours <= got[1]
        return Finding(t, MATCH if ok else DIVERGES,
                       f"ours {ours:.4g} L·bar/mol effective; export implies "
                       f"{got[0]:.4g}..{got[1]:.4g}")
    if name == "density reference" and DENSITY in pins:
        got = infer_density_molar_volume(ev, surface_p, msw_per_bar)
        ours = b.MOLAR_VOLUME * b.P_ATM
        if got and not (got[0] <= ours <= got[1]):
            return Finding(t, DIVERGES,
                           f"ours {ours:.4g}, export {got[0]:.4g}..{got[1]:.4g} "
                           "— a reference-state difference, not physics")
        return Finding(t, MATCH, "same reference state")
    if OXTOX in pins and ev.oxtox is not None and name in (
            "_CNS_RATE", "OTU_THRESHOLD_PPO2", "OTU_EXPONENT"):
        cns_t, otu_t, cns_o, otu_o, tol = ev.oxtox
        worst = max(abs(cns_o - cns_t) / cns_t, abs(otu_o - otu_t) / otu_t)
        return Finding(t, JOINT_OK if worst <= tol else DIVERGES,
                       f"CNS/OTU agree to {worst * 100:.1f} % "
                       f"(tolerance {tol * 100:.0f} %); not separately identified")
    if VOLUMES in pins and ev.volumes:
        worst = max(abs(theirs - ours) / theirs for _l, theirs, ours, _t in ev.volumes)
        tol = max(t_ for *_x, t_ in ev.volumes)
        return Finding(t, JOINT_OK if worst <= tol else DIVERGES,
                       f"gas volumes agree to {worst * 100:.1f} %; "
                       "rate and billing convention not separately identified")
    if SCHEDULE in pins and ev.schedule is not None:
        sd = ev.schedule
        return Finding(t, JOINT_OK if sd.agrees else DIVERGES,
                       f"schedule {'agrees to' if sd.agrees else 'is out by'} "
                       f"{sd.describe()}; joint with every other model constant")
    return Finding(t, UNDETERMINED, "pinned in principle, not by this export")


def format_report(findings: Sequence[Finding], title: str = "") -> str:
    lines = [f"=== {title}" if title else "==="]
    counts = {v: sum(1 for f in findings if f.verdict == v) for v in VERDICT_ORDER}
    lines.append("  ".join(f"{v}: {counts[v]}" for v in VERDICT_ORDER))
    lines.append("")
    lines.extend(str(f) for f in findings)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The bundled exports, as evidence
# ---------------------------------------------------------------------------

def _schedule_delta(scenario: int, surface_p: float, msw_per_bar: float
                    ) -> ScheduleDelta:
    """Worst per-stop and TTS disagreement against the golden fixtures for this
    scenario, **measured now** rather than transcribed.

    Hardcoding the deltas would defeat the purpose: a model change has to move
    this number, or the SCHEDULE evidence stops being evidence.
    """
    import json
    import os

    from tests import test_multideco_scenarios as md

    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "shearwater_golden.json")) as fh:
        dives = json.load(fh)["dives"]
    tag = f"scenario_{scenario}"
    worst_stop = worst_tts = 0.0
    stop_tol = tts_tol = 0.0
    planned_tts = 0.0            # the export's own TTS, for the relative term
    for dive in dives:
        if tag not in (dive.get("source") or "") or not dive.get("expected"):
            continue
        decos = tuple(b.Gas(g["o2"] / 100.0, g.get("he", 0) / 100.0)
                      for g in dive["deco_gases"])
        segs = md._plan(scenario, decos, surface_p=surface_p,
                        msw_per_bar=msw_per_bar)
        ours = {round(s.depth_start): s.duration
                for s in segs if s.kind == "stop"}
        want = {round(float(d)): float(t) for d, t in dive["expected"]["stops"]}
        for depth in set(ours) | set(want):
            worst_stop = max(worst_stop,
                             abs(ours.get(depth, 0.0) - want.get(depth, 0.0)))
        worst_tts = max(worst_tts,
                        abs(b.time_to_surface(segs) - dive["expected"]["tts_min"]))
        stop_tol = max(stop_tol, dive.get("stop_tol_min", 2.0))
        tts_tol = max(tts_tol, dive.get("tts_tol_min", 3.0))
        # The no-loss plan is the dive itself; its TTS is what a relative
        # error should be measured against, not a lost-gas contingency's.
        if not any(w in dive["name"] for w in ("lost", "only")):
            planned_tts = float(dive["expected"]["tts_min"])
    return ScheduleDelta(worst_stop, worst_tts, planned_tts, stop_tol, tts_tol)


def multideco_evidence(scenario: int, *, surface_p: float, msw_per_bar: float,
                       planner: Callable[..., list] | None = None) -> Evidence:
    """`Evidence` for examples/scenario_1 or _2, transcribed from the export.

    Kept next to the inference machinery rather than in the test so a new
    export can be added the same way and immediately get a full report.
    """
    from tests import test_multideco_scenarios as md

    gas = md.SCENARIOS[scenario][1]
    e50, o2 = md.EAN50, md.O2
    # This scenario's printed values ONLY. The two exports are different dives
    # (EAN36/GF 40-85 vs EAN28/GF 5-50); letting one stand in for the other
    # would credit a conclusion to evidence that came from somewhere else.
    ppo2 = tuple((g, d, p) for g, d, p in md.PRINTED_PPO2[scenario])
    ead = tuple((g, d, float(p), False) for g, d, p in md.PRINTED_EAD[scenario])
    segs = md._plan(scenario, surface_p=surface_p, msw_per_bar=msw_per_bar)
    cns, otu = b.cns_otu(segs, surface_p, msw_per_bar)
    _l, _g, _gf, otu_t, cns_t, dens_t = md.SCENARIOS[scenario]
    vols = []
    for label, want in md.MD_LITERS[scenario]["OK"].items():
        g = gas if label == "bottom" else label
        assert isinstance(g, b.Gas)
        ours = b.segment_gas_liters([s for s in segs if s.gas == g],
                                    md.MD_BOTTOM_RMV)
        vols.append((str(label), want, ours, 0.01 if label == "bottom" else 0.25))
    return Evidence(
        ppo2=ppo2, ead=ead,
        density=((gas, 32.0, dens_t),),
        schedule=_schedule_delta(scenario, surface_p, msw_per_bar),
        oxtox=(cns_t, otu_t, cns, otu, 0.10),
        volumes=tuple(vols),
        stated={"DivePlan.gf_low": md.SCENARIOS[scenario][2][0],
                "DivePlan.gf_high": md.SCENARIOS[scenario][2][1],
                "DivePlan.descent_rate": 8.0, "DivePlan.ascent_rate": 9.0},
        gases_used=tuple({g for g, _d, _p in md.PRINTED_PPO2[scenario]}
                         | {gas, e50, o2}),
    )


def main() -> None:
    gaps = registry_gaps()
    print(f"registry gaps: {gaps or 'none'}\n")
    from tests import test_multideco_scenarios as md

    for scenario in (1, 2):
        for label, surf, mpb in (
                ("eko-deco defaults (sea level, salt)", b.P_ATM, b.MSW_PER_BAR),
                ("MultiDeco's printed environment (1.0 bar, fresh)",
                 md.MD_SURFACE_P, md.MD_MSW_PER_BAR)):
            ev = multideco_evidence(scenario, surface_p=surf, msw_per_bar=mpb)
            print(format_report(compare(ev, surface_p=surf, msw_per_bar=mpb),
                                f"scenario {scenario} vs {label}"))
            print()


if __name__ == "__main__":
    main()
