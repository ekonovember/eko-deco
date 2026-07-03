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
- "What's the NDL at X m on air / EAN32?"
- "Show the tissue loading after this profile"
- "How does GF low/high change the schedule?"
- Trimix, nitrox, multi-gas deco plans
- "Ratio Deco to 51 m for 25 min" (GUE standard gases)
- "Rock bottom / minimum gas for this dive" (two SAC values) and TTS
- Hypoxic trimix that needs a travel gas

## Files

- `buhlmann.py` — library: `Gas`, `Tissues`, `plan_dive` (multi-gas/travel), `ndl`, `ceiling`, `time_to_surface`, `GasPlan`/`rock_bottom_liters`
- `cli.py` — `python cli.py {plan|ndl|tissues|ratio} …` (`--json` for machine output)
- `ratio_deco.py` — Ratio Deco (GUE/UTD) with standard gases (used by `ratio`)
- `dive_config.py` / `dive_plan.json` — shared JSON dive config; `plan --save` writes it, the GUI reads it
- `tests/` — `python -m unittest discover -s tests`
- `examples/*.json` — ready-to-run command snippets

## CLI recipes

```
python cli.py plan --depth 30 --time 25 --gas air
python cli.py plan --depth 45 --time 25 --gas 21/35 --deco-gas 50 --deco-gas 100 --gf-low 0.30 --gf-high 0.70
python cli.py ndl  --depth 30 --gas air
python cli.py tissues --depth 40 --time 20 --gas ean32 --json
python cli.py plan --depth 60 --time 25 --gas 10/70 --travel-gas 35/25 --deco-gas 50 --deco-gas 100 --sac 18 --sac-stress 36 --tank-size 24
python cli.py plan --depth 45 --time 10 --gas air@24 --deco-gas 50@11 --sac 20 --save   # write dive_plan.json
python cli.py plan dive_plan.json                                                        # replan the saved dive
python cli.py ratio --depth 51 --time 25
```

Gas syntax: `air`, `o2`, `ean32` / `nx32` / `32`, trimix `21/35` (fO2/fHe %).
Defaults: GF 30/80, descent 18 m/min, ascent 10 m/min, 3 m stops, deco ppO2 1.6,
sea level 1.01325 bar, 10 msw/bar. On Windows set `PYTHONUTF8=1` for clean output.

## Library use

```python
import buhlmann as b
segs, tissues = b.plan_dive(40, 20, b.AIR,
    b.DivePlan(gf_low=0.40, gf_high=0.85, deco_gases=(b.EAN50,)))
for s in segs:
    print(s.as_dict())
print("NDL 30m air:", b.ndl(30, b.AIR))
```
