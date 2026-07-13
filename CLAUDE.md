# CLAUDE.md — deco

> Agent instructions for this repo. **Read automatically by both Claude Code and
> GitHub Copilot CLI** when you open a terminal here (Copilot lists `CLAUDE.md`
> among its instruction sources). This file is the single source of truth; the
> other agent files (`AGENTS.md`, `.github/copilot-instructions.md`) point back here.

## ⚠️ Scope & safety

`deco` is an **educational** implementation of the Bühlmann ZHL-16C decompression
model with gradient factors. It is **not** validated for planning real dives and
must never be presented as dive-safe. Keep this disclaimer in any output that
produces a schedule, NDL, or ceiling.

## What this is

A small, dependency-free Python library (+ CLI and optional GUI) that computes:

- No-decompression limits (NDL)
- Decompression stop schedules (square profile, multi-gas)
- Tissue inert-gas loading (16 compartments, N₂ + He)
- Ceilings via Erik Baker's gradient factors

## Module map

| File | Role | Deps |
|------|------|------|
| `buhlmann.py` | Core model: `Gas`/`Tissues`, Schreiner, `ceiling`, gradient factors, multi-gas/travel `plan_dive`, `ndl`, `time_to_surface`, `GasPlan`/`rock_bottom_liters`. **Keep dependency-free.** | stdlib only |
| `cli.py` | CLI front end: `plan`, `ndl`, `tissues`, `ratio` (+ `--json`); `plan --load/--save` a config; `mix@tank@bar` gas suffix; per-cylinder gas. | buhlmann, dive_config, ratio_deco |
| `ratio_deco.py` | Ratio Deco (GUE/UTD) with standard gases: `standard_bottom_gas`, `ratio_deco`. Educational. | buhlmann |
| `dive_config.py` | Shared JSON dive config (`load`/`save`/`to_buhlmann`) read by the GUI and written by `plan --save`. | buhlmann |
| `dive_plan.json` | The full dive: depth, time, GF, gas stack (per-gas tank + fill pressure + `enabled` toggle), SAC + emergency SAC multiplier, problem time, ascent/descent/stop rates + ppO2 window, RD toggle. Agent-editable. | — |
| `app.py` | Tkinter + matplotlib GUI: left settings (depth/time + SAC/multiplier as spinbox rows, editable gas list w/ tank+bar, GF row + a 'Last stop 6 m' switch), middle results (stops + lost-deco-gas scenario table, per-scenario gas usage, gas plan) + a printable **Runtime** wetnotes card with contingency columns (PNG export), right profile + Ratio-Deco overlay. Dark mode in the **Settings** menu. Loads/saves `dive_plan.json`; dark mode persisted to `ui_settings.json` (per-user, git-ignored — never mix UI prefs into the dive config). | matplotlib, tkinter, dive_config |
| `tests/` | `unittest` suites: `test_buhlmann.py`, `test_ratio_deco.py`, `test_dive_config.py`, `test_subsurface_crosscheck.py`, `test_baker_crosscheck.py`, `test_shearwater_golden.py`. | stdlib |
| `tests/subsurface_oracle/` | **GPL-2.0, test-only.** Unmodified Subsurface `core/deco.cpp` (pinned commit in `upstream/UPSTREAM.txt`) + stub headers; `build.sh` compiles `libsubsurface_deco.so`. Never import at runtime, never copy code out of it (license boundary — see its README). | g++ |
| `tests/subsurface_deco.py` | ctypes wrapper around the oracle `.so` (auto-builds it); `SubsurfaceDeco.plan()` is a small planner-style schedule loop of ours, the model calls are native Subsurface code. | stdlib + oracle |
| `tests/baker_oracle/` | Erik Baker's original `gfdeco.f` ("distribute freely — credit the author"), the reference for the Shearwater/MultiDeco GF convention. ZH-L16B + WV 0.0567 bar + surface 1.000 bar — the test patches eko-deco to match. `build.sh` compiles the `gfdeco` binary. | gfortran |
| `tests/baker_deco.py` | Runner for the GFDECO binary: writes `GFDECO.IN`/`.SET` in a temp dir, parses the schedule from `GFDECO.OUT`. | stdlib + oracle |
| `tests/shearwater_golden.json` | Golden schedules from real planners: 4 MultiDeco schedules (transcribed from `multideco_screenshots/`, incl. the lost-gas scenario columns; settings inferred — see `_multideco_provenance` in the file) + Shearwater Cloud templates to fill. Unfilled entries show up as skipped tests. | — |
| `examples/*.json` | Ready-to-run command snippets. | — |

Data flow: a `Gas` + depth/time goes into `plan_dive`, which steps the 16
compartments with the **Schreiner equation**; `ceiling` + gradient-factor
interpolation (`gf_at`) drive first-stop detection and stop lengths.

## Commands

Python 3.10+ (verified on 3.14). The core library and tests need **no**
third-party packages.

```bash
# Plan a deco schedule (trimix + deco gases)
python cli.py plan --depth 45 --time 25 --gas 21/35 --deco-gas 50 --deco-gas 100 --gf-low 0.30 --gf-high 0.70
# Hypoxic trimix + travel gas + gas planning (TTS + rock bottom)
python cli.py plan --depth 60 --time 25 --gas 10/70 --travel-gas 35/25 --deco-gas 50 --sac 18 --sac-multiplier 1.5 --tank-size 24
# Per-gas tanks + fill pressures, save to the shared config (dive_plan.json)
python cli.py plan --depth 45 --time 10 --gas air@24@232 --deco-gas 50@11@200 --sac 20 --gf-high 0.70 --save
python cli.py plan dive_plan.json  # (or --load) replan the saved dive; the GUI shares this file
# No-decompression limit
python cli.py ndl --depth 30 --gas air
# Tissue-loading report (machine-readable)
python cli.py tissues --depth 40 --time 20 --gas ean32 --json
# Ratio Deco (GUE standard gases) + Bühlmann cross-check
python cli.py ratio --depth 51 --time 25
# GUI (needs matplotlib; tkinter ships with CPython on Windows)
python app.py
# Shearwater/MultiDeco-style last stop at 6 m
python cli.py plan --depth 45 --time 25 --gas 21/35 --deco-gas 50 --deco-gas 100 --last-stop 6
# Tests (cross-checks need g++ / gfortran; those modules skip without them)
python -m unittest discover -s tests -v
# Individual oracles: native Subsurface deco.cpp / Baker's GFDECO Fortran
python -m unittest tests.test_subsurface_crosscheck -v
python -m unittest tests.test_baker_crosscheck -v
```

Gas syntax: `air`, `o2`, `ean32` / `nx32` / `32`, trimix `21/35` (fO₂/fHe %).

Gas planning: each cylinder has a tank size + fill pressure (`mix@tank@bar`, e.g.
`air@24@232`). Planning is **single-diver**: one basic SAC plus an emergency SAC
multiplier (`sac_multiplier`, e.g. 1.5). **Rock bottom** is standard *minimum
gas* — problem time plus a direct ascent to the surface at the emergency SAC
(SAC × multiplier) — **not** the whole deco billed to back gas (that would be
hundreds of bar deep). The GUI also re-plans lost-deco-gas contingencies: one
schedule per lost deco gas plus an all-lost worst case (any N of deco gases),
with per-scenario litres usage. The full dive (depth,
time, GF, gas stack, SAC, multiplier, problem time, ascent/descent/stop rates + ppO2
window, RD toggle) lives in `dive_plan.json`, shared by the CLI (`plan dive_plan.json`
/ `--load` / `--save`) and the GUI (Save / Reload). Save / `--save` captures **every**
value for an exact round-trip; the GUI preserves fields it has no control for.

## Conventions

- **Zero runtime deps in `buhlmann.py`, `cli.py`, `ratio_deco.py`.** Only `app.py`
  may import matplotlib/tkinter. Do not add dependencies to the core.
- Python style: `from __future__ import annotations`, full type hints, frozen/plain
  `@dataclass`, module docstrings. Match the existing terse style.
- Units: depth = msw, pressure = bar absolute, time = minutes, gas fractions 0..1.
- Defaults (see `DivePlan`): GF 30/80, descent 18 m/min, ascent 10 m/min, 3 m stops,
  last stop 3 m (`last_stop_depth`, 6 = Shearwater style), deco ppO₂ 1.6,
  P_atm 1.01325 bar, 10 msw/bar, P_H₂O 0.0627 bar. Ascent gas switches snap
  to stop depths (`switch_depth`, ppO₂ overshoot ≤ `ppo2_switch_tol` 0.05 bar
  — that's what puts O₂ at the 6 m stop despite its 5.9 m MOD).
- Comments only where the math is non-obvious — cite the equation/source, as done now.

## When you change things

- Touch model math/constants → **run the tests** and add/adjust a test for the new
  behaviour. NDL tests tolerate ±5–6 min vs published Bühlmann tables. The
  Subsurface cross-check pins tissue math and ceilings to machine precision —
  if it fails after a model change, the change is almost certainly wrong (or
  deliberately diverges from Subsurface: then update the test *and* document
  why).
- **License boundary:** `tests/subsurface_oracle/` is GPL-2.0. Compare outputs
  freely; never copy code, constants-with-structure, or comments from there
  into MIT-licensed files. Fix model bugs clean-room from Bühlmann/Baker's
  published papers plus the numeric disagreement.
- Known aligned-constants differences vs Subsurface (deliberate, see the
  cross-check module docstring): air 21/79 vs 20.9/79.1, surface saturation
  fN₂ 0.79 vs 0.781, 10 msw/bar vs salinity-based 9.8968, surface 1.01325 vs
  1.013 bar, static rounded GF-low anchor vs dynamic smooth anchor with a
  surface+1 bar floor.
- **eko-deco deliberately follows the Baker/Shearwater/MultiDeco GF
  convention** (static GF-low anchor at the rounded first stop, air 21/79,
  10 msw/bar, NDL at GF-high) — `tests/test_baker_crosscheck.py` pins it
  (≤1 min/stop vs GFDECO). Do not "fix" the planner toward Subsurface's
  dynamic anchor; that divergence is intentional.
- Add a CLI flag → update `cli.py` argparse, `README.md`, and the Commands block above.
- Keep `README.md`, the skill (`.claude/skills/deco-buhlmann/SKILL.md`) and this file consistent.

## Windows gotcha (UTF-8)

Source is UTF-8 (`Bühlmann`, `₂`). The Windows console (cp1252) renders those as
mojibake (`B�hlmann`) — cosmetic only. For clean output set `PYTHONUTF8=1` (or
run `chcp 65001`) before the CLI.

## Agent layout (works for Claude *and* Copilot CLI)

- `CLAUDE.md` (this file) — canonical instructions; loaded by Claude Code **and** Copilot CLI.
- `AGENTS.md` — pointer here, for other AGENTS.md-aware tools.
- `.github/copilot-instructions.md` + `.github/instructions/*.instructions.md` — Copilot-native instruction files.
- `.claude/skills/deco-buhlmann/` — Agent Skill, auto-discovered by Claude **and** Copilot CLI.
- `.claude/commands/*.md` — Claude slash commands: `/plan-dive`, `/ndl`, `/tissues`, `/ratio`, `/run-tests`.
- `.claude/agents/dive-planner.md` — dive-planning subagent.
- `.claude/settings.json` — pre-approves running Python + the test suite.
