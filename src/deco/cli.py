"""CLI front-end for the Bühlmann module.

Examples
--------
    deco plan --depth 30 --time 25 --gas air
    deco plan --depth 45 --time 25 --gas 21/35 --deco-gas 50 --deco-gas 100
    deco plan --depth 60 --time 25 --gas 10/70 --travel-gas 35/25 --deco-gas 50 --sac 18
    deco ndl --depth 30 --gas air
    deco tissues --depth 30 --time 25 --gas air
"""

from __future__ import annotations

import argparse
import json
import sys

from deco import buhlmann as b
from deco import contingency as ct
from deco import dive_config as dc
from deco import report as rp
from deco import toxicity as tox


def _positive_float(s: str) -> float:
    v = float(s)
    if v <= 0:
        raise argparse.ArgumentTypeError(f"must be > 0 (got {s})")
    return v


def _nonneg_float(s: str) -> float:
    v = float(s)
    if v < 0:
        raise argparse.ArgumentTypeError(f"must be >= 0 (got {s})")
    return v


def _positive_int(s: str) -> int:
    v = int(s)
    if v < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1 (got {s})")
    return v


#: The leanest oxygen percentage the CLI accepts. Nothing below it is a
#: breathing mix even at 100 m+, so a smaller number is a typo — almost always
#: a fraction typed where the percentage belongs.
MIN_O2_PCT = 5.0


def parse_gas(spec: str) -> b.Gas:
    """Parse 'air', 'ean32', 'nx32', '32', or trimix '21/35' (= 21% O2, 35% He).

    The numbers are **percent**. A fraction is refused, not divided: ``0.32``
    used to plan a 0.32 % O₂ mix labelled "EAN0" and ``--deco-gas 1`` a silent
    EAN1 with a 1590 m MOD — the deco then computed with no oxygen at all. A
    config file has refused the same typo since DECISIONS.md #9; the CLI is held
    to it too, with the likely meaning in the error."""
    s = spec.strip().lower()
    if s == "air":
        return b.AIR
    if s == "o2":
        return b.O2
    if "/" in s:
        a, c = s.split("/", 1)
        o2, he = float(a), float(c)
    else:
        o2, he = float(s.removeprefix("ean").removeprefix("nx")), 0.0
    if o2 < MIN_O2_PCT:
        if o2 > 0 and o2 <= 1.0 and he <= 1.0:
            meant = (f"{o2 * 100:g}/{he * 100:g}" if "/" in s
                     else "100 (or 'o2')" if o2 == 1.0 else f"{o2 * 100:g}")
            hint = f" — did you mean {meant}? Mixes are in percent"
        else:
            hint = f" — below {MIN_O2_PCT:g} % O2 is not a breathing mix"
        raise ValueError(f"gas '{spec}': {o2:g} % oxygen{hint}")
    return b.Gas(o2 / 100.0, he / 100.0)


def parse_gas_spec(spec: str):
    """Parse a gas with optional '@<litres>' tank and '@<bar>' pressure suffixes,
    e.g. '50@11', 'air@24@232'. Returns (Gas, tank_l_or_None, pressure_bar_or_None)."""
    parts = spec.split("@")
    if len(parts) > 3:
        raise ValueError(f"gas '{spec}': expected MIX[@LITRES[@BAR]], "
                         "at most a tank size and a fill pressure")
    gas = parse_gas(parts[0])
    tank = float(parts[1]) if len(parts) > 1 and parts[1].strip() else None
    pressure = float(parts[2]) if len(parts) > 2 and parts[2].strip() else None
    return gas, tank, pressure


def parse_level(spec: str) -> b.Level:
    """Parse a level as 'DEPTH:RUNTIME', e.g. '45:25'.

    RUNTIME is the runtime in minutes at the END of the level — cumulative,
    descent included. Levels are contiguous: the transit to the depth runs at
    the standard rate and its time is part of that runtime. Gas is chosen
    automatically by role — levels are pure depth/time periods."""
    parts = spec.split(":")
    if len(parts) != 2:
        raise ValueError(
            f"level '{spec}': expected DEPTH:RUNTIME, e.g. 45:25")
    try:
        depth, runtime = float(parts[0]), float(parts[1])
    except ValueError as e:
        raise ValueError(
            f"level '{spec}': depth and runtime must be numbers") from e
    return b.Level(depth, runtime)


def parse_dive(spec: str) -> tuple[float, b.Level]:
    """Parse one dive of a series as 'DEPTH:RUNTIME[:SURFACE_INTERVAL]'.

    SURFACE_INTERVAL is the time on the surface BEFORE this dive, in minutes —
    it belongs to the gap, not to the dive, which is why it is the third field
    and why omitting it on the first dive is the normal case."""
    parts = spec.split(":")
    if len(parts) not in (2, 3):
        raise ValueError(
            f"dive '{spec}': expected DEPTH:RUNTIME[:SURFACE_INTERVAL], "
            "e.g. 30:25 or 30:25:60")
    try:
        depth, runtime = float(parts[0]), float(parts[1])
        interval = float(parts[2]) if len(parts) == 3 else 0.0
    except ValueError as e:
        raise ValueError(f"dive '{spec}': depth, runtime and surface "
                         "interval must be numbers") from e
    if interval < 0:
        raise ValueError(f"dive '{spec}': surface interval must be >= 0")
    return interval, b.Level(depth, runtime)


def _level_dict(l: b.Level) -> dict:
    """Serialize a Level to the config/JSON shape."""
    return {"depth_m": l.depth, "runtime_min": l.runtime}


def parse_contingency(spec: str) -> tuple[int | None, int | None, int | None, int | None]:
    """Parse a cut-table step-count spec 'TB[:TA[:DB[:DA]]]' — bottom-time rows
    3 min shorter/longer, depth columns 3 m shallower/deeper — e.g. '1:2:0:1'.
    Empty parts (and the empty string, from a bare --contingency) mean "use the
    config's value": returns a 4-tuple of count-or-None."""
    parts = spec.strip().split(":")
    if len(parts) > 4:
        raise ValueError(f"contingency '{spec}': expected TB[:TA[:DB[:DA]]], "
                         "e.g. 1 or 1:2:0:1")
    counts: list[int | None] = []
    for p in parts + [""] * (4 - len(parts)):
        if not p.strip():
            counts.append(None)
            continue
        try:
            n = int(p)
        except ValueError as e:
            raise ValueError(
                f"contingency '{spec}': step counts must be integers") from e
        if n < 0:
            raise ValueError(f"contingency '{spec}': step counts must be >= 0")
        counts.append(n)
    tb, ta, db, da = counts
    return tb, ta, db, da


def _args_levels(args) -> list[b.Level]:
    """Levels from --level (repeatable), or the --depth/--time shorthand."""
    if args.level:
        return [parse_level(spec) for spec in args.level]
    return [b.Level(args.depth, args.time)]


def _profile(args) -> dict[str, float]:
    """The --planner constant set, or an empty dict. Individual flags win."""
    name = getattr(args, "planner", None)
    return dict(b.PLANNER_PROFILES[name]) if name else {}


def _msw_per_bar(args) -> float:
    """Metres of water per bar: explicit --msw-per-bar wins, then --water if it
    was given, then the --planner profile."""
    if getattr(args, "msw_per_bar", None) is not None:
        return args.msw_per_bar
    prof = _profile(args)
    if prof and getattr(args, "water", "salt") == "salt":
        return prof["msw_per_bar"]
    return b.WATER_TYPES[getattr(args, "water", "salt")]


def _surface_p(args) -> float:
    """Surface pressure in bar: explicit --surface-p wins, then --altitude,
    then the --planner profile."""
    if getattr(args, "surface_p", None) is not None:
        return args.surface_p
    if getattr(args, "altitude", 0.0):
        return b.surface_p_at_altitude(args.altitude)
    prof = _profile(args)
    return prof["surface_p"] if prof else b.P_ATM


def _p_h2o(args) -> float:
    """Alveolar water vapour: explicit --p-h2o wins over the profile."""
    if getattr(args, "p_h2o", None) is not None:
        return args.p_h2o
    return _profile(args).get("p_h2o", b.P_H2O)


def _build_plan(args) -> b.DivePlan:
    return b.DivePlan(
        surface_p=_surface_p(args),
        msw_per_bar=_msw_per_bar(args),
        descent_rate=args.descent_rate,
        ascent_rate=args.ascent_rate,
        stop_interval=args.stop_interval,
        last_stop_depth=args.last_stop,
        gf_low=args.gf_low,
        gf_high=args.gf_high,
        travel_gases=tuple(parse_gas_spec(g)[0] for g in (args.travel_gas or [])),
        deco_gases=tuple(parse_gas_spec(g)[0] for g in (args.deco_gas or [])),
        ppo2_deco=args.ppo2_deco,
        ppo2_bottom=args.ppo2_bottom,
        ppo2_min=args.ppo2_min,
        ppo2_switch_tol=args.ppo2_switch_tol,
        gas_switch_policy=args.gas_switch_policy,
        min_stop_time=args.min_stop_time,
        p_h2o=_p_h2o(args),
    )


def _args_gas_context(args):
    """Build (GasPlan, gases) from CLI args, where gases is a list of
    (role, Gas, tank_l, pressure_bar).

    There is **always** a GasPlan: gas estimates are part of a plan, not an
    extra unlocked by remembering a flag, so without ``--sac`` the baseline
    falls back to `report.DEFAULT_SAC` and the output says it was assumed
    (DECISIONS.md #28). ``--no-emergency`` drops the reserve accounting."""
    bg, bt, bp = parse_gas_spec(args.gas)
    gases = [("Bottom", bg, bt if bt is not None else float(args.tank_size or 0),
              bp if bp is not None else rp.DEFAULT_FILL_BAR)]
    for spec in (args.travel_gas or []):
        g, t, pr = parse_gas_spec(spec)
        gases.append(("Travel", g, float(t or 0),
                      pr if pr is not None else rp.DEFAULT_FILL_BAR))
    for spec in (args.deco_gas or []):
        g, t, pr = parse_gas_spec(spec)
        gases.append(("Deco", g, float(t or 0),
                      pr if pr is not None else rp.DEFAULT_FILL_BAR))
    gp = b.GasPlan(sac=args.sac if args.sac is not None else rp.DEFAULT_SAC,
                   sac_deco=args.sac_deco,
                   sac_emergency=args.sac_emergency or 0.0,
                   problem_minutes=args.problem_time, divers=args.divers,
                   emergency=args.emergency,
                   turn_pressure=args.turn_pressure,
                   turn_rule=args.turn_rule)
    return gp, gases


def _config_from_args(args) -> dict:
    """Serialise the CLI dive into a dive_config dict (for --save), using the
    canonical schema: levels are pure depth/time periods and gas is chosen
    automatically by role, so no per-level gas references are written."""
    gp, gases = _args_gas_context(args)
    sac = gp.sac
    counts: tuple[int | None, ...] = (None, None, None, None)
    if args.contingency is not None:
        counts = parse_contingency(args.contingency)
    c_default = dc.default_config()["contingency"]
    gas_entries = [{"role": role,
                    "o2": round(g.fO2 * 100), "he": round(g.fHe * 100),
                    "tank_l": tk, "pressure_bar": pr}
                   for role, g, tk, pr in gases]

    # `levels` is dive 1; `repeats` are the dives after it, each carrying the
    # surface interval that precedes it (dive_config.REPEAT_KEYS).
    if getattr(args, "dive", None):
        parsed = [parse_dive(d) for d in args.dive]
        levels = [_level_dict(parsed[0][1])]
        repeats = [{"surface_interval_min": si, "levels": [_level_dict(lv)]}
                   for si, lv in parsed[1:]]
    else:
        levels = [_level_dict(l) for l in _args_levels(args)]
        repeats = []
    return {
        "levels": levels,
        "repeats": repeats,
        "gf_low": round(args.gf_low * 100), "gf_high": round(args.gf_high * 100),
        "sac_normal": sac, "sac_deco": args.sac_deco,
        # `gp` has already resolved "no --sac-emergency" into a real rate, so
        # the saved file states the emergency SAC the plan was made at rather
        # than a blank the GUI would have to re-derive.
        "emergency": args.emergency, "sac_emergency": gp.sac_emergency,
        "turn_pressure": args.turn_pressure, "turn_rule": args.turn_rule,
        "problem_minutes": args.problem_time, "divers": args.divers,
        "ascent_rate": args.ascent_rate,
        "descent_rate": args.descent_rate,
        "stop_interval": args.stop_interval,
        "last_stop_m": args.last_stop,
        "ppo2_bottom": args.ppo2_bottom,
        "ppo2_deco": args.ppo2_deco,
        "ppo2_min": args.ppo2_min,
        "ppo2_switch_tol": args.ppo2_switch_tol,
        "gas_switch_policy": args.gas_switch_policy,
        "min_stop_time": args.min_stop_time,
        "surface_p_bar": _surface_p(args),
        "msw_per_bar": _msw_per_bar(args),
        "p_h2o_bar": _p_h2o(args),
        "contingency": {k: (n if n is not None else c_default[k])
                        for k, n in zip(dc.CONTINGENCY_KEYS, counts, strict=True)},
        "gases": gas_entries,
    }


def _gas_output(rep, max_depth: float, sac_assumed: bool = False):
    """(json_dict, text_lines) rendering a ``report.GasReport``, or (None, [])
    when no GasPlan was supplied. All figures come from the shared report
    layer; this only formats them.

    Two shapes, one per gas plan. With the emergency block on, every cylinder
    also carries the emergency total (need + rock-bottom reserve) and the
    report ends on the rock-bottom/turn-pressure line. With it off, none of
    that is printed *or* put in the JSON — an agent reading ``emergency:
    false`` and finding no reserve keys learns the truth, where a zero would
    read as "no reserve needed"."""
    if rep is None:
        return None, []
    gp = rep.plan
    baseline = (f"Gas  need vs have (SAC {gp.sac:g} L/min"
                + (" assumed — pass --sac" if sac_assumed else "") + ")")
    if rep.emergency:
        shared = f" × {gp.divers} divers" if gp.divers > 1 else ""
        lines = [f"{baseline}  ·  emrg in parens = need + rock-bottom reserve:"
                 f" problem {gp.problem_minutes:g} min @ max depth +"
                 f" ascent/deco at {gp.sac_emergency:g} L/min{shared}:"]
    else:
        lines = [f"{baseline}  ·  emergency reserve off:"]
    if gp.sac_deco is not None:
        lines.append(f"  SAC {gp.sac:g} L/min bottom · {gp.sac_deco:g} L/min "
                     "on the deco gases")
    cylinders = []
    for c in rep.cylinders:
        entry = {"gas": repr(c.gas), "role": c.role,
                 "liters": round(c.liters, 1),
                 "tank_l": c.tank_l, "pressure_bar": c.pressure_bar}
        # " (emrg …)" fragments, empty when no emergency was asked for.
        emrg_l = ("" if c.liters_emergency is None
                  else f" (emrg {c.liters_emergency:.0f})")
        if c.tank_l <= 0:
            if c.liters_emergency is not None:
                entry["liters_emergency"] = round(c.liters_emergency, 1)
            lines.append(f"  {c.role} {c.gas!r}: {c.liters:.0f} L{emrg_l}"
                         " (no tank set)")
        else:
            used, used_e = c.bar_used, c.bar_used_emergency
            entry["bar_used"] = round(used, 1)
            if c.liters_emergency is not None:
                entry["liters_emergency"] = round(c.liters_emergency, 1)
                entry["bar_used_emergency"] = round(used_e, 1)
            if c.pressure_bar > 0:
                entry["bar_left"] = round(c.bar_left, 1)
                short = " SHORT!" if c.short else ""
                emrg = ""
                if used_e is not None:
                    entry["bar_left_emergency"] = round(c.bar_left_emergency, 1)
                    emrg = (f" (emrg {used_e:.0f}"
                            + (" SHORT!" if c.short_emergency else "") + ")")
                lines.append(f"  {c.role} {c.gas!r}: {used:.0f} bar need vs "
                             f"{c.pressure_bar:.0f}"
                             f" fill{short} ({c.bar_left:.0f} left)"
                             f"{emrg} / {c.tank_l:.0f} L")
            else:
                emrg = "" if used_e is None else f" (emrg {used_e:.0f})"
                lines.append(f"  {c.role} {c.gas!r}: {used:.0f} bar need / "
                             f"{c.tank_l:.0f} L{emrg}")
        cylinders.append(entry)
    data = {"sac_normal_l_min": gp.sac, "sac_deco_l_min": gp.sac_deco,
            "sac_assumed": sac_assumed,
            "emergency": rep.emergency, "cylinders": cylinders}
    if not rep.emergency:
        lines.append("  (cylinder litres are ideal-gas: a 232 bar fill actually "
                     "holds ~5% less, 300 bar ~10%)")
        return data, lines
    data.update({"sac_emergency_l_min": gp.sac_emergency,
                 "problem_minutes": gp.problem_minutes, "divers": gp.divers,
                 "rock_bottom_l": round(rep.rock_bottom_l, 1)})
    rock_bar = rep.rock_bottom_bar
    if rock_bar is not None:
        data["rock_bottom_bar"] = round(rock_bar, 1)
        line = f"  Rock bottom: {rock_bar:.0f} bar reserve (back gas)"
        if rep.back_pressure_bar > 0:
            turn = rep.turn_pressure_bar
            if turn is not None:
                data["turn_pressure_bar"] = round(turn, 1)
                data["turn_rule"] = gp.turn_rule
                data["turn_reserve_bar"] = round(rep.turn_reserve_bar, 1)
                line += (f"; from {rep.back_pressure_bar:.0f} turn "
                         f"~{turn:.0f} bar ({gp.turn_rule})")
                # A third of the fill knows nothing about the profile, so it
                # can leave the team surfacing on less than minimum gas. That
                # is a finding, not a formatting detail.
                if rep.turn_below_rock_bottom:
                    data["turn_below_rock_bottom"] = True
                    line += (f" — leaves {rep.turn_reserve_bar:.0f} bar, under"
                             f" the {rock_bar:.0f} bar reserve!")
            elif gp.turn_pressure:
                # Wanted one, could not have one: rock bottom is the whole fill
                # (or more), so there is no usable gas to halve.
                line += f" — over the {rep.back_pressure_bar:.0f} bar fill!"
        lines.append(line)
    else:
        lines.append(f"  Rock bottom: {rep.rock_bottom_l:.0f} L "
                     "(set bottom-gas tank for bar)")
    lines.append("  (cylinder litres are ideal-gas: a 232 bar fill actually "
                 "holds ~5% less, 300 bar ~10%)")
    return data, lines


def _contingency_output(grid, planned_depth: float, planned_time: float):
    """(json_dict, text_lines) for the cut-table matrix from
    ``buhlmann.contingency_schedules``: rows = bottom-time variants, columns =
    depth variants, each cell the stop schedule as 'depth:min' pairs plus the
    TTS rounded up to whole minutes, the wetnotes way ('no deco' when clean,
    'n/a' when unplannable); '*' marks the planned row and column."""
    rows: list[dict] = []
    data: dict = {"time_step_min": ct.CONTINGENCY_TIME_STEP,
                  "depth_step_m": ct.CONTINGENCY_DEPTH_STEP,
                  "depths_m": [c.depth for c in grid[0]], "rows": rows}
    for row in grid:
        cells = []
        for c in row:
            entry = {"depth_m": c.depth, "plannable": c.segments is not None}
            if c.segments is not None:
                entry["stops"] = [{"depth_m": s.depth_start,
                                   "min": round(s.duration, 1)}
                                  for s in c.segments if s.kind == "stop"]
                entry["tts_min"] = round(b.time_to_surface(c.segments), 2)
                entry["runtime_min"] = round(b.total_runtime(c.segments), 2)
            cells.append(entry)
        rows.append({"bottom_time_min": row[0].bottom_time, "cells": cells})

    lines = ["", "Contingency cut table (square profile at max depth, steps "
                 f"{ct.CONTINGENCY_TIME_STEP:g} min × {ct.CONTINGENCY_DEPTH_STEP:g}"
                 " m, * = planned; cell: stop depth:min · TTS rounded UP):"]
    heads = [f"{c.depth:g} m" + ("*" if abs(c.depth - planned_depth) < 1e-9
                                 else "") for c in grid[0]]
    texts = [[c.text() for c in row] for row in grid]
    widths = [max(len(heads[j]), max(len(t[j]) for t in texts))
              for j in range(len(heads))]
    corner = "time\\depth"
    lines.append((f"    {corner:<11}"
                  + "  ".join(f"{heads[j]:<{widths[j]}}"
                              for j in range(len(heads)))).rstrip())
    for row, txt in zip(grid, texts, strict=True):
        label = f"{row[0].bottom_time:g}′" + (
            "*" if abs(row[0].bottom_time - planned_time) < 1e-9 else "")
        lines.append((f"    {label:<11}"
                      + "  ".join(f"{txt[j]:<{widths[j]}}"
                                  for j in range(len(heads)))).rstrip())
    return data, lines


def cmd_plan(args) -> int:
    load_path = args.config or args.load
    if load_path:
        # A typo'd path or a broken hand-edit must never silently plan the
        # default dive — that is the worst failure mode for planning software.
        try:
            cfg = dc.load(load_path, strict=True)
        except FileNotFoundError:
            print(f"plan: config '{load_path}' not found.", file=sys.stderr)
            return 2
        except json.JSONDecodeError as e:
            print(f"plan: config '{load_path}' is not readable JSON: {e}",
                  file=sys.stderr)
            return 2
        except (OSError, ValueError) as e:
            # Valid JSON, invalid dive: a mistyped key, an out-of-range mix, a
            # level missing its runtime. Saying "not readable JSON" here sent
            # the reader looking for a comma that was never the problem.
            print(f"plan: config '{load_path}': {e}", file=sys.stderr)
            return 2
        print(f"plan: dive loaded from '{load_path}' — CLI profile/gas/GF "
              "flags are ignored (edit the config instead).", file=sys.stderr)
        try:
            bottom, plan, gp, gas_rows = dc.to_buhlmann(cfg)
        except ValueError as e:
            print(f"plan: {e}", file=sys.stderr)
            return 2
        series = dc.series_of(cfg)
        gf_low, gf_high = cfg["gf_low"] / 100.0, cfg["gf_high"] / 100.0
    else:
        if args.dive and (args.level or args.depth is not None
                          or args.time is not None):
            print("plan: --dive describes a whole series, so it cannot be "
                  "combined with --depth/--time/--level.", file=sys.stderr)
            return 2
        if not args.dive and not args.level and (args.depth is None
                                                 or args.time is None):
            print("plan: --depth and --time (or --level DEPTH:RUNTIME, or "
                  "--dive DEPTH:RUNTIME[:SI]) are required (or pass a config "
                  "file / --load).", file=sys.stderr)
            return 2
        try:
            bottom = parse_gas_spec(args.gas)[0]
            plan = _build_plan(args)          # validates the gradient factors
            if args.dive:
                first, *rest = [parse_dive(d) for d in args.dive]
                if first[0]:
                    print("plan: the first --dive cannot have a surface "
                          "interval — nothing precedes it.", file=sys.stderr)
                    return 2
                series = [(si, [lv]) for si, lv in [first, *rest]]
            else:
                series = [(0.0, _args_levels(args))]
            gp, gas_rows = _args_gas_context(args)
        except ValueError as e:
            print(f"plan: {e}", file=sys.stderr)
            return 2
        gf_low, gf_high = args.gf_low, args.gf_high

    counts4: tuple[int, int, int, int] | None = None
    if args.contingency is not None:
        try:
            counts = parse_contingency(args.contingency)
        except ValueError as e:
            print(f"plan: {e}", file=sys.stderr)
            return 2
        base = dc.contingency_of(cfg if load_path else {})
        tb, ta, db, da = (dflt if given is None else given
                          for dflt, given in zip(base, counts, strict=True))
        counts4 = (tb, ta, db, da)

    try:
        results = rp.compute_series_result(series, bottom, plan, gp, gas_rows,
                                           contingency=counts4)
    except ValueError as e:
        print(f"plan: {e}", file=sys.stderr)
        return 2

    if args.dive_index is not None:
        if not 1 <= args.dive_index <= len(results):
            print(f"plan: --dive-index {args.dive_index} is outside the "
                  f"series (1..{len(results)}).", file=sys.stderr)
            return 2
        shown = [(args.dive_index, results[args.dive_index - 1])]
    else:
        shown = list(enumerate(results, start=1))

    model_label = f"Bühlmann GF {int(gf_low * 100)}/{int(gf_high * 100)}"
    saved_to = dc.save(cfg if load_path else _config_from_args(args),
                       args.save) if args.save else None

    # Two separate accumulators, not one list of "either": the JSON and text
    # projections have nothing in common but the loop that builds them.
    json_dives: list[dict] = []
    text_lines: list[str] = []
    for n, res in shown:
        # A config always states its SAC; only a flagless command line assumes
        # one, and then the output says so rather than quoting litres that
        # nobody chose.
        gas_data, gas_lines = _gas_output(
            res.gas, res.max_depth_m,
            sac_assumed=not load_path and args.sac is None)
        cont_data, cont_lines = None, []
        if res.contingency is not None:
            cont_data, cont_lines = _contingency_output(
                res.contingency, res.max_depth_m, res.levels[-1].runtime)
        # The surface interval belongs to the gap before the dive, so dive 1
        # never has one: it is the only dive that starts on clean tissues.
        interval = series[n - 1][0] if n > 1 else None
        if args.json:
            data = _plan_json(res, model_label, gas_data, cont_data,
                              saved_to if n == len(results) else None)
            data["dive"] = n
            data["surface_interval_min"] = interval
            json_dives.append(data)
        else:
            if len(results) > 1:
                text_lines.append(
                    f"\n=== Dive {n} of {len(results)}"
                    + (f"  ·  after {interval:g} min on the surface"
                       if interval is not None else "  ·  first dive")
                    + " ===")
            text_lines.extend(_plan_text(
                res, model_label, gas_lines, cont_lines,
                saved_to if n == len(results) else None))

    # The oxygen clocks are the one thing a day accumulates that the per-dive
    # results cannot show: OTU is a *daily* Repex dose by definition, and CNS
    # carries across the surface intervals decaying as it goes. Only for a real
    # series — a single dive's totals are its own figures (DECISIONS.md #33).
    totals = (rp.series_totals(results, series) if len(results) > 1 else None)

    if args.json:
        # A single dive keeps the flat shape it has always had, so nothing that
        # reads `deco plan --json` today has to learn about series.
        single = len(results) == 1 and args.dive_index is None
        if single:
            print(json.dumps(json_dives[0], indent=2))
        else:
            out: dict = {"dives": json_dives}
            if totals is not None:
                out["day_totals"] = {"cns_pct": round(totals.cns_pct, 1),
                                     "otu": round(totals.otu, 1),
                                     "warnings": totals.warnings}
            print(json.dumps(out, indent=2))
    else:
        for line in text_lines:
            print(line)
        if totals is not None and args.dive_index is None:
            print(f"\n=== Day total over {len(results)} dives ===")
            print(f"CNS {totals.cns_pct:.0f}% (carried across the surface "
                  f"intervals) · OTU {totals.otu:.0f} "
                  f"of {tox.OTU_DAILY_LIMIT:.0f} daily")
            for w in totals.warnings:
                print(f"⚠  {w}")
    return 0


def _plan_json(res: rp.PlanResult, model_label: str, gas_data, cont_data,
               saved_to) -> dict:
    """The --json projection of a PlanResult."""
    # `leg_pressures` guarantees one entry per stop leg, so the zips below are
    # strict: a length mismatch is a bug in the report layer, not something to
    # paper over with a short iterator.
    legs = b.stop_legs(res.segments)
    bars = res.leg_bars or [None] * len(legs)
    out = {
        "model": model_label,
        "input": {"levels": [_level_dict(l) for l in res.levels],
                  "max_depth_m": round(res.max_depth_m, 2),
                  "avg_depth_m": round(res.avg_depth_m, 2),
                  "gas": repr(res.bottom_gas),
                  "travel_gases": [repr(g) for g in res.plan.travel_gases],
                  "deco_gases": [repr(g) for g in res.plan.deco_gases],
                  "surface_p_bar": res.plan.surface_p,
                  "msw_per_bar": res.plan.msw_per_bar,
                  "p_h2o_bar": res.plan.p_h2o},
        "segments": [s.as_dict() for s in res.segments],
        # The printed-schedule notation (buhlmann.StopLeg), so an agent reads
        # the same numbers the runtime card and the GUI show: `run` is when you
        # LEAVE that stop (truncated to whole minutes) and `leg` is the ascent
        # to it plus the hold. `segments` above is the raw, untruncated dump.
        "stops": [{"depth_m": l.depth, "leg_min": l.leg, "run_min": l.run,
                   "hold_min": round(l.hold, 2), "gas": repr(l.gas),
                   "ead_m": round(l.gas.end(l.depth, res.plan.surface_p,
                                            res.plan.msw_per_bar,
                                            o2_narcotic=False), 1),
                   "end_bar": None if bar is None else round(bar, 1)}
                  for l, bar in zip(legs, bars, strict=True)],
        "backup_line": res.backup,
        # Losing the BOTTOM gas: the ascent re-flown on the remaining stack.
        # null means it cannot be survived on this stack — a finding, not a
        # missing key (see buhlmann.bailout_schedule).
        "bailout_bottom_gas": None if res.bailout is None else {
            "tts_min": round(b.time_to_surface(res.bailout), 2),
            "stops": [{"depth_m": l.depth, "leg_min": l.leg, "run_min": l.run,
                       "gas": repr(l.gas)}
                      for l in b.stop_legs(res.bailout)],
        },
        "total_runtime_min": round(res.total_runtime_min, 2),
        "tts_min": round(res.tts_min, 2),
        "final_ceiling_m": round(res.surface_ceiling_m, 2),
        "surf_gf": round(res.surf_gf, 4),
        "cns_pct": round(res.cns_pct, 1),
        "otu": round(res.otu, 1),
        "end_m": round(res.end_m, 1),
        "gas_density_g_l": round(res.density_g_l, 2),
        "gas_stack": [{"gas": repr(r.gas), "role": r.role,
                       "mod_m": round(r.mod_m, 1),
                       "end_m": round(r.end_m, 1),
                       "ead_m": round(r.ead_m, 1),
                       "density_g_l": round(r.density_g_l, 2)}
                      for r in res.gas_stack],
        "warnings": res.warnings,
        "notices": res.notices,
    }
    if gas_data is not None:
        out["gas"] = gas_data
    if cont_data is not None:
        out["contingency"] = cont_data
    if saved_to:
        out["saved_to"] = saved_to
    return out


def _plan_text(res: rp.PlanResult, model_label: str, gas_lines, cont_lines,
               saved_to) -> list[str]:
    """The human-readable projection of a PlanResult, one line per entry."""
    levels, plan, depth = res.levels, res.plan, res.max_depth_m
    if len(levels) == 1:
        profile = f"bottom {depth:g} m for {levels[0].runtime:g} min"
    else:
        profile = " → ".join(f"{l.depth:g} m @ {l.runtime:g} min"
                             for l in levels)
        profile = f"{len(levels)} levels: {profile}"
    lines = [f"\nDive plan  {model_label}  {profile} on {res.bottom_gas!r}"]
    if len(levels) > 1:
        lines.append(f"Max depth {depth:g} m · average depth "
                     f"{res.avg_depth_m:.1f} m")
    lines.append(
        f"Bottom gas @ {depth:g} m: ppO₂ "
        f"{res.bottom_gas.ppo2(depth, plan.surface_p, plan.msw_per_bar):.2f}"
        f" bar · END {res.end_m:.0f} m (O₂ narcotic) · density "
        f"{res.density_g_l:.1f} g/L")
    # Only worth a line when the dive is NOT sea-level salt water: those two
    # constants move every pressure below, so a fresh-water or altitude plan
    # must say so rather than look like a plain sea dive.
    note = rp.environment_note(plan)
    if note:
        lines.append(f"Water: {note}")
    # Every mix quoted at its OWN MOD — the deepest it would ever be breathed.
    # The line above quotes the bottom gas at the actual bottom depth, which is
    # a different question ("what am I breathing down there") from this one
    # ("is each mix safe at the worst depth it is planned for").
    if res.gas_stack:
        lines.append(f"{'gas stack':<14}{'role':>8}{'MOD':>7}{'END':>7}"
                     f"{'EAD':>7}{'ρ g/L':>8}")
        for r in res.gas_stack:
            flag = " ⚠" if r.dense else ""
            lines.append(f"{r.gas!r:<14}{r.role:>8}{r.mod_m:>7.1f}"
                         f"{r.end_m:>7.1f}{r.ead_m:>7.1f}"
                         f"{r.density_g_l:>8.1f}{flag}")
    lines.append("-" * 78)
    lines.append(f"{'segment':<10}{'from':>7}{'to':>7}{'min':>8}{'run':>8}"
                 f"{'gas':>14}{'EAD':>7}{'GF':>6}")
    lines.append("-" * 78)
    run = 0.0
    for s in res.segments:
        run += s.duration
        gf = "" if s.gf_used is None else f"{s.gf_used:.2f}"
        # Quoted at the segment's deepest point: narcosis is a worst-case
        # number, and on an ascent leg the start is the deep end.
        ead = s.gas.end(max(s.depth_start, s.depth_end), plan.surface_p,
                        plan.msw_per_bar, o2_narcotic=False)
        lines.append(f"{s.kind:<10}{s.depth_start:>7.1f}{s.depth_end:>7.1f}"
                     f"{s.duration:>8.1f}{run:>8.1f}{s.gas!r:>14}"
                     f"{ead:>7.1f}{gf:>6}")
    lines.append("-" * 78)
    lines.append(f"Total runtime: {res.total_runtime_min:.1f} min    "
                 f"Time to surface (TTS): {res.tts_min:.1f} min")
    legs = b.stop_legs(res.segments)
    if legs:
        # The card/GUI notation alongside the raw segment dump above: `run` is
        # when you LEAVE the stop, truncated; the minutes are the leg (ascent
        # to the stop + hold), so they add up to the runtimes.
        # With cylinders on the stack each stop also carries the pressure the
        # diver should see leaving it — the one gas figure an SPG can check.
        # The bar figure is the pressure of the cylinder IN USE at that stop,
        # so it jumps stack when the gas switches (124 back-gas → 196 on the
        # 50 %). The framed card has a gas column that says which; this
        # one-liner did not, leaving a column of numbers off three different
        # SPGs with nothing to tell them apart. Name the mix wherever it
        # changes — the same "only where it changes" rule `backup_line` uses.
        bars = res.leg_bars or [None] * len(legs)
        parts = []
        prev_gas: b.Gas | None = None
        for leg, bar in zip(legs, bars, strict=True):
            part = f"{leg.depth:g}m {leg.leg:d}′@{leg.run:d}"
            if bar is not None:
                tag = "" if leg.gas == prev_gas else f" {leg.gas!r}"
                part += f"{tag} {bar:.0f}bar"
            parts.append(part)
            prev_gas = leg.gas
        lines.append("Stops as printed on a card (leave-at runtime · leg min): "
                     + "  ".join(parts))
    lines.append(f"Backup line: {res.backup}")
    # The one contingency the deco-gas scenarios cannot express. Usually "no",
    # and saying so plainly is the point: it is what decides whether the stage
    # on your hip is a bailout or only an accelerant.
    if res.bailout is None:
        # NOT "not survivable": nothing on the stack is breathable AT MAX
        # DEPTH, which is the ordinary state of a 30 m twinset dive carrying
        # EAN50 and O2 — you ascend to 21 m and take the 50 %. What cannot be
        # planned is a schedule *from depth* on the remaining gas; calling that
        # a survivability verdict states something the model never computed
        # (DECISIONS.md #33).
        lines.append("Lost bottom gas: no schedule from depth — nothing else "
                     f"on the stack is breathable at {res.max_depth_m:g} m "
                     "(ascend on a buddy's gas to the shallowest mix's MOD)")
    else:
        lines.append(f"Lost bottom gas: TTS {b.time_to_surface(res.bailout):.0f}"
                     f" min on " + ", ".join(
                         dict.fromkeys(repr(l.gas)
                                       for l in b.stop_legs(res.bailout))))
    lines.append(f"CNS {res.cns_pct:.0f}% · OTU {res.otu:.0f}    "
                 f"Surface ceiling at GF-High: {res.surface_ceiling_m:.2f} m"
                 f"    SurfGF {res.surf_gf * 100:.0f}%")
    lines.extend(f"⚠  {w}" for w in res.warnings)
    # Notices, not warnings: what the planner chose on the diver's behalf.
    lines.extend(f"·  {n}" for n in res.notices)
    lines.extend(gas_lines)
    lines.extend(cont_lines)
    if saved_to:
        lines.append(f"Saved dive to {saved_to}")
    return lines


def cmd_ndl(args) -> int:
    try:
        plan = _build_plan(args)
        gas = parse_gas(args.gas)
    except ValueError as e:
        print(f"ndl: {e}", file=sys.stderr)
        return 2
    n = b.ndl(args.depth, gas, plan)
    label = "(>10h)" if n is None else f"{n} min"
    if args.json:
        print(json.dumps({"depth_m": args.depth, "gas": args.gas,
                          "gf_high": args.gf_high, "ndl_min": n}))
    else:
        print(f"NDL at {args.depth} m on {gas!r} "
              f"(Bühlmann GF-High {args.gf_high:.2f}): {label}")
    return 0


def cmd_tissues(args) -> int:
    try:
        plan = _build_plan(args)
        gas = parse_gas(args.gas)
    except ValueError as e:
        print(f"tissues: {e}", file=sys.stderr)
        return 2
    _segs, tissues = b.plan_dive(args.depth, args.time, gas, plan)
    rows = []
    for i in range(b.N_COMP):
        p_comp = tissues.pN2[i] + tissues.pHe[i]
        a, bv = b.compartment_ab(tissues.pN2[i], tissues.pHe[i], i)
        rows.append({
            "compartment": i + 1,
            "halftime_N2_min": b.N2_HALFTIME[i],
            "pN2_bar": round(tissues.pN2[i], 4),
            "pHe_bar": round(tissues.pHe[i], 4),
            "p_total_bar": round(p_comp, 4),
            "a": round(a, 4), "b": round(bv, 4),
        })
    if args.json:
        print(json.dumps({"compartments": rows}, indent=2))
        return 0
    print(f"\nTissue loading after {args.time} min @ {args.depth} m on {gas!r}")
    print(f"{'#':>3}{'t½N2':>8}{'pN2':>10}{'pHe':>10}{'pTot':>10}{'a':>9}{'b':>9}")
    for r in rows:
        print(f"{r['compartment']:>3}{r['halftime_N2_min']:>8.1f}"
              f"{r['pN2_bar']:>10.4f}{r['pHe_bar']:>10.4f}{r['p_total_bar']:>10.4f}"
              f"{r['a']:>9.4f}{r['b']:>9.4f}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="deco",
        description="Bühlmann ZHL-16C + Gradient Factor dive planner.")
    # Shared options
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--gf-low", type=float, default=0.30,
                        help="default 0.30")
    common.add_argument("--gf-high", type=float, default=0.70,
                        help="default 0.70 (same as the GUI/config default)")
    common.add_argument("--descent-rate", type=_positive_float, default=18.0,
                        help="m/min")
    common.add_argument("--ascent-rate", type=_positive_float, default=10.0,
                        help="m/min")
    common.add_argument("--stop-interval", type=_positive_float, default=3.0,
                        help="m")
    common.add_argument("--last-stop", type=_nonneg_float, default=3.0,
                        help="shallowest stop depth in m "
                             "(6 = Shearwater-style last stop at 6 m)")
    common.add_argument("--travel-gas", action="append",
                        help="Descent/travel gas for a hypoxic bottom mix. Repeatable.")
    common.add_argument("--deco-gas", action="append",
                        help="e.g. 50, ean50, 100, 21/35. Repeatable.")
    common.add_argument("--ppo2-deco", type=_positive_float, default=1.6,
                        help="ppO2 ceiling for deco gases on ascent.")
    common.add_argument("--ppo2-bottom", type=_positive_float, default=1.4,
                        help="ppO2 ceiling for the bottom/travel gas on descent.")
    common.add_argument("--ppo2-min", type=_nonneg_float, default=0.18,
                        help="Hypoxia floor; a gas is unusable below this ppO2.")
    common.add_argument("--min-stop-time", type=_positive_float, default=1.0,
                        help="Grid a stop's runtime is padded onto (min) — "
                             "Baker's Minimum_Deco_Stop_Time. 1 makes a "
                             "table-friendly schedule; 0.1 a near-continuous "
                             "one.")
    common.add_argument("--ppo2-switch-tol", type=_nonneg_float, default=0.05,
                        help="How far over --ppo2-deco a gas switch may be "
                             "rounded deeper to land on a stop depth (bar). "
                             "0.05 is what puts O2 on the 6 m stop.")
    common.add_argument("--dive", dest="dive", action="append", metavar="SPEC",
                        help="One square dive of a repetitive series, "
                             "DEPTH:RUNTIME[:SURFACE_INTERVAL] (the interval "
                             "is the surface time BEFORE this dive, minutes). "
                             "Repeatable, one per dive; residual loading is "
                             "carried through. Multi-level series come from a "
                             "config's 'repeats'. Not combinable with "
                             "--depth/--time/--level.")
    common.add_argument("--dive-index", type=int, metavar="N",
                        help="Print only dive N of a series (1-based). "
                             "Default: every dive.")
    common.add_argument("--gas-switch", dest="gas_switch_policy",
                        choices=sorted(b.GAS_SWITCH_POLICIES),
                        default="at-mod",
                        help="WHERE a deco gas is taken. 'at-mod' (default) "
                             "switches as soon as the ppO2 allows, at the "
                             "stop depth the MOD snaps to. 'at-first-stop' "
                             "holds every deco switch until the first stop, "
                             "the team convention of arriving before "
                             "switching; it lengthens the deco, never "
                             "shortens it. Note a real Shearwater Predator "
                             "does neither exactly: it switches only at a "
                             "stop it actually holds (see DECISIONS.md #27).")
    common.add_argument("--p-h2o", type=_positive_float, default=None,
                        help=f"Alveolar water-vapour pressure (bar). Default "
                             f"{b.P_H2O:g} (Schreiner) — what MultiDeco, "
                             "Shearwater and Baker's GFDECO use; Buhlmann's "
                             f"own is {b.P_H2O_BUHLMANN:g} (Subsurface's).")
    common.add_argument("--planner", choices=sorted(b.PLANNER_PROFILES),
                        help="Plan in another planner's constants, so the "
                             "schedule can sit beside one of theirs: sets "
                             "P_H2O, surface pressure and metres-per-bar "
                             "together. The default already matches multideco "
                             "/ shearwater; use subsurface or buhlmann for "
                             "0.0627 water vapour. Individual flags override.")
    common.add_argument("--water", choices=sorted(b.WATER_TYPES),
                        default="salt",
                        help="Water type, i.e. how many metres make a bar: "
                             f"salt {b.MSW_PER_BAR_SALT:g} (default), fresh "
                             f"{b.MSW_PER_BAR_FRESH:.4g}. Overridden by "
                             "--msw-per-bar.")
    common.add_argument("--msw-per-bar", type=_positive_float, default=None,
                        help="Metres of water per bar, explicitly (wins over "
                             "--water).")
    common.add_argument("--altitude", type=_nonneg_float, default=0.0,
                        metavar="M",
                        help="Altitude of the dive site in m; sets the surface "
                             "pressure by the standard atmosphere (1500 m ≈ "
                             "0.845 bar). Overridden by --surface-p.")
    common.add_argument("--surface-p", type=_positive_float, default=None,
                        help=f"Surface pressure in bar, explicitly (wins over "
                             f"--altitude). Default {b.P_ATM:g} (sea level); "
                             "MultiDeco/GFDECO plans use 1.0.")
    common.add_argument("--json", action="store_true")

    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("plan", parents=[common], help="Compute a deco schedule.")
    sp.add_argument("config", nargs="?",
                    help="dive config JSON to load (same as --load), "
                         "e.g. `deco plan dive_plan.json`.")
    sp.add_argument("--depth", type=_positive_float,
                    help="bottom depth (m); square dive")
    sp.add_argument("--time", type=_positive_float,
                    help="bottom time (min); runtime at the end of the bottom")
    sp.add_argument("--level", action="append",
                    help="multi-level dive: DEPTH:RUNTIME, e.g. 45:25 (RUNTIME "
                         "is cumulative minutes since the surface, at the END of "
                         "the level, transit included — levels are contiguous). "
                         "Gas is chosen automatically by role. Repeatable; "
                         "replaces --depth/--time.")
    sp.add_argument("--gas", default="air",
                    help="bottom gas, optional @tank e.g. air@24, 21/35@24")
    sp.add_argument("--sac", type=_positive_float,
                    help=f"Baseline surface air consumption / RMV (L/min) every"
                         f" gas estimate is built on. Default"
                         f" {rp.DEFAULT_SAC:g}, and the output says when it was"
                         f" assumed.")
    sp.add_argument("--sac-deco", type=_positive_float,
                    help="Separate SAC (L/min) for gas breathed off a deco "
                         "cylinder; defaults to --sac.")
    sp.add_argument("--emergency", action=argparse.BooleanOptionalAction,
                    default=True,
                    help="Include the emergency reserve (rock bottom and the "
                         "(emrg) figures). --no-emergency drops it from every "
                         "view and from the JSON.")
    sp.add_argument("--sac-emergency", type=_positive_float,
                    help="Stressed SAC (L/min) for the emergency ascent — an "
                         "absolute rate, one for every mix. Default: twice "
                         "--sac.")
    sp.add_argument("--turn-pressure", action=argparse.BooleanOptionalAction,
                    default=True,
                    help="Print a turn pressure beside the reserve. "
                         "--no-turn-pressure drops it (a deco dive usually "
                         "turns on runtime, not on gas).")
    sp.add_argument("--turn-rule", choices=b.TURN_RULES, default="rock-bottom",
                    help="How the turn pressure is worked out: 'rock-bottom' "
                         "(half the gas above minimum gas — surfaces exactly "
                         "on the reserve) or 'thirds' (the cave rule, 2/3 of "
                         "the fill; flagged when that leaves less than rock "
                         "bottom). Default rock-bottom.")
    sp.add_argument("--problem-time", type=_nonneg_float, default=1.0,
                    help="Minutes solving the problem at max depth (rock bottom"
                         " and the end-of-bottom emergency gas need).")
    sp.add_argument("--divers", type=_positive_int, default=1,
                    help="Divers sharing the supply in the emergency (2 = buddy"
                         " out of gas, sharing every litre of the ascent, deco"
                         " stages included). Scales rock bottom too. Default 1.")
    sp.add_argument("--tank-size", type=_positive_float,
                    help="Bottom-gas cylinder volume (L); or use --gas mix@litres.")
    sp.add_argument("--contingency", nargs="?", const="",
                    metavar="TB[:TA[:DB[:DA]]]",
                    help="Backup cut-table matrix for a bottom timer: square-"
                         "profile schedules on a 3 min × 3 m grid, TB/TA "
                         "bottom-time rows shorter/longer and DB/DA depth "
                         "columns shallower/deeper than planned (default from "
                         "the config, else 1:1:1:1; a zero count disables "
                         "that direction).")
    sp.add_argument("--load", nargs="?", const=dc.default_path(),
                    help="Load the dive from a JSON config (default dive_plan.json).")
    sp.add_argument("--save", nargs="?", const=dc.default_path(),
                    help="Save this dive to a JSON config (default dive_plan.json).")
    sp.set_defaults(func=cmd_plan)

    sn = sub.add_parser("ndl", parents=[common], help="No-decompression limit.")
    sn.add_argument("--depth", type=_positive_float, required=True)
    sn.add_argument("--gas", default="air")
    sn.set_defaults(func=cmd_ndl)

    st = sub.add_parser("tissues", parents=[common],
                        help="Tissue loading report after a square dive.")
    st.add_argument("--depth", type=_positive_float, required=True)
    st.add_argument("--time", type=_positive_float, required=True)
    st.add_argument("--gas", default="air")
    st.set_defaults(func=cmd_tissues)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
