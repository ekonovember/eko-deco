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

# Bühlmann uses 0.0627 bar for water-vapor pressure in the alveoli (37 °C).
P_H2O = 0.0627
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
        if self.fN2 < -1e-9:
            raise ValueError("fO2 + fHe > 1")

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
    def at_surface(cls, surface_p: float = P_ATM, gas: Gas = AIR) -> Tissues:
        """Fully saturated at surface on the given gas (default air)."""
        p_insp_n2 = (surface_p - P_H2O) * gas.fN2
        p_insp_he = (surface_p - P_H2O) * gas.fHe
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
                   t_min: float) -> None:
    """Update all 16 compartments over a segment of constant ascent/descent
    rate (or flat, if p_amb_start == p_amb_end). In-place."""
    if t_min <= 0:
        return
    rate_amb = (p_amb_end - p_amb_start) / t_min
    p_insp_n2_0 = (p_amb_start - P_H2O) * gas.fN2
    p_insp_he_0 = (p_amb_start - P_H2O) * gas.fHe
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
                     "surface_p", "msw_per_bar"):
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

    def _usable(self, gas: Gas, depth: float, ppo2_ceiling: float) -> bool:
        pp = gas.ppo2(depth, self.surface_p, self.msw_per_bar)
        return self.ppo2_min - 1e-9 <= pp <= ppo2_ceiling + 1e-9

    def switch_depth(self, gas: Gas) -> float:
        """Ascent switch depth for `gas`: its MOD at ppo2_deco snapped to the
        nearest stop-interval multiple (subject to ppo2_switch_tol)."""
        mod = gas.mod(self.ppo2_deco, self.surface_p, self.msw_per_bar)
        if mod <= 0:
            return mod
        snapped = round(mod / self.stop_interval) * self.stop_interval
        if (snapped > mod and gas.ppo2(snapped, self.surface_p, self.msw_per_bar)
                > self.ppo2_deco + self.ppo2_switch_tol + 1e-9):
            snapped = math.floor(mod / self.stop_interval) * self.stop_interval
        return snapped

    def best_gas(self, depth: float, bottom_gas: Gas) -> Gas:
        """Richest breathable gas for the ASCENT at `depth` (bottom + travel +
        deco gases): floored at ppo2_min, switched in at switch_depth()."""
        candidates = [bottom_gas, *self.travel_gases, *self.deco_gases]
        usable = [g for g in candidates
                  if depth <= self.switch_depth(g) + 1e-9
                  and g.ppo2(depth, self.surface_p, self.msw_per_bar)
                  >= self.ppo2_min - 1e-9]
        if not usable:
            return bottom_gas
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
    if depth <= 0:
        return 0.0
    return math.ceil(depth / interval - 1e-9) * interval


def _gas_switch_depths(plan: DivePlan, bottom_gas: Gas) -> list[float]:
    """Depths (msw) where the breathable-gas choice can change: each gas's
    (stop-rounded) ascent switch depth, its raw MOD at the descent ppO2
    ceiling, and each hypoxic mix's minimum breathable depth."""
    depths = set()
    for g in (bottom_gas, *plan.travel_gases, *plan.deco_gases):
        mod_descent = g.mod(plan.ppo2_bottom, plan.surface_p, plan.msw_per_bar)
        if mod_descent > 0:
            depths.add(round(mod_descent, 6))
        switch = plan.switch_depth(g)
        if switch > 0:
            depths.add(round(switch, 6))
        dmin = g.min_depth(plan.ppo2_min, plan.surface_p, plan.msw_per_bar)
        if dmin > 0:
            depths.add(round(dmin, 6))
    return sorted(depths)


def _move(tissues: Tissues, segs: list[DiveSegment], plan: DivePlan,
          bottom_gas: Gas, from_depth: float, to_depth: float, gas_for,
          kind: str, p_first_stop: float | None) -> None:
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
    breaks = [d for d in _gas_switch_depths(plan, bottom_gas)
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
        update_tissues(tissues, gas, p_a, p_c, t)
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
               else Tissues.at_surface(plan.surface_p, AIR))
    segs: list[DiveSegment] = []
    def descent_gas_for(d: float) -> Gas:
        return plan.descent_gas(d, bottom_gas)

    def ascent_gas_for(d: float) -> Gas:
        return plan.best_gas(d, bottom_gas)

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
        update_tissues(tissues, gas_here, p_level, p_level, t_flat)
        segs.append(DiveSegment("bottom", depth, depth, t_flat, gas_here,
                                ceiling_m=violated))
        run = level.runtime

    bottom_depth = depth

    # ---- find first stop using GF-Low ----
    ceil_low = ceiling_depth(tissues, plan.gf_low, plan.surface_p, plan.msw_per_bar)
    first_stop_depth = _round_up_to_stop(ceil_low, plan.stop_interval)
    if first_stop_depth > 0:
        first_stop_depth = max(first_stop_depth, plan.last_stop_depth)
    if first_stop_depth <= 0:
        # No deco: ascend to the surface, switching to a breathable gas if the
        # bottom mix is hypoxic near the surface.
        _move(tissues, segs, plan, bottom_gas, bottom_depth, 0.0,
              ascent_gas_for, "ascent", plan.surface_p)
        return segs, tissues

    p_first_stop = depth_to_p_amb(first_stop_depth, plan.surface_p, plan.msw_per_bar)

    # ---- ascend from bottom to first stop ----
    _move(tissues, segs, plan, bottom_gas, bottom_depth, first_stop_depth,
          ascent_gas_for, "ascent", p_first_stop)

    # ---- iterate stops ----
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
        gas_here = plan.best_gas(current_depth, bottom_gas)
        p_here = depth_to_p_amb(current_depth, plan.surface_p, plan.msw_per_bar)

        # Wait at this stop in 1-minute increments until ceiling allows next stop.
        stop_minutes = 0.0
        while ceiling(tissues, gf_at_next) > p_next + 1e-6:
            update_tissues(tissues, gas_here, p_here, p_here, 1.0)
            stop_minutes += 1.0
            if stop_minutes > 24 * 60:
                raise RuntimeError("Stop exceeded 24h; aborting (bad input?)")
        if stop_minutes > 0:
            segs.append(DiveSegment("stop", current_depth, current_depth,
                                    stop_minutes, gas_here, gf_used=gf_at_next))

        # Ascend to the next stop, switching gas at any MOD crossed on the way up.
        if next_depth < current_depth:
            _move(tissues, segs, plan, bottom_gas, current_depth, next_depth,
                  ascent_gas_for, "ascent", p_first_stop)
        current_depth = next_depth

    return segs, tissues


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
            else Tissues.at_surface(plan.surface_p, AIR))
    p_amb = depth_to_p_amb(depth_m, plan.surface_p, plan.msw_per_bar)
    for minute in range(1, max_min + 1):
        update_tissues(base, gas, p_amb, p_amb, 1.0)
        if ceiling(base, plan.gf_high) > plan.surface_p + 1e-6:
            return minute - 1
    return None


def total_runtime(segments: Iterable[DiveSegment]) -> float:
    return sum(s.duration for s in segments)


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
        key = (repr(v.segment.gas), v.kind)
        cur = worst.get(key)
        if (cur is None or (v.kind == "high" and v.ppo2 > cur.ppo2)
                or (v.kind == "low" and v.ppo2 < cur.ppo2)):
            worst[key] = v
    return list(worst.values())


# -----------------------------------------------------------------------------
# Oxygen toxicity: CNS% (NOAA single-exposure clock) and OTU (Repex)
# -----------------------------------------------------------------------------

# NOAA single-exposure oxygen limits (ppO2 bar -> minutes), NOAA Diving Manual.
# Stored as (ppO2, CNS fraction per minute); linear between points, zero below
# 0.5 bar. Above 1.6 bar the last slope extrapolates — there is no published
# limit up there, only a steeply growing hazard.
_CNS_RATE = (
    (0.5, 0.0),
    (0.6, 1.0 / 720.0), (0.7, 1.0 / 570.0), (0.8, 1.0 / 450.0),
    (0.9, 1.0 / 360.0), (1.0, 1.0 / 300.0), (1.1, 1.0 / 240.0),
    (1.2, 1.0 / 210.0), (1.3, 1.0 / 180.0), (1.4, 1.0 / 150.0),
    (1.5, 1.0 / 120.0), (1.6, 1.0 / 45.0),
)


# Repex / Hamilton pulmonary oxygen dose (OTU): rate = ((ppO2 - THRESH)/THRESH)
# ^ EXP per minute above the threshold. Named rather than inlined so the
# constant registry in tests/planner_diff.py can enumerate them — a model
# constant that only exists as a literal cannot be compared against a
# reference planner.
OTU_THRESHOLD_PPO2 = 0.5
OTU_EXPONENT = 0.83


def _cns_rate(po2: float) -> float:
    """CNS clock fraction per minute at a ppO2 (bar)."""
    if po2 <= _CNS_RATE[0][0]:
        return 0.0
    for (p0, r0), (p1, r1) in pairwise(_CNS_RATE):
        if po2 <= p1:
            return r0 + (r1 - r0) * (po2 - p0) / (p1 - p0)
    (p0, r0), (p1, r1) = _CNS_RATE[-2], _CNS_RATE[-1]
    return r1 + (r1 - r0) * (po2 - p1) / (p1 - p0)


def cns_otu(segments: Iterable[DiveSegment], surface_p: float = P_ATM,
            msw_per_bar: float = MSW_PER_BAR,
            step: float = 0.5) -> tuple[float, float]:
    """(CNS %, OTU) accumulated over the planned segments.

    CNS integrates the NOAA single-exposure clock (`_CNS_RATE`); OTU uses the
    Repex / Hamilton pulmonary dose (`OTU_THRESHOLD_PPO2`, `OTU_EXPONENT`),
    rate = ((ppO2 - 0.5) / 0.5)^0.83 per minute for ppO2 > 0.5 bar.
    Depth-changing segments are integrated in sub-steps of `step` minutes at
    the midpoint ppO2."""
    cns = otu = 0.0
    for s in segments:
        if s.duration <= 0:
            continue
        n = max(1, math.ceil(s.duration / step - 1e-9))
        dt = s.duration / n
        for k in range(n):
            frac = (k + 0.5) / n
            depth = s.depth_start + (s.depth_end - s.depth_start) * frac
            po2 = s.gas.ppo2(depth, surface_p, msw_per_bar)
            cns += _cns_rate(po2) * dt
            if po2 > OTU_THRESHOLD_PPO2:
                otu += dt * ((po2 - OTU_THRESHOLD_PPO2)
                             / OTU_THRESHOLD_PPO2) ** OTU_EXPONENT
    return cns * 100.0, otu


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
               else Tissues.at_surface(plan.surface_p, AIR))
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
            update_tissues(tissues, s.gas, p0, p1, s.duration / n)
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


# Cut-table grid pitch: 3 m matches the stop interval, 3 min keeps the
# round-up penalty small — the diver rounds the gauge UP to the next cell.
CONTINGENCY_TIME_STEP = 3.0    # min per time step
CONTINGENCY_DEPTH_STEP = 3.0   # m per depth step


@dataclass
class ContingencyCell:
    """One cell of a contingency ("cut table") matrix: a square-profile dive at
    `depth` msw leaving the bottom at `bottom_time` min runtime. `segments` is
    None when the variant cannot be planned (e.g. the shortened time is less
    than the descent takes)."""
    depth: float
    bottom_time: float
    segments: list[DiveSegment] | None

    def text(self) -> str:
        """Wetnotes cell text: stops deep→shallow as 'depth:min', then the TTS
        rounded UP ('· N′'); 'no deco' when clean, 'n/a' when unplannable."""
        if self.segments is None:
            return "n/a"
        stops = [f"{s.depth_start:g}:{s.duration:g}" for s in self.segments
                 if s.kind == "stop" and s.duration > 0]
        tts = math.ceil(time_to_surface(self.segments) - 1e-9)
        return f"{' '.join(stops) if stops else 'no deco'} · {tts:g}′"


def contingency_schedules(levels: Sequence[Level], bottom_gas: Gas,
                          plan: DivePlan | None = None, *,
                          time_before: int = 1, time_after: int = 1,
                          depth_before: int = 1, depth_after: int = 1,
                          time_step: float = CONTINGENCY_TIME_STEP,
                          depth_step: float = CONTINGENCY_DEPTH_STEP
                          ) -> list[list[ContingencyCell]]:
    """Backup "cut table" matrix for a bottom-timer (gauge) diver: schedules for
    the planned dive and its neighbours on a fixed grid.

    The profile is flattened to a square dive at max depth x total bottom time
    — deliberately more conservative than the real multilevel schedule, because
    max depth and dive time are what a gauge shows (average depth is not live
    on a bottom timer). Rows are bottom-time variants (`time_before` steps
    shorter … planned … `time_after` steps longer), columns depth variants
    (`depth_before` shallower … `depth_after` deeper), both on the fixed
    `time_step` × `depth_step` pitch (3 min × 3 m: round the gauge UP to the
    next row/column). Zero counts disable a direction; variants at or below
    zero are dropped. The full gas stack stays available — the table covers
    computer failure, not gas loss.

    Unlike the lost-gas scenarios (which drop unplannable variants), the grid
    stays rectangular: an unplannable cell keeps its place with segments=None,
    so renderers can align columns across rows. Tissues start fresh per cell.
    """
    d0 = max_depth(levels)
    if plan is None:
        plan = DivePlan()
    t0 = levels[-1].runtime
    times = [t0 + i * time_step for i in range(-int(time_before),
                                               int(time_after) + 1) if
             t0 + i * time_step > 0]
    depths = [d0 + j * depth_step for j in range(-int(depth_before),
                                                 int(depth_after) + 1) if
              d0 + j * depth_step > 0]
    grid: list[list[ContingencyCell]] = []
    for t in times:
        row = []
        for d in depths:
            try:
                segs, _ = plan_dive(d, t, bottom_gas, plan)
            except (ValueError, RuntimeError):
                segs = None
            row.append(ContingencyCell(d, t, segs))
        grid.append(row)
    return grid


# -----------------------------------------------------------------------------
# Gas management: consumption, TTS and "rock bottom" (minimum) gas
# -----------------------------------------------------------------------------

@dataclass
class GasPlan:
    """Consumption inputs. SAC = surface air consumption in litres/min at 1 bar."""
    sac: float                            # normal / working SAC
    sac_multiplier: float = 2.0           # emergency SAC = sac * sac_multiplier
    problem_minutes: float = 1.0          # time solving the problem at max depth
    divers: int = 1                       # divers sharing the supply in an
                                          # emergency (2 = buddy out of gas,
                                          # shared until the first gas switch)
    tank_liters: float | None = None   # total cylinder volume, for bar output
    # Separate SAC for gas breathed off a designated deco cylinder — hanging on
    # a stop is not working the bottom, and MultiDeco/Shearwater plan the two
    # rates apart. None = one rate for the whole dive (see DECISIONS.md #16).
    sac_deco: float | None = None

    def __post_init__(self) -> None:
        if self.sac <= 0:
            raise ValueError(f"SAC must be > 0 L/min (got {self.sac:g})")
        if self.sac_deco is not None and self.sac_deco <= 0:
            raise ValueError(
                f"deco SAC must be > 0 L/min when set (got {self.sac_deco:g})")
        if self.sac_multiplier < 1.0:
            raise ValueError(
                f"emergency SAC multiplier must be >= 1 "
                f"(got {self.sac_multiplier:g})")
        if self.problem_minutes < 0:
            raise ValueError(
                f"problem_minutes must be >= 0 (got {self.problem_minutes:g})")
        if self.divers < 1:
            raise ValueError(f"divers must be >= 1 (got {self.divers})")
        if self.tank_liters is not None and self.tank_liters <= 0:
            raise ValueError(
                f"tank_liters must be > 0 when set (got {self.tank_liters:g})")

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


def emergency_gas_liters(segments: Iterable[DiveSegment], gas: Gas,
                         gas_plan: GasPlan, surface_p: float = P_ATM,
                         msw_per_bar: float = MSW_PER_BAR,
                         deco_gases: Sequence[Gas] = ()) -> float:
    """Litres of `gas` that must be held in reserve ("rock bottom" logic) for a
    problem striking at the worst moment of the dive — the end of the bottom
    phase, where tissue loading and therefore the deco obligation are greatest.

    Only the emergency reserve is counted, not the gas already breathed on the
    way down (that is the normal-SAC `need`, reported separately). From the
    worst moment the diver spends `problem_minutes` at max depth, then follows
    the **real planned ascent + deco** — up to the next gas switch on that gas,
    or, with no switch, all the way to the surface including every deco stop —
    all at the emergency SAC (that gas's `sac_for` × `sac_multiplier`, so a
    deco mix reserves at the deco rate when one is set). The problem minutes
    are billed to the gas breathed at the deepest point (the bottom gas).

    With `divers > 1` the team shares the supply (a buddy out of gas): the
    problem minutes and the ascent up to the first planned gas switch are
    multiplied by `divers`; from the switch on each diver is back on their own
    cylinder, so the rest of the deco is billed once. No switch = shared all
    the way to the surface.

    Known limitation (see DECISIONS.md #7): the emergency ascent
    is taken from the *last* level, so on a deep-first multilevel profile
    (a deep level followed by shallower ones) this mixes two moments and can
    UNDERSTATE the true worst case at the deep level. It is a single-square /
    shallowest-last approximation, not a guaranteed absolute worst case."""
    segs = list(segments)
    be = _bottom_phase_end(segs)
    sac_e = gas_plan.sac_for(gas, deco_gases) * gas_plan.sac_multiplier
    asc = segs[be:]
    total = 0.0
    if asc:
        n_shared = 0                   # ascent prefix before the first switch
        for s in asc:
            if s.gas != asc[0].gas:
                break
            n_shared += 1
        total += segment_gas_liters(
            [s for s in asc[:n_shared] if s.gas == gas],
            sac_e * gas_plan.divers, surface_p, msw_per_bar)
        total += segment_gas_liters(
            [s for s in asc[n_shared:] if s.gas == gas],
            sac_e, surface_p, msw_per_bar)
    if segs[:be]:
        deepest = max(segs[:be],
                      key=lambda s: max(s.depth_start, s.depth_end))
        if deepest.gas == gas:
            d_max = max(deepest.depth_start, deepest.depth_end)
            total += (sac_e * gas_plan.divers * gas_plan.problem_minutes
                      * depth_to_p_amb(d_max, surface_p, msw_per_bar))
    return total


def rock_bottom_liters(segments: Iterable[DiveSegment], bottom_gas: Gas,
                       gas_plan: GasPlan, surface_p: float = P_ATM,
                       msw_per_bar: float = MSW_PER_BAR,
                       deco_gases: Sequence[Gas] = ()) -> float:
    """Minimum gas ("rock bottom") in litres of the back/bottom gas: the reserve
    needed to survive a problem at the worst moment (end of the bottom phase)
    and follow the **real ascent + deco** on the bottom gas — up to the next gas
    switch if there is one, otherwise all the way to the surface through every
    deco stop — at the emergency SAC (`sac * sac_multiplier`), the shared
    portion multiplied by `divers`.

    This is exactly the bottom gas's `emergency_gas_liters`, so the rock-bottom
    reserve and the emergency column always agree. It deliberately follows the
    planned profile only until the first deco-gas switch (standard minimum-gas
    practice — the diver is on the deco gas after that), so the figure stays a
    realistic back-gas reserve rather than the whole schedule billed to back
    gas."""
    return emergency_gas_liters(segments, bottom_gas, gas_plan,
                                surface_p, msw_per_bar, deco_gases)
