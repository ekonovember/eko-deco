<div align="center">

<img src="pictures/logo.png" alt="eko-deco logo" width="380">

# Bühlmann ZHL-16C + gradient factors + ratio deco + rock bottom

A small Python implementation of the Bühlmann ZHL-16C decompression model with
Erik Baker's gradient factors — a zero-dependency core, plus a CLI and a Tkinter GUI.

**⚠️ Educational only — not validated for planning real dives.**

<img src="pictures/app_ui.png" alt="eko-deco GUI" width="900">

</div>

> Dive inputs on the left, the depth/time profile with a Ratio-Deco overlay in the
> centre, and framed results + a printable wetnotes runtime on the right.

## What it does

- 16 tissue compartments, N₂ and He, ZHL-16C coefficients.
- Schreiner equation for variable-depth segments (descents/ascents),
  reduces to Haldane at constant depth.
- Erik Baker's gradient-factor formulation:
  `P_amb_tol = (P_comp − a·GF) / (GF/b + 1 − GF)`,
  linearly interpolated between GF-Low at the first stop and GF-High at the
  surface.
- **Multi-level planning**: a dive is a list of levels (depth + runtime, each
  with an optional gas — otherwise the planner breathes the gas relevant at that
  depth), not just one square bottom. A level shallower than the ceiling is
  flagged rather than silently planned.
- Automatic first-stop detection, 3 m stops (last stop 3 m or 6 m), and best-gas
  selection: deco gases switch at their MOD (ppO₂ ≤ 1.6) snapped to a standard
  stop depth — O₂ at the 6 m stop, EAN50 at 21 m.
- Multi-gas support: bottom + multiple acceleration/deco gases + travel gases,
  switched automatically by ppO₂ window (MOD ceiling + hypoxia floor). Handles
  hypoxic trimixes (e.g. 10/70) that need a travel gas near the surface.
- Rock-bottom / minimum-gas planning for a single diver: one basic SAC plus an
  emergency SAC multiplier (e.g. 1.5) and a problem-solving time, plus
  Time-To-Surface (TTS).
- Lost-deco-gas contingencies in the GUI: the schedule re-planned without each
  deco gas (and without all of them), with per-scenario gas usage showing what
  the dive **needs at the normal SAC against what you actually carry** (tank size
  × fill pressure), the emergency-SAC need (SAC × multiplier) in parentheses, bar
  remaining, and a `SHORT!` flag when a contingency outruns a cylinder — plus a
  second `SHORT!` inside the parens when even the emergency need is exceeded.
- Ratio Deco (GUE/UTD) utility with standard gases and a Bühlmann cross-check.
- Shared JSON config (`dive_plan.json`): the GUI and the CLI read/write the same
  dive, so `cli.py plan --save` shows up in the app on Reload and vice-versa.
- Printable **runtime** (wetnotes card) in the GUI — depth / stop / runtime / gas
  plus TTS and minimum-gas / turn pressure — exportable to PNG to take in the water.
- NDL calculator and tissue-loading report.

## The app (GUI)

Run `python app.py` for the visual planner shown above:

- **Left** — every input: gradient factors and a **Last stop 6 m** switch
  (Shearwater/MultiDeco style); an editable **Levels** list — add a level per
  row (depth, runtime, and a gas picked from the gases below — or `auto`, which
  breathes whatever is relevant at that depth) to plan a multi-level dive; an
  editable gas stack (bottom / travel / deco, each with its own O₂, He, tank and
  fill, and a **use** checkbox to leave a gas out of the plan without deleting
  it); SAC and the emergency SAC multiplier; plus **Save / Reload** of the
  shared `dive_plan.json`.
- **Centre** — results as framed cards (gas, dive summary, the MultiDeco-style
  stops + lost-deco-gas scenario table, per-scenario gas usage (have / need per
  cylinder, emergency need in parens), per-cylinder gas + rock bottom, Ratio-Deco cross-check) and a
  printable **runtime** wetnotes
  card — with the contingency columns — exportable to PNG with the
  `<//> eko-deco` mark.
- **Right** — the depth-vs-time profile: the Bühlmann GF ascent with stops and
  gas switches, and the Ratio-Deco schedule overlaid for comparison.

**Dark mode** lives in the **Settings** menu and themes the whole app including
the chart; the choice is remembered in `ui_settings.json` (per-user,
git-ignored), kept separate from the dive itself in `dive_plan.json`.

## Install

Python 3.10+. The core library and CLI need **nothing** beyond the standard
library; the GUI (`app.py`) also needs `matplotlib` (tkinter ships with CPython):

```bash
pip install matplotlib   # GUI only
```

## Command line

```bash
# Recreational
python cli.py plan --depth 30 --time 25 --gas air

# Tech with deco gases
python cli.py plan --depth 45 --time 25 --gas 21/35 \
    --deco-gas 50 --deco-gas 100 --gf-low 0.30 --gf-high 0.70

# Multi-level: RUNTIME is cumulative (minutes since the surface, at the END of the level)
python cli.py plan --level 45:25 --level 30:40 --level 18:55 \
    --gas 21/35 --deco-gas 50 --deco-gas 100

# ...with a gas forced on a level (deep bottom mix, then a shallower leg)
python cli.py plan --level 120:20:10/70 --level 45:40 --gas 10/70 --travel-gas 35/25

# Last stop at 6 m instead of 3 m (Shearwater/MultiDeco style)
python cli.py plan --depth 45 --time 25 --gas 21/35 --deco-gas 50 --last-stop 6

# Hypoxic trimix + travel gas, per-gas tanks, gas planning (TTS + rock bottom)
python cli.py plan --depth 60 --time 25 --gas 10/70@24 \
    --travel-gas 35/25@11 --deco-gas 50@11 --deco-gas 100@7 \
    --sac 18 --sac-multiplier 1.5

# Save a dive to the shared config, then re-plan it (the GUI reads the same file)
python cli.py plan --depth 45 --time 10 --gas air@24@232 --deco-gas 50@11@200 --sac 20 --save
python cli.py plan dive_plan.json     # positional config (or --load)

# Ratio Deco with GUE standard gases (+ Bühlmann cross-check)
python cli.py ratio --depth 51 --time 25

# NDL & tissue report
python cli.py ndl     --depth 30 --gas air
python cli.py tissues --depth 40 --time 20 --gas ean32 --json
```

Gas syntax: `air`, `o2`, `ean32` / `nx32` / `32`, trimix `21/35` (fO₂/fHe %).
Each gas takes an optional cylinder suffix `mix@tank@bar` — tank size in litres
and fill pressure in bar (e.g. `air@24@232` = 24 L twinset filled to 232 bar;
`50@11` = 11 L stage at the default fill) — used for per-cylinder gas needs and
rock bottom. Add `--json` to any command for machine-readable output.

Deco-gas switches happen at standard stop depths (O₂ at the 6 m stop, EAN50
at 21 m), the way dive computers plan them, with a small ppO₂ tolerance for
the rounding.

A dive is one or more **levels**. `--depth/--time` is the square-profile
shorthand for a single level; `--level DEPTH:RUNTIME[:GAS]` (repeatable) plans a
multi-level dive. **Runtime is cumulative** — minutes since leaving the surface,
at the *end* of that level, descent included — which is how MultiDeco, Baker's
GFDECO and Subsurface all take a profile.

There are more knobs than shown above — ascent/descent/stop rates, the
shallowest-stop depth (`--last-stop`), the ppO₂
window (`--ppo2-bottom` / `--ppo2-deco` / `--ppo2-min`), the emergency SAC
multiplier and problem time for rock bottom (`--sac-multiplier`,
`--problem-time`), `ratio --avg-depth` — see
`python cli.py plan -h` (or `ratio -h`, …) for the full list. Ready-to-run
command snippets live in [`examples/`](examples/).

> **Windows note:** the source is UTF-8 (`Bühlmann`, `₂`); the default cp1252
> console renders those as mojibake — cosmetic only. Set `PYTHONUTF8=1` (or run
> `chcp 65001`) for clean output.

## Test

```bash
python -m unittest discover -s tests -v
```

The suite has two tiers:

- **80 core tests** — constant counts, surface saturation, Haldane equivalence,
  NDLs against published Bühlmann values (±5 min), multi-level profiles,
  gas-switch and travel-gas behaviour, the last-stop option, TTS / rock-bottom
  gas, config round-trips and the Ratio Deco schedule. Pure standard library:
  these run everywhere, including a bare Windows Python.
- **24 cross-check tests** — these compile the reference implementations
  (Subsurface's `deco.cpp` with **g++**, Baker's `GFDECO` with **gfortran**) and
  run eko-deco against them. Without those compilers the two modules skip
  themselves and you see `Ran 80 tests` — that is a *missing compiler*, not
  missing data; the skip message says so and tells you what to install. On
  Windows, install MSYS2/MinGW-w64 (or just run the suite under WSL) to get all
  104.

The oracles are compiled on demand from Python, so no `make` step is needed.

## Validation

The planner deliberately follows the **Baker / Shearwater / MultiDeco**
gradient-factor convention: GF-Low anchored at the rounded first stop, a static
slope to GF-High at the surface, gas switches at standard stop depths. That
claim is enforced by tests, not asserted:

| Reference | How | Agreement |
|---|---|---|
| [Subsurface](https://github.com/subsurface/subsurface) `deco.cpp` | its **unmodified C++** compiled on the fly into a test oracle and driven over ctypes | tissue loading, M-value ceilings and the GF line to **machine precision**; NDLs exact at GF 100/100 |
| Erik Baker's `GFDECO` | his **original Fortran** — the published reference for the GF convention — compiled and run | ≤ **1 min** per stop, ≤ 1.3 min TTS — **square *and* multi-level** |
| MultiDeco | golden schedules, including every lost-gas column | no-loss plan matches **to the minute** |
| Shearwater | the worked planner example in the Perdix 2 manual (GF 30/70, its stated rates) | runtime and TTS match **exactly** |

- `tests/test_subsurface_crosscheck.py` — the Subsurface oracle (`tests/subsurface_oracle/`,
  GPL-2.0, test-only; see the README there for the license boundary). Cross-checks
  tissue loading (incl. seeded random multi-level profiles), ceilings, the GF
  interpolation line, NDL sweeps, repetitive dives, and multi-gas schedules to
  60 m at altitude and in fresh water. Needs `g++`.
- `tests/test_baker_crosscheck.py` — Baker's `GFDECO` (`tests/baker_oracle/`).
  Pins the first-stop anchor and the `--last-stop 6` behaviour. Needs `gfortran`.
- `tests/test_shearwater_golden.py` — golden schedules in
  `tests/shearwater_golden.json`, with provenance recorded per fixture.

Both oracles build themselves on first run and **skip cleanly** when the
compiler isn't installed, so the core suite stays dependency-free.

Remaining differences from Subsurface — air at 20.9 % vs 21 % O₂, salinity-based
depth conversion, a dynamic GF anchor — are **intentional**: they are exactly
what separates the Subsurface convention from the Shearwater one.

## AI-agent friendly

The repo ships instructions and tooling for coding agents — open it in
**Claude Code** or **GitHub Copilot CLI** and the agent already knows the
project:

- `CLAUDE.md` — canonical agent instructions (module map, commands, conventions),
  also read by Copilot CLI; `AGENTS.md` points here for other tools.
- `.claude/skills/deco-buhlmann/` — an Agent Skill for dive-planning math.
- `.claude/commands/` — slash commands: `/plan-dive`, `/ndl`, `/tissues`,
  `/ratio`, `/run-tests`.
- `.claude/agents/dive-planner.md` — a dive-planning subagent.
- `dive_plan.json` is agent-editable: ask the agent to change the dive and
  hit **Reload** in the GUI.

## License

[MIT](LICENSE). The educational disclaimer stands regardless of license: this
code is **not validated for planning real dives**.

## References

- A.A. Bühlmann, *Tauchmedizin* (5th ed., 2002) — ZHL-16 coefficients.
- E. C. Baker, *Clearing Up the Confusion About "Deep Stops"* (gradient
  factors).
- E. C. Baker, *Understanding M-values*.
- Subsurface dive-log source (constants cross-check).
