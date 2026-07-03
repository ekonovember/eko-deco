"""CLI front-end for the Bühlmann module.

Examples
--------
    python cli.py plan --depth 30 --time 25 --gas air
    python cli.py plan --depth 45 --time 25 --gas 21/35 --deco-gas 50 --deco-gas 100
    python cli.py plan --depth 60 --time 25 --gas 10/70 --travel-gas 35/25 --deco-gas 50 --sac 18
    python cli.py ndl --depth 30 --gas air
    python cli.py tissues --depth 30 --time 25 --gas air
    python cli.py ratio --depth 51 --time 25
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import List

import buhlmann as b
import dive_config as dc
import ratio_deco as r


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


def _build_plan(args) -> b.DivePlan:
    return b.DivePlan(
        descent_rate=args.descent_rate,
        ascent_rate=args.ascent_rate,
        stop_interval=args.stop_interval,
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
    sac_stress = args.sac_stress if args.sac_stress is not None else args.sac * 2.0
    gp = b.GasPlan(sac=args.sac, sac_stress=sac_stress, divers=args.divers,
                   problem_minutes=args.problem_time)
    return gp, gases


def _config_from_args(args) -> dict:
    """Serialise the CLI dive into a dive_config dict (for --save)."""
    _gp, gases = _args_gas_context(args)
    sac = args.sac if args.sac is not None else 20.0
    sac_stress = (args.sac_stress if args.sac_stress is not None
                  else (args.sac * 2.0 if args.sac else 40.0))
    return {
        "depth_m": args.depth, "bottom_time_min": args.time,
        "gf_low": round(args.gf_low * 100), "gf_high": round(args.gf_high * 100),
        "solo": args.divers == 1,
        "sac_normal": sac, "sac_stress": sac_stress,
        "problem_minutes": args.problem_time,
        "ascent_rate": args.ascent_rate,
        "descent_rate": args.descent_rate,
        "stop_interval": args.stop_interval,
        "ppo2_bottom": args.ppo2_bottom,
        "ppo2_deco": args.ppo2_deco,
        "ppo2_min": args.ppo2_min,
        "gases": [{"role": role, "o2": round(g.fO2 * 100), "he": round(g.fHe * 100),
                   "tank_l": tk, "pressure_bar": pr} for (role, g, tk, pr) in gases],
    }


def _percylinder_gas(segs, depth, bottom_gas, gp, gases, ascent_rate=10.0):
    """(json_dict, text_lines) for a per-cylinder gas breakdown, or (None, [])
    when no GasPlan is available."""
    if gp is None:
        return None, []
    sac = gp.sac
    tank_by = {repr(g): tk for (_r, g, tk, _p) in gases}
    press_by = {repr(g): pr for (_r, g, _t, pr) in gases}
    role_by = {repr(g): role for (role, g, _t, _p) in gases}
    back_tank, back_pressure = next(((tk, pr) for (_r, g, tk, pr) in gases
                                     if g == bottom_gas), (0.0, 0.0))
    team = "solo" if gp.divers == 1 else f"{gp.divers} divers"
    lines = [f"Gas  SAC {gp.sac:g}/{gp.sac_stress:g} L/min, {team}:"]
    cylinders, seen = [], []
    for s in segs:
        if repr(s.gas) in seen:
            continue
        seen.append(repr(s.gas))
        liters = b.segment_gas_liters([x for x in segs if x.gas == s.gas], sac)
        tk = tank_by.get(repr(s.gas), 0.0)
        pr = press_by.get(repr(s.gas), 0.0)
        role = role_by.get(repr(s.gas), "Bottom" if s.gas == bottom_gas else "stage")
        entry = {"gas": repr(s.gas), "role": role, "liters": round(liters, 1),
                 "tank_l": tk, "pressure_bar": pr}
        if tk <= 0:
            lines.append(f"  {role} {s.gas!r}: {liters:.0f} L (no tank set)")
        else:
            used = liters / tk
            entry["bar_used"] = round(used, 1)
            if pr > 0:
                entry["bar_left"] = round(pr - used, 1)
                short = "  SHORT!" if used > pr + 1e-9 else ""
                lines.append(f"  {role} {s.gas!r}: {used:.0f}/{pr:.0f} bar "
                             f"({pr - used:.0f} left) / {tk:.0f} L{short}")
            else:
                lines.append(f"  {role} {s.gas!r}: {used:.0f} bar / {tk:.0f} L")
        cylinders.append(entry)
    rock = b.rock_bottom_liters(depth, gp, ascent_rate)
    data = {"sac_normal_l_min": gp.sac, "sac_stress_l_min": gp.sac_stress,
            "divers": gp.divers, "cylinders": cylinders, "rock_bottom_l": round(rock, 1)}
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
    return data, lines


def cmd_plan(args) -> int:
    load_path = args.config or args.load
    if load_path:
        if not os.path.exists(load_path):
            print(f"plan: config '{load_path}' not found; using defaults.",
                  file=sys.stderr)
        cfg = dc.load(load_path)
        bottom, plan, gp, gas_rows = dc.to_buhlmann(cfg)
        depth, time = cfg["depth_m"], cfg["bottom_time_min"]
        gf_low, gf_high = cfg["gf_low"] / 100.0, cfg["gf_high"] / 100.0
    else:
        if args.depth is None or args.time is None:
            print("plan: --depth and --time are required "
                  "(or pass a config file / --load).", file=sys.stderr)
            return 2
        bottom = parse_gas_spec(args.gas)[0]
        plan = _build_plan(args)
        depth, time = args.depth, args.time
        gf_low, gf_high = args.gf_low, args.gf_high
        gp, gas_rows = _args_gas_context(args)

    segs, tissues = b.plan_dive(depth, time, bottom, plan)
    model_label = f"Bühlmann GF {int(gf_low * 100)}/{int(gf_high * 100)}"
    surface_ceiling = b.ceiling_depth(tissues, gf_high)
    tts = b.time_to_surface(segs)
    gas_data, gas_lines = _percylinder_gas(segs, depth, bottom, gp, gas_rows,
                                           plan.ascent_rate)

    saved_to = dc.save(cfg if load_path else _config_from_args(args),
                       args.save) if args.save else None

    if args.json:
        out = {
            "model": model_label,
            "input": {"depth_m": depth, "bottom_time_min": time, "gas": repr(bottom),
                       "travel_gases": [repr(g) for g in plan.travel_gases],
                       "deco_gases": [repr(g) for g in plan.deco_gases]},
            "segments": [s.as_dict() for s in segs],
            "total_runtime_min": round(b.total_runtime(segs), 2),
            "tts_min": round(tts, 2),
            "final_ceiling_m": round(surface_ceiling, 2),
        }
        if gas_data is not None:
            out["gas"] = gas_data
        if saved_to:
            out["saved_to"] = saved_to
        print(json.dumps(out, indent=2))
        return 0

    print(f"\nDive plan  {model_label}  "
          f"bottom {depth:g} m for {time:g} min on {bottom!r}")
    if plan.travel_gases:
        print(f"Travel gases: {', '.join(repr(g) for g in plan.travel_gases)}")
    if plan.deco_gases:
        print(f"Deco gases: {', '.join(repr(g) for g in plan.deco_gases)}")
    print("-" * 78)
    print(f"{'segment':<10}{'from':>7}{'to':>7}{'min':>8}{'gas':>14}{'GF':>8}")
    print("-" * 78)
    for s in segs:
        gf = "" if s.gf_used is None else f"{s.gf_used:.2f}"
        print(f"{s.kind:<10}{s.depth_start:>7.1f}{s.depth_end:>7.1f}"
              f"{s.duration:>8.1f}{repr(s.gas):>14}{gf:>8}")
    print("-" * 78)
    print(f"Total runtime: {b.total_runtime(segs):.1f} min    "
          f"Time to surface (TTS): {tts:.1f} min")
    print(f"Surface ceiling at GF-High: {surface_ceiling:.2f} m")
    for line in gas_lines:
        print(line)
    if saved_to:
        print(f"Saved dive to {saved_to}")
    return 0


def cmd_ndl(args) -> int:
    plan = _build_plan(args)
    gas = parse_gas(args.gas)
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
    plan = _build_plan(args)
    segs, tissues = b.plan_dive(args.depth, args.time, parse_gas(args.gas), plan)
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
    print(f"\nTissue loading after {args.time} min @ {args.depth} m on {parse_gas(args.gas)!r}")
    print(f"{'#':>3}{'t½N2':>8}{'pN2':>10}{'pHe':>10}{'pTot':>10}{'a':>9}{'b':>9}")
    for r in rows:
        print(f"{r['compartment']:>3}{r['halftime_N2_min']:>8.1f}"
              f"{r['pN2_bar']:>10.4f}{r['pHe_bar']:>10.4f}{r['p_total_bar']:>10.4f}"
              f"{r['a']:>9.4f}{r['b']:>9.4f}")
    return 0


def _ratio_cross_check(args) -> dict:
    """Bühlmann schedule using the same GUE standard gases, for comparison."""
    bottom, travel, deco = r.standard_dive_gases(args.depth)
    plan = b.DivePlan(gf_low=args.gf_low, gf_high=args.gf_high,
                      travel_gases=travel, deco_gases=deco)
    segs, _ = b.plan_dive(args.depth, args.time, bottom, plan)
    return {
        "gf_low": args.gf_low, "gf_high": args.gf_high,
        "deco_stop_min": round(sum(s.duration for s in segs if s.kind == "stop"), 1),
        "tts_min": round(b.time_to_surface(segs), 1),
    }


def cmd_ratio(args) -> int:
    res = r.ratio_deco(args.depth, args.time, avg_depth_m=args.avg_depth)
    cross = _ratio_cross_check(args)

    if args.json:
        out = res.as_dict()
        out["buhlmann_cross_check"] = cross
        print(json.dumps(out, indent=2))
        return 0

    print(f"\nRatio Deco (educational)  max {res.max_depth_m:.0f} m, "
          f"avg {res.avg_depth_m:.0f} m, bottom {res.bottom_time_min:.0f} min")
    deco_txt = f" | deco {', '.join(res.deco_gases)}" if res.deco_gases else ""
    print(f"  Standard gas: bottom {res.bottom_gas}{deco_txt}")
    print(f"  Ratio {res.ratio:.2f} (1:1@46 m, 2:1@67 m)  ->  "
          f"total deco {res.total_deco_min:.0f} min")
    if res.min_deco:
        print("  Minimum deco (no mandatory stops) - ascend slowly + safety stop.")
    else:
        print(f"  First stop: {res.first_stop_m:.0f} m (80% of max ambient pressure)")
        print(f"  {'stop':>7}{'min':>7}   gas")
        for s in res.stops:
            print(f"  {s.depth_m:>5.0f} m{s.minutes:>6.1f}   {s.gas}")
        print(f"  Scheduled deco (sum of stops): {res.scheduled_deco_min:.0f} min")
    print(f"  Bühlmann GF {int(args.gf_low*100)}/{int(args.gf_high*100)} cross-check: "
          f"deco {cross['deco_stop_min']:.0f} min, TTS {cross['tts_min']:.0f} min")
    print("  NOTE: coarse mental-math estimate - verify against the model, a "
          "computer, and your training.")
    return 0


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="deco",
        description="Bühlmann ZHL-16C + Gradient Factor dive planner (educational).")
    # Shared options
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--gf-low", type=float, default=0.30)
    common.add_argument("--gf-high", type=float, default=0.80)
    common.add_argument("--descent-rate", type=float, default=18.0, help="m/min")
    common.add_argument("--ascent-rate", type=float, default=10.0, help="m/min")
    common.add_argument("--stop-interval", type=float, default=3.0, help="m")
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
    sp.add_argument("--depth", type=float, help="bottom depth (m)")
    sp.add_argument("--time", type=float, help="bottom time (min)")
    sp.add_argument("--gas", default="air",
                    help="bottom gas, optional @tank e.g. air@24, 21/35@24")
    sp.add_argument("--sac", type=float,
                    help="Normal surface air consumption (L/min); enables gas planning.")
    sp.add_argument("--sac-stress", type=float,
                    help="Distress SAC (L/min) for rock bottom; default = 2x --sac.")
    sp.add_argument("--divers", type=int, default=2,
                    help="Divers sharing gas in the emergency (1 = solo). Default 2.")
    sp.add_argument("--problem-time", type=float, default=1.0,
                    help="Minutes solving the problem at max depth (rock bottom).")
    sp.add_argument("--tank-size", type=float,
                    help="Bottom-gas cylinder volume (L); or use --gas mix@litres.")
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

    sr = sub.add_parser("ratio", parents=[common],
                        help="Ratio Deco schedule with GUE standard gases "
                             "(educational).")
    sr.add_argument("--depth", type=float, required=True, help="max depth (m)")
    sr.add_argument("--time", type=float, required=True, help="bottom time (min)")
    sr.add_argument("--avg-depth", type=float, default=None,
                    help="average depth (m); defaults to max depth (square dive).")
    sr.set_defaults(func=cmd_ratio)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
