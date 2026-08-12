---
name: deco-buhlmann
description: Compute Bühlmann ZHL-16C decompression schedules, NDLs, tissue loading, ceilings, and gas-switch plans with Erik Baker gradient factors. Use when the user asks about dive planning, no-decompression limits, deco stops, tissue loading, ceilings, or trimix/nitrox planning math.
allowed-tools: Bash(python:*)
---

# deco-buhlmann

Self-contained Python implementation of the Bühlmann ZHL-16C decompression model
with Erik Baker's gradient factors. Lives entirely in this repo. Output carries
no printed disclaimer — the **warnings** are the safety surface instead, so
always relay them (`DECISIONS.md` #4, #5). Run commands from the repo root; the
package lives in `src/deco/` and the project sets `PYTHONPATH=src`, so
`python -m deco.cli` works with nothing installed (an installed checkout also
has `deco` on PATH).

## When to use

- "Plan a dive to X m for Y min on gas Z"
- "Multi-level dive: X m for Y min, then Z m until runtime W"
- "What's the NDL at X m on air / EAN32?"
- "Show the tissue loading after this profile"
- "How does GF low/high change the schedule?"
- Trimix, nitrox, multi-gas deco plans
- "Rock bottom / minimum gas for this dive" (emergency SAC in L/min + problem time + diver count; `--no-emergency` drops the whole block) and TTS
- "Where do I turn this dive?" (`--turn-rule rock-bottom|thirds`, `--no-turn-pressure`)
- "Do I have enough gas?" — per-cylinder need vs carried (tank size x fill pressure)
- Hypoxic trimix that needs a travel gas
- "Backup / cut table for a bottom timer" — contingency matrix on a 3 min × 3 m grid (time rows × depth columns)

## Files

- `src/deco/buhlmann.py` — library: `Gas` (incl. `end`/`density`), `Tissues`, `Level`/`plan_multilevel` (multi-level; `plan_dive` = one level; a `Level` is depth + cumulative runtime only — levels are contiguous, the transit is billed to the level's runtime, and a runtime too short to cover it is an error), `ndl`, `ceiling`, `ceiling_profile`, `time_to_surface`, `max_depth`/`average_depth`, `GasPlan`/`rock_bottom_liters`, `ppo2_violations`/`worst_ppo2_violations` (segments outside the ppO2 window — always surface these), `cns_otu` (NOAA CNS% + OTU), `contingency_schedules` (cut-table matrix, square @ max depth)
- `src/deco/cli.py` — `python -m deco.cli {plan|ndl|tissues} …` (`--json` for machine output)
- `src/deco/dive_config.py` / `dive_plan.json` — shared JSON dive config (`levels` + gases + GF); `plan --save` writes it, the GUI reads it
- `tests/` — `python -m unittest discover -s tests -t .` (the `-t .` is required); includes cross-checks against
  native Subsurface `deco.cpp` and Erik Baker's `GFDECO` Fortran, plus golden
  schedules from MultiDeco / the Shearwater manual (need g++ / gfortran, else skip)
- `examples/*.json` — ready-to-run command snippets
- `DECISIONS.md` — numbered decision log; code cites it (`see DECISIONS.md #7`)

## CLI recipes

```
python -m deco.cli plan --depth 30 --time 25 --gas air
python -m deco.cli plan --depth 45 --time 25 --gas 21/35 --deco-gas 50 --deco-gas 100 --gf-low 0.30 --gf-high 0.70
python -m deco.cli ndl  --depth 30 --gas air
python -m deco.cli tissues --depth 40 --time 20 --gas ean32 --json
python -m deco.cli plan --depth 60 --time 25 --gas 10/70 --travel-gas 35/25 --deco-gas 50 --deco-gas 100 --sac 18 --sac-emergency 27 --tank-size 24
python -m deco.cli plan --depth 40 --time 25 --gas air --deco-gas 50 --no-emergency   # baseline litres only, no reserve figures
python -m deco.cli plan --depth 40 --time 25 --gas air@24@232 --deco-gas 50 --sac 20 --turn-rule thirds   # turn at 2/3 of the fill
python -m deco.cli plan --depth 45 --time 10 --gas air@24 --deco-gas 50@11 --sac 20 --save   # write dive_plan.json
python -m deco.cli plan dive_plan.json                                                        # replan the saved dive
python -m deco.cli plan --depth 45 --time 25 --gas 21/35 --deco-gas 50 --last-stop 6   # Shearwater-style last stop
python -m deco.cli plan --level 45:25 --level 30:40 --level 18:55 --gas 21/35 --deco-gas 50   # multi-level
python -m deco.cli plan --level 120:20 --level 45:40 --gas 10/70 --travel-gas 35/25            # gas auto by role
python -m deco.cli plan --depth 40 --time 25 --gas air --deco-gas 50 --contingency 0:2:0:1    # cut table +2 time steps, +1 depth step
python -m deco.cli plan --depth 32 --time 40 --gas ean36 --deco-gas 50 --water fresh --altitude 150   # lake at altitude
python -m deco.cli plan --depth 40 --time 25 --gas air --deco-gas 50 --sac 20 --sac-deco 16          # separate deco-cylinder SAC
python -m deco.cli plan --dive 30:25 --dive 30:25:60 --gas air --deco-gas 50    # repetitive: DEPTH:RUNTIME[:SURFACE_INTERVAL]
python -m deco.cli plan --depth 40 --time 25 --gas air --deco-gas 50 --gas-switch at-first-stop   # hold switches to the first stop
```

Gas syntax: `air`, `o2`, `ean32` / `nx32` / `32`, trimix `21/35` (fO2/fHe %).
Defaults: GF 30/70 on the CLI (the library `DivePlan` uses 30/80), descent
18 m/min, ascent 10 m/min, 3 m stops, last stop 3 m
(`--last-stop 6` for the Shearwater/MultiDeco option), deco ppO2 1.6, sea level
1.01325 bar, salt water 10 msw/bar. The last two are settings, not constants:
`--water salt|fresh` (or `--msw-per-bar`) and `--altitude M` (or `--surface-p
BAR`) plan fresh water and altitude dives, and they move the schedule, ppO2,
MOD, END, density, CNS/OTU and gas volumes together — say so when relaying a
plan for a lake. Altitude assumes an acclimatised diver. `--sac-deco` bills gas
breathed off a deco cylinder at its own rate. **Gas is on every plan**: with no
`--sac` the baseline is 20 L/min and the output says it was assumed. The
emergency reserve is a separate block — `--sac-emergency` (absolute L/min, one
stressed rate for every mix), `--problem-time`, `--divers` (2 shares the whole
ascent, stages included) — and `--no-emergency` removes it from the text and
the JSON entirely rather than zeroing it. The turn pressure inside it has its
own switch (`--no-turn-pressure`) and two rules (`--turn-rule
rock-bottom|thirds`); when thirds leaves less than rock bottom the output says
so, and that flag is worth quoting (DECISIONS #28). Every algorithm input is settable
from the CLI, `dive_plan.json` and the GUI alike (DECISIONS #19) — including
`--p-h2o` (0.0627 Bühlmann / 0.0567 Schreiner) and `--ppo2-switch-tol`. Deco-gas switches snap to standard stop depths (O2 at
the 6 m stop, EAN50 at 21 m). On Windows set `PYTHONUTF8=1` for clean output.
Every plan prints ppO2/density/ceiling warnings (`warnings` in `--json`),
CNS%/OTU, END + gas density — quote the warnings when relaying a schedule; with
no disclaimer in the output they are the only caveat the user sees. It also
prints **SurfGF** (the GF actually surfaced at, against the GF-High allowed —
`surf_gf`), the **gas stack** (MOD/END/EAD/density per mix, each at its own MOD
— `gas_stack`), the cylinder pressure **leaving each stop** (`stops[].end_bar`),
a one-line schedule for a slate (`backup_line`), and whether losing the
**bottom** gas is survivable on the remaining stack (`bailout_bottom_gas`,
`null` = not survivable; on a deep dive that is the usual and correct answer —
relay it as such, never as a missing feature).

**Repetitive dives:** `--dive DEPTH:RUNTIME[:SURFACE_INTERVAL]`, repeatable, one
per dive; the interval is surface minutes BEFORE that dive and the first dive
cannot have one. Residual loading carries through, so the same profile repeated
owes more deco. `--json` returns a `dives` array (a single dive keeps the flat
shape); `--dive-index N` prints one. In a config the dives after the first live
in `repeats`, and settings are shared across the day (DECISIONS #26).

**`--gas-switch at-first-stop`** holds every deco switch until the first stop
instead of taking each mix at its MOD. It can only lengthen the deco, and on the
default 1-minute stop grid it usually changes nothing — say that rather than
letting an unchanged TTS read as a broken control (DECISIONS #25). Printed schedules use one notation everywhere (`buhlmann.stop_legs`,
DECISIONS #17): **`run` is the runtime you LEAVE that depth**, truncated to
whole minutes; the stop minutes are the **leg** — the ascent to the stop plus
the hold, measured from the previous stop — so they add up to the runtimes;
TTS rounds UP. Quote it that way: "leave 6 m at 43", not "stop 3 min".
`--json` carries it as `stops`. GF-low > GF-high is rejected. `plan <config>` errors out (exit 2) on a missing/corrupt file and
ignores other CLI flags.

## Library use

```python
from deco import buhlmann as b
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

# repetitive dive: off-gas at the surface, then plan from that loading
after = b.surface_interval(tissues, 60.0, plan)          # 60 min on the surface
segs2, _ = b.plan_dive(30, 25, b.AIR, plan, start_tissues=after)
print("SurfGF:", b.surface_gf(tissues, plan.surface_p))  # what you surfaced at
# losing the BOTTOM gas: None when nothing left is breathable down there
bail = b.bailout_schedule(segs, plan, b.AIR, (b.AIR,))
```
