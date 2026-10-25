"""
Bühlmann ZHL-16C decompression model with Erik Baker's Gradient Factors.

References
----------
* A.A. Bühlmann, "Tauchmedizin" (1995), ZHL-16 coefficients (variant C).
* Erik C. Baker, "Clearing Up The Confusion About 'Deep Stops'" and
  "Understanding M-values" (gradient factor formulation).
* Subsurface dive log source (cross-check of constants).

Units
-----
* depth: meters of sea water (msw); 1 bar ≈ 10 msw (configurable)
* pressure: bar absolute
* time: minutes
* gas fractions: 0..1
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from itertools import pairwise

# -----------------------------------------------------------------------------
# ZHL-16C constants (16 compartments). N2 and He.
# Sources: Bühlmann 1990/1995, cross-checked with Subsurface deco.c.
# -----------------------------------------------------------------------------

N2_HALFTIME = (
    5.0, 8.0, 12.5, 18.5, 27.0, 38.3, 54.3, 77.0,
    109.0, 146.0, 187.0, 239.0, 305.0, 390.0, 498.0, 635.0,
)
N2_A = (
    1.1696, 1.0000, 0.8618, 0.7562, 0.6200, 0.5043, 0.4410, 0.4000,
    0.3750, 0.3500, 0.3295, 0.3065, 0.2835, 0.2610, 0.2480, 0.2327,
)
N2_B = (
    0.5578, 0.6514, 0.7222, 0.7825, 0.8126, 0.8434, 0.8693, 0.8910,
    0.9092, 0.9222, 0.9319, 0.9403, 0.9477, 0.9544, 0.9602, 0.9653,
)

HE_HALFTIME = (
    1.88, 3.02, 4.72, 6.99, 10.21, 14.48, 20.53, 29.11,
    41.20, 55.19, 70.69, 90.34, 115.29, 147.42, 188.24, 240.03,
)
HE_A = (
    1.6189, 1.3830, 1.1919, 1.0458, 0.9220, 0.8205, 0.7305, 0.6502,
    0.5950, 0.5545, 0.5333, 0.5189, 0.5181, 0.5176, 0.5172, 0.5119,
)
HE_B = (
    0.4770, 0.5747, 0.6527, 0.7223, 0.7582, 0.7957, 0.8279, 0.8553,
    0.8757, 0.8903, 0.8997, 0.9073, 0.9122, 0.9171, 0.9217, 0.9267,
)

N_COMP = 16

# Alveolar water-vapour pressure (bar, 37 °C). Schreiner's 0.0567 is the
# default because it is what every planner these schedules are compared against
# uses — MultiDeco, Shearwater and Erik Baker's GFDECO — so a plan made here
# sits beside one of theirs without a flag. Bühlmann's own figure is 0.0627,
# which Subsurface uses (WV_PRESSURE in its deco.cpp) and which the Subsurface
# cross-check therefore passes explicitly. Lower vapour pressure means MORE
# inspired inert gas, so this default is also the conservative one of the two
# (see DECISIONS.md #20).
P_H2O = 0.0567
#: Bühlmann's value, for a plan that wants it (Subsurface's convention).
P_H2O_BUHLMANN = 0.0627
#: Schreiner's value — the default; MultiDeco / Shearwater / GFDECO.
P_H2O_SCHREINER = 0.0567
# Atmospheric pressure at sea level (bar).
P_ATM = 1.01325
# msw per bar (sea water). Use 10.0 for "metric-friendly" rounding.
MSW_PER_BAR = 10.0

# Water types as msw-per-bar. `salt` is the EN 13319 / dive-planner convention
# (1 msw = 0.1 bar exactly) and is the default. `fresh` is 10 1/3 m per bar —
# the old "1 atm = 10.33 m of water" figure, which is the constant real
# MultiDeco fresh-water plans were measured to print (see DECISIONS.md #15),
# rather than the textbook 10.20 m column of a bar. The difference is ~1.3 % of
# ambient pressure; pass msw_per_bar=10.197 explicitly for the textbook value.
MSW_PER_BAR_SALT = 10.0
MSW_PER_BAR_FRESH = 31.0 / 3.0
WATER_TYPES = {"salt": MSW_PER_BAR_SALT, "fresh": MSW_PER_BAR_FRESH}

#: Allowed values of `DivePlan.gas_switch_policy`. A frozenset, not a tuple, on
#: purpose: `tests/planner_diff.registry_gaps` enumerates tuple/dict constants as
#: tunables needing registration, and this is not a tunable — it is the set of
#: legal values for one. The tunable is the DivePlan field, registered there.
GAS_SWITCH_POLICIES = frozenset({"at-mod", "at-first-stop"})


#: Named constant sets that reproduce a given planner's output.
#:
#: Every planner in this family runs the same Bühlmann + gradient-factor model
#: and still prints different schedules, because each picks different values
#: for a handful of constants nobody thinks of as choices. Naming those sets
#: turns "why is theirs two minutes longer" into a question with an answer, and
#: lets a schedule be planned deliberately in someone else's convention rather
#: than by hunting flags (DECISIONS.md #20).
#:
#: `default` IS `multideco`: the planners divers actually carry — MultiDeco,
#: Shearwater, and Erik Baker's GFDECO, which both descend from — agree on
#: these, so agreeing with them out of the box is worth more than matching
#: Bühlmann's book. `subsurface` is the odd one out and is what its
#: cross-check oracle pins.
PLANNER_PROFILES: dict[str, dict[str, float]] = {
    "multideco":  {"p_h2o": P_H2O_SCHREINER, "surface_p": P_ATM,
                   "msw_per_bar": MSW_PER_BAR_SALT},
    "shearwater": {"p_h2o": P_H2O_SCHREINER, "surface_p": P_ATM,
                   "msw_per_bar": MSW_PER_BAR_SALT},
    "gfdeco":     {"p_h2o": P_H2O_SCHREINER, "surface_p": 1.0,
                   "msw_per_bar": MSW_PER_BAR_SALT},
    "subsurface": {"p_h2o": P_H2O_BUHLMANN, "surface_p": 1.013,
                   "msw_per_bar": MSW_PER_BAR_SALT},
    "buhlmann":   {"p_h2o": P_H2O_BUHLMANN, "surface_p": P_ATM,
                   "msw_per_bar": MSW_PER_BAR_SALT},
}


def surface_p_at_altitude(altitude_m: float) -> float:
    """Atmospheric pressure (bar) at `altitude_m` above sea level, by the
    international barometric formula for the standard troposphere::

        P = P_ATM * (1 - 2.25577e-5 * h) ** 5.25588

    This is the surface pressure to plan an altitude dive with — a mountain
    lake at 1500 m sits near 0.845 bar, so the same tissue loading is far
    closer to its surfacing ceiling than at sea level.

    It does NOT model **acclimatisation**: the tissues start the dive
    equilibrated at this pressure, which is true of a diver who has been up
    there for many hours, not of one who drove up that morning and is still
    carrying sea-level nitrogen. Arriving unacclimatised is the conservative
    error in the ascent direction but not in the loading direction, so treat
    same-day altitude dives with extra margin."""
    if altitude_m <= 0:
        return P_ATM
    return P_ATM * (1.0 - 2.25577e-5 * altitude_m) ** 5.25588


def altitude_at_surface_p(surface_p: float) -> float:
    """Inverse of `surface_p_at_altitude`: the altitude (m) whose standard
    atmosphere is `surface_p` bar. 0 at or above sea-level pressure. Front ends
    use it to show an altitude next to a stored surface pressure."""
    if surface_p >= P_ATM:
        return 0.0
    return (1.0 - (surface_p / P_ATM) ** (1.0 / 5.25588)) / 2.25577e-5


def depth_to_p_amb(depth_m: float, surface_p: float = P_ATM,
                   msw_per_bar: float = MSW_PER_BAR) -> float:
    return surface_p + depth_m / msw_per_bar


def p_amb_to_depth(p_amb: float, surface_p: float = P_ATM,
                   msw_per_bar: float = MSW_PER_BAR) -> float:
    return max(0.0, (p_amb - surface_p) * msw_per_bar)


# -----------------------------------------------------------------------------
# Gas
# -----------------------------------------------------------------------------

# Molar masses (g/mol) and the ideal-gas molar volume at 0 °C / 1 atm (L/mol),
# for the gas-density figure (Anthony & Mitchell's 5.2 / 6.2 g/L guidance).
M_O2, M_N2, M_HE = 31.9988, 28.0134, 4.0026
MOLAR_VOLUME = 22.414

# Density above which work of breathing / CO2 retention risk is unacceptable
# (Anthony & Mitchell 2015; preferred maximum is 5.2 g/L).
DENSITY_MAX_G_L = 6.2
# Anthony & Mitchell's *recommended* maximum — the number the training agencies
# teach and the one a gas plan is actually built to. Air passes it at about
# 31 m and only reaches DENSITY_MAX_G_L at about 39 m, so warning on the hard
# ceiling alone leaves the whole band where the paper says to add helium
# unflagged. Two tiers, not one (see DECISIONS.md #33).
DENSITY_WORKING_G_L = 5.2


@dataclass(frozen=True)
class Gas:
    """Breathing gas. fO2 + fHe + fN2 == 1."""
    fO2: float
    fHe: float = 0.0

    @property
    def fN2(self) -> float:
        # Clamp to zero: the constructor tolerates fO2 + fHe = 1 + 1e-9 (float
        # rounding on e.g. a 79% He mix), and a tiny negative N2 fraction must
        # never leak into the molar-mass / narcotic / Schreiner math.
        return max(0.0, 1.0 - self.fO2 - self.fHe)

    def __post_init__(self) -> None:
        if not (0.0 < self.fO2 <= 1.0):
            raise ValueError(f"fO2 out of range: {self.fO2}")
        if not (0.0 <= self.fHe < 1.0):
            raise ValueError(f"fHe out of range: {self.fHe}")
        # Checked on the RAW sum, never on `fN2`: that property clamps at zero
        # to keep float slop (21/79 sums to 1 + 1e-9 in binary) out of the
        # molar-mass and Schreiner math, and the clamp made this guard
        # unreachable — `Gas(0.50, 0.60)` built a "Trimix 50/60" with fN2 0.0
        # and went on to quote a density, a MOD and an END for it. The 1e-9 is
        # the same slop tolerance the clamp exists for (DECISIONS.md #34).
        if self.fO2 + self.fHe > 1.0 + 1e-9:
            raise ValueError(
                f"fO2 + fHe > 1: {self.fO2:g} + {self.fHe:g} is not a gas")

    def mod(self, ppo2_max: float = 1.4, surface_p: float = P_ATM,
            msw_per_bar: float = MSW_PER_BAR) -> float:
        """Maximum operating depth in msw for the given ppO2 limit."""
        return (ppo2_max / self.fO2 - surface_p) * msw_per_bar

    def ppo2(self, depth_m: float, surface_p: float = P_ATM,
             msw_per_bar: float = MSW_PER_BAR) -> float:
        """Partial pressure of O2 (bar) at the given depth."""
        return self.fO2 * depth_to_p_amb(depth_m, surface_p, msw_per_bar)

    def min_depth(self, ppo2_min: float = 0.18, surface_p: float = P_ATM,
                  msw_per_bar: float = MSW_PER_BAR) -> float:
        """Shallowest depth (msw) where ppO2 >= ppo2_min. 0 if breathable at the
        surface; positive for a hypoxic mix that needs a travel gas above it."""
        return max(0.0, (ppo2_min / self.fO2 - surface_p) * msw_per_bar)

    def end(self, depth_m: float, surface_p: float = P_ATM,
            msw_per_bar: float = MSW_PER_BAR, o2_narcotic: bool = True) -> float:
        """Equivalent narcotic depth (msw): the depth at which AIR carries the
        same narcotic gas pressure. O2 counted as narcotic as N2 (the GUE /
        MultiDeco convention, so END = depth of p_amb*(1-fHe)); pass
        o2_narcotic=False for the N2-only convention (scaled by air's fN2)."""
        p_amb = depth_to_p_amb(depth_m, surface_p, msw_per_bar)
        p_narc = p_amb * ((1.0 - self.fHe) if o2_narcotic
                          else self.fN2 / AIR.fN2)
        return p_amb_to_depth(p_narc, surface_p, msw_per_bar)

    def density(self, depth_m: float = 0.0, surface_p: float = P_ATM,
                msw_per_bar: float = MSW_PER_BAR) -> float:
        """Gas density (g/L) at depth, ideal gas at 0 °C. Anthony & Mitchell
        (2015): keep it <= 5.2 g/L, hard ceiling 6.2 g/L (air passes that at
        about 39 m) — high density drives CO2 retention regardless of narcosis."""
        molar_mass = (self.fO2 * M_O2 + self.fHe * M_HE + self.fN2 * M_N2)
        p_amb = depth_to_p_amb(depth_m, surface_p, msw_per_bar)
        return molar_mass / MOLAR_VOLUME * p_amb / P_ATM

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        if self.fHe > 0:
            return f"Trimix {round(self.fO2*100)}/{round(self.fHe*100)}"
        if abs(self.fO2 - 0.21) < 1e-6:
            return "Air"
        if abs(self.fO2 - 1.0) < 1e-6:
            return "O2"          # what a diver writes on a slate, not "EAN100"
        return f"EAN{round(self.fO2*100)}"


AIR = Gas(0.21)
EAN32 = Gas(0.32)
EAN50 = Gas(0.50)
O2 = Gas(1.00)


# -----------------------------------------------------------------------------
# Tissue compartments
# -----------------------------------------------------------------------------

@dataclass
class Tissues:
    """16-compartment N2/He loading (partial pressures, bar)."""
    pN2: list[float] = field(default_factory=lambda: [0.0] * N_COMP)
    pHe: list[float] = field(default_factory=lambda: [0.0] * N_COMP)

    @classmethod
    def at_surface(cls, surface_p: float = P_ATM, gas: Gas = AIR,
                   p_h2o: float = P_H2O) -> Tissues:
        """Fully saturated at surface on the given gas (default air)."""
        p_insp_n2 = (surface_p - p_h2o) * gas.fN2
        p_insp_he = (surface_p - p_h2o) * gas.fHe
        return cls(pN2=[p_insp_n2] * N_COMP, pHe=[p_insp_he] * N_COMP)

    def copy(self) -> Tissues:
        return Tissues(pN2=list(self.pN2), pHe=list(self.pHe))


def _schreiner(p0: float, p_insp_start: float, rate_insp: float,
               t: float, halftime: float) -> float:
    """Schreiner equation for one compartment, one gas.

    Reduces to the Haldane instantaneous-equilibrium update when rate = 0.

    p0           initial compartment partial pressure (bar)
    p_insp_start initial inspired inert-gas partial pressure (bar)
    rate_insp    rate of change of inspired inert-gas pressure (bar/min)
    t            interval length (min)
    halftime     compartment half-time (min)
    """
    k = math.log(2.0) / halftime
    return (p_insp_start
            + rate_insp * (t - 1.0 / k)
            - (p_insp_start - p0 - rate_insp / k) * math.exp(-k * t))


def update_tissues(tissues: Tissues, gas: Gas,
                   p_amb_start: float, p_amb_end: float,
                   t_min: float, p_h2o: float = P_H2O) -> None:
    """Update all 16 compartments over a segment of constant ascent/descent
    rate (or flat, if p_amb_start == p_amb_end). In-place."""
    if t_min <= 0:
        return
    rate_amb = (p_amb_end - p_amb_start) / t_min
    p_insp_n2_0 = (p_amb_start - p_h2o) * gas.fN2
    p_insp_he_0 = (p_amb_start - p_h2o) * gas.fHe
    rate_n2 = rate_amb * gas.fN2
    rate_he = rate_amb * gas.fHe
    for i in range(N_COMP):
        tissues.pN2[i] = _schreiner(tissues.pN2[i], p_insp_n2_0, rate_n2,
                                    t_min, N2_HALFTIME[i])
        tissues.pHe[i] = _schreiner(tissues.pHe[i], p_insp_he_0, rate_he,
                                    t_min, HE_HALFTIME[i])


# -----------------------------------------------------------------------------
# M-values, ceiling, gradient factors
# -----------------------------------------------------------------------------

def compartment_ab(pN2: float, pHe: float, idx: int) -> tuple[float, float]:
    """Bühlmann combined a/b coefficients weighted by N2/He partial pressure."""
    total = pN2 + pHe
    if total <= 0:
        return N2_A[idx], N2_B[idx]
    a = (N2_A[idx] * pN2 + HE_A[idx] * pHe) / total
    b = (N2_B[idx] * pN2 + HE_B[idx] * pHe) / total
    return a, b


def ceiling(tissues: Tissues, gf: float) -> float:
    """Lowest tolerated ambient pressure (bar) across all 16 compartments
    at the given gradient factor (0..1). Baker's formula:

        P_amb_tol = (P_comp - a*GF) / (GF/b + 1 - GF)
    """
    worst = 0.0
    for i in range(N_COMP):
        p_comp = tissues.pN2[i] + tissues.pHe[i]
        a, b = compartment_ab(tissues.pN2[i], tissues.pHe[i], i)
        p_tol = (p_comp - a * gf) / (gf / b + 1.0 - gf)
        if p_tol > worst:
            worst = p_tol
    return worst


def ceiling_depth(tissues: Tissues, gf: float,
                  surface_p: float = P_ATM,
                  msw_per_bar: float = MSW_PER_BAR) -> float:
    return p_amb_to_depth(ceiling(tissues, gf), surface_p, msw_per_bar)


def surface_gf(tissues: Tissues, surface_p: float = P_ATM) -> float:
    """The gradient factor the diver actually **surfaces at** (0..1, sometimes
    more) — Shearwater's SurfGF.

    `gf_high` is the budget; this is what was spent. Baker's discretisation pads
    every stop onto a whole-minute grid, so a schedule flown as printed usually
    surfaces some way under its own GF-High, and that headroom is exactly the
    number a diver wants after a plan changes underwater.

    Closed form, not a search: invert `ceiling`'s

        P_amb_tol = (P_comp - a*GF) / (GF/b + 1 - GF)

    for the GF that puts the tolerated pressure exactly at the surface,

        GF = (P_comp - P_surf) / (a + P_surf/b - P_surf)

    and take the worst compartment. The denominator is always positive (b < 1,
    a > 0), so there is no singular case to guard.

    Returned raw: a value over 1.0 means the schedule surfaces beyond its own
    M-value line and is a real warning, not something to clamp away. Zero means
    no compartment is supersaturated at the surface at all.
    """
    worst = 0.0
    for i in range(N_COMP):
        p_comp = tissues.pN2[i] + tissues.pHe[i]
        a, b_coef = compartment_ab(tissues.pN2[i], tissues.pHe[i], i)
        gf = (p_comp - surface_p) / (a + surface_p / b_coef - surface_p)
        if gf > worst:
            worst = gf
    return worst


def gf_at(p_amb: float, gf_low: float, gf_high: float,
          p_first_stop: float, p_surface: float = P_ATM) -> float:
    """Linearly interpolate GF between GF-Low at the first stop and
    GF-High at the surface."""
    if p_first_stop <= p_surface:
        return gf_high
    if p_amb >= p_first_stop:
        return gf_low
    if p_amb <= p_surface:
        return gf_high
    frac = (p_first_stop - p_amb) / (p_first_stop - p_surface)
    return gf_low + (gf_high - gf_low) * frac


# -----------------------------------------------------------------------------
# Dive planner
# -----------------------------------------------------------------------------

@dataclass
class DiveSegment:
    """One leg of the dive. depth in msw, duration in min, gas used."""
    kind: str          # "descent" | "bottom" | "ascent" | "stop"
    depth_start: float
    depth_end: float
    duration: float
    gas: Gas
    gf_used: float | None = None  # for stops / ceiling at end
    # Set on a level that sits shallower than the decompression ceiling at that
    # point (only reachable on a multi-level profile): the ceiling depth in msw.
    # The schedule is still computed — the profile is the diver's to fix.
    ceiling_m: float | None = None

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "depth_start_m": round(self.depth_start, 2),
            "depth_end_m": round(self.depth_end, 2),
            "duration_min": round(self.duration, 2),
            "gas": repr(self.gas),
            "gf_used": None if self.gf_used is None else round(self.gf_used, 3),
            "ceiling_m": None if self.ceiling_m is None else round(self.ceiling_m, 2),
        }


@dataclass(frozen=True)
class Level:
    """One leg of a multi-level bottom phase.

    depth    msw
    runtime  minutes since leaving the surface, at the END of this level
             (descent included — the same meaning `bottom_time` has always had,
             and what MultiDeco / Baker's GFDECO / Subsurface take as input)

    Levels are contiguous: the transit to `depth` runs at the plan's standard
    rate and starts the moment the previous level ends, so its time is part of
    this level's runtime. No planner models an arrival time separately — in
    MultiDeco a level's time is rejected outright if it is "too short … for
    descent/ascent" — so to loiter shallow before going deeper you add a level
    for the shallow depth, exactly as you would there.

    Gas is always chosen automatically by role: the bottom mix while it is
    breathable, a travel mix where it is not (`DivePlan.descent_gas`). Levels
    are pure depth/time periods — they never force a mix of their own.
    """
    depth: float
    runtime: float

    def __post_init__(self) -> None:
        if self.depth < 0:
            raise ValueError(f"level depth must be >= 0 m (got {self.depth:g})")
        if self.runtime <= 0:
            raise ValueError(
                f"level runtime must be > 0 min (got {self.runtime:g})")


@dataclass
class DivePlan:
    descent_rate: float = 18.0   # m/min
    ascent_rate: float = 10.0    # m/min  (used between bottom and stops, and stop-to-stop)
    stop_interval: float = 3.0   # m
    # Shallowest stop depth. 3.0 = stops all the way to 3 m (default);
    # 6.0 = the Shearwater/MultiDeco "last stop 6 m" option: any deco shallower
    # than 6 m is served at 6 m, followed by a direct ascent to the surface.
    last_stop_depth: float = 3.0
    gf_low: float = 0.30
    gf_high: float = 0.80
    surface_p: float = P_ATM
    msw_per_bar: float = MSW_PER_BAR
    # The grid a deco stop's RUNTIME is padded onto (min). Baker's
    # `Minimum_Deco_Stop_Time`, a parameter in gfdeco.f rather than a constant
    # — his comment notes that at 0.1 min with a 0.2 msw step "a near
    # continuous decompression schedule can be computed". 1 min is the usual
    # table-friendly value (DECISIONS.md #21).
    min_stop_time: float = 1.0
    # Alveolar water-vapour pressure (bar). Schreiner's 0.0567 by default —
    # what Baker's GFDECO, MultiDeco and Shearwater use (DECISIONS.md #20);
    # Bühlmann's own 0.0627 is `P_H2O_BUHLMANN`. It is a real input to the
    # schedule, so it is a plan field rather than a module constant nobody can
    # reach (DECISIONS.md #19). The default is bound at import time, so
    # assigning to the module global afterwards does not reach a DivePlan —
    # pass `p_h2o=` instead.
    p_h2o: float = P_H2O
    # Travel (descent) gases: breathed while the bottom gas is too hypoxic to use
    # near the surface (e.g. a hypoxic trimix such as 10/70).
    travel_gases: Sequence[Gas] = field(default_factory=tuple)
    # Deco / acceleration gases, switched to on ascent at their MOD.
    deco_gases: Sequence[Gas] = field(default_factory=tuple)
    ppo2_deco: float = 1.6      # ppO2 ceiling for deco gases on ascent
    ppo2_bottom: float = 1.4    # ppO2 ceiling for the bottom/travel gas going down
    ppo2_min: float = 0.18      # hypoxia floor: a gas is not breathable below this ppO2
    # Ascent gas switches happen at standard stop depths (MOD rounded to the
    # nearest stop_interval multiple), the way divers and dive computers plan
    # them — e.g. O2 at the 6 m stop even though its MOD at ppO2 1.6 is 5.9 m.
    # Rounding a switch *deeper* than the MOD is only allowed while the ppO2
    # excess stays within this tolerance (bar); otherwise the switch rounds
    # down to the next shallower stop.
    ppo2_switch_tol: float = 0.05
    # WHERE on the ascent a deco gas is switched to. "at-mod" (default) takes it
    # as soon as the ppO2 allows, at the stop depth `switch_depth` snaps to —
    # what MultiDeco, Shearwater and this planner have always done, and what
    # gets the richest mix breathing soonest.
    #
    # "at-first-stop" holds every deco switch until the first stop is reached.
    # Teams plan it that way on purpose: a switch flown mid-ascent is a
    # valve/regulator drill done while moving and negatively task-loaded, so the
    # convention is to arrive, settle, then switch. It buys safety with deco
    # time — the richer mix starts working later, so the schedule gets longer,
    # never shorter (DECISIONS.md #25).
    gas_switch_policy: str = "at-mod"

    def __post_init__(self) -> None:
        # GF-low > GF-high would make the GF line *rise* toward the first stop —
        # a profile no agency teaches and almost certainly a swapped input.
        if not (0.0 < self.gf_low <= self.gf_high <= 1.0):
            raise ValueError(
                f"gradient factors must satisfy 0 < GF-low <= GF-high <= 1.0 "
                f"(got {self.gf_low:g}/{self.gf_high:g})")
        # The planner divides by every rate/interval below and converts depth
        # to pressure with surface_p / msw_per_bar: zero or negative values
        # mean division-by-zero crashes or physically impossible schedules.
        for name in ("descent_rate", "ascent_rate", "stop_interval",
                     "surface_p", "msw_per_bar", "p_h2o", "min_stop_time"):
            v = getattr(self, name)
            if v <= 0:
                raise ValueError(f"{name} must be > 0 (got {v:g})")
        if self.last_stop_depth < 0:
            raise ValueError(
                f"last_stop_depth must be >= 0 m (got {self.last_stop_depth:g})")
        if self.ppo2_min < 0 or self.ppo2_switch_tol < 0:
            raise ValueError("ppo2_min and ppo2_switch_tol must be >= 0")
        if min(self.ppo2_bottom, self.ppo2_deco) <= self.ppo2_min:
            raise ValueError(
                f"ppO2 ceilings (bottom {self.ppo2_bottom:g}, deco "
                f"{self.ppo2_deco:g}) must sit above the hypoxia floor "
                f"ppo2_min ({self.ppo2_min:g})")
        if self.gas_switch_policy not in GAS_SWITCH_POLICIES:
            raise ValueError(
                f"gas_switch_policy must be one of "
                f"{', '.join(sorted(GAS_SWITCH_POLICIES))} "
                f"(got {self.gas_switch_policy!r})")

    def _usable(self, gas: Gas, depth: float, ppo2_ceiling: float) -> bool:
        pp = gas.ppo2(depth, self.surface_p, self.msw_per_bar)
        return self.ppo2_min - 1e-9 <= pp <= ppo2_ceiling + 1e-9

    def switch_depth(self, gas: Gas, first_stop: float | None = None) -> float:
        """Ascent switch depth for `gas`: its MOD at ppo2_deco snapped to the
        nearest stop-interval multiple (subject to ppo2_switch_tol).

        Under `gas_switch_policy` "at-first-stop" a **deco** gas is additionally
        held back to `first_stop` when its MOD is deeper than that — the team
        convention of arriving, settling, then switching. Bottom and travel
        gases are untouched: they are what got the diver down, not a switch made
        on the way up. `first_stop=None` (an NDL ascent has no stop to hold to)
        leaves the policy with nothing to apply, so it behaves as "at-mod".
        """
        mod = gas.mod(self.ppo2_deco, self.surface_p, self.msw_per_bar)
        if mod <= 0:
            return mod
        snapped = round(mod / self.stop_interval) * self.stop_interval
        if (snapped > mod and gas.ppo2(snapped, self.surface_p, self.msw_per_bar)
                > self.ppo2_deco + self.ppo2_switch_tol + 1e-9):
            snapped = math.floor(mod / self.stop_interval) * self.stop_interval
        if (self.gas_switch_policy == "at-first-stop" and first_stop is not None
                and gas in self.deco_gases):
            snapped = min(snapped, first_stop)
        return snapped

    def best_gas(self, depth: float, bottom_gas: Gas,
                 first_stop: float | None = None,
                 exclude: Sequence[Gas] = ()) -> Gas:
        """Richest breathable gas for the ASCENT at `depth` (bottom + travel +
        deco gases): floored at ppo2_min, switched in at switch_depth().

        `exclude` drops mixes the diver no longer has — a lost-gas bailout. The
        bottom gas is excluded like any other, so when nothing at all is
        breathable this returns the *first remaining candidate* rather than
        pretending the lost cylinder is still there; callers that can fail
        (`bailout_schedule`) check breathability themselves first.
        """
        candidates = [g for g in (bottom_gas, *self.travel_gases,
                                  *self.deco_gases) if g not in exclude]
        usable = [g for g in candidates
                  if depth <= self.switch_depth(g, first_stop) + 1e-9
                  and g.ppo2(depth, self.surface_p, self.msw_per_bar)
                  >= self.ppo2_min - 1e-9]
        if not usable:
            return candidates[0] if candidates else bottom_gas
        return max(usable, key=lambda g: g.fO2)

    def descent_gas(self, depth: float, bottom_gas: Gas) -> Gas:
        """Gas to breathe on the way DOWN at `depth`: the bottom gas as soon as it
        is breathable (ppO2 >= ppo2_min), otherwise the richest usable travel gas."""
        if self._usable(bottom_gas, depth, self.ppo2_bottom):
            return bottom_gas
        travel = [g for g in self.travel_gases if self._usable(g, depth, self.ppo2_bottom)]
        if travel:
            return max(travel, key=lambda g: g.fO2)
        candidates = [bottom_gas, *self.travel_gases, *self.deco_gases]
        usable = [g for g in candidates if self._usable(g, depth, self.ppo2_bottom)]
        return max(usable, key=lambda g: g.fO2) if usable else bottom_gas


def _round_up_to_stop(depth: float, interval: float) -> float:
    """A ceiling depth rounded to the stop grid, Baker's way.

    GFDECO does ``ANINT(ceiling/step + 0.5) * step``, which is the **strictly
    next** step, not a ceiling: a ceiling of exactly 6 m rounds to 9, not 6.
    The difference only shows when the ceiling lands exactly on a step, and
    Baker's choice is the conservative one — never hold *at* the ceiling, where
    supersaturation equals the GF-adjusted M-value with nothing in hand.

    Zero or less is no stop at all, as in gfdeco.f's
    ``IF (Deco_Ceiling_Depth .LE. 0.0) THEN Deco_Stop_Depth = 0.0``.
    """
    if depth <= 0:
        return 0.0
    return (math.floor(depth / interval + 1e-9) + 1) * interval


def _gas_switch_depths(plan: DivePlan, bottom_gas: Gas,
                       first_stop: float | None = None) -> list[float]:
    """Depths (msw) where the breathable-gas choice can change: each gas's
    (stop-rounded) ascent switch depth, its raw MOD at the descent ppO2
    ceiling, and each hypoxic mix's minimum breathable depth.

    `first_stop` must match what `best_gas` is given on the same leg — these are
    the depths `_move` splits at, so a break computed at a switch depth the gas
    chooser no longer uses would load a whole sub-segment on the wrong mix."""
    depths = set()
    for g in (bottom_gas, *plan.travel_gases, *plan.deco_gases):
        mod_descent = g.mod(plan.ppo2_bottom, plan.surface_p, plan.msw_per_bar)
        if mod_descent > 0:
            depths.add(round(mod_descent, 6))
        switch = plan.switch_depth(g, first_stop)
        if switch > 0:
            depths.add(round(switch, 6))
        dmin = g.min_depth(plan.ppo2_min, plan.surface_p, plan.msw_per_bar)
        if dmin > 0:
            depths.add(round(dmin, 6))
    return sorted(depths)


def _move(tissues: Tissues, segs: list[DiveSegment], plan: DivePlan,
          bottom_gas: Gas, from_depth: float, to_depth: float, gas_for,
          kind: str, p_first_stop: float | None,
          first_stop: float | None = None) -> None:
    """Change depth continuously from `from_depth` to `to_depth`, splitting into
    sub-segments at gas-switch depths and loading tissues with the gas chosen
    (by `gas_for`) for each sub-segment.

    `p_first_stop` anchors the gradient-factor line for the deco ascent; pass
    None for legs that are not part of it (travel between levels), so they are
    not annotated with a GF they never used."""
    if abs(to_depth - from_depth) < 1e-9:
        return
    descending = to_depth > from_depth
    rate = plan.descent_rate if descending else plan.ascent_rate
    lo, hi = min(from_depth, to_depth), max(from_depth, to_depth)
    breaks = [d for d in _gas_switch_depths(plan, bottom_gas, first_stop)
              if lo + 1e-9 < d < hi - 1e-9]
    seq = [from_depth] + (breaks if descending else breaks[::-1]) + [to_depth]
    runs: list[tuple[float, float, Gas]] = []
    for a, c in pairwise(seq):
        gas = gas_for((a + c) / 2.0)
        if runs and runs[-1][2] == gas:
            runs[-1] = (runs[-1][0], c, gas)   # coalesce same-gas sub-segments
        else:
            runs.append((a, c, gas))
    for a, c, gas in runs:
        p_a = depth_to_p_amb(a, plan.surface_p, plan.msw_per_bar)
        p_c = depth_to_p_amb(c, plan.surface_p, plan.msw_per_bar)
        t = abs(c - a) / rate
        update_tissues(tissues, gas, p_a, p_c, t, plan.p_h2o)
        gf = (gf_at(p_c, plan.gf_low, plan.gf_high, p_first_stop, plan.surface_p)
              if kind == "ascent" and p_first_stop is not None else None)
        segs.append(DiveSegment(kind, a, c, t, gas, gf_used=gf))


def plan_dive(bottom_depth: float, bottom_time: float, bottom_gas: Gas,
              plan: DivePlan | None = None,
              start_tissues: Tissues | None = None
              ) -> tuple[list[DiveSegment], Tissues]:
    """Compute a square-profile dive plan with deco stops.

    `bottom_time` is the total runtime to leaving the bottom (descent + flat).
    Returns the segment list and the final tissue state.

    A square dive is a one-level dive: this is `plan_multilevel` with a single
    `Level`.
    """
    return plan_multilevel([Level(bottom_depth, bottom_time)], bottom_gas,
                           plan, start_tissues)


def plan_multilevel(levels: Sequence[Level], bottom_gas: Gas,
                    plan: DivePlan | None = None,
                    start_tissues: Tissues | None = None
                    ) -> tuple[list[DiveSegment], Tissues]:
    """Plan a multi-level dive: a sequence of levels, then the deco ascent.

    Each `Level.runtime` is the runtime (minutes since leaving the surface) at
    the END of that level, so the levels are cumulative and must increase. The
    diver travels between levels at the plan's descent/ascent rate; the travel
    time is part of the runtime, exactly as on the initial descent.

    Gas during the bottom phase is always automatic: the bottom gas, with
    travel mixes substituted where the bottom mix is not breathable — deco
    gases are only switched to on the final ascent.

    A level shallower than the decompression ceiling is *not* an error: the
    schedule is still computed and the offending level's `DiveSegment.ceiling_m`
    records the ceiling it broke (Baker's GFDECO warns about the same thing).

    Returns the segment list and the final tissue state.
    """
    if not levels:
        raise ValueError("a dive needs at least one level")
    if plan is None:
        plan = DivePlan()
    for i, (prev, cur) in enumerate(pairwise(levels), start=2):
        if cur.runtime <= prev.runtime:
            raise ValueError(
                f"level {i} runtime ({cur.runtime:g} min) must be later than "
                f"level {i - 1}'s ({prev.runtime:g} min) — runtimes are "
                f"cumulative, i.e. minutes since leaving the surface")

    tissues = (start_tissues.copy() if start_tissues
               else Tissues.at_surface(plan.surface_p, AIR, plan.p_h2o))
    segs: list[DiveSegment] = []
    def descent_gas_for(d: float) -> Gas:
        return plan.descent_gas(d, bottom_gas)

    # ---- levels: travel to each in turn, then hold it until its runtime ------
    run = 0.0
    depth = 0.0
    for i, level in enumerate(levels, start=1):
        going_down = level.depth > depth
        # Time the standard-rate transit to this level's depth. Levels are
        # contiguous: the transit leaves the moment the previous level ends and
        # its time is billed to this level's runtime.
        rate = plan.descent_rate if going_down else plan.ascent_rate
        transit_t = abs(level.depth - depth) / rate

        # Bottom-phase gas is always automatic: the bottom gas, with a travel
        # mix swapped in where the bottom mix is hypoxic (descent_gas). Deco
        # gases are only switched to on the final ascent.
        _move(tissues, segs, plan, bottom_gas, depth, level.depth, descent_gas_for,
              "descent" if going_down else "ascent", None)
        run += transit_t
        depth = level.depth

        # Shallower than the ceiling? Worst right on arrival, before off-gassing.
        ceil = ceiling_depth(tissues, plan.gf_low, plan.surface_p, plan.msw_per_bar)
        violated = ceil if ceil > depth + 1e-6 else None

        t_flat = level.runtime - run
        if t_flat < -1e-9:
            raise ValueError(
                f"level {i} runtime ({level.runtime:g} min) is before the diver "
                f"even reaches {level.depth:g} m (arrives at {run:.1f} min)")
        t_flat = max(0.0, t_flat)
        # The gas actually relevant at this depth — the bottom mix while it is
        # breathable, a travel mix where it is not (deep enough to blow the ppO2
        # ceiling, or too shallow for a hypoxic mix). Same rule as the travel
        # legs; on a normal dive it simply is the bottom gas.
        gas_here = plan.descent_gas(depth, bottom_gas)
        p_level = depth_to_p_amb(depth, plan.surface_p, plan.msw_per_bar)
        update_tissues(tissues, gas_here, p_level, p_level, t_flat,
                       plan.p_h2o)
        segs.append(DiveSegment("bottom", depth, depth, t_flat, gas_here,
                                ceiling_m=violated))
        run = level.runtime

    _ascend(tissues, segs, plan, bottom_gas, depth)
    return segs, tissues


def _ascend(tissues: Tissues, segs: list[DiveSegment], plan: DivePlan,
            bottom_gas: Gas, bottom_depth: float,
            exclude: Sequence[Gas] = ()) -> None:
    """The decompression ascent from `bottom_depth`, appended to `segs`.

    Split out of `plan_multilevel` so a bailout can re-fly the same ascent from
    the same tissues on a different gas stack (`bailout_schedule`) instead of
    re-planning the bottom phase, which already happened and cannot be undone by
    losing a cylinder afterwards.

    `exclude` are mixes the diver no longer has. Everything else — Baker's stop
    discretisation, the GF line anchored at the rounded first stop, the
    last-stop rule — is unchanged, because this is the same code the normal
    plan runs.
    """
    # ---- find first stop using GF-Low ----
    ceil_low = ceiling_depth(tissues, plan.gf_low, plan.surface_p, plan.msw_per_bar)
    first_stop_depth = _round_up_to_stop(ceil_low, plan.stop_interval)
    if first_stop_depth > 0:
        first_stop_depth = max(first_stop_depth, plan.last_stop_depth)

    def ascent_gas_for(d: float) -> Gas:
        # `first_stop_depth` is read at call time, not captured by value: on an
        # NDL ascent it is 0 and the "at-first-stop" policy must fall back to
        # at-MOD rather than hold every switch to the surface.
        return plan.best_gas(d, bottom_gas,
                             first_stop_depth if first_stop_depth > 0 else None,
                             exclude)

    if first_stop_depth <= 0:
        # No deco: ascend to the surface, switching to a breathable gas if the
        # bottom mix is hypoxic near the surface.
        _move(tissues, segs, plan, bottom_gas, bottom_depth, 0.0,
              ascent_gas_for, "ascent", plan.surface_p)
        return

    p_first_stop = depth_to_p_amb(first_stop_depth, plan.surface_p, plan.msw_per_bar)

    # ---- ascend from bottom to first stop ----
    _move(tissues, segs, plan, bottom_gas, bottom_depth, first_stop_depth,
          ascent_gas_for, "ascent", p_first_stop, first_stop_depth)

    # ---- iterate stops ----
    # Is this a decompression dive at all? The GF-LOW ceiling sets where the
    # first stop would be, but what decides whether the diver may simply
    # surface is the GF-HIGH ceiling — so that is the test, and it is the same
    # question GFDECO asks with "leading compartment enters the decompression
    # zone". A dive that can surface directly gets no stops, pass-through or
    # otherwise: 18 m for 30 min on air has a 5 m GF-low ceiling and a 0 m
    # GF-high one, and it is an NDL dive.
    has_obligation = ceiling_depth(tissues, plan.gf_high, plan.surface_p,
                                   plan.msw_per_bar) > 1e-9
    current_depth = first_stop_depth
    while current_depth > 0:
        next_depth = max(0.0, current_depth - plan.stop_interval)
        if next_depth < plan.last_stop_depth:
            # below the last-stop depth there are no further stops
            next_depth = (0.0 if current_depth <= plan.last_stop_depth + 1e-9
                          else plan.last_stop_depth)
        p_next = depth_to_p_amb(next_depth, plan.surface_p, plan.msw_per_bar)
        gf_at_next = gf_at(p_next, plan.gf_low, plan.gf_high,
                           p_first_stop, plan.surface_p)
        gas_here = ascent_gas_for(current_depth)
        p_here = depth_to_p_amb(current_depth, plan.surface_p, plan.msw_per_bar)

        # gfdeco.f's DECOMPRESSION_STOP, in his order — which is not the same
        # as holding to the obligation and rounding afterwards:
        #
        #   Round_Up_Operation = ANINT(Run_Time/mst + 0.5) * mst
        #   Segment_Time       = Round_Up_Operation - Run_Time    ! the pad
        #   700 <apply Segment_Time>; IF ceiling > next stop THEN
        #      Segment_Time = mst; GOTO 700                       ! +1 grid step
        #
        # So a stop is the pad onto the next runtime grid point plus whole
        # increments of `min_stop_time` — never a sub-minute remainder, and
        # never zero, because ANINT(x + 0.5) is the STRICTLY next point. That
        # is where GFDECO's 0.4 / 0.7 / 2.7 minute segments come from.
        #
        # Rounding afterwards instead gets the same answer everywhere except
        # when the obligation lands exactly on the pad, where it spends a whole
        # extra minute the diver does not owe.
        stop_minutes = 0.0
        mst = plan.min_stop_time
        if has_obligation:
            run_arrival = sum(x.duration for x in segs)
            pad = (math.floor(run_arrival / mst + 1e-9) + 1) * mst - run_arrival
            update_tissues(tissues, gas_here, p_here, p_here, pad, plan.p_h2o)
            stop_minutes = pad
        while ceiling(tissues, gf_at_next) > p_next + 1e-6:
            update_tissues(tissues, gas_here, p_here, p_here, mst, plan.p_h2o)
            stop_minutes += mst
            if stop_minutes > 24 * 60:
                raise RuntimeError("Stop exceeded 24h; aborting (bad input?)")
        if stop_minutes > 0:
            segs.append(DiveSegment("stop", current_depth, current_depth,
                                    stop_minutes, gas_here, gf_used=gf_at_next))
            has_obligation = True

        # Ascend to the next stop, switching gas at any MOD crossed on the way up.
        if next_depth < current_depth:
            _move(tissues, segs, plan, bottom_gas, current_depth, next_depth,
                  ascent_gas_for, "ascent", p_first_stop, first_stop_depth)
        current_depth = next_depth


def surface_interval(tissues: Tissues, minutes: float, plan: DivePlan,
                     gas: Gas = AIR) -> Tissues:
    """Off-gas at the surface for `minutes`, returning the new loading.

    The whole of repetitive diving in one function: the second dive is the first
    one's `plan_multilevel(..., start_tissues=...)` after this. No tables, no
    pressure groups — the compartments carry the residual themselves, which is
    what every modern computer does and what makes a "repetitive" dive nothing
    more than a dive that did not start clean.

    Breathed on air by default. Surface oxygen shortens the interval a great
    deal and is worth being able to say, so it is a parameter rather than an
    assumption.
    """
    if minutes < 0:
        raise ValueError(f"surface interval must be >= 0 min (got {minutes:g})")
    out = tissues.copy()
    update_tissues(out, gas, plan.surface_p, plan.surface_p, minutes,
                   plan.p_h2o)
    return out


def tissues_after(segments: Iterable[DiveSegment], plan: DivePlan,
                  start_tissues: Tissues | None = None) -> Tissues:
    """Replay `segments` through the compartments and return the loading.

    The planner returns only the state at the *end* of a dive, but the tissue
    state part-way through is what a bailout or a repeat dive starts from. This
    walks the segments the planner already produced, so it is the same Schreiner
    step applied to the same profile rather than a second model.
    """
    tissues = (start_tissues.copy() if start_tissues
               else Tissues.at_surface(plan.surface_p, AIR, plan.p_h2o))
    for s in segments:
        update_tissues(
            tissues, s.gas,
            depth_to_p_amb(s.depth_start, plan.surface_p, plan.msw_per_bar),
            depth_to_p_amb(s.depth_end, plan.surface_p, plan.msw_per_bar),
            s.duration, plan.p_h2o)
    return tissues


def bailout_schedule(segments: Sequence[DiveSegment], plan: DivePlan,
                     bottom_gas: Gas, lost: Sequence[Gas],
                     start_tissues: Tissues | None = None
                     ) -> list[DiveSegment] | None:
    """Re-fly the ascent from the end of the bottom phase without `lost`.

    The bottom phase already happened: losing a cylinder at depth does not undo
    the loading it produced, so this keeps the bottom segments and the loading
    they caused, and re-runs only the ascent on what is left. That is what
    separates it from dropping a gas and re-planning — a re-plan would also
    change the descent and the bottom, which is a different (and wrong)
    question.

    Returns the FULL segment list (bottom phase + new ascent), or **None** when
    the scenario cannot be flown: with the bottom gas gone and nothing else
    breathable at that depth there is no schedule to print, and inventing one
    would be worse than saying so. Callers surface that as "not plannable"
    rather than silently skipping it.

    Losing the bottom gas is the case the deco-gas scenarios cannot express, and
    it is the one that decides whether the stage you carry is a bailout or just
    an accelerant.

    `start_tissues` must be what `segments` were planned from: the bottom phase
    is replayed onto it, so on a repetitive dive leaving it out re-flies the
    ascent on a diver who never made dive 1 (DECISIONS.md #35).
    """
    remaining = [g for g in (bottom_gas, *plan.travel_gases, *plan.deco_gases)
                 if g not in lost]
    if not remaining:
        return None
    bottom_end = _bottom_phase_end(segments)
    if not bottom_end:
        return None
    depth = segments[bottom_end - 1].depth_end
    # Breathable *here*, right now: ppO2 between the hypoxia floor and the deco
    # ceiling. Nothing breathable at the bottom depth is a real outcome, not an
    # error — it is what "you cannot bail out from here on this stack" means.
    if not any(plan._usable(g, depth, plan.ppo2_deco) for g in remaining):
        return None
    segs = list(segments[:bottom_end])
    tissues = tissues_after(segs, plan, start_tissues)
    _ascend(tissues, segs, plan, bottom_gas, depth, exclude=lost)
    return segs


# -----------------------------------------------------------------------------
# Convenience: NDL (no-decompression limit) at a given depth on a gas
# -----------------------------------------------------------------------------

def ndl(depth_m: float, gas: Gas = AIR, plan: DivePlan | None = None,
        start_tissues: Tissues | None = None,
        max_min: int = 600) -> int | None:
    """Minutes you can stay at `depth_m` (after instantaneous descent) before
    a stop is required at GF-High. Returns None if > max_min."""
    if plan is None:
        plan = DivePlan()
    base = (start_tissues.copy() if start_tissues
            else Tissues.at_surface(plan.surface_p, AIR, plan.p_h2o))
    p_amb = depth_to_p_amb(depth_m, plan.surface_p, plan.msw_per_bar)
    for minute in range(1, max_min + 1):
        update_tissues(base, gas, p_amb, p_amb, 1.0, plan.p_h2o)
        if ceiling(base, plan.gf_high) > plan.surface_p + 1e-6:
            return minute - 1
    return None


def total_runtime(segments: Iterable[DiveSegment]) -> float:
    return sum(s.duration for s in segments)


# -----------------------------------------------------------------------------
# Printed-schedule notation — ONE definition, used by every renderer
# -----------------------------------------------------------------------------

def runtime_min(minutes: float) -> int:
    """A runtime as a schedule shows it: **truncated** to whole minutes.

    MultiDeco's convention, verified against real exports — the plan prints the
    runtime in parentheses and every row is the floor of the true value
    (1.61 → 1, 41.22 → 41, 42.56 → 42, 43.875 → 43, 50.44 → 50). Truncating
    rather than rounding also fails safe: a stop is never printed as finishing
    earlier than it does.

    Re-exported as ``report.runtime_min``; it lives here so the schedule
    notation has a single home that the dependency-free core can reach.
    """
    return math.floor(minutes + 1e-9)


@dataclass(frozen=True)
class StopLeg:
    """One row of a printed schedule, in the notation every renderer uses.

    The numbers a diver reads, and exactly what each one means:

    ``depth``  the stop depth (msw).
    ``run``    **the runtime at which you LEAVE this depth**, truncated to
               whole minutes. Not when you arrive, and not a stopwatch
               restarted at each stop — the ascent is flown off one runtime
               clock.
    ``leg``    **the time from leaving the row above to leaving this one** —
               so the ascent down-time to the stop plus the hold on it. By
               construction it is the difference of the printed runtimes, which
               is the whole point: the leg column always adds up to the run
               column.
    ``hold``   the exact hold in minutes, for anything that needs the
               underlying number rather than the printed one.

    ``leg`` is the subtle one and the reason this type exists. The planner
    produces whole-minute *holds* with fractional ascents on top, so the
    runtime advances further than the hold does: a 3-minute hold at 3 m moves
    the clock by 3 ⅓. Printing the hold beside the runtime reads as a
    contradiction underwater — "3 minutes" against a clock that advanced 4 —
    and a diver adding the column up surfaces one ascent early per stop.
    MultiDeco prints the leg for the same reason (DECISIONS.md #17).

    ``leg`` is measured from the previous **stop**, and for the first stop from
    leaving the bottom — never from whatever else a particular view happens to
    print. That is what lets the runtime card, the GUI's stop table and the
    contingency cut table show identical numbers for one dive: a gas-switch row
    on the card is an annotation, not a row the clock is measured from.
    """
    depth: float
    leg: int
    run: int
    hold: float
    gas: Gas


def stop_legs(segments: Sequence[DiveSegment]) -> list[StopLeg]:
    """The deco stops of a planned dive as printable rows — see `StopLeg`.

    Renderer-independent by construction: the first leg runs from leaving the
    bottom phase, each later one from the previous stop. Every view of the same
    dive therefore prints the same minutes for the same stop.
    """
    segs = list(segments)
    be = _bottom_phase_end(segs)
    prev = runtime_min(sum(s.duration for s in segs[:be]))
    legs: list[StopLeg] = []
    run = float(sum(s.duration for s in segs[:be]))
    for s in segs[be:]:
        run += s.duration
        if s.kind != "stop" or s.duration <= 0:
            continue
        printed = runtime_min(run)
        legs.append(StopLeg(depth=s.depth_start, leg=printed - prev,
                            run=printed, hold=s.duration, gas=s.gas))
        prev = printed
    return legs


def max_depth(levels: Sequence[Level]) -> float:
    """Deepest level (msw) — the depth rock-bottom gas is reserved for."""
    return max(l.depth for l in levels) if levels else 0.0


def _bottom_phase_end(segments: Sequence[DiveSegment]) -> int:
    """Index just past the last level. Everything before it is the bottom phase
    (descent + levels + the travel legs between them); everything after it is
    the decompression ascent. On a multi-level dive the legs *between* levels
    are ascents too, so a plain kind filter would mistake them for deco."""
    last = -1
    for i, s in enumerate(segments):
        if s.kind == "bottom":
            last = i
    return last + 1


def average_depth(segments: Iterable[DiveSegment]) -> float:
    """Time-weighted mean depth of the bottom phase (on a square profile just
    the max depth)."""
    segs = list(segments)
    total_t = weighted = 0.0
    for s in segs[:_bottom_phase_end(segs)]:
        weighted += (s.depth_start + s.depth_end) / 2.0 * s.duration
        total_t += s.duration
    return weighted / total_t if total_t > 0 else 0.0


def ceiling_violations(segments: Iterable[DiveSegment]) -> list[DiveSegment]:
    """Levels that sat shallower than the decompression ceiling."""
    return [s for s in segments if s.ceiling_m is not None]


@dataclass(frozen=True)
class PpO2Violation:
    """A segment breathed outside the plan's ppO2 window."""
    segment: DiveSegment
    ppo2: float        # worst ppO2 on the segment (bar)
    limit: float       # the bound it broke (bar)
    kind: str          # "high" (over the working ceiling) | "low" (hypoxic)
    depth: float       # depth of the worst point (msw)


def ppo2_violations(segments: Iterable[DiveSegment],
                    plan: DivePlan | None = None) -> list[PpO2Violation]:
    """Segments breathed outside the ppO2 window — hyperoxic past the working
    ceiling or hypoxic below ppo2_min.

    The high ceiling follows the gas, not just the segment kind: a designated
    deco gas is judged against ppo2_deco (1.6) wherever it is breathed — even
    forced onto a shallow bottom-phase level — because switching to a deco mix
    is a deliberate choice of the higher deco ppO2. The bottom/travel gas going
    down or held on a level uses the working ceiling ppo2_bottom (1.4); ascent
    stops use ppo2_deco. Both carry the switch tolerance (so O2 at the 6 m stop,
    ppO2 1.61, is fine).

    The planner never *chooses* an out-of-window gas, but it faithfully plans
    what it is given (air deeper than its MOD, a hypoxic mix with no travel gas,
    a level that names a gas over its MOD) and that must never pass silently.
    Segments are constant-gas and constant-rate, so the worst ppO2 sits at an
    endpoint."""
    if plan is None:
        plan = DivePlan()
    out: list[PpO2Violation] = []
    for s in segments:
        if s.gas in plan.deco_gases:
            hi = plan.ppo2_deco               # deco gas: 1.6 wherever breathed
        elif s.kind in ("descent", "bottom"):
            hi = plan.ppo2_bottom             # working ceiling for the bottom gas
        else:
            hi = plan.ppo2_deco               # ascent stops
        hi_limit = hi + plan.ppo2_switch_tol
        d_deep = max(s.depth_start, s.depth_end)
        d_shallow = min(s.depth_start, s.depth_end)
        po2_deep = s.gas.ppo2(d_deep, plan.surface_p, plan.msw_per_bar)
        po2_shallow = s.gas.ppo2(d_shallow, plan.surface_p, plan.msw_per_bar)
        if po2_deep > hi_limit + 1e-6:
            out.append(PpO2Violation(s, po2_deep, hi_limit, "high", d_deep))
        if po2_shallow < plan.ppo2_min - 1e-6:
            out.append(PpO2Violation(s, po2_shallow, plan.ppo2_min, "low",
                                     d_shallow))
    return out


def worst_ppo2_violations(segments: Iterable[DiveSegment],
                          plan: DivePlan | None = None) -> list[PpO2Violation]:
    """`ppo2_violations` reduced to the single worst offence per (gas, kind) —
    what a warning banner should show (air below its MOD flags the descent AND
    the bottom; one line with the deepest ppO2 says everything)."""
    worst: dict = {}
    for v in ppo2_violations(segments, plan):
        # Keyed by the frozen Gas VALUE, never its rounded repr: EAN20.6 and
        # EAN21.4 both print "EAN21", and collapsing them would attribute one
        # mix's ppO2 to the other's label on the banner (DECISIONS.md #8).
        key = (v.segment.gas, v.kind)
        cur = worst.get(key)
        if (cur is None or (v.kind == "high" and v.ppo2 > cur.ppo2)
                or (v.kind == "low" and v.ppo2 < cur.ppo2)):
            worst[key] = v
    return list(worst.values())


# -----------------------------------------------------------------------------
# Ceiling profile and TTS
# -----------------------------------------------------------------------------

def ceiling_profile(segments: Sequence[DiveSegment],
                    plan: DivePlan | None = None,
                    start_tissues: Tissues | None = None,
                    step: float = 0.5) -> list[tuple[float, float]]:
    """(runtime_min, ceiling_m) samples along a planned dive, for plotting.

    Re-walks `segments` with the same tissue math as the planner (Schreiner is
    exact on constant-rate legs, so subdividing only adds sampling density) and
    uses its GF convention: GF-Low through the bottom phase, then interpolated
    towards GF-High at the surface, anchored on the first stop derived exactly
    as plan_multilevel derives it — so the curve agrees with the schedule it is
    drawn under. On a no-deco dive the anchor is the surface, gf_at returns
    GF-High everywhere, and the ceiling stays at 0."""
    if plan is None:
        plan = DivePlan()
    segs = list(segments)
    tissues = (start_tissues.copy() if start_tissues
               else Tissues.at_surface(plan.surface_p, AIR, plan.p_h2o))
    bottom_end = _bottom_phase_end(segs)
    p_first_stop: float | None = None       # unknown until the deco ascent
    out = [(0.0, ceiling_depth(tissues, plan.gf_low,
                               plan.surface_p, plan.msw_per_bar))]
    run = 0.0
    for i, s in enumerate(segs):
        if i == bottom_end:
            first = _round_up_to_stop(
                ceiling_depth(tissues, plan.gf_low,
                              plan.surface_p, plan.msw_per_bar),
                plan.stop_interval)
            if first > 0:
                first = max(first, plan.last_stop_depth)
            p_first_stop = (depth_to_p_amb(first, plan.surface_p,
                                           plan.msw_per_bar)
                            if first > 0 else plan.surface_p)
        if s.duration <= 0:
            continue
        p_a = depth_to_p_amb(s.depth_start, plan.surface_p, plan.msw_per_bar)
        p_b = depth_to_p_amb(s.depth_end, plan.surface_p, plan.msw_per_bar)
        n = max(1, math.ceil(s.duration / step - 1e-9))
        for k in range(1, n + 1):
            p0 = p_a + (p_b - p_a) * (k - 1) / n
            p1 = p_a + (p_b - p_a) * k / n
            update_tissues(tissues, s.gas, p0, p1, s.duration / n,
                           plan.p_h2o)
            gf = (plan.gf_low if p_first_stop is None
                  else gf_at(p1, plan.gf_low, plan.gf_high,
                             p_first_stop, plan.surface_p))
            out.append((run + s.duration * k / n,
                        ceiling_depth(tissues, gf,
                                      plan.surface_p, plan.msw_per_bar)))
        run += s.duration
    return out


def time_to_surface(segments: Iterable[DiveSegment]) -> float:
    """TTS — minutes from leaving the bottom to surfacing (ascent + stop time).

    Only the final ascent counts: travel between levels is bottom time, not TTS.
    """
    segs = list(segments)
    return sum(s.duration for s in segs[_bottom_phase_end(segs):]
               if s.kind in ("ascent", "stop"))


# -----------------------------------------------------------------------------
# Gas management: consumption and "rock bottom" (minimum) gas
# -----------------------------------------------------------------------------

#: Emergency SAC when none is given: twice the working SAC, the rule of thumb
#: minimum-gas calculations have always used. It is a *fallback*, not the input
#: — the emergency rate is an absolute L/min figure everywhere it is set
#: (DECISIONS.md #28), so nothing downstream multiplies anything.
EMERGENCY_SAC_FACTOR = 2.0

#: How the turn pressure is worked out. Both rules answer "at what pressure do
#: I turn the dive", and both leave the same shape of reserve at the end — the
#: difference is what sizes it (`report.GasReport.turn_pressure_bar`):
#:
#: * ``rock-bottom`` — split the gas *above* the computed minimum-gas reserve in
#:   half. The reserve on surfacing is exactly rock bottom, so it follows the
#:   dive: a deeper or longer profile turns you earlier.
#: * ``thirds`` — the cave rule: a third in, a third out, a third untouched, so
#:   the turn is at ⅔ of the fill whatever the profile. Simple enough to do on
#:   a wrist slate, and independent of any model — which is the point of it.
TURN_RULES = ("rock-bottom", "thirds")


@dataclass
class GasPlan:
    """Consumption inputs. SAC = surface air consumption in litres/min at 1 bar.

    Two rates, both absolute: `sac` is what the diver breathes on the planned
    dive, `sac_emergency` what the whole team breathes once something has gone
    wrong. `emergency` is whether the emergency accounting is asked for at all
    — see the flag's own comment."""
    sac: float                            # normal / working SAC
    #: Stressed consumption for the emergency ascent, in L/min at the surface.
    #: 0 = derive it from `sac` (× `EMERGENCY_SAC_FACTOR`), the same "0 means
    #: follow the other field" convention as `sac_deco`; `__post_init__`
    #: resolves it, so readers always see a real rate.
    sac_emergency: float = 0.0
    problem_minutes: float = 1.0          # time solving the problem at max depth
    divers: int = 1                       # divers sharing the supply in an
                                          # emergency (2 = buddy out of gas,
                                          # shared to the surface — DECISIONS #28)
    # Separate SAC for gas breathed off a designated deco cylinder — hanging on
    # a stop is not working the bottom, and MultiDeco/Shearwater plan the two
    # rates apart. None = one rate for the whole dive (see DECISIONS.md #16).
    # It splits the *planned* dive only: the emergency has one rate for
    # everything, because a stressed diver does not have a deco SAC.
    sac_deco: float | None = None
    #: Is the emergency reserve part of this plan? False drops it from the
    #: accounting and from every view — no reserve, no rock bottom, no (emrg)
    #: column — so a card carries the baseline numbers and nothing else. The
    #: toggle is honoured by `report.gas_report`, which then never computes it;
    #: the helpers below always answer when asked directly (DECISIONS.md #28).
    emergency: bool = True
    #: Print a turn pressure alongside the reserve? A one-number "turn here" is
    #: the most-used figure on a slate for some teams and noise for others (a
    #: deco dive turns on runtime, not on gas), so it is its own switch inside
    #: the emergency block rather than something to mentally filter out.
    turn_pressure: bool = True
    #: Which rule sizes it — one of `TURN_RULES`.
    turn_rule: str = "rock-bottom"

    def __post_init__(self) -> None:
        if self.sac <= 0:
            raise ValueError(f"SAC must be > 0 L/min (got {self.sac:g})")
        if self.sac_deco is not None and self.sac_deco <= 0:
            raise ValueError(
                f"deco SAC must be > 0 L/min when set (got {self.sac_deco:g})")
        if self.sac_emergency < 0:
            raise ValueError(
                f"emergency SAC must be >= 0 L/min "
                f"(got {self.sac_emergency:g})")
        if self.sac_emergency == 0:
            self.sac_emergency = self.sac * EMERGENCY_SAC_FACTOR
        if self.problem_minutes < 0:
            raise ValueError(
                f"problem_minutes must be >= 0 (got {self.problem_minutes:g})")
        if self.divers < 1:
            raise ValueError(f"divers must be >= 1 (got {self.divers})")
        if self.turn_rule not in TURN_RULES:
            raise ValueError(
                f"unknown turn rule {self.turn_rule!r} — expected one of "
                f"{', '.join(TURN_RULES)}")

    def sac_for(self, gas: Gas, deco_gases: Sequence[Gas] = ()) -> float:
        """The consumption rate to bill `gas` at: `sac_deco` when `gas` is one
        of the dive's designated deco mixes and a deco SAC is set, else `sac`.

        Membership is by the frozen `Gas` value, so it follows the *role* the
        mix was given in the plan — a mix carried as both bottom and deco gas
        is billed at the deco rate wherever it is breathed, which is the same
        simplification MultiDeco makes."""
        if self.sac_deco is not None and gas in tuple(deco_gases):
            return self.sac_deco
        return self.sac


def segment_gas_liters(segments: Iterable[DiveSegment], sac: float,
                       surface_p: float = P_ATM, msw_per_bar: float = MSW_PER_BAR,
                       kinds: tuple[str, ...] | None = None) -> float:
    """Litres breathed across `segments` at `sac`, using each segment's average
    depth. `kinds` optionally restricts which segment kinds are counted."""
    total = 0.0
    for s in segments:
        if kinds is not None and s.kind not in kinds:
            continue
        avg_depth = (s.depth_start + s.depth_end) / 2.0
        ata = depth_to_p_amb(avg_depth, surface_p, msw_per_bar)
        total += sac * ata * s.duration
    return total


def levels_of(segments: Sequence[DiveSegment]) -> list[Level]:
    """The bottom phase back as `Level`s — depth + cumulative end runtime.

    A planned dive carries its own profile: every ``bottom`` segment is one
    level, and the runtime at its end is the elapsed time up to and including
    it. Used to re-plan the dive as if it had ended at an earlier level
    (`emergency_gas_liters`)."""
    levels: list[Level] = []
    run = 0.0
    for s in segments[:_bottom_phase_end(segments)]:
        run += s.duration
        if s.kind == "bottom":
            levels.append(Level(s.depth_end, run))
    return levels


def reserve_candidates(segments: Sequence[DiveSegment], plan: DivePlan,
                       bottom_gas: Gas | None = None
                       ) -> list[list[DiveSegment]]:
    """The candidate "worst moment" profiles a reserve is the maximum over —
    one per level end, each the dive re-planned as if it had ended there.

    Split out of `emergency_gas_liters` because the candidates depend only on
    the profile and the plan, **never on the gas being costed**. Computed
    inside that function they were re-derived once per cylinder, so a
    three-level dive with three mixes re-planned the same two truncated dives
    six times over — about three quarters of the cost of a whole
    `report.PlanResult`. `report.gas_report` now builds them once and passes
    them to every gas.

    A square dive has exactly one candidate — the dive itself — and never
    re-plans anything.

    `bottom_gas` is the mix the truncated dives are re-flown on. Left None it
    is taken from the deepest bottom-phase segment, which is what the gas
    actually breathed down there is; callers that know the declared bottom gas
    (`report.gas_report` does) should pass it rather than have it inferred.
    """
    segs = list(segments)
    levels = levels_of(segs)
    if len(levels) <= 1:
        return [segs]
    if bottom_gas is None:
        bottom_gas = max(segs[:_bottom_phase_end(segs)],
                         key=lambda s: max(s.depth_start, s.depth_end)).gas
    # Re-planning the truncated dive is exact: levels are contiguous, so
    # cutting the profile short cannot change the tissue history before the cut.
    return [segs if k == len(levels)
            else plan_multilevel(levels[:k], bottom_gas, plan)[0]
            for k in range(1, len(levels) + 1)]


def emergency_gas_liters(segments: Sequence[DiveSegment], gas: Gas,
                         gas_plan: GasPlan, plan: DivePlan, *,
                         candidates: Sequence[Sequence[DiveSegment]] | None
                         = None) -> float:
    """Litres of `gas` that must be held in reserve ("rock bottom" logic) for a
    problem striking at **the worst moment of the dive** — evaluated at the end
    of every level, not only the last one, and the largest reserve returned.

    On a square dive there is one candidate and this is the end of the bottom.
    On a deep-first multi-level profile the worst moment is the end of the deep
    level: tissue loading and the deco obligation are greatest there, and the
    ascent is longest. Each candidate is costed by re-planning the dive as if
    it had ended at that level (`levels_of` + `plan_multilevel`), which gives
    the true tissue state at that moment rather than an estimate of it.

    The environment and the deco stack come from `plan`, like
    `report.gas_report` — a reserve billed at the wrong water or without the
    deco stack is a wrong safety number, not a rounding difference.

    Only the emergency reserve is counted, not the gas already breathed on the
    way down (that is the normal-SAC `need`, reported separately). From the
    worst moment the diver spends `problem_minutes` at max depth, then follows
    the **real planned ascent + deco** — up to the next gas switch on that gas,
    or, with no switch, all the way to the surface including every deco stop —
    all at `gas_plan.sac_emergency`, one stressed rate for every mix (the deco
    SAC splits the *planned* dive, not the emergency). The problem minutes are
    billed to the gas breathed at the deepest point (the bottom gas).

    With `divers > 1` the team shares the supply (a buddy out of gas) **for the
    whole ascent, deco stages included**: every litre on the way up is doubled,
    because the diver who lost their gas has no stage of their own to switch to
    — two divers hang on one 50 % cylinder. Until 2026-08 the sharing stopped
    at the first gas switch and the stages were billed once, which is only true
    if the out-of-gas diver still has their own deco bottle (DECISIONS.md #28).

    Until 2026-08 this was taken from the *last* level only and documented as
    an approximation that "can understate the true worst case". It understated
    it by 48 % on a 45 m → 18 m profile — 14 bar of minimum gas where the deep
    level needs 27 — which is not a rounding difference on the one number whose
    whole job is to be the pessimistic one (DECISIONS.md #7).

    `candidates` is the list `reserve_candidates` returns, for a caller costing
    several gases against one profile; None recomputes it. It is a keyword and
    it is optional because the candidates are an optimisation, never an input:
    the answer for a given gas must not depend on who else was asked.
    """
    cands = (reserve_candidates(segments, plan) if candidates is None
             else candidates)
    return max(_reserve_at(c, gas, gas_plan, plan) for c in cands)


def _reserve_at(segs: Sequence[DiveSegment], gas: Gas, gas_plan: GasPlan,
                plan: DivePlan) -> float:
    """The reserve for a problem at the end of THIS dive's bottom phase — one
    candidate moment. `emergency_gas_liters` picks the worst of them."""
    be = _bottom_phase_end(segs)
    surface_p, msw_per_bar = plan.surface_p, plan.msw_per_bar
    # One stressed rate for every mix, shared by the whole team all the way up.
    sac_e = gas_plan.sac_emergency * gas_plan.divers
    total = segment_gas_liters([s for s in segs[be:] if s.gas == gas],
                               sac_e, surface_p, msw_per_bar)
    if segs[:be]:
        # The gas the problem is billed to is the one being BREATHED at the
        # deepest point, which is not necessarily the declared bottom gas — a
        # bottom mix over its ppO2 ceiling down there is planned on a travel
        # mix, and the reserve has to follow the regulator, not the label. So
        # this is inferred on purpose rather than taken as a parameter, unlike
        # `reserve_candidates`' re-planning gas. The descent/bottom tie at the
        # same depth is harmless: `plan_multilevel` chooses both with the same
        # `descent_gas()` call, so they are always the same mix.
        deepest = max(segs[:be],
                      key=lambda s: max(s.depth_start, s.depth_end))
        if deepest.gas == gas:
            d_max = max(deepest.depth_start, deepest.depth_end)
            # sac_e already carries `divers` — do not scale it again here.
            total += (sac_e * gas_plan.problem_minutes
                      * depth_to_p_amb(d_max, surface_p, msw_per_bar))
    return total


def rock_bottom_liters(segments: Sequence[DiveSegment], bottom_gas: Gas,
                       gas_plan: GasPlan, plan: DivePlan, *,
                       candidates: Sequence[Sequence[DiveSegment]] | None
                       = None) -> float:
    """Minimum gas ("rock bottom") in litres of the back/bottom gas: the reserve
    needed to survive a problem at the worst moment (the end of the worst level,
    see `emergency_gas_liters`)
    and follow the **real ascent + deco** on the bottom gas — up to the next gas
    switch if there is one, otherwise all the way to the surface through every
    deco stop — at `gas_plan.sac_emergency`, multiplied by `divers`.

    This is exactly the bottom gas's `emergency_gas_liters`, so the rock-bottom
    reserve and the emergency column always agree. It deliberately follows the
    planned profile only until the first deco-gas switch (standard minimum-gas
    practice — the diver is on the deco gas after that), so the figure stays a
    realistic back-gas reserve rather than the whole schedule billed to back
    gas.

    `candidates` is passed straight through — see `emergency_gas_liters`."""
    return emergency_gas_liters(segments, bottom_gas, gas_plan, plan,
                                candidates=candidates)
