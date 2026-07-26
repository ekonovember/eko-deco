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
from deco import dive_config as dc
from deco import report as rp


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


def parse_gas(spec: str) -> b.Gas:
    """Parse 'air', 'ean32', 'nx32', '32', or trimix '21/35' (= 21% O2, 35% He)."""
    s = spec.strip().lower()
    if s == "air":
        return b.AIR
    if s == "o2":
        return b.O2
    if "/" in s:
        a, c = s.split("/", 1)
        return b.Gas(float(a) / 100.0, float(c) / 100.0)
    s = s.removeprefix("ean").removeprefix("nx")
    return b.Gas(float(s) / 100.0)


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


def _build_plan(args) -> b.DivePlan:
    return b.DivePlan(
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
    )


def _args_gas_context(args):
    """Build (GasPlan|None, gases) from CLI args, where gases is a list of
    (role, Gas, tank_l, pressure_bar). GasPlan is None unless --sac was supplied."""
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
    if args.sac is None:
        return None, gases
    gp = b.GasPlan(sac=args.sac, sac_multiplier=args.sac_multiplier,
                   problem_minutes=args.problem_time, divers=args.divers)
    return gp, gases


def _config_from_args(args) -> dict:
    """Serialise the CLI dive into a dive_config dict (for --save), using the
    canonical schema: levels are pure depth/time periods and gas is chosen
    automatically by role, so no per-level gas references are written."""
    _gp, gases = _args_gas_context(args)
    sac = args.sac if args.sac is not None else 20.0
    counts: tuple[int | None, ...] = (None, None, None, None)
    if args.contingency is not None:
        counts = parse_contingency(args.contingency)
    c_default = dc.default_config()["contingency"]
    gas_entries = [{"role": role,
                    "o2": round(g.fO2 * 100), "he": round(g.fHe * 100),
                    "tank_l": tk, "pressure_bar": pr}
                   for role, g, tk, pr in gases]

    levels = [_level_dict(l) for l in _args_levels(args)]
    return {
        "levels": levels,
        "gf_low": round(args.gf_low * 100), "gf_high": round(args.gf_high * 100),
        "sac_normal": sac, "sac_multiplier": args.sac_multiplier,
        "problem_minutes": args.problem_time, "divers": args.divers,
        "ascent_rate": args.ascent_rate,
        "descent_rate": args.descent_rate,
        "stop_interval": args.stop_interval,
        "last_stop_m": args.last_stop,
        "ppo2_bottom": args.ppo2_bottom,
        "ppo2_deco": args.ppo2_deco,
        "ppo2_min": args.ppo2_min,
        "contingency": {k: (n if n is not None else c_default[k])
                        for k, n in zip(dc.CONTINGENCY_KEYS, counts, strict=True)},
        "gases": gas_entries,
    }


def _gas_output(rep, max_depth: float):
    """(json_dict, text_lines) rendering a ``report.GasReport``, or (None, [])
    when no GasPlan was supplied. All figures come from the shared report
    layer; this only formats them."""
    if rep is None:
        return None, []
    gp = rep.plan
    sac_e = gp.sac * gp.sac_multiplier
    shared = (f" × {gp.divers} divers to the first switch"
              if gp.divers > 1 else "")
    lines = [f"Gas  need vs have (emrg in parens = need + rock-bottom reserve:"
             f" problem {gp.problem_minutes:g} min @ max depth + ascent/deco to"
             f" the next switch at {sac_e:g} L/min{shared}):"]
    cylinders = []
    for c in rep.cylinders:
        entry = {"gas": repr(c.gas), "role": c.role,
                 "liters": round(c.liters, 1),
                 "liters_emergency": round(c.liters_emergency, 1),
                 "tank_l": c.tank_l, "pressure_bar": c.pressure_bar}
        if c.tank_l <= 0:
            lines.append(f"  {c.role} {c.gas!r}: {c.liters:.0f} L (emrg"
                         f" {c.liters_emergency:.0f}) (no tank set)")
        else:
            used, used_e = c.bar_used, c.bar_used_emergency
            entry["bar_used"] = round(used, 1)
            entry["bar_used_emergency"] = round(used_e, 1)
            if c.pressure_bar > 0:
                entry["bar_left"] = round(c.bar_left, 1)
                entry["bar_left_emergency"] = round(c.bar_left_emergency, 1)
                short = " SHORT!" if c.short else ""
                short_e = " SHORT!" if c.short_emergency else ""
                lines.append(f"  {c.role} {c.gas!r}: {used:.0f} bar need vs "
                             f"{c.pressure_bar:.0f}"
                             f" fill{short} ({c.bar_left:.0f} left)"
                             f" (emrg {used_e:.0f}{short_e}) / {c.tank_l:.0f} L")
            else:
                lines.append(f"  {c.role} {c.gas!r}: {used:.0f} bar need / "
                             f"{c.tank_l:.0f} L (emrg {used_e:.0f})")
        cylinders.append(entry)
    data = {"sac_normal_l_min": gp.sac, "sac_multiplier": gp.sac_multiplier,
            "sac_emergency_l_min": sac_e,
            "problem_minutes": gp.problem_minutes, "divers": gp.divers,
            "cylinders": cylinders, "rock_bottom_l": round(rep.rock_bottom_l, 1)}
    rock_bar = rep.rock_bottom_bar
    if rock_bar is not None:
        data["rock_bottom_bar"] = round(rock_bar, 1)
        line = f"  Rock bottom: {rock_bar:.0f} bar reserve (back gas)"
        if rep.back_pressure_bar > 0:
            turn = rep.turn_pressure_bar
            if turn is not None:
                data["turn_pressure_bar"] = round(turn, 1)
                line += (f"; from {rep.back_pressure_bar:.0f} turn "
                         f"~{turn:.0f} bar")
            else:
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
    data: dict = {"time_step_min": b.CONTINGENCY_TIME_STEP,
                  "depth_step_m": b.CONTINGENCY_DEPTH_STEP,
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
                 f"{b.CONTINGENCY_TIME_STEP:g} min × {b.CONTINGENCY_DEPTH_STEP:g}"
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
        except (OSError, ValueError) as e:
            print(f"plan: config '{load_path}' is not readable JSON: {e}",
                  file=sys.stderr)
            return 2
        print(f"plan: dive loaded from '{load_path}' — CLI profile/gas/GF "
              "flags are ignored (edit the config instead).", file=sys.stderr)
        try:
            bottom, plan, gp, gas_rows = dc.to_buhlmann(cfg)
        except ValueError as e:
            print(f"plan: {e}", file=sys.stderr)
            return 2
        levels = dc.levels_of(cfg)
        gf_low, gf_high = cfg["gf_low"] / 100.0, cfg["gf_high"] / 100.0
    else:
        if not args.level and (args.depth is None or args.time is None):
            print("plan: --depth and --time (or --level DEPTH:RUNTIME) are "
                  "required (or pass a config file / --load).", file=sys.stderr)
            return 2
        try:
            bottom = parse_gas_spec(args.gas)[0]
            plan = _build_plan(args)          # validates the gradient factors
            levels = _args_levels(args)
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
        res = rp.compute_plan_result(levels, bottom, plan, gp, gas_rows,
                                     contingency=counts4)
    except ValueError as e:
        print(f"plan: {e}", file=sys.stderr)
        return 2

    model_label = f"Bühlmann GF {int(gf_low * 100)}/{int(gf_high * 100)}"
    gas_data, gas_lines = _gas_output(res.gas, res.max_depth_m)
    cont_data, cont_lines = None, []
    if res.contingency is not None:
        cont_data, cont_lines = _contingency_output(res.contingency,
                                                    res.max_depth_m,
                                                    levels[-1].runtime)
    saved_to = dc.save(cfg if load_path else _config_from_args(args),
                       args.save) if args.save else None

    if args.json:
        print(json.dumps(_plan_json(res, model_label, gas_data, cont_data,
                                    saved_to), indent=2))
    else:
        for line in _plan_text(res, model_label, gas_lines, cont_lines,
                               saved_to):
            print(line)
    return 0


def _plan_json(res: rp.PlanResult, model_label: str, gas_data, cont_data,
               saved_to) -> dict:
    """The --json projection of a PlanResult."""
    out = {
        "model": model_label,
        "input": {"levels": [_level_dict(l) for l in res.levels],
                  "max_depth_m": round(res.max_depth_m, 2),
                  "avg_depth_m": round(res.avg_depth_m, 2),
                  "gas": repr(res.bottom_gas),
                  "travel_gases": [repr(g) for g in res.plan.travel_gases],
                  "deco_gases": [repr(g) for g in res.plan.deco_gases]},
        "segments": [s.as_dict() for s in res.segments],
        "total_runtime_min": round(res.total_runtime_min, 2),
        "tts_min": round(res.tts_min, 2),
        "final_ceiling_m": round(res.surface_ceiling_m, 2),
        "cns_pct": round(res.cns_pct, 1),
        "otu": round(res.otu, 1),
        "end_m": round(res.end_m, 1),
        "gas_density_g_l": round(res.density_g_l, 2),
        "warnings": res.warnings,
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
    if plan.travel_gases:
        lines.append("Travel gases: "
                     + ", ".join(repr(g) for g in plan.travel_gases))
    if plan.deco_gases:
        lines.append("Deco gases: "
                     + ", ".join(repr(g) for g in plan.deco_gases))
    lines.append("-" * 78)
    lines.append(f"{'segment':<10}{'from':>7}{'to':>7}{'min':>8}{'run':>8}"
                 f"{'gas':>14}{'GF':>6}")
    lines.append("-" * 78)
    run = 0.0
    for s in res.segments:
        run += s.duration
        gf = "" if s.gf_used is None else f"{s.gf_used:.2f}"
        lines.append(f"{s.kind:<10}{s.depth_start:>7.1f}{s.depth_end:>7.1f}"
                     f"{s.duration:>8.1f}{run:>8.1f}{s.gas!r:>14}{gf:>6}")
    lines.append("-" * 78)
    lines.append(f"Total runtime: {res.total_runtime_min:.1f} min    "
                 f"Time to surface (TTS): {res.tts_min:.1f} min")
    lines.append(f"CNS {res.cns_pct:.0f}% · OTU {res.otu:.0f}    "
                 f"Surface ceiling at GF-High: {res.surface_ceiling_m:.2f} m")
    lines.extend(f"⚠  {w}" for w in res.warnings)
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
                    help="Normal surface air consumption (L/min); enables gas planning.")
    sp.add_argument("--sac-multiplier", type=float, default=2.0,
                    help="Emergency SAC multiplier for rock bottom (e.g. 1.5); "
                         "emergency SAC = --sac x this. Default 2.0.")
    sp.add_argument("--problem-time", type=_nonneg_float, default=1.0,
                    help="Minutes solving the problem at max depth (rock bottom"
                         " and the end-of-bottom emergency gas need).")
    sp.add_argument("--divers", type=_positive_int, default=1,
                    help="Divers sharing the supply in the emergency (2 = buddy"
                         " out of gas, shared until the first gas switch)."
                         " Scales rock bottom too. Default 1.")
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
