"""Oxygen toxicity clocks: CNS % (NOAA single-exposure) and OTU (Repex).

Split out of `deco.buhlmann` because it is a **downstream analysis of a planned
dive, not part of the model**: nothing in the planner calls it, and nothing here
touches a tissue compartment. It reads a segment list and integrates two
published dose curves over it — which is the same shape of job `deco.report`
does, one layer further out.

Standard library only, like everything below `deco.app`.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from itertools import pairwise

from deco.buhlmann import MSW_PER_BAR, P_ATM, DiveSegment

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

