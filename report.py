"""Shared plan-result and gas-accounting layer for the deco front ends.

Everything user-facing that is *computed* — warning texts, per-cylinder gas
accounting (need / have / emergency / SHORT), rock bottom, the assembled
``PlanResult`` — lives here exactly once, so the CLI and the GUI cannot drift
apart. Front ends stay renderers: they format these values, they do not
re-derive them.

Design rules (see CLAUDE.md):
* stdlib only — this module sits between ``buhlmann`` and the front ends;
* warnings are load-bearing: `PlanResult.warnings` must be surfaced, with the
  educational disclaimer, by every renderer;
* gases are identified by the frozen ``Gas`` value itself (equality/hash),
  never by its display ``repr`` — two mixes that round to the same label must
  not merge their accounting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import buhlmann as b

DISCLAIMER = "Educational model — NOT validated for planning real dives."

#: Default cylinder fill pressure (bar) when none is given.
DEFAULT_FILL_BAR = 232.0


# -----------------------------------------------------------------------------
# Warnings (shared wording)
# -----------------------------------------------------------------------------

def warning_lines(segments: Sequence[b.DiveSegment], plan: b.DivePlan,
                  bottom_gas: b.Gas, max_depth_m: float) -> List[str]:
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


def aggregate_banks(gases: Sequence[Tuple[str, b.Gas, float, float]]
                    ) -> List[Bank]:
    """Aggregate ``(role, Gas, tank_l, pressure_bar)`` rows by exact mix
    (``Gas`` equality, not display label), preserving first-seen order."""
    order: List[b.Gas] = []
    tank: Dict[b.Gas, float] = {}
    press: Dict[b.Gas, float] = {}
    role: Dict[b.Gas, str] = {}
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
    (`buhlmann.emergency_gas_liters`, an approximation — see its docstring)."""
    gas: b.Gas
    role: str
    liters: float
    liters_emergency: float
    tank_l: float
    pressure_bar: float

    @property
    def bar_used(self) -> Optional[float]:
        return self.liters / self.tank_l if self.tank_l > 0 else None

    @property
    def bar_used_emergency(self) -> Optional[float]:
        return self.liters_emergency / self.tank_l if self.tank_l > 0 else None

    @property
    def bar_left(self) -> Optional[float]:
        if self.tank_l > 0 and self.pressure_bar > 0:
            return self.pressure_bar - self.liters / self.tank_l
        return None

    @property
    def bar_left_emergency(self) -> Optional[float]:
        if self.tank_l > 0 and self.pressure_bar > 0:
            return self.pressure_bar - self.liters_emergency / self.tank_l
        return None

    @property
    def short(self) -> bool:
        """True when the normal-SAC need exceeds the carried fill."""
        return (self.tank_l > 0 and self.pressure_bar > 0
                and self.liters / self.tank_l > self.pressure_bar + 1e-9)

    @property
    def short_emergency(self) -> bool:
        return (self.tank_l > 0 and self.pressure_bar > 0
                and self.liters_emergency / self.tank_l
                > self.pressure_bar + 1e-9)


@dataclass(frozen=True)
class GasReport:
    """Per-mix consumption plus the rock-bottom (minimum gas) reserve."""
    plan: b.GasPlan
    cylinders: List[CylinderNeed]
    rock_bottom_l: float
    back_tank_l: float
    back_pressure_bar: float

    @property
    def rock_bottom_bar(self) -> Optional[float]:
        return (self.rock_bottom_l / self.back_tank_l
                if self.back_tank_l > 0 else None)

    @property
    def turn_pressure_bar(self) -> Optional[float]:
        """Half the usable gas above rock bottom, from the fill — None when
        rock bottom is not expressible in bar or exceeds the fill."""
        rb = self.rock_bottom_bar
        if rb is None or self.back_pressure_bar <= 0:
            return None
        usable = self.back_pressure_bar - rb
        return self.back_pressure_bar - usable / 2.0 if usable > 0 else None


def gas_report(segments: Sequence[b.DiveSegment],
               bottom_gas: b.Gas, gas_plan: Optional[b.GasPlan],
               gases: Sequence[Tuple[str, b.Gas, float, float]],
               surface_p: float = b.P_ATM,
               msw_per_bar: float = b.MSW_PER_BAR) -> Optional[GasReport]:
    """Per-mix need/have accounting for a planned dive, or None without a
    ``GasPlan``. Mixes appear in the order they are first breathed; same-mix
    cylinders act as one bank (`aggregate_banks`)."""
    if gas_plan is None:
        return None
    banks = {bk.gas: bk for bk in aggregate_banks(gases)}
    cylinders: List[CylinderNeed] = []
    seen: List[b.Gas] = []
    for s in segments:
        if s.gas in seen:
            continue
        seen.append(s.gas)
        liters = b.segment_gas_liters(
            [x for x in segments if x.gas == s.gas], gas_plan.sac,
            surface_p, msw_per_bar)
        # Emergency TOTAL for this gas = the normal need plus the rock-bottom
        # reserve held on top for the worst-moment issue (the diver carries
        # both — the reserve is not dipped into on a normal dive).
        reserve = b.emergency_gas_liters(segments, s.gas, gas_plan,
                                         surface_p, msw_per_bar)
        liters_e = liters + reserve
        bank = banks.get(s.gas)
        role = (bank.role if bank
                else "Bottom" if s.gas == bottom_gas else "stage")
        cylinders.append(CylinderNeed(
            gas=s.gas, role=role, liters=liters, liters_emergency=liters_e,
            tank_l=bank.tank_l if bank else 0.0,
            pressure_bar=bank.pressure_bar if bank else 0.0))
    back = banks.get(bottom_gas)
    rock = b.rock_bottom_liters(segments, bottom_gas, gas_plan,
                                surface_p, msw_per_bar)
    return GasReport(plan=gas_plan, cylinders=cylinders, rock_bottom_l=rock,
                     back_tank_l=back.tank_l if back else 0.0,
                     back_pressure_bar=back.pressure_bar if back else 0.0)


# -----------------------------------------------------------------------------
# The assembled plan result
# -----------------------------------------------------------------------------

@dataclass
class PlanResult:
    """Everything a front end needs to render one planned dive. Computed once
    by `compute_plan_result`; renderers must surface `warnings` and the
    `DISCLAIMER` on anything that looks like a schedule."""
    levels: List[b.Level]
    bottom_gas: b.Gas
    plan: b.DivePlan
    segments: List[b.DiveSegment]
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
    warnings: List[str] = field(default_factory=list)
    gas: Optional[GasReport] = None
    contingency: Optional[List[List[b.ContingencyCell]]] = None


def compute_plan_result(levels: Sequence[b.Level], bottom_gas: b.Gas,
                        plan: b.DivePlan,
                        gas_plan: Optional[b.GasPlan] = None,
                        gases: Sequence[Tuple[str, b.Gas, float, float]] = (),
                        contingency: Optional[Tuple[int, int, int, int]] = None
                        ) -> PlanResult:
    """Plan the dive and derive every shared figure: schedule, warnings,
    CNS/OTU, END/density, gas accounting, and (optionally) the contingency
    cut-table grid as ``(time_before, time_after, depth_before, depth_after)``
    step counts. Raises ValueError on invalid input, exactly as the planner
    does."""
    segments, tissues = b.plan_multilevel(list(levels), bottom_gas, plan)
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
    result.warnings = warning_lines(segments, plan, bottom_gas, depth)
    result.gas = gas_report(segments, bottom_gas, gas_plan, gases,
                            plan.surface_p, plan.msw_per_bar)
    if contingency is not None:
        tb, ta, db, da = contingency
        result.contingency = b.contingency_schedules(
            list(levels), bottom_gas, plan, time_before=tb, time_after=ta,
            depth_before=db, depth_after=da)
    return result
