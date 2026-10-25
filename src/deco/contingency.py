"""The bottom-timer contingency matrix — a "cut table" for a failed computer.

Split out of `deco.buhlmann` for the same reason as `deco.toxicity`: it sits
**above** the planner rather than inside it. It calls `plan_dive` once per cell
and formats the results; nothing in the model calls back into it.

The profile is flattened to a square dive at max depth × total bottom time —
deliberately more conservative than the real multilevel schedule, because max
depth and elapsed time are what a gauge shows. Average depth is not live on a
bottom timer.

Standard library only.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from deco.buhlmann import (
    DivePlan,
    DiveSegment,
    Gas,
    Level,
    Tissues,
    max_depth,
    plan_dive,
    stop_legs,
    time_to_surface,
)

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
        rounded UP ('· N′'); 'no deco' when clean, 'n/a' when unplannable.

        'min' is the `StopLeg` leg — ascent to the stop plus the hold — the
        same notation as the runtime card and the GUI's stop table, so a cut
        table and a plan for the same profile never print different numbers.
        That holds for the FIRST stop too: its 'min' is the leg from leaving
        the bottom, ascent included, not the hold — the same number the card
        prints, which is the point of sharing the notation (DECISIONS.md #17).
        TTS is rounded UP, unlike a runtime: it is a budget, not a clock."""
        if self.segments is None:
            return "n/a"
        stops = [f"{leg.depth:g}:{leg.leg:g}" for leg in stop_legs(self.segments)]
        tts = math.ceil(time_to_surface(self.segments) - 1e-9)
        return f"{' '.join(stops) if stops else 'no deco'} · {tts:g}′"


def contingency_schedules(levels: Sequence[Level], bottom_gas: Gas,
                          plan: DivePlan | None = None, *,
                          time_before: int = 1, time_after: int = 1,
                          depth_before: int = 1, depth_after: int = 1,
                          time_step: float = CONTINGENCY_TIME_STEP,
                          depth_step: float = CONTINGENCY_DEPTH_STEP,
                          start_tissues: Tissues | None = None
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
    so renderers can align columns across rows.

    `start_tissues` is the loading the dive begins with, exactly as for
    `plan_multilevel`, and every cell starts from it. On dive 2 of a day it is
    the residual nitrogen dive 1 left behind; leaving it out planned every cell
    on clean tissues, so the cell for the planned dive itself printed dive 1's
    deco — 29′ against the plan's 41′ on 45 m/25 min after a 30 min interval,
    surfacing at SurfGF 94 % on GF-High 70 % (DECISIONS.md #35). None is right
    only for the first dive of a day.
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
                segs, _ = plan_dive(d, t, bottom_gas, plan, start_tissues)
            except (ValueError, RuntimeError):
                segs = None
            row.append(ContingencyCell(d, t, segs))
        grid.append(row)
    return grid

