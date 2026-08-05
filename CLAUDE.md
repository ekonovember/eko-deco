# CLAUDE.md — deco

> Agent instructions for this repo. **Read automatically by both Claude Code and
> GitHub Copilot CLI** when you open a terminal here (Copilot lists `CLAUDE.md`
> among its instruction sources). This file is the single source of truth; the
> other agent files (`AGENTS.md`, `.github/copilot-instructions.md`) point back here.
>
> Companion: [`DECISIONS.md`](DECISIONS.md) is the numbered decision log this
> file and the code both cite (`see DECISIONS.md #7`). Read it before "fixing"
> anything that looks wrong — it is probably intentional and the entry says why.

## ⚠️ Scope & safety

`deco` is an implementation of the Bühlmann ZHL-16C decompression model with
gradient factors, written to be read and cross-checked against the reference
implementations. It carries no printed disclaimer — that was removed from every
output path deliberately, on the repo owner's decision, and must not be
reintroduced. What replaces it is the **warnings**: `ppo2_violations`,
`ceiling_violations` and the density ceiling are the safety surface now, so they
are non-negotiable on anything that produces a schedule, NDL or ceiling.

## What this is

A small, dependency-free Python library (+ CLI and optional GUI) that computes:

- No-decompression limits (NDL)
- Decompression stop schedules (square profile, multi-gas)
- Tissue inert-gas loading (16 compartments, N₂ + He)
- Ceilings via Erik Baker's gradient factors

## Module map

| File | Role | Deps |
|------|------|------|
| `src/deco/buhlmann.py` | Core model: `Gas`/`Tissues`, Schreiner, `ceiling`, gradient factors, `Level`/`plan_multilevel` (multi-level; `plan_dive` = one level; a `Level` is depth + cumulative runtime and nothing else — levels are contiguous, the transit is billed to the level's runtime, and a runtime too short to cover it is an error, as in MultiDeco), `ndl`, `time_to_surface`, `max_depth`/`average_depth`/`ceiling_violations`, `ceiling_profile` (time-series of the GF ceiling for plotting), `GasPlan`/`rock_bottom_liters`/`emergency_gas_liters` (per-gas rock-bottom emergency reserve — an approximation, see [DECISIONS.md](DECISIONS.md) #7: the reserve from the worst moment only, i.e. `problem_minutes` at max depth — billed to the max-depth/bottom gas — plus the real planned ascent + deco at SAC × multiplier, following each gas only to the next switch; the gas already breathed on the way down is NOT part of the reserve; `GasPlan.divers` > 1 shares the supply — problem + ascent up to the first gas switch × divers, no switch = shared to the surface. `rock_bottom_liters` is just the bottom gas's `emergency_gas_liters`; the front-end emergency *column* adds this reserve on top of the normal need (`need + emergency_gas_liters`, in `report.py`)), safety checks: `ppo2_violations`/`worst_ppo2_violations` (segments breathed outside the ppO₂ window — a designated deco gas is judged against the deco ceiling `ppo2_deco` 1.6 wherever it is breathed, even on a shallow deco stop; the bottom/travel gas uses the working ceiling `ppo2_bottom` 1.4 going down or held on a level — the planner plans what it is given, air below its MOD or a hypoxic mix without travel gas included, but never silently: front ends must surface these), `cns_otu` (NOAA CNS% clock + Repex OTU), `Gas.end` (equivalent narcotic depth, O₂-narcotic convention) and `Gas.density` (g/L, `DENSITY_MAX_G_L` = 6.2 Anthony & Mitchell ceiling), `runtime_min`/`StopLeg`/`stop_legs` — **the printed-schedule notation, defined once and rendered by every view** (`run` = the runtime you LEAVE that depth, truncated; `leg` = ascent to the stop + hold, measured from the previous stop and from leaving the bottom for the first; TTS rounds UP; a gas-switch row is an annotation the legs are NOT measured from — DECISIONS #17), `surface_p_at_altitude`/`altitude_at_surface_p` (standard-atmosphere conversion for altitude dives) and `WATER_TYPES` (`salt` 10.0 / `fresh` 10⅓ msw per bar) — the environment is a *setting* now, not a constant (DECISIONS #15), `PLANNER_PROFILES` + `P_H2O_SCHREINER`/`P_H2O_BUHLMANN` — **`P_H2O` defaults to Schreiner 0.0567** (MultiDeco/Shearwater/GFDECO), not Bühlmann's 0.0627 (Subsurface's, passed explicitly by that cross-check); `--planner NAME` selects a whole constant set so a plan can sit beside another tool's without flag-hunting (DECISIONS #20), `GasPlan.sac_deco`/`sac_for` (an optional second SAC for gas breathed off a designated deco cylinder, DECISIONS #16), `DivePlan` carries **every** algorithm input including `p_h2o` and `ppo2_switch_tol` — all of them settable from the config, CLI and GUI, with `tests/test_input_coverage.py` failing if one is not (DECISIONS #19); `DivePlan.__post_init__` rejects GF-low > GF-high / out-of-range GFs, `contingency_schedules` (bottom-timer cut-table matrix: square @ max depth on a fixed 3 min × 3 m grid, rows = bottom-time variants × columns = depth variants, step counts before/after per axis; rectangular grid — unplannable cells stay as `segments=None` for column alignment, `ContingencyCell.text()` is the shared wetnotes cell format `depth:min … · TTS′`). **Keep dependency-free.** | stdlib only |
| `src/deco/cli.py` | CLI front end: `plan`, `ndl`, `tissues` (+ `--json`); `plan --load/--save` a config; `mix@tank@bar` gas suffix (a 4th `@` field is rejected); per-cylinder gas; `plan --contingency [TB[:TA[:DB[:DA]]]]` (step counts) prints the cut-table matrix (and a `contingency` key in `--json`). The schedule table has a cumulative `run` column; every plan prints ppO₂/density/ceiling warnings, CNS/OTU, END + density of the bottom gas, (also `warnings`/`cns_pct`/`otu`/`end_m`/`gas_density_g_l` and a `stops` list in the card notation in `--json`; no disclaimer key). `cmd_plan` computes a `report.PlanResult` once, then `_plan_json`/`_plan_text` render it (no re-derivation). `--level DEPTH:RUNTIME` (cumulative runtime at the END of the level, transit included). `--water salt|fresh` / `--msw-per-bar` / `--altitude M` / `--surface-p BAR` / `--p-h2o` / `--ppo2-switch-tol` / `--planner NAME` set the environment and model (explicit values win over the preset/altitude; a non-default environment gets its own header line), `--sac-deco` the deco-cylinder SAC. `--save` writes levels as pure depth/time periods (gas is automatic by role — no per-level references or inline mixes). CLI GF default is 30/**70** (matches the config/GUI; the library `DivePlan` default stays 30/80). Loading a config is **strict** — missing/corrupt file = error exit 2, never a silent default plan — and other CLI flags are ignored with a stderr note. Same-mix cylinders aggregate (volumes add, volume-weighted fill). | buhlmann, dive_config, report |
| `src/deco/report.py` | Shared stdlib-only layer between `buhlmann` and both front ends: everything user-facing that is *computed* lives here once so the CLI and GUI cannot drift. `DEFAULT_FILL_BAR`, `water_name` (msw/bar → salt/fresh/custom label), `wetnotes_rows` (the printed runtime-card rows, built on `buhlmann.stop_legs`), `runtime_min` (re-exported from `buhlmann`; a runtime truncated to whole minutes — MultiDeco's convention, verified against a real export; every rendered runtime goes through it), `warning_lines`, `Bank`/`aggregate_banks` (same-mix cylinders → one bank), `CylinderNeed`/`GasReport`/`gas_report` (per-mix need/have/emergency/SHORT + rock bottom), `PlanResult`/`compute_plan_result`. **Gases are keyed by the frozen `Gas` value, never its rounded `repr`** — two mixes that render the same label keep separate accounting. **Keep dependency-free.** | buhlmann |
| `src/deco/dive_config.py` | Shared JSON dive config (`load`/`save`/`normalize`/`to_buhlmann`) read by the GUI and written by `plan --save`. `load(strict=True)` raises on a missing/corrupt file (CLI); the lenient default falls back to `default_config()` (GUI first launch) — normalization happens *inside* that strict/lenient boundary so a semantically corrupt file can't slip through as a silent default. `save()` is atomic (temp file + `os.replace`). Where the file lives is `default_path()`: `$DECO_CONFIG`, else `./dive_plan.json` if the cwd has one, else the per-user config dir (`user_config_path()`) — there is no module-level `DEFAULT_PATH` any more (DECISIONS #11). Public `normalize(cfg)` (front ends use it instead of `_merged`). Levels are pure depth/time periods (`depth_m` + cumulative `runtime_min`) and gas is chosen automatically by role. Legacy per-level gas references (`gas_id` or inline mixes), legacy `"Level"`-role gases and legacy `start_min` arrival times are dropped on load. Adds `surface_p_bar`/`msw_per_bar` (environment) and `sac_deco` (`null` = one rate); a config predating them still loads as sea-level salt water with a single SAC. | buhlmann |
| `dive_plan.json` | The full dive: `levels` (depth + cumulative runtime — pure depth/time periods; gas is chosen automatically by role, so levels carry no mix of their own), GF, gas stack (per-gas tank + fill pressure + `enabled` toggle + role Bottom/Travel/Deco; a disabled gas is never planned; legacy per-level gas references and `"Level"`-role gases are dropped on load), SAC + optional deco SAC + emergency SAC multiplier, problem time + `divers` (emergency team size), water type + surface pressure (`msw_per_bar`/`surface_p_bar`), ascent/descent/stop rates + ppO2 window, `contingency` cut-table step counts on the fixed 3 min × 3 m grid (`time_before`/`time_after`/`depth_before`/`depth_after`, 0 disables a direction; legacy `time_delta_min`/`depth_delta_m` migrate on load). Agent-editable. | — |
| `src/deco/app.py` | Tkinter + matplotlib GUI: left settings (GF row + 'Last stop 6 m' switch on top, then the **environment** row — water dropdown (salt/fresh/custom) writing m/bar, plus altitude writing surface pressure (both one-way: the numeric fields are the stored truth and stay hand-editable, so a constant from another planner survives a round trip), then an editable **Levels** list (depth / cumulative **runtime**, + Add level — two fields only, read/written via `_row_levels`/`_level_row_dict`; levels are contiguous so the transit is part of the runtime) and the editable gas list w/ tank+bar, then SAC + an optional deco SAC (0 = same rate) / multiplier / problem minutes + a '2 divers' checkbox, then a collapsed **Algorithm & rates** panel (descent/ascent rate, stop interval, free last-stop depth, the whole ppO₂ window incl. the switch tolerance, and P_H₂O — every remaining plan input, none of it config-passthrough any more) (stored as `divers` 1/2), then four **Contingency (cut table)** sliders — bottom-time steps −/+ and depth steps −/+ on the fixed 3 min × 3 m grid, persisted in the config's `contingency` block, 0 disables a direction); the rest is a two-tab notebook — **Results** (stops + lost-deco-gas scenario table, per-scenario gas usage as **have / need (emergency)** — tank×bar carried vs litres required at the normal SAC, with the rock-bottom emergency reserve (`buhlmann.emergency_gas_liters`: problem minutes @ max depth + the real ascent/deco to the next switch at SAC × multiplier) **added on top of the normal need** in parentheses (the `(emrg)` figure = need + reserve); `SHORT!` flags a shortfall at the normal SAC and a second `SHORT!` inside the emergency parens when even need-plus-reserve is exceeded — plus bar left at both the normal and emergency need, and the gas plan whose columns are **need / have / (emrg)**) + a printable **Runtime** wetnotes card — one framed card per lost-gas scenario, rows from `report.wetnotes_rows` so the STOP column always adds up to the RUN column (DECISIONS #17), then the bottom-timer **CUT TABLE** matrix card from `buhlmann.contingency_schedules` (bottom-time rows × depth columns, each cell `ContingencyCell.text()` — stops + TTS rounded UP, `no deco`/`n/a`; `*` marks the planned row/column) — with PNG export, and **Profile** (the depth/time chart with the deco ceiling overlaid via `buhlmann.ceiling_profile`). Dark mode in the **Settings** menu. Loads/saves `dive_plan.json`; dark mode + window geometry (saved on close, restored on start; 1x1 unmapped geometries never persisted) live in `ui_settings.json` next to the per-user config dir (never mix UI prefs into the dive config — DECISIONS #10). `--install-launcher` (`deco-gui --install-launcher`) registers a per-user Linux `.desktop` + icon whose `Exec` is `<python> -m deco.app` (so it survives moving the checkout), so GNOME docks show the `<//>` tile (window icon alone is ignored there; keep iconphoto images ≤128 px — Tk 8.6 silently writes an empty `_NET_WM_ICON` above that). Safety surfacing: ppO₂/ceiling/density warnings as ⚠ cards, CNS/OTU + END/density + the config-driven rates/ppO₂ limits in the DIVE/GAS cards, silent-fallback notices (no Bottom gas, invalid mix row), gas-switch rows (`gas` in the stop column) on the wetnotes card, same-mix cylinders aggregated via `_cylinders_by_mix`, and a strict config load on startup (a corrupt file shows "⚠ config unreadable — defaults", never a silent default plan). | matplotlib, tkinter, dive_config |
| `tests/` | `unittest` suites: `test_buhlmann.py`, `test_cli.py`, `test_report.py`, `test_dive_config.py`, `test_app_levels.py`, `test_cards_format.py` (the printed card carries the planner's own numbers; skips without matplotlib), `test_input_coverage.py` (every plan input binds in config+CLI+GUI), `test_multideco_scenarios.py`, `test_planner_diff.py`, `test_subsurface_crosscheck.py`, `test_baker_crosscheck.py`, `test_shearwater_golden.py`. `tests/__init__.py` puts `src/` on `sys.path`, which is why discovery needs `-t .` (DECISIONS #13). | stdlib |
| `tests/planner_diff.py` | **Constant/variable divergence harness.** `registry()` is every model constant and planner setting we have, each tagged with the observables that could pin it; `registry_gaps()` introspects `buhlmann` and a test **fails if anything is unregistered**, so a new constant cannot be added invisibly. `Evidence` holds what a reference export prints (ppO₂, ead, density, schedule deltas, CNS/OTU, gas litres, stated settings); `infer_environment` inverts printed pressures to a feasible (surface_p, msw_per_bar) box by grid search; `compare()` returns one verdict per tunable — `DIVERGES` / `UNDETERMINED` (nothing in the evidence touches it — never confuse with agreement) / `SETTING` (the export states it; just pass it) / `JOINT_OK` (only identifiable as a group, and the group agrees) / `MATCH`. Run `python -m tests.planner_diff` for a report on the bundled exports. Add a new planner by writing one `Evidence`. | stdlib |
| `tests/python_oracles.py`, `tests/test_python_oracles.py` | **Third-party Python oracles** — `decotengu` + `decodaitengu`, `pip install -e ".[dev]"`, GPL-3, **test-only and never vendored** (nothing in `src/deco` imports them). Four implementations make "who is wrong" answerable: our ceiling matches decodaitengu to 0.03 mbar (vs a 5.4 mbar MultiDeco gap), the 4.0/5.0 min first compartment splits two-two, and decodaitengu's slow-compartment helium `a` is a different model so it is a **nitrogen** oracle only (DECISIONS #22). Skips when absent, like g++/gfortran. | decotengu, decodaitengu |
| `tests/subsurface_oracle/` | **GPL-2.0, test-only.** Unmodified Subsurface `core/deco.cpp` (pinned commit in `upstream/UPSTREAM.txt`) + stub headers; `build.sh` compiles `libsubsurface_deco.so`. Never import at runtime, never copy code out of it (license boundary — see its README). | g++ |
| `tests/subsurface_deco.py` | ctypes wrapper around the oracle `.so` (auto-builds it); `SubsurfaceDeco.plan()` is a small planner-style schedule loop of ours, the model calls are native Subsurface code. | stdlib + oracle |
| `tests/baker_oracle/` | Erik Baker's original `gfdeco.f` ("distribute freely — credit the author"), the reference for the Shearwater/MultiDeco GF convention. ZH-L16B + WV 0.0567 bar + surface 1.000 bar — the test patches eko-deco to match. `build.sh` compiles the `gfdeco` binary. | gfortran |
| `tests/baker_deco.py` | Runner for the GFDECO binary: writes `GFDECO.IN`/`.SET` in a temp dir, parses the schedule from `GFDECO.OUT`. | stdlib + oracle |
| `tests/shearwater_golden.json` | Golden schedules from real planners: 4 MultiDeco schedules (transcribed from `multideco_screenshots/`, incl. the lost-gas scenario columns; settings inferred — see `_multideco_provenance` in the file) + 8 from the two real exports in `examples/scenario_1|2/` (settings printed, not inferred: each dive plus its three lost-gas columns — `_scenario_provenance`) + Shearwater Cloud templates to fill. Unfilled entries show up as skipped tests. | — |
| `examples/*.json` | Ready-to-run command snippets. | — |
| `examples/scenario_1/`, `examples/scenario_2/` | **Real MultiDeco 4.24 exports** (Polish UI, `data.txt`) kept verbatim as evidence: a 32 m/40 min fresh-water dive at 150 m on EAN36 GF 40/85 and on EAN28 GF 5/50, each with its plan, gas volumes and lost-gas table. Transcribed into `tests/shearwater_golden.json` (8 schedules) and `tests/test_multideco_scenarios.py` (everything else the exports print). **Don't reformat or 'fix' them** — they are the source. | — |
| `src/deco/assets/` | Packaged window/taskbar icons (`icon.png`, `icon.ico`) — package data, ship in the wheel. | — |
| `cards/` | **Layout engine** for print-ready 90 × 64 mm wetnotes **runtime cards**: `make_cards.py` renders a card spec to an exact-size PDF (+ PNG) and imposes several 4× on A4 with crop marks — it computes nothing, you feed it numbers from `deco.cli`. `EXAMPLE` at the bottom of the file is the spec shape (placeholder numbers, not a dive plan); run the module directly to render it. Generated PDFs/PNGs are gitignored — cards are made per dive and not kept. [`cards/README.md`](cards/README.md) is the **reference for the printed runtime format** (columns `DEPTH · GAS · STOP · RUN`, ascent order, RUN = when you leave the stop, TTS last, contingencies as parallel columns) with the sources it was verified against — chiefly the two real exports in `examples/`. **No PDFs are committed**: generated cards and third-party manuals are both gitignored, and `cards/reference/README.md` cites the vendor MultiDeco-X1 manual by URL + SHA-256 instead of redistributing it (© HHS Software; never copy text out of it). `table_from_plans`/`gas_line` build a card straight from `deco plan --json`, so a cell cannot drift from the schedule; `fit_size` auto-fits the type so a 7-stop trimix schedule still fits the 90 × 64 mm card. Follow that format for any new printed/exported schedule. | matplotlib |
| `pictures/` | Branding + README screenshots: `logo.png`, `app_ui.png`/`app_profile.png`, `social_preview.png` (upload manually under GitHub Settings → Social preview — no API for it), `gen_assets.py` regenerates the icons (into `src/deco/assets/`) and the social card (dev-only: matplotlib + Pillow). | — |
| `pyproject.toml` | Packaging (`eko-deco`, entry points `deco` / `deco-gui`, extras `[gui]`/`[dev]`) **and** the ruff + mypy configuration. | — |
| `DECISIONS.md` | Numbered, stable decision log. Code cites it (`see DECISIONS.md #7`). Read it before "fixing" something intentional; add an entry when you make a choice a future reader would question. | — |
| `CONTRIBUTING.md`, `CHANGELOG.md` | Setup + house rules; notable changes. | — |
| `.github/workflows/ci.yml` | CI: core suite on 3.10–3.14 × Linux/macOS/Windows, a cross-check job that **fails if the oracles skip**, ruff + mypy, a GUI smoke test under Xvfb, and a wheel build. | — |

Data flow: a `Gas` + depth/time goes into `plan_dive`, which steps the 16
compartments with the **Schreiner equation**; `ceiling` + gradient-factor
interpolation (`gf_at`) drive first-stop detection and stop lengths.

## Commands

Python 3.10+ (verified on 3.14). The core library and tests need **no**
third-party packages. The package is `src/deco/`, so run either front end as a
module from the repo root (`.claude/settings.json` sets `PYTHONPATH=src`; add it
by hand if your shell does not) — or `pip install -e ".[gui]"` and use the
`deco` / `deco-gui` console scripts, which take the identical arguments.

```bash
# Plan a deco schedule (trimix + deco gases)
python -m deco.cli plan --depth 45 --time 25 --gas 21/35 --deco-gas 50 --deco-gas 100 --gf-low 0.30 --gf-high 0.70
# Hypoxic trimix + travel gas + gas planning (TTS + rock bottom)
python -m deco.cli plan --depth 60 --time 25 --gas 10/70 --travel-gas 35/25 --deco-gas 50 --sac 18 --sac-multiplier 1.5 --tank-size 24
# Per-gas tanks + fill pressures, save to the shared config (dive_plan.json)
python -m deco.cli plan --depth 45 --time 10 --gas air@24@232 --deco-gas 50@11@200 --sac 20 --gf-high 0.70 --save
python -m deco.cli plan dive_plan.json  # (or --load) replan the saved dive; the GUI shares this file
# No-decompression limit
python -m deco.cli ndl --depth 30 --gas air
# Tissue-loading report (machine-readable)
python -m deco.cli tissues --depth 40 --time 20 --gas ean32 --json
# GUI (needs matplotlib; tkinter ships with CPython on Windows)
python -m deco.app
# Multi-level dive (RUNTIME is cumulative: minutes since the surface, at the END of the level)
python -m deco.cli plan --level 45:25 --level 30:40 --level 18:55 --gas 21/35 --deco-gas 50 --deco-gas 100
python -m deco.cli plan --level 120:20 --level 45:40 --gas 10/70 --travel-gas 35/25   # gas auto by role
# Shearwater/MultiDeco-style last stop at 6 m
python -m deco.cli plan --depth 45 --time 25 --gas 21/35 --deco-gas 50 --deco-gas 100 --last-stop 6
# Environment: fresh water and/or altitude (both move every pressure the plan
# derives — schedule, ppO2, MOD, END, density, CNS/OTU, gas volumes)
python -m deco.cli plan --depth 32 --time 40 --gas ean36 --deco-gas 50 --water fresh --altitude 150
python -m deco.cli plan --depth 32 --time 40 --gas ean36 --planner subsurface   # plan in another tool's constants
python -m deco.cli ndl --depth 30 --gas air --altitude 1500
# Separate deco-cylinder SAC (MultiDeco/Shearwater plan the two rates apart)
python -m deco.cli plan --depth 40 --time 25 --gas air --deco-gas 50 --sac 20 --sac-deco 16
# Contingency cut table (bottom-timer backup): square @ max depth on a 3 min × 3 m
# grid, time rows −TB/+TA steps × depth columns −DB/+DA steps
python -m deco.cli plan --depth 40 --time 25 --gas air --deco-gas 50 --contingency          # counts from config (1:1:1:1)
python -m deco.cli plan --depth 40 --time 25 --gas air --deco-gas 50 --contingency 0:2:0:1  # explicit TB[:TA[:DB[:DA]]]
# Tests: 307 total = 269 core (stdlib only) + 26 compiled cross-checks
#        + 12 python-oracle cross-checks (pip, skip when absent).
# The cross-checks COMPILE the reference implementations (g++ for Subsurface's
# deco.cpp, gfortran for Baker's GFDECO) and skip when those are absent — so
# "Ran 269 tests" with 38 skipped on a bare machine is expected, not a data problem.
python -m unittest discover -s tests -t . -v
# Individual oracles: native Subsurface deco.cpp / Baker's GFDECO Fortran
python -m unittest tests.test_subsurface_crosscheck -v
python -m unittest tests.test_baker_crosscheck -v
# Which constants differ from a reference planner, and which the evidence
# cannot speak to at all (UNDETERMINED != agrees)
python -m tests.planner_diff
# Lint + types (config in pyproject.toml; both are clean and CI enforces them)
pip install -e ".[dev]" && ruff check . && mypy
```

Gas syntax: `air`, `o2`, `ean32` / `nx32` / `32`, trimix `21/35` (fO₂/fHe %).

Gas planning: each cylinder has a tank size + fill pressure (`mix@tank@bar`, e.g.
`air@24@232`). One basic SAC plus an emergency SAC multiplier (`sac_multiplier`,
e.g. 1.5), a problem time (`problem_minutes`) and a diver count (`divers`).
The library helper `emergency_gas_liters` is the *rock-bottom reserve* for
a problem striking at the worst moment — the end of the bottom phase (deepest
loading → longest deco). It counts only the reserve from that moment: the
problem minutes at max depth (billed to the gas breathed there, i.e. the bottom
gas) plus the real planned ascent + deco at the emergency SAC (SAC ×
multiplier), following each gas only to the next switch. The gas already
breathed on the way down is the normal-SAC `need`, not part of the reserve.
With `divers` = 2 the team shares the supply (buddy out of gas): the problem
minutes and the ascent **up to the first gas switch** are doubled; from the
switch each diver is back on their own cylinder (no switch = shared to the
surface). The front-end **emergency column** (`(emrg)` / the parenthesised
figure = `report.CylinderNeed.liters_emergency`) is the *total* to carry: the
normal `need` PLUS that reserve held on top (`need + emergency_gas_liters`), so
`SHORT!` in the parens means the fill can't cover need-plus-reserve. **Rock
bottom** is standard *minimum gas* — it is exactly the bottom gas's
`emergency_gas_liters` (problem + the real ascent/deco to the first switch, ×
divers) — **not** the whole deco billed to back gas (that would be hundreds of
bar deep). The GUI also re-plans lost-deco-gas contingencies:
one schedule per lost deco gas plus an all-lost worst case (any N of deco gases),
with per-scenario usage as have / need (emergency) — carried (tank × fill pressure)
vs need at the normal SAC, with the emergency total (need + rock-bottom reserve) in parentheses; SHORT!
flags a normal-SAC shortfall and a second SHORT! inside the parens an emergency one. The full dive
(`levels`, GF, last stop, gas stack, SAC, multiplier, problem time, divers,
ascent/descent/stop rates + ppO2 window) lives in `dive_plan.json`, shared by the CLI (`plan dive_plan.json`
/ `--load` / `--save`) and the GUI (Save / Reload). Save / `--save` captures **every**
value for an exact round-trip; the GUI preserves fields it has no control for.

## Conventions

- **Zero runtime deps in `deco.buhlmann`, `deco.report`, `deco.dive_config`
  and `deco.cli`.** Only `deco.app` may import matplotlib/tkinter. Do not add
  dependencies to the core (DECISIONS #1).
- Python style: `from __future__ import annotations`, full type hints, frozen/plain
  `@dataclass`, module docstrings. Match the existing terse style. Modern
  annotations only (`list[str]`, `X | None`). Intra-package imports are absolute:
  `from deco import buhlmann as b`.
- **`ruff check .` and `mypy` must stay clean** — both are configured in
  `pyproject.toml` and enforced in CI. There is deliberately no auto-formatter
  (DECISIONS #14): the coefficient tables, schedule columns and wetnotes card are
  hand-aligned. Line length 96.
- Units: depth = msw, pressure = bar absolute, time = minutes, gas fractions 0..1.
- A dive is a list of `Level(depth, runtime)` — depth + cumulative runtime, and
  **nothing else**. **`runtime` is cumulative** — minutes since the surface at the
  END of the level, descent included (what `bottom_time` always meant, and what
  MultiDeco/GFDECO/Subsurface take). `plan_dive` is `plan_multilevel` with one
  level; keep it that way so square dives can't drift. Levels are **contiguous**:
  the transit to a level leaves the moment the previous one ends and its time is
  billed to that level's runtime. **Do not re-add an arrival-time field** — no
  planner has one (MultiDeco rejects a level time that cannot cover the
  descent/ascent: "Segment time for the … level is too short"), and the version
  that did produced duplicate same-depth rows and phantom 0 m holds on the
  wetnotes card. To loiter shallow before going deeper, add a level for the
  shallow depth. Travel between levels is bottom time, not TTS
  (`_bottom_phase_end`).
- **Stops follow Baker's discretisation, in his order** (DECISIONS #21, read
  off `gfdeco.f`): pad the runtime onto the next `min_stop_time` grid point
  **first**, then add whole increments while the ceiling blocks the next stop.
  A stop is therefore *pad + k × min_stop_time*, never a sub-minute remainder,
  and the diver stops at the rounded GF-low ceiling even where the ascent
  already cleared it (*pass-through* stops, gated on the GF-high ceiling so an
  NDL dive gets none). TTS matches GFDECO to **0.00 min** on all seven
  cross-check cases. Don't reorder it to "resolve the obligation, then round" —
  that charges an extra minute when the obligation lands on the pad, and it is
  what made our runtimes drift from every other planner.
- **The printed-schedule notation is `buhlmann.StopLeg`/`stop_legs`, and every
  renderer uses it** — the runtime card, the GUI stop table and the cut-table
  cell. `run` = the runtime you LEAVE that depth (truncated), `leg` = the
  ascent to the stop plus the hold measured from the previous stop, TTS rounds
  UP. Never print a bare hold beside a runtime (DECISIONS #17).
- **Runtimes are rendered through `report.runtime_min`** — truncated to whole
  minutes. That is MultiDeco's convention, verified against a real export
  (`1.61 → 1`, `43.875 → 43`, `50.44 → 50`): every row is the floor, never a
  round. Both front ends go through the helper so the cards cannot drift.
- Defaults (see `DivePlan`): GF 30/80 (the **CLI and config/GUI default to
  30/70** — the front ends must agree with each other; the library keeps 30/80),
  descent 18 m/min, ascent 10 m/min, 3 m stops,
  last stop 3 m (`last_stop_depth`, 6 = Shearwater style), deco ppO₂ 1.6,
  P_atm 1.01325 bar, 10 msw/bar, P_H₂O **0.0567** (Schreiner — what the
  planners divers carry use; DECISIONS #20). The first two are
  **defaults, not constants**: `surface_p`/`msw_per_bar` are settings all
  the way out to the config, CLI and GUI (fresh water, altitude —
  DECISIONS #15). P_H₂O stays a module global, patched only by tests.
  Ascent gas switches snap
  to stop depths (`switch_depth`, ppO₂ overshoot ≤ `ppo2_switch_tol` 0.05 bar
  — that's what puts O₂ at the 6 m stop despite its 5.9 m MOD).
- **Warnings are load-bearing.** `ppo2_violations`, `ceiling_violations` and the
  density ceiling exist because the planner deliberately plans whatever profile
  it is given (GFDECO-style) instead of refusing — any new front end or output
  path must surface them on anything that looks like a schedule. With the
  disclaimer gone they are the only safety surface left, so this is stricter
  than before, not looser (DECISIONS #4, #5).
- Comments only where the math is non-obvious — cite the equation/source, as done now.

## When you change things

- Touch model math/constants → **run the tests** and add/adjust a test for the new
  behaviour. A new **plan field** must also be wired into the config, the CLI
  and the GUI — `tests/test_input_coverage.py` fails until it is, and until it
  has a probe value there (DECISIONS #19). A *new* constant must also be registered in
  `tests/planner_diff.registry()` with the observables that could pin it —
  `test_planner_diff` fails until it is, on purpose: a constant nobody
  enumerated is a difference nobody can detect. NDL tests tolerate ±5–6 min vs published Bühlmann tables. The
  Subsurface cross-check pins tissue math and ceilings to machine precision —
  if it fails after a model change, the change is almost certainly wrong (or
  deliberately diverges from Subsurface: then update the test *and* document
  why).
- **Persistence:** the GUI saves what the user *typed*, not what currently plans.
  `_row_levels()` keeps every level row (a field blanked mid-edit must not delete
  the level); `_levels()` filters to plannable rows and is only for computing.
  `dive_config._merged()` guarantees at least one level — never persist an empty
  profile. Both are regression-tested; don't collapse the two accessors back.
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
- Add a CLI flag → update `src/deco/cli.py` argparse, `README.md`, and the Commands block above.
- Keep `README.md`, the skill (`.claude/skills/deco-buhlmann/SKILL.md`) and this file consistent.
- **Made a choice a future reader would want to undo?** Add a numbered entry to
  [`DECISIONS.md`](DECISIONS.md) and cite it from the code (`see DECISIONS.md #N`).
  Numbers are stable — never reuse or renumber them.
- User-visible change → a line in `CHANGELOG.md` under `[Unreleased]`.
- Before you claim done: `python -m unittest discover -s tests -t .`,
  `ruff check .`, `mypy`.

## Windows gotcha (UTF-8)

Source is UTF-8 (`Bühlmann`, `₂`). The Windows console (cp1252) renders those as
mojibake (`B�hlmann`) — cosmetic only. For clean output set `PYTHONUTF8=1` (or
run `chcp 65001`) before the CLI.

## Agent layout (works for Claude *and* Copilot CLI)

- `CLAUDE.md` (this file) — canonical instructions; loaded by Claude Code **and** Copilot CLI.
- `AGENTS.md` — pointer here, for other AGENTS.md-aware tools.
- `.github/copilot-instructions.md` + `.github/instructions/*.instructions.md` — Copilot-native instruction files.
- `.claude/skills/deco-buhlmann/` — Agent Skill, auto-discovered by Claude **and** Copilot CLI.
- `.claude/commands/*.md` — Claude slash commands: `/plan-dive`, `/ndl`, `/tissues`, `/run-tests`.
- `.claude/agents/dive-planner.md` — dive-planning subagent.
- `.claude/settings.json` — pre-approves running Python/ruff/mypy, and sets
  `PYTHONPATH=src` so `python -m deco.cli …` works with nothing installed.
