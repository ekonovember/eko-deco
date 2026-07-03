"""Ratio Deco (GUE / UTD style) with standard gases. EDUCATIONAL ONLY.

Implements the average-depth "ratio" method as summarised on Wikipedia's
*Ratio decompression* article:

* The ratio of total deco time to bottom time is fixed by depth:
  ~1:1 at 46 m (150 ft), ~2:1 at 67 m (220 ft), linear in between.
* Deco is referenced to **average** depth (defaults to max depth for a square
  profile here).
* Deep stops begin at 80 % of the maximum ambient pressure — i.e. at
  ``0.8 * Dmax - 2`` msw, rounded down to a 3 m increment.
* The total deco time is split in half: the deep half spread equally over the
  stops from the first stop down to 9 m, the shallow half taken at 6 m, then a
  slow ascent to the surface. A minimum acclimatisation stop is kept at the
  50 % gas switch (21 m).

Standard gases follow the GUE standard-gas scheme (bottom mix chosen by depth;
deco on 50 % from 21 m and O2 from 6 m).

This is a coarse mental-math approximation, **not** a validated schedule. Always
cross-check against the Bühlmann planner (``buhlmann.plan_dive``), a dive
computer, and your own training before relying on any number here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from buhlmann import Gas

# GUE standard bottom gases: (max_depth_m, Gas, label). First band that covers
# the depth wins.
STANDARD_BOTTOM_GASES: Tuple[Tuple[float, Gas, str], ...] = (
    (30.0, Gas(0.32), "EAN32"),
    (45.0, Gas(0.30, 0.30), "30/30"),
    (60.0, Gas(0.21, 0.35), "21/35"),
    (75.0, Gas(0.18, 0.45), "18/45"),
    (90.0, Gas(0.15, 0.55), "15/55"),
    (120.0, Gas(0.12, 0.65), "12/65"),
)

# Standard deco gases: (switch_depth_m, Gas, label).
STANDARD_DECO_GASES: Tuple[Tuple[float, Gas, str], ...] = (
    (21.0, Gas(0.50), "EAN50"),
    (6.0, Gas(1.00), "O2"),
)

# Ratio anchors (depth_m, ratio): 1:1 at ~46 m, 2:1 at ~67 m.
_RATIO_LO = (46.0, 1.0)
_RATIO_HI = (67.0, 2.0)


def standard_bottom_gas(depth_m: float) -> Tuple[Gas, str]:
    """The GUE standard bottom mix for a given maximum depth."""
    for max_d, gas, label in STANDARD_BOTTOM_GASES:
        if depth_m <= max_d + 1e-9:
            return gas, label
    return STANDARD_BOTTOM_GASES[-1][1], STANDARD_BOTTOM_GASES[-1][2]


def standard_deco_gases(max_depth_m: float) -> List[Tuple[float, Gas, str]]:
    """Standard deco gases usable on a dive to ``max_depth_m`` (a gas applies
    only if the dive goes deeper than its switch depth)."""
    return [(d, g, l) for (d, g, l) in STANDARD_DECO_GASES if max_depth_m > d - 1e-9]


def standard_dive_gases(max_depth_m: float) -> Tuple[Gas, Tuple[Gas, ...], Tuple[Gas, ...]]:
    """(bottom_gas, travel_gases, deco_gases) for a Bühlmann cross-check. A travel
    gas (EAN32) is added when the standard bottom mix is hypoxic at the surface."""
    bottom, _label = standard_bottom_gas(max_depth_m)
    deco = tuple(g for (_d, g, _l) in standard_deco_gases(max_depth_m))
    travel: Tuple[Gas, ...] = (Gas(0.32),) if bottom.min_depth() > 0 else ()
    return bottom, travel, deco


def ratio_at(avg_depth_m: float) -> float:
    """Deco-to-bottom-time ratio for an average depth (clamped at 0 = min deco)."""
    (d0, r0), (d1, r1) = _RATIO_LO, _RATIO_HI
    return max(0.0, r0 + (avg_depth_m - d0) * (r1 - r0) / (d1 - d0))


def first_stop_depth(max_depth_m: float, stop_interval: float = 3.0) -> float:
    """Deep-stop onset: 80 % of max ambient pressure, rounded down to a stop."""
    raw = 0.8 * max_depth_m - 2.0
    if raw <= 0:
        return 0.0
    return math.floor(raw / stop_interval) * stop_interval


def _deco_gas_label(depth_m: float, bottom_label: str) -> str:
    if depth_m <= 6.0 + 1e-9:
        return "O2"
    if depth_m <= 21.0 + 1e-9:
        return "EAN50"
    return bottom_label


@dataclass
class RatioStop:
    depth_m: float
    minutes: float
    gas: str

    def as_dict(self) -> dict:
        return {"depth_m": round(self.depth_m, 1),
                "minutes": round(self.minutes, 1), "gas": self.gas}


@dataclass
class RatioDecoResult:
    max_depth_m: float
    avg_depth_m: float
    bottom_time_min: float
    ratio: float
    total_deco_min: float
    first_stop_m: float
    bottom_gas: str
    deco_gases: List[str]
    stops: List[RatioStop] = field(default_factory=list)
    min_deco: bool = False

    @property
    def scheduled_deco_min(self) -> float:
        return sum(s.minutes for s in self.stops)

    def as_dict(self) -> dict:
        return {
            "max_depth_m": self.max_depth_m,
            "avg_depth_m": self.avg_depth_m,
            "bottom_time_min": self.bottom_time_min,
            "ratio": round(self.ratio, 2),
            "total_deco_min": round(self.total_deco_min, 1),
            "scheduled_deco_min": round(self.scheduled_deco_min, 1),
            "first_stop_m": self.first_stop_m,
            "bottom_gas": self.bottom_gas,
            "deco_gases": self.deco_gases,
            "min_deco": self.min_deco,
            "stops": [s.as_dict() for s in self.stops],
        }


def ratio_deco(max_depth_m: float, bottom_time_min: float,
               avg_depth_m: Optional[float] = None,
               stop_interval: float = 3.0,
               gas_switch_min: float = 3.0) -> RatioDecoResult:
    """Estimate a Ratio Deco schedule with GUE standard gases. Educational."""
    avg = max_depth_m if avg_depth_m is None else avg_depth_m
    ratio = ratio_at(avg)
    total = bottom_time_min * ratio
    _bottom_gas, bottom_label = standard_bottom_gas(max_depth_m)
    deco_labels = [l for (_d, _g, l) in standard_deco_gases(max_depth_m)]
    first_stop = first_stop_depth(max_depth_m, stop_interval)

    result = RatioDecoResult(
        max_depth_m=max_depth_m, avg_depth_m=avg, bottom_time_min=bottom_time_min,
        ratio=ratio, total_deco_min=total, first_stop_m=first_stop,
        bottom_gas=bottom_label, deco_gases=deco_labels,
    )

    if total <= 1e-9 or first_stop <= 0:
        result.min_deco = True
        return result

    deep_half = total / 2.0
    shallow_half = total / 2.0

    deep_depths: List[float] = []
    d = first_stop
    while d >= 9.0 - 1e-9:
        deep_depths.append(round(d, 6))
        d -= stop_interval

    stops: List[RatioStop] = []
    if deep_depths:
        per = deep_half / len(deep_depths)
        for dd in deep_depths:
            minutes = per
            if abs(dd - 21.0) < 1e-9:          # acclimatise at the 50 % switch
                minutes = max(minutes, gas_switch_min)
            stops.append(RatioStop(dd, minutes, _deco_gas_label(dd, bottom_label)))
    stops.append(RatioStop(6.0, shallow_half, _deco_gas_label(6.0, bottom_label)))

    result.stops = stops
    return result
