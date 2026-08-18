"""Shared plan-result and gas-accounting layer for the deco front ends.

Everything user-facing that is *computed* — warning texts, per-cylinder gas
accounting (need / have / emergency / SHORT), rock bottom, the assembled
``PlanResult`` — lives here exactly once, so the CLI and the GUI cannot drift
apart. Front ends stay renderers: they format these values, they do not
re-derive them.

Design rules (see CLAUDE.md):
* stdlib only — this module sits between ``buhlmann`` and the front ends;
* warnings are load-bearing: `PlanResult.warnings` must be surfaced by every
  renderer;
* gases are identified by the frozen ``Gas`` value itself (equality/hash),
  never by its display ``repr`` — two mixes that round to the same label must
  not merge their accounting.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import overload

from deco import buhlmann as b

#: Default cylinder fill pressure (bar) when none is given.
DEFAULT_FILL_BAR = 232.0

#: Baseline consumption (L/min at the surface, SAC/RMV) when the caller names
#: none. Every plan carries gas estimates now — CLI, GUI and agent alike — so
#: there is always a rate; the only question is whether the diver chose it or
#: took this one (DECISIONS.md #28). Shared with `dive_config.default_config`
#: so the two front ends start from the same number.
DEFAULT_SAC = 20.0


#: The printed-schedule notation lives in `buhlmann` so the dependency-free
#: core can reach it too (the contingency cut table renders cells there).
#: Re-exported here because both front ends already reach for it via `report`.
runtime_min = b.runtime_min


def water_name(msw_per_bar: float) -> str:
    """The water-type label for a metres-per-bar constant: ``salt``, ``fresh``
    or ``custom``. Shared so the CLI header and the GUI dropdown agree.

    The tolerance is 0.001 m/bar — six-significant-digit round trips through
    the config and the GUI spinboxes must still read as the preset they came
    from, and a difference that small is far below anything physical."""
    return next((n for n, v in b.WATER_TYPES.items()
                 if abs(v - msw_per_bar) < 1e-3), "custom")


def environment_note(plan: b.DivePlan) -> str | None:
    """One line describing the dive's environment, or None at the defaults.

    The defaults — sea-level salt water — are what MultiDeco, Shearwater and
    GFDECO plan with, so a schedule made at them is comparable with a plan from
    any of those. Changing water type or surface pressure is a real physical
    correction and moves every pressure the plan derives, but it also means the
    schedule will NO LONGER match another planner's for the same dive: the two
    exports in `examples/` print fresh-water pressures yet compute their
    schedules at sea-level salt, so eko-deco's fresh-water plan for that dive
    is ~2 min shorter than MultiDeco's. Saying so is the difference between an
    informed choice and a surprise on the boat.
    """
    if plan.msw_per_bar == b.MSW_PER_BAR and plan.surface_p == b.P_ATM:
        return None
    alt = b.altitude_at_surface_p(plan.surface_p)
    where = (f"{water_name(plan.msw_per_bar)} water ({plan.msw_per_bar:.4g} m/bar)"
             f" · surface {plan.surface_p:g} bar")
    if alt >= 50:
        where += f" (~{alt:.0f} m altitude)"
    return (f"{where} — non-default environment, so this schedule will differ "
            f"from a planner set to sea-level salt water")


def wetnotes_rows(segments: Sequence[b.DiveSegment],
                  pressures: Sequence[float | None] | None = None
                  ) -> list[list[str]]:
    """The printed schedule as ``[depth, stop, run, gas]`` string rows — the
    wetnotes/runtime-card format (see ``cards/README.md``).

    With `pressures` (from `leg_pressures`, one entry per stop) each row gains a
    fifth ``bar`` column: the cylinder pressure on leaving that depth. Non-stop
    rows — gas-switch annotations and the surface row — carry ``""`` there,
    because there is no hold at which to read a gauge.

    The notation is `buhlmann.StopLeg`'s: ``run`` is the runtime you **leave**
    that depth (truncated), ``stop`` is the **leg** — the time from leaving the
    row above to leaving this one, ascent included — so the stop column always
    adds up to the run column.

    A gas-switch row is an annotation — it carries the runtime the switch
    happens at, but the stop legs are measured from the previous stop (from
    leaving the bottom for the first), so this card, the GUI's stop table and
    the cut table print identical minutes for the same stop.

    A zero-duration bottom segment gets no row: a level whose whole time is
    transit would otherwise print a duplicate of the depth above it.
    """
    rows: list[list[str]] = []
    legs = iter(b.stop_legs(segments))
    bars = iter(pressures) if pressures is not None else None
    run = 0.0
    prev: b.Gas | None = None

    def emit(depth: str, stop: str, run_min: int, gas: str,
             bar: float | None = None) -> None:
        row = [depth, stop, f"{run_min:d}", gas]
        if bars is not None:
            row.append("" if bar is None else f"{bar:.0f}")
        rows.append(row)

    for s in segments:
        # A gas switch with no stop at that depth (EAN50 at 21 m on a 40 m dive
        # whose first stop is shallower) must still get a row — this card is
        # what the diver takes underwater. A switch *at* a stop already shows
        # on the stop row's gas column.
        # Compared as frozen `Gas` values, never as the rounded label they
        # print under: EAN21.4 and EAN20.6 both render "Air", and a switch
        # between two such mixes must still put a row on the card the diver
        # carries. Same rule as the gas accounting keys by (DECISIONS.md #8).
        if prev is not None and s.gas != prev and s.kind != "stop":
            emit(f"{s.depth_start:.0f} m", "gas", runtime_min(run), repr(s.gas))
        run += s.duration
        if s.kind == "bottom" and s.duration > 0:
            emit(f"{s.depth_end:.0f} m", "-", runtime_min(run), repr(s.gas))
        elif s.kind == "stop" and s.duration > 0:
            leg = next(legs)
            emit(f"{leg.depth:.0f} m", f"{leg.leg:d}", leg.run, repr(leg.gas),
                 next(bars) if bars is not None else None)
        prev = s.gas
    emit("surf", "-", runtime_min(run), "")
    return rows


def backup_line(segments: Sequence[b.DiveSegment]) -> str:
    """The whole schedule on one line, for a slate, a log or a chat message.

    Same notation as the card and every other view (`buhlmann.StopLeg`): the
    bottom carries the runtime it is LEFT at, each stop carries its **leg**, and
    a mix is named only where it changes. Built from `b.stop_legs`, so a line
    pasted into a message cannot disagree with the card in a pocket.

        45m/25 -> 24m/3' -> 21m/1' EAN50 -> ... -> 3m/11' -> surf 53
    """
    parts: list[str] = []
    run = 0.0
    prev: b.Gas | None = None
    for s in segments:
        run += s.duration
        if s.kind == "bottom" and s.duration > 0:
            parts.append(f"{s.depth_end:.0f}m/{runtime_min(run)}")
            prev = s.gas          # switches are named from the last bottom mix
    for leg in b.stop_legs(segments):
        token = f"{leg.depth:.0f}m/{leg.leg:d}'"
        if leg.gas != prev:
            token += f" {leg.gas!r}"
            prev = leg.gas
        parts.append(token)
    parts.append(f"surf {runtime_min(b.total_runtime(segments))}")
    return " -> ".join(parts)


# -----------------------------------------------------------------------------
# The gas stack: is each mix safe where it would actually be breathed?
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class GasStackRow:
    """One mix of the stack, quoted **at its own MOD** — the deepest point it
    would ever be breathed, and so the only depth at which "is this mix safe"
    has a worst-case answer. Quoting the whole stack at the bottom depth instead
    would report a deco mix at a depth it is never switched to."""
    gas: b.Gas
    role: str
    mod_m: float
    end_m: float
    ead_m: float
    density_g_l: float

    @property
    def dense(self) -> bool:
        """Over the Anthony & Mitchell working ceiling at its own MOD."""
        return self.density_g_l > b.DENSITY_MAX_G_L


def gas_stack_table(plan: b.DivePlan, bottom_gas: b.Gas) -> list[GasStackRow]:
    """Every mix the plan may breathe, with MOD / END / EAD / density.

    The bottom gas is quoted at its working-ppO2 MOD (`plan.ppo2_bottom`) and
    travel/deco mixes at the deco ceiling (`plan.ppo2_deco`) — the limit each is
    actually planned against, the same split `_gas_switch_depths` uses.

    END counts oxygen as narcotic and EAD does not: they are the two published
    conventions and a diver reading a mix wants both, which is why `Gas.end`
    already takes the flag rather than this module computing narcosis twice.
    """
    rows: list[GasStackRow] = []
    seen: list[b.Gas] = []
    stack = ((bottom_gas, "Bottom", plan.ppo2_bottom),
             *((g, "Travel", plan.ppo2_deco) for g in plan.travel_gases),
             *((g, "Deco", plan.ppo2_deco) for g in plan.deco_gases))
    for gas, role, ppo2 in stack:
        if gas in seen:
            continue
        seen.append(gas)
        mod = gas.mod(ppo2, plan.surface_p, plan.msw_per_bar)
        rows.append(GasStackRow(
            gas=gas, role=role, mod_m=mod,
            end_m=gas.end(mod, plan.surface_p, plan.msw_per_bar),
            ead_m=gas.end(mod, plan.surface_p, plan.msw_per_bar,
                          o2_narcotic=False),
            density_g_l=gas.density(mod, plan.surface_p, plan.msw_per_bar)))
    return rows


# -----------------------------------------------------------------------------
# Warnings (shared wording)
# -----------------------------------------------------------------------------

def warning_lines(segments: Sequence[b.DiveSegment], plan: b.DivePlan,
                  bottom_gas: b.Gas, max_depth_m: float) -> list[str]:
    """The load-bearing warning texts for a planned dive: ceiling violations,
    worst ppO2 offences, and the gas-density ceiling. One string per warning,
    identical wording in every front end."""
    warnings = [f"level at {s.depth_start:g} m is above the "
                f"{s.ceiling_m:.1f} m ceiling"
                for s in b.ceiling_violations(segments)]
    for v in b.worst_ppo2_violations(segments, plan):
        if v.kind == "high":
            warnings.append(f"ppO2 {v.ppo2:.2f} bar on {v.segment.gas!r} at "
                            f"{v.depth:.0f} m — over the {v.limit:.2f} limit")
        else:
            warnings.append(f"ppO2 {v.ppo2:.2f} bar on {v.segment.gas!r} at "
                            f"{v.depth:.0f} m — hypoxic (min {v.limit:.2f})")
    density = bottom_gas.density(max_depth_m, plan.surface_p, plan.msw_per_bar)
    if density > b.DENSITY_MAX_G_L:
        warnings.append(f"gas density {density:.1f} g/L at {max_depth_m:g} m "
                        f"exceeds {b.DENSITY_MAX_G_L:g} g/L (CO2 retention "
                        f"risk)")
    return warnings


# -----------------------------------------------------------------------------
# Cylinder banks and per-gas accounting
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class Bank:
    """Same-mix cylinders aggregated into one manifolded bank: volumes add,
    the fill pressure is volume-weighted (design decision — per-cylinder
    identity below the mix level is out of scope)."""
    role: str            # first role seen for the mix
    gas: b.Gas
    tank_l: float
    pressure_bar: float


def aggregate_banks(gases: Sequence[tuple[str, b.Gas, float, float]]
                    ) -> list[Bank]:
    """Aggregate ``(role, Gas, tank_l, pressure_bar)`` rows by exact mix
    (``Gas`` equality, not display label), preserving first-seen order."""
    order: list[b.Gas] = []
    tank: dict[b.Gas, float] = {}
    press: dict[b.Gas, float] = {}
    role: dict[b.Gas, str] = {}
    for r, g, tk, pr in gases:
        if g not in tank:
            order.append(g)
            tank[g], press[g], role[g] = 0.0, 0.0, r
        vol = tank[g]
        total = vol + (tk or 0.0)
        press[g] = ((press[g] * vol + (pr or 0.0) * (tk or 0.0)) / total
                    if total > 0 else (pr or 0.0))
        tank[g] = total
    return [Bank(role[g], g, tank[g], press[g]) for g in order]


@dataclass(frozen=True)
class CylinderNeed:
    """Need vs have for one breathed mix. ``liters`` is the planned dive at
    the normal SAC; ``liters_emergency`` is the emergency TOTAL — that normal
    need PLUS the rock-bottom reserve held on top for a worst-moment issue
    (`buhlmann.emergency_gas_liters`: the worst level's reserve, not the last
    level's).

    ``liters_emergency`` is **None when the plan's emergency block is off**
    (``GasPlan.emergency``), and so is every figure derived from it. None means
    "not asked for", which is why it is not 0.0: a renderer that prints a zero
    reserve says the dive needs none, and that is a different — and dangerous —
    claim from saying nothing (DECISIONS.md #28)."""
    gas: b.Gas
    role: str
    liters: float
    liters_emergency: float | None
    tank_l: float
    pressure_bar: float

    @property
    def bar_used(self) -> float | None:
        return self.liters / self.tank_l if self.tank_l > 0 else None

    @property
    def bar_used_emergency(self) -> float | None:
        if self.liters_emergency is None or self.tank_l <= 0:
            return None
        return self.liters_emergency / self.tank_l

    @property
    def bar_left(self) -> float | None:
        if self.tank_l > 0 and self.pressure_bar > 0:
            return self.pressure_bar - self.liters / self.tank_l
        return None

    @property
    def bar_left_emergency(self) -> float | None:
        if (self.liters_emergency is not None
                and self.tank_l > 0 and self.pressure_bar > 0):
            return self.pressure_bar - self.liters_emergency / self.tank_l
        return None

    @property
    def short(self) -> bool:
        """True when the normal-SAC need exceeds the carried fill."""
        return (self.tank_l > 0 and self.pressure_bar > 0
                and self.liters / self.tank_l > self.pressure_bar + 1e-9)

    @property
    def short_emergency(self) -> bool:
        """True when even need-plus-reserve exceeds the fill. False — not a
        crash — when no emergency was asked for: nothing was claimed, so
        nothing is short."""
        return (self.liters_emergency is not None
                and self.tank_l > 0 and self.pressure_bar > 0
                and self.liters_emergency / self.tank_l
                > self.pressure_bar + 1e-9)


@dataclass(frozen=True)
class GasReport:
    """Per-mix consumption plus the rock-bottom (minimum gas) reserve.

    ``rock_bottom_l`` is None exactly when the emergency block is off, like
    `CylinderNeed.liters_emergency`."""
    plan: b.GasPlan
    cylinders: list[CylinderNeed]
    rock_bottom_l: float | None
    back_tank_l: float
    back_pressure_bar: float

    @property
    def emergency(self) -> bool:
        """Does this report carry emergency figures at all? One place for the
        front ends to ask, so no view has to test a litre count for None to
        decide whether to draw a column."""
        return self.rock_bottom_l is not None

    @property
    def rock_bottom_bar(self) -> float | None:
        return (self.rock_bottom_l / self.back_tank_l
                if self.rock_bottom_l is not None and self.back_tank_l > 0
                else None)

    @property
    def turn_pressure_bar(self) -> float | None:
        """The pressure at which the dive turns, by `GasPlan.turn_rule`:

        * ``rock-bottom`` — half the usable gas above rock bottom, from the
          fill. Surfacing pressure is exactly rock bottom.
        * ``thirds`` — ⅔ of the fill, the cave rule, whatever the profile.

        None when the plan does not want one (`GasPlan.turn_pressure` off, or
        the whole emergency block off), when there is no fill to divide, or —
        for the rock-bottom rule — when the reserve is not expressible in bar
        or already exceeds the fill. A turn pressure that cannot be computed is
        absent, never a plausible-looking number."""
        if not (self.emergency and self.plan.turn_pressure):
            return None
        if self.back_pressure_bar <= 0:
            return None
        if self.plan.turn_rule == "thirds":
            return self.back_pressure_bar * 2.0 / 3.0
        rb = self.rock_bottom_bar
        if rb is None:
            return None
        usable = self.back_pressure_bar - rb
        return self.back_pressure_bar - usable / 2.0 if usable > 0 else None

    @property
    def turn_reserve_bar(self) -> float | None:
        """What is left in the back gas on surfacing if the dive turns at
        `turn_pressure_bar` and the way out costs what the way in did:
        ``2 × turn − fill``. Rock bottom by construction under the
        ``rock-bottom`` rule; a third of the fill under ``thirds``."""
        turn = self.turn_pressure_bar
        return (None if turn is None
                else 2.0 * turn - self.back_pressure_bar)

    @property
    def turn_below_rock_bottom(self) -> bool:
        """Does the turn pressure surface the diver with LESS than minimum gas?

        Only ``thirds`` can fail this — it is a rule of thumb that knows
        nothing about the profile, so on a deep or long dive a third of the
        fill is simply not enough to get two divers up. Saying so is the whole
        value of computing both numbers (DECISIONS.md #28)."""
        left, rb = self.turn_reserve_bar, self.rock_bottom_bar
        return left is not None and rb is not None and left < rb - 1e-9


@overload
def gas_report(segments: Sequence[b.DiveSegment],
               bottom_gas: b.Gas, gas_plan: b.GasPlan,
               gases: Sequence[tuple[str, b.Gas, float, float]],
               plan: b.DivePlan) -> GasReport: ...


@overload
def gas_report(segments: Sequence[b.DiveSegment],
               bottom_gas: b.Gas, gas_plan: None,
               gases: Sequence[tuple[str, b.Gas, float, float]],
               plan: b.DivePlan) -> None: ...


def gas_report(segments: Sequence[b.DiveSegment],
               bottom_gas: b.Gas, gas_plan: b.GasPlan | None,
               gases: Sequence[tuple[str, b.Gas, float, float]],
               plan: b.DivePlan) -> GasReport | None:
    """Per-mix need/have accounting for a planned dive, or None without a
    ``GasPlan``. Mixes appear in the order they are first breathed; same-mix
    cylinders act as one bank (`aggregate_banks`).

    The **whole ``DivePlan``** is required, not the three values this needs off
    it: gas breathed off ``plan.deco_gases`` is billed at ``GasPlan.sac_deco``,
    and every litre is measured at ``plan.surface_p`` / ``plan.msw_per_bar``.
    They used to be optional parameters defaulting to sea-level salt water and
    an empty deco stack, and the GUI omitted all three — so a deco SAC the user
    had typed, saved and could see on screen changed no number anywhere, and an
    altitude dive was billed at sea level. Omitting a plan is now a TypeError
    rather than a wrong figure (DECISIONS.md #24).

    Overloaded so a caller that *has* a ``GasPlan`` (the GUI always does) gets
    a plain ``GasReport`` back and does not have to re-prove non-None at every
    field access."""
    if gas_plan is None:
        return None
    surface_p, msw_per_bar = plan.surface_p, plan.msw_per_bar
    deco_gases = plan.deco_gases
    banks = {bk.gas: bk for bk in aggregate_banks(gases)}
    # The "worst moment" profiles the reserve is a maximum over depend only on
    # the dive, never on the gas being costed, so they are built ONCE here and
    # handed to every cylinder. Derived per gas — which is what happened before
    # — a three-level dive with three mixes re-planned the same two truncated
    # dives six times, three quarters of the cost of this whole function.
    candidates = (b.reserve_candidates(segments, plan, bottom_gas)
                  if gas_plan.emergency else None)
    cylinders: list[CylinderNeed] = []
    seen: list[b.Gas] = []
    for s in segments:
        if s.gas in seen:
            continue
        seen.append(s.gas)
        liters = b.segment_gas_liters(
            [x for x in segments if x.gas == s.gas],
            gas_plan.sac_for(s.gas, deco_gases), surface_p, msw_per_bar)
        # Emergency TOTAL for this gas = the normal need plus the rock-bottom
        # reserve held on top for the worst-moment issue (the diver carries
        # both — the reserve is not dipped into on a normal dive). With the
        # emergency block off it is not computed at all: the re-planning inside
        # `emergency_gas_liters` is the expensive part of this function, and a
        # figure nobody will print should not be paid for.
        liters_e = (liters + b.emergency_gas_liters(segments, s.gas, gas_plan,
                                                    plan,
                                                    candidates=candidates)
                    if gas_plan.emergency else None)
        bank = banks.get(s.gas)
        role = (bank.role if bank
                else "Bottom" if s.gas == bottom_gas else "stage")
        cylinders.append(CylinderNeed(
            gas=s.gas, role=role, liters=liters, liters_emergency=liters_e,
            tank_l=bank.tank_l if bank else 0.0,
            pressure_bar=bank.pressure_bar if bank else 0.0))
    back = banks.get(bottom_gas)
    # Deliberately a second call rather than reusing the bottom gas's cylinder
    # figure above: `cylinders` covers the mixes actually breathed, and a
    # bottom gas that is never breathable at depth is not among them. Sharing
    # `candidates` already removes the expensive half.
    rock = (b.rock_bottom_liters(segments, bottom_gas, gas_plan, plan,
                                 candidates=candidates)
            if gas_plan.emergency else None)
    return GasReport(plan=gas_plan, cylinders=cylinders, rock_bottom_l=rock,
                     back_tank_l=back.tank_l if back else 0.0,
                     back_pressure_bar=back.pressure_bar if back else 0.0)


def leg_pressures(segments: Sequence[b.DiveSegment], gas_plan: b.GasPlan | None,
                  gases: Sequence[tuple[str, b.Gas, float, float]],
                  plan: b.DivePlan) -> list[float | None]:
    """Cylinder pressure (bar) as the diver **leaves** each stop — one entry per
    `buhlmann.stop_legs` row, aligned with it position for position.

    This is the column an SPG can be checked against at every stop, which is the
    only gas figure a diver can verify underwater: the plan says 158 bar leaving
    21 m, and the needle either agrees or the dive has changed.

    ``None`` where the answer would be a guess rather than a number — no
    ``GasPlan``, or a mix with no cylinder on the stack (its size and fill are
    what turn litres into bar). Consumption is billed exactly as `gas_report`
    bills it: each mix at `GasPlan.sac_for`, so a deco cylinder is charged at the
    deco SAC, and every litre measured in the dive's own environment.

    Same-mix cylinders are one bank (`aggregate_banks`), so twin 12s read as a
    24 L supply — the diver has one manifolded pressure to look at, not two.
    """
    legs = b.stop_legs(segments)
    if gas_plan is None:
        return [None] * len(legs)
    banks = {bk.gas: bk for bk in aggregate_banks(gases)}
    used: dict[b.Gas, float] = {}
    out: list[float | None] = []
    for s in segments:
        used[s.gas] = used.get(s.gas, 0.0) + b.segment_gas_liters(
            [s], gas_plan.sac_for(s.gas, plan.deco_gases),
            plan.surface_p, plan.msw_per_bar)
        # Mirrors `stop_legs`' own filter, so the two lists stay index-aligned.
        if s.kind != "stop" or s.duration <= 0:
            continue
        bank = banks.get(s.gas)
        out.append(None if bank is None or bank.tank_l <= 0
                   else bank.pressure_bar - used[s.gas] / bank.tank_l)
    return out


# -----------------------------------------------------------------------------
# The assembled plan result
# -----------------------------------------------------------------------------

@dataclass
class PlanResult:
    """Everything a front end needs to render one planned dive. Computed once
    by `compute_plan_result`; renderers must surface `warnings` on anything
    that looks like a schedule."""
    levels: list[b.Level]
    bottom_gas: b.Gas
    plan: b.DivePlan
    segments: list[b.DiveSegment]
    tissues: b.Tissues
    max_depth_m: float
    avg_depth_m: float
    total_runtime_min: float
    tts_min: float
    surface_ceiling_m: float
    cns_pct: float
    otu: float
    end_m: float
    density_g_l: float
    #: The GF actually surfaced at (fraction). `surface_ceiling_m` is a depth —
    #: how much ceiling is left; this is how much of the GF-High budget was
    #: spent. Over 1.0 means the schedule surfaces past its own M-value line.
    surf_gf: float = 0.0
    gas_stack: list[GasStackRow] = field(default_factory=list)
    backup: str = ""
    #: Cylinder pressure leaving each stop, aligned to `buhlmann.stop_legs`.
    #: All-None without a GasPlan — the litres are known, the bar are not.
    leg_bars: list[float | None] = field(default_factory=list)
    #: The ascent re-flown with the BOTTOM gas gone, or None when that cannot be
    #: survived on the remaining stack (the usual answer on a deep dive). None
    #: is a finding, not a missing feature — see `buhlmann.bailout_schedule`.
    bailout: list[b.DiveSegment] | None = None
    warnings: list[str] = field(default_factory=list)
    gas: GasReport | None = None
    contingency: list[list[b.ContingencyCell]] | None = None


def compute_series_result(
        series: Sequence[tuple[float, Sequence[b.Level]]],
        bottom_gas: b.Gas, plan: b.DivePlan,
        gas_plan: b.GasPlan | None = None,
        gases: Sequence[tuple[str, b.Gas, float, float]] = (),
        contingency: tuple[int, int, int, int] | None = None
        ) -> list[PlanResult]:
    """One `PlanResult` per dive in a day, tissues carried through.

    `series` is ``(surface_interval_min, levels)`` per dive — what
    `dive_config.series_of` returns. Each dive starts from the previous dive's
    final loading after `buhlmann.surface_interval`, so dive 2 is planned on the
    nitrogen dive 1 actually left behind rather than on a table's pressure group.

    Every dive keeps its own full `PlanResult`, which is what lets both front
    ends render a repetitive dive with the code they already had: a series is a
    list of ordinary results, not a new kind of thing.
    """
    results: list[PlanResult] = []
    tissues: b.Tissues | None = None
    for interval, levels in series:
        if tissues is not None:
            tissues = b.surface_interval(tissues, interval, plan)
        results.append(compute_plan_result(
            levels, bottom_gas, plan, gas_plan, gases, contingency,
            start_tissues=tissues))
        tissues = results[-1].tissues
    return results


def compute_plan_result(levels: Sequence[b.Level], bottom_gas: b.Gas,
                        plan: b.DivePlan,
                        gas_plan: b.GasPlan | None = None,
                        gases: Sequence[tuple[str, b.Gas, float, float]] = (),
                        contingency: tuple[int, int, int, int] | None = None,
                        start_tissues: b.Tissues | None = None) -> PlanResult:
    """Plan the dive and derive every shared figure: schedule, warnings,
    CNS/OTU, END/density, gas accounting, and (optionally) the contingency
    cut-table grid as ``(time_before, time_after, depth_before, depth_after)``
    step counts. Raises ValueError on invalid input, exactly as the planner
    does.

    `start_tissues` is the loading the dive begins with — residual nitrogen from
    an earlier dive (`compute_series_result`). None means clean tissues."""
    segments, tissues = b.plan_multilevel(list(levels), bottom_gas, plan,
                                          start_tissues)
    depth = b.max_depth(levels)
    result = PlanResult(
        levels=list(levels), bottom_gas=bottom_gas, plan=plan,
        segments=segments, tissues=tissues,
        max_depth_m=depth,
        avg_depth_m=b.average_depth(segments),
        total_runtime_min=b.total_runtime(segments),
        tts_min=b.time_to_surface(segments),
        surface_ceiling_m=b.ceiling_depth(tissues, plan.gf_high,
                                          plan.surface_p, plan.msw_per_bar),
        cns_pct=0.0, otu=0.0,
        end_m=bottom_gas.end(depth, plan.surface_p, plan.msw_per_bar),
        density_g_l=bottom_gas.density(depth, plan.surface_p,
                                       plan.msw_per_bar),
    )
    result.cns_pct, result.otu = b.cns_otu(segments, plan.surface_p,
                                           plan.msw_per_bar)
    result.surf_gf = b.surface_gf(tissues, plan.surface_p)
    result.gas_stack = gas_stack_table(plan, bottom_gas)
    result.backup = backup_line(segments)
    result.leg_bars = leg_pressures(segments, gas_plan, gases, plan)
    try:
        result.bailout = b.bailout_schedule(segments, plan, bottom_gas,
                                            (bottom_gas,))
    except (ValueError, RuntimeError):
        result.bailout = None    # unplannable is a result, not a crash
    result.warnings = warning_lines(segments, plan, bottom_gas, depth)
    result.gas = gas_report(segments, bottom_gas, gas_plan, gases, plan)
    if contingency is not None:
        tb, ta, db, da = contingency
        result.contingency = b.contingency_schedules(
            list(levels), bottom_gas, plan, time_before=tb, time_after=ta,
            depth_before=db, depth_after=da)
    return result
