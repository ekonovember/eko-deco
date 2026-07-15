"""CLI front-end for the Bühlmann module.

Examples
--------
    python cli.py plan --depth 30 --time 25 --gas air
    python cli.py plan --depth 45 --time 25 --gas 21/35 --deco-gas 50 --deco-gas 100
    python cli.py plan --depth 60 --time 25 --gas 10/70 --travel-gas 35/25 --deco-gas 50 --sac 18
    python cli.py ndl --depth 30 --gas air
    python cli.py tissues --depth 30 --time 25 --gas air
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import List

import buhlmann as b
import dive_config as dc

DISCLAIMER = "Educational model — NOT validated for planning real dives."


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
    gas = parse_gas(parts[0])
    tank = float(parts[1]) if len(parts) > 1 and parts[1].strip() else None
    pressure = float(parts[2]) if len(parts) > 2 and parts[2].strip() else None
    return gas, tank, pressure


def parse_level(spec: str) -> b.Level:
    """Parse a level as 'DEPTH:RUNTIME[:GAS]', e.g. '45:25' or '120:20:10/70'.

    RUNTIME is the runtime in minutes at the END of the level (cumulative,
    descent included). GAS forces a mix for the level; omit it to breathe the
    bottom gas."""
    parts = spec.split(":")
    if len(parts) not in (2, 3):
        raise ValueError(f"level '{spec}': expected DEPTH:RUNTIME[:GAS], "
                         "e.g. 45:25 or 120:20:10/70")
    try:
        depth, runtime = float(parts[0]), float(parts[1])
    except ValueError:
        raise ValueError(f"level '{spec}': depth and runtime must be numbers")
    gas = parse_gas(parts[2]) if len(parts) == 3 and parts[2].strip() else None
    return b.Level(depth, runtime, gas)


def parse_contingency(spec: str):
    """Parse a cut-table step-count spec 'TB[:TA[:DB[:DA]]]' — bottom-time rows
    3 min shorter/longer, depth columns 3 m shallower/deeper — e.g. '1:2:0:1'.
    Empty parts (and the empty string, from a bare --contingency) mean "use the
    config's value": returns a 4-tuple of count-or-None."""
    parts = spec.strip().split(":")
    if len(parts) > 4:
        raise ValueError(f"contingency '{spec}': expected TB[:TA[:DB[:DA]]], "
                         "e.g. 1 or 1:2:0:1")
    counts = []
    for p in parts + [""] * (4 - len(parts)):
        if not p.strip():
            counts.append(None)
            continue
        try:
            n = int(p)
        except ValueError:
            raise ValueError(f"contingency '{spec}': step counts must be integers")
        if n < 0:
            raise ValueError(f"contingency '{spec}': step counts must be >= 0")
        counts.append(n)
    return tuple(counts)


def _args_levels(args) -> List[b.Level]:
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
              bp if bp is not None else 232.0)]
    for spec in (args.travel_gas or []):
        g, t, pr = parse_gas_spec(spec)
        gases.append(("Travel", g, float(t or 0), pr if pr is not None else 232.0))
    for spec in (args.deco_gas or []):
        g, t, pr = parse_gas_spec(spec)
        gases.append(("Deco", g, float(t or 0), pr if pr is not None else 232.0))
    if args.sac is None:
        return None, gases
    gp = b.GasPlan(sac=args.sac, sac_multiplier=args.sac_multiplier,
                   problem_minutes=args.problem_time, divers=args.divers)
    return gp, gases


def _config_from_args(args) -> dict:
    """Serialise the CLI dive into a dive_config dict (for --save)."""
    _gp, gases = _args_gas_context(args)
    sac = args.sac if args.sac is not None else 20.0
    counts = (None, None, None, None)
    if args.contingency is not None:
        counts = parse_contingency(args.contingency)
    c_default = dc.default_config()["contingency"]
    return {
        "levels": [{"depth_m": l.depth, "runtime_min": l.runtime,
                    "gas": (None if l.gas is None
                            else {"o2": round(l.gas.fO2 * 100),
                                  "he": round(l.gas.fHe * 100)})}
                   for l in _args_levels(args)],
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
                        for k, n in zip(dc.CONTINGENCY_KEYS, counts)},
        "gases": [{"role": role, "o2": round(g.fO2 * 100), "he": round(g.fHe * 100),
                   "tank_l": tk, "pressure_bar": pr} for (role, g, tk, pr) in gases],
    }


def _percylinder_gas(segs, depth, bottom_gas, gp, gases, ascent_rate=10.0):
    """(json_dict, text_lines) for a per-cylinder gas breakdown, or (None, [])
    when no GasPlan is available."""
    if gp is None:
        return None, []
    sac = gp.sac
    sac_e = gp.sac * gp.sac_multiplier
    # Same-mix cylinders (twin bottom tanks, two identical stages) act as one
    # manifolded bank: volumes add, the fill pressure is volume-weighted.
    tank_by: dict = {}
    press_by: dict = {}
    role_by: dict = {}
    for role, g, tk, pr in gases:
        key = repr(g)
        vol = tank_by.get(key, 0.0)
        total = vol + (tk or 0.0)
        press_by[key] = ((press_by.get(key, 0.0) * vol + (pr or 0.0) * (tk or 0.0))
                         / total if total > 0 else (pr or 0.0))
        tank_by[key] = total
        role_by.setdefault(key, role)
    back_tank = tank_by.get(repr(bottom_gas), 0.0)
    back_pressure = press_by.get(repr(bottom_gas), 0.0)
    shared = (f" × {gp.divers} divers to the first switch"
              if gp.divers > 1 else "")
    lines = [f"Gas  need vs have (emrg in parens: bottom at SAC {gp.sac:g}, then"
             f" problem {gp.problem_minutes:g} min @ max depth + ascent/deco"
             f" at {sac_e:g} L/min{shared}):"]
    cylinders, seen = [], []
    for s in segs:
        if repr(s.gas) in seen:
            continue
        seen.append(repr(s.gas))
        liters = b.segment_gas_liters([x for x in segs if x.gas == s.gas], sac)
        liters_e = b.emergency_gas_liters(segs, s.gas, gp)
        tk = tank_by.get(repr(s.gas), 0.0)
        pr = press_by.get(repr(s.gas), 0.0)
        role = role_by.get(repr(s.gas), "Bottom" if s.gas == bottom_gas else "stage")
        entry = {"gas": repr(s.gas), "role": role, "liters": round(liters, 1),
                 "liters_emergency": round(liters_e, 1),
                 "tank_l": tk, "pressure_bar": pr}
        if tk <= 0:
            lines.append(f"  {role} {s.gas!r}: {liters:.0f} L (emrg"
                         f" {liters_e:.0f}) (no tank set)")
        else:
            used, used_e = liters / tk, liters_e / tk
            entry["bar_used"] = round(used, 1)
            entry["bar_used_emergency"] = round(used_e, 1)
            if pr > 0:
                entry["bar_left"] = round(pr - used, 1)
                entry["bar_left_emergency"] = round(pr - used_e, 1)
                short = " SHORT!" if used > pr + 1e-9 else ""
                short_e = " SHORT!" if used_e > pr + 1e-9 else ""
                lines.append(f"  {role} {s.gas!r}: {used:.0f} bar need vs {pr:.0f}"
                             f" fill{short} ({pr - used:.0f} left)"
                             f" (emrg {used_e:.0f}{short_e}) / {tk:.0f} L")
            else:
                lines.append(f"  {role} {s.gas!r}: {used:.0f} bar need / {tk:.0f} L"
                             f" (emrg {used_e:.0f})")
        cylinders.append(entry)
    rock = b.rock_bottom_liters(depth, gp, ascent_rate)
    data = {"sac_normal_l_min": gp.sac, "sac_multiplier": gp.sac_multiplier,
            "sac_emergency_l_min": gp.sac * gp.sac_multiplier,
            "problem_minutes": gp.problem_minutes, "divers": gp.divers,
            "cylinders": cylinders, "rock_bottom_l": round(rock, 1)}
    if back_tank > 0:
        rock_bar = rock / back_tank
        data["rock_bottom_bar"] = round(rock_bar, 1)
        line = f"  Rock bottom: {rock_bar:.0f} bar reserve (back gas)"
        if back_pressure > 0:
            usable = back_pressure - rock_bar
            if usable > 0:
                turn = back_pressure - usable / 2.0
                data["turn_pressure_bar"] = round(turn, 1)
                line += f"; from {back_pressure:.0f} turn ~{turn:.0f} bar"
            else:
                line += f" — over the {back_pressure:.0f} bar fill!"
        lines.append(line)
    else:
        lines.append(f"  Rock bottom: {rock:.0f} L (set bottom-gas tank for bar)")
    lines.append("  (cylinder litres are ideal-gas: a 232 bar fill actually "
                 "holds ~5% less, 300 bar ~10%)")
    return data, lines


def _contingency_output(grid, planned_depth: float, planned_time: float):
    """(json_dict, text_lines) for the cut-table matrix from
    ``buhlmann.contingency_schedules``: rows = bottom-time variants, columns =
    depth variants, each cell the stop schedule as 'depth:min' pairs plus the
    TTS rounded up to whole minutes, the wetnotes way ('no deco' when clean,
    'n/a' when unplannable); '*' marks the planned row and column."""
    data = {"time_step_min": b.CONTINGENCY_TIME_STEP,
            "depth_step_m": b.CONTINGENCY_DEPTH_STEP,
            "depths_m": [c.depth for c in grid[0]], "rows": []}
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
        data["rows"].append({"bottom_time_min": row[0].bottom_time,
                             "cells": cells})

    lines = ["", "Contingency cut table (square profile at max depth, steps "
                 f"{b.CONTINGENCY_TIME_STEP:g} min × {b.CONTINGENCY_DEPTH_STEP:g}"
                 " m, * = planned; cell: stop depth:min · TTS rounded UP) — "
                 "educational, NOT dive-safe:"]
    heads = [f"{c.depth:g} m" + ("*" if abs(c.depth - planned_depth) < 1e-9
                                 else "") for c in grid[0]]
    texts = [[c.text() for c in row] for row in grid]
    widths = [max(len(heads[j]), max(len(t[j]) for t in texts))
              for j in range(len(heads))]
    corner = "time\\depth"
    lines.append((f"    {corner:<11}"
                  + "  ".join(f"{heads[j]:<{widths[j]}}"
                              for j in range(len(heads)))).rstrip())
    for row, txt in zip(grid, texts):
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

    try:
        segs, tissues = b.plan_multilevel(levels, bottom, plan)
    except ValueError as e:
        print(f"plan: {e}", file=sys.stderr)
        return 2
    depth = b.max_depth(levels)
    avg_depth = b.average_depth(segs)
    violations = b.ceiling_violations(segs)
    po2_viol = b.worst_ppo2_violations(segs, plan)
    cns, otu = b.cns_otu(segs)
    end_m = bottom.end(depth, plan.surface_p, plan.msw_per_bar)
    density = bottom.density(depth, plan.surface_p, plan.msw_per_bar)
    model_label = f"Bühlmann GF {int(gf_low * 100)}/{int(gf_high * 100)}"
    surface_ceiling = b.ceiling_depth(tissues, gf_high)
    tts = b.time_to_surface(segs)
    gas_data, gas_lines = _percylinder_gas(segs, depth, bottom, gp, gas_rows,
                                           plan.ascent_rate)

    warnings = [f"level at {s.depth_start:g} m is above the "
                f"{s.ceiling_m:.1f} m ceiling" for s in violations]
    for v in po2_viol:
        if v.kind == "high":
            warnings.append(f"ppO2 {v.ppo2:.2f} bar on {v.segment.gas!r} at "
                            f"{v.depth:.0f} m — over the {v.limit:.2f} limit")
        else:
            warnings.append(f"ppO2 {v.ppo2:.2f} bar on {v.segment.gas!r} at "
                            f"{v.depth:.0f} m — hypoxic (min {v.limit:.2f})")
    if density > b.DENSITY_MAX_G_L:
        warnings.append(f"gas density {density:.1f} g/L at {depth:g} m exceeds "
                        f"{b.DENSITY_MAX_G_L:g} g/L (CO2 retention risk)")

    cont_data, cont_lines = None, []
    if args.contingency is not None:
        try:
            counts = parse_contingency(args.contingency)
        except ValueError as e:
            print(f"plan: {e}", file=sys.stderr)
            return 2
        base = dc.contingency_of(cfg if load_path else {})
        tb, ta, db, da = (base[i] if counts[i] is None else counts[i]
                          for i in range(4))
        grid = b.contingency_schedules(levels, bottom, plan,
                                       time_before=tb, time_after=ta,
                                       depth_before=db, depth_after=da)
        cont_data, cont_lines = _contingency_output(grid, depth,
                                                    levels[-1].runtime)

    saved_to = dc.save(cfg if load_path else _config_from_args(args),
                       args.save) if args.save else None

    if args.json:
        out = {
            "model": model_label,
            "input": {"levels": [{"depth_m": l.depth, "runtime_min": l.runtime,
                                  "gas": None if l.gas is None else repr(l.gas)}
                                 for l in levels],
                      "max_depth_m": round(depth, 2),
                      "avg_depth_m": round(avg_depth, 2),
                      "gas": repr(bottom),
                      "travel_gases": [repr(g) for g in plan.travel_gases],
                      "deco_gases": [repr(g) for g in plan.deco_gases]},
            "segments": [s.as_dict() for s in segs],
            "total_runtime_min": round(b.total_runtime(segs), 2),
            "tts_min": round(tts, 2),
            "final_ceiling_m": round(surface_ceiling, 2),
            "cns_pct": round(cns, 1),
            "otu": round(otu, 1),
            "end_m": round(end_m, 1),
            "gas_density_g_l": round(density, 2),
            "warnings": warnings,
            "disclaimer": DISCLAIMER,
        }
        if gas_data is not None:
            out["gas"] = gas_data
        if cont_data is not None:
            out["contingency"] = cont_data
        if saved_to:
            out["saved_to"] = saved_to
        print(json.dumps(out, indent=2))
        return 0

    if len(levels) == 1:
        profile = f"bottom {depth:g} m for {levels[0].runtime:g} min"
    else:
        profile = " → ".join(f"{l.depth:g} m @ {l.runtime:g} min" for l in levels)
        profile = f"{len(levels)} levels: {profile}"
    print(f"\nDive plan  {model_label}  {profile} on {bottom!r}")
    if len(levels) > 1:
        print(f"Max depth {depth:g} m · average depth {avg_depth:.1f} m")
    print(f"Bottom gas @ {depth:g} m: ppO₂ {bottom.ppo2(depth):.2f} bar · "
          f"END {end_m:.0f} m (O₂ narcotic) · density {density:.1f} g/L")
    if plan.travel_gases:
        print(f"Travel gases: {', '.join(repr(g) for g in plan.travel_gases)}")
    if plan.deco_gases:
        print(f"Deco gases: {', '.join(repr(g) for g in plan.deco_gases)}")
    print("-" * 78)
    print(f"{'segment':<10}{'from':>7}{'to':>7}{'min':>8}{'run':>8}"
          f"{'gas':>14}{'GF':>6}")
    print("-" * 78)
    run = 0.0
    for s in segs:
        run += s.duration
        gf = "" if s.gf_used is None else f"{s.gf_used:.2f}"
        print(f"{s.kind:<10}{s.depth_start:>7.1f}{s.depth_end:>7.1f}"
              f"{s.duration:>8.1f}{run:>8.1f}{repr(s.gas):>14}{gf:>6}")
    print("-" * 78)
    print(f"Total runtime: {b.total_runtime(segs):.1f} min    "
          f"Time to surface (TTS): {tts:.1f} min")
    print(f"CNS {cns:.0f}% · OTU {otu:.0f}    "
          f"Surface ceiling at GF-High: {surface_ceiling:.2f} m")
    for w in warnings:
        print(f"⚠  {w}")
    for line in gas_lines:
        print(line)
    for line in cont_lines:
        print(line)
    if saved_to:
        print(f"Saved dive to {saved_to}")
    print(DISCLAIMER)
    return 0


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
                          "gf_high": args.gf_high, "ndl_min": n,
                          "disclaimer": DISCLAIMER}))
    else:
        print(f"NDL at {args.depth} m on {gas!r} "
              f"(Bühlmann GF-High {args.gf_high:.2f}): {label}")
        print(DISCLAIMER)
    return 0


def cmd_tissues(args) -> int:
    try:
        plan = _build_plan(args)
        gas = parse_gas(args.gas)
    except ValueError as e:
        print(f"tissues: {e}", file=sys.stderr)
        return 2
    segs, tissues = b.plan_dive(args.depth, args.time, gas, plan)
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


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="deco",
        description="Bühlmann ZHL-16C + Gradient Factor dive planner (educational).")
    # Shared options
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--gf-low", type=float, default=0.30,
                        help="default 0.30")
    common.add_argument("--gf-high", type=float, default=0.70,
                        help="default 0.70 (same as the GUI/config default)")
    common.add_argument("--descent-rate", type=float, default=18.0, help="m/min")
    common.add_argument("--ascent-rate", type=float, default=10.0, help="m/min")
    common.add_argument("--stop-interval", type=float, default=3.0, help="m")
    common.add_argument("--last-stop", type=float, default=3.0,
                        help="shallowest stop depth in m (6 = Shearwater-style last stop at 6 m)")
    common.add_argument("--travel-gas", action="append",
                        help="Descent/travel gas for a hypoxic bottom mix. Repeatable.")
    common.add_argument("--deco-gas", action="append",
                        help="e.g. 50, ean50, 100, 21/35. Repeatable.")
    common.add_argument("--ppo2-deco", type=float, default=1.6,
                        help="ppO2 ceiling for deco gases on ascent.")
    common.add_argument("--ppo2-bottom", type=float, default=1.4,
                        help="ppO2 ceiling for the bottom/travel gas on descent.")
    common.add_argument("--ppo2-min", type=float, default=0.18,
                        help="Hypoxia floor; a gas is unusable below this ppO2.")
    common.add_argument("--json", action="store_true")

    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("plan", parents=[common], help="Compute a deco schedule.")
    sp.add_argument("config", nargs="?",
                    help="dive config JSON to load (same as --load), "
                         "e.g. `python cli.py plan dive_plan.json`.")
    sp.add_argument("--depth", type=float, help="bottom depth (m); square dive")
    sp.add_argument("--time", type=float,
                    help="bottom time (min); runtime at the end of the bottom")
    sp.add_argument("--level", action="append",
                    help="multi-level dive: DEPTH:RUNTIME[:GAS], e.g. 45:25 or "
                         "120:20:10/70. RUNTIME is cumulative (minutes since the "
                         "surface, at the END of the level). GAS is optional — "
                         "without it the planner uses the gas relevant at that "
                         "depth. Repeatable; replaces --depth/--time.")
    sp.add_argument("--gas", default="air",
                    help="bottom gas, optional @tank e.g. air@24, 21/35@24")
    sp.add_argument("--sac", type=float,
                    help="Normal surface air consumption (L/min); enables gas planning.")
    sp.add_argument("--sac-multiplier", type=float, default=2.0,
                    help="Emergency SAC multiplier for rock bottom (e.g. 1.5); "
                         "emergency SAC = --sac x this. Default 2.0.")
    sp.add_argument("--problem-time", type=float, default=1.0,
                    help="Minutes solving the problem at max depth (rock bottom"
                         " and the worst-moment emergency gas need).")
    sp.add_argument("--divers", type=int, default=1,
                    help="Divers sharing the supply in the emergency (2 = buddy"
                         " out of gas, shared until the first gas switch)."
                         " Scales rock bottom too. Default 1.")
    sp.add_argument("--tank-size", type=float,
                    help="Bottom-gas cylinder volume (L); or use --gas mix@litres.")
    sp.add_argument("--contingency", nargs="?", const="",
                    metavar="TB[:TA[:DB[:DA]]]",
                    help="Backup cut-table matrix for a bottom timer: square-"
                         "profile schedules on a 3 min × 3 m grid, TB/TA "
                         "bottom-time rows shorter/longer and DB/DA depth "
                         "columns shallower/deeper than planned (default from "
                         "the config, else 1:1:1:1; a zero count disables "
                         "that direction).")
    sp.add_argument("--load", nargs="?", const=dc.DEFAULT_PATH,
                    help="Load the dive from a JSON config (default dive_plan.json).")
    sp.add_argument("--save", nargs="?", const=dc.DEFAULT_PATH,
                    help="Save this dive to a JSON config (default dive_plan.json).")
    sp.set_defaults(func=cmd_plan)

    sn = sub.add_parser("ndl", parents=[common], help="No-decompression limit.")
    sn.add_argument("--depth", type=float, required=True)
    sn.add_argument("--gas", default="air")
    sn.set_defaults(func=cmd_ndl)

    st = sub.add_parser("tissues", parents=[common],
                        help="Tissue loading report after a square dive.")
    st.add_argument("--depth", type=float, required=True)
    st.add_argument("--time", type=float, required=True)
    st.add_argument("--gas", default="air")
    st.set_defaults(func=cmd_tissues)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
