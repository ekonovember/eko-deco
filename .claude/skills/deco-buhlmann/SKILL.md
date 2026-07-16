---
name: deco-buhlmann
description: Compute Bühlmann ZHL-16C decompression schedules, NDLs, tissue loading, ceilings, and gas-switch plans with Erik Baker gradient factors. Use when the user asks about dive planning, no-decompression limits, deco stops, tissue loading, ceilings, or trimix/nitrox planning math.
allowed-tools: Bash(python:*)
---

# deco-buhlmann

Self-contained Python implementation of the Bühlmann ZHL-16C decompression model
with Erik Baker's gradient factors. Lives entirely in this repo. **Educational —
never present results as safe for real dives.** Run commands from the repo root.

## When to use

- "Plan a dive to X m for Y min on gas Z"
- "Multi-level dive: X m for Y min, then Z m until runtime W"
- "What's the NDL at X m on air / EAN32?"
- "Show the tissue loading after this profile"
- "How does GF low/high change the schedule?"
- Trimix, nitrox, multi-gas deco plans
- "Rock bottom / minimum gas for this dive" (SAC + emergency multiplier + problem time, single diver) and TTS
- "Do I have enough gas?" — per-cylinder need vs carried (tank size x fill pressure)
- Hypoxic trimix that needs a travel gas
- "Backup / cut table for a bottom timer" — contingency matrix on a 3 min × 3 m grid (time rows × depth columns)

## Files

- `buhlmann.py` — library: `Gas` (incl. `end`/`density`), `Tissues`, `Level`/`plan_multilevel` (multi-level; `plan_dive` = one level), `ndl`, `ceiling`, `ceiling_profile`, `time_to_surface`, `max_depth`/`average_depth`, `GasPlan`/`rock_bottom_liters`, `ppo2_violations`/`worst_ppo2_violations` (segments outside the ppO2 window — always surface these), `cns_otu` (NOAA CNS% + OTU), `contingency_schedules` (cut-table matrix, square @ max depth)
- `cli.py` — `python cli.py {plan|ndl|tissues} …` (`--json` for machine output)
- `dive_config.py` / `dive_plan.json` — shared JSON dive config (`levels` + gases + GF); `plan --save` writes it, the GUI reads it
- `tests/` — `python -m unittest discover -s tests`; includes cross-checks against
  native Subsurface `deco.cpp` and Erik Baker's `GFDECO` Fortran, plus golden
  schedules from MultiDeco / the Shearwater manual (need g++ / gfortran, else skip)
- `examples/*.json` — ready-to-run command snippets

## CLI recipes

```
python cli.py plan --depth 30 --time 25 --gas air
python cli.py plan --depth 45 --time 25 --gas 21/35 --deco-gas 50 --deco-gas 100 --gf-low 0.30 --gf-high 0.70
python cli.py ndl  --depth 30 --gas air
python cli.py tissues --depth 40 --time 20 --gas ean32 --json
python cli.py plan --depth 60 --time 25 --gas 10/70 --travel-gas 35/25 --deco-gas 50 --deco-gas 100 --sac 18 --sac-multiplier 1.5 --tank-size 24
python cli.py plan --depth 45 --time 10 --gas air@24 --deco-gas 50@11 --sac 20 --save   # write dive_plan.json
python cli.py plan dive_plan.json                                                        # replan the saved dive
python cli.py plan --depth 45 --time 25 --gas 21/35 --deco-gas 50 --last-stop 6   # Shearwater-style last stop
python cli.py plan --level 45:25 --level 30:40 --level 18:55 --gas 21/35 --deco-gas 50   # multi-level
python cli.py plan --level 120:20 --level 45:40 --gas 10/70 --travel-gas 35/25            # gas auto by role
python cli.py plan --depth 40 --time 25 --gas air --deco-gas 50 --contingency 0:2:0:1    # cut table +2 time steps, +1 depth step
```

Gas syntax: `air`, `o2`, `ean32` / `nx32` / `32`, trimix `21/35` (fO2/fHe %).
Defaults: GF 30/70 on the CLI (the library `DivePlan` uses 30/80), descent
18 m/min, ascent 10 m/min, 3 m stops, last stop 3 m
(`--last-stop 6` for the Shearwater/MultiDeco option), deco ppO2 1.6, sea level
1.01325 bar, 10 msw/bar. Deco-gas switches snap to standard stop depths (O2 at
the 6 m stop, EAN50 at 21 m). On Windows set `PYTHONUTF8=1` for clean output.
Every plan prints ppO2/density/ceiling warnings (`warnings` in `--json`),
CNS%/OTU, END + gas density, and an educational disclaimer — quote the
warnings, and the disclaimer, when relaying a schedule. GF-low > GF-high is
rejected. `plan <config>` errors out (exit 2) on a missing/corrupt file and
ignores other CLI flags.

## Library use

```python
import buhlmann as b
plan = b.DivePlan(gf_low=0.40, gf_high=0.85, deco_gases=(b.EAN50,),
                  last_stop_depth=3.0)          # 6.0 = last stop at 6 m
# multi-level: runtime is cumulative (minutes since the surface, END of level)
segs, tissues = b.plan_multilevel(
    [b.Level(40, 20), b.Level(20, 35)], b.AIR, plan)
# square profile = a single level
segs, tissues = b.plan_dive(40, 20, b.AIR, plan)
for s in segs:
    print(s.as_dict())
print("NDL 30m air:", b.ndl(30, b.AIR))
```
