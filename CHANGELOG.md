# Changelog

Notable changes, newest first. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project is
pre-1.0, so anything may still move.

## [Unreleased]

### Changed — packaging and layout (breaking)

- The library moved to a **src layout**: `src/deco/`, installable as
  `eko-deco`. `python cli.py …` and `python app.py` no longer work; use the
  console scripts `deco` and `deco-gui`, or `python -m deco.cli` /
  `python -m deco.app`.
- `dive_plan.json` is now resolved by `dive_config.default_path()`:
  `$DECO_CONFIG`, else `./dive_plan.json` in the working directory, else the
  per-user config directory. `dive_config.DEFAULT_PATH` is gone
  ([DECISIONS.md #11](DECISIONS.md)).
- The GUI's `ui_settings.json` (dark mode, window geometry) moved to the
  per-user config directory. Existing preferences in the repo root are not
  read; dark mode and window size reset once.
- `--install-launcher` now writes `Exec=<python> -m deco.app`, so the desktop
  entry survives moving the checkout.
- The app icons moved from `pictures/` into the package (`deco/assets/`) and
  ship in the wheel. `pictures/` keeps the README screenshots and branding.

### Added

- **Water type and altitude are settings now** ([DECISIONS.md #15](DECISIONS.md)).
  `surface_p` and `msw_per_bar` existed in the library but nothing outside it
  could reach them, so every dive planned as sea-level salt water. Now:
  `--water salt|fresh`, `--msw-per-bar`, `--altitude M` and `--surface-p BAR`
  on the CLI (explicit values win over the preset/altitude); `surface_p_bar`
  and `msw_per_bar` in `dive_plan.json`; a water dropdown plus altitude and
  surface-pressure boxes in the GUI. They move the schedule, ppO₂, MOD, END,
  density, CNS/OTU and gas volumes alike. New helpers
  `buhlmann.surface_p_at_altitude` / `altitude_at_surface_p` /
  `WATER_TYPES`, and `report.water_name`.
- **An optional separate deco SAC** ([DECISIONS.md #16](DECISIONS.md)):
  `GasPlan.sac_deco` + `sac_for`, `--sac-deco` on the CLI, `sac_deco` in the
  config (`null` = one rate, unchanged behaviour), a "Deco SAC" box in the GUI
  (0 = same as SAC). Applies to gas breathed off a designated deco mix, and to
  that gas's emergency reserve; **rock bottom is unaffected** — it is back gas.
- Two real MultiDeco 4.24 exports in [`examples/`](examples/) as cross-check
  evidence, plus 44 tests over them: 8 golden schedules (each dive and its
  three lost-gas columns) in `tests/shearwater_golden.json`, and
  `tests/test_multideco_scenarios.py` for the printed ppO₂/ead/CNS/OTU, the
  gas volumes, and two deliberate divergences (gas-density reference state,
  and MultiDeco's stop-time printing).
- `report.wetnotes_rows` — the printable runtime card's rows, moved out of the
  GUI into the shared layer so they are testable without a display.
- **Every algorithm input is now settable from the config, the CLI and the
  GUI** ([DECISIONS.md #19](DECISIONS.md)), with
  `tests/test_input_coverage.py` enumerating `DivePlan`/`GasPlan` by reflection
  and failing if one is not *binding* — set through a front end and arriving in
  the plan the planner is handed. New: `DivePlan.p_h2o` (the alveolar
  water-vapour pressure was a module global the tests monkeypatched;
  `--p-h2o`, `p_h2o_bar`), `ppo2_switch_tol` (previously reachable from
  nothing; `--ppo2-switch-tol`), and GUI controls for the ascent/descent rates,
  stop interval, free last-stop depth and the whole ppO₂ window — all of which
  the GUI had been reading from `dive_plan.json` and writing back untouched,
  invisible and unchangeable in the app.
- **A constant/variable divergence harness**, `tests/planner_diff.py`. The
  fresh-water environment was found by a manual parameter scan; this makes that
  mechanical. It keeps a registry of every model constant and planner setting —
  with an introspection guard that fails the suite if one is missing, so
  "every possible difference" is checkable rather than hoped for — and grades
  each against a reference export as `DIVERGES` / `UNDETERMINED` / `SETTING` /
  `JOINT_OK` / `MATCH`. `UNDETERMINED` is the point: a constant the evidence
  cannot speak to must not read as agreement. Evidence is kept per dive (the
  two exports are different dives — EAN36 at GF 40/85 vs EAN28 at GF 5/50 — so
  pooling their printed values would credit one's conclusion to the other's
  data), and schedule error is judged relative to each dive's own TTS as well
  as in absolute minutes, since 8 minutes of deco and 26 are not comparable on
  a single tolerance. `python -m tests.planner_diff` prints a report; adding a
  planner means writing one `Evidence`.
- `buhlmann.OTU_THRESHOLD_PPO2` and `OTU_EXPONENT` — the Repex dose constants
  were inline literals, and a constant that exists only as a literal cannot be
  enumerated or compared.
- `pyproject.toml`: project metadata, `deco` / `deco-gui` entry points,
  `[gui]` and `[dev]` extras, ruff and mypy configuration, `py.typed`.
- GitHub Actions CI: the stdlib-only suite across Python 3.10–3.14 on Linux,
  macOS and Windows; a job that compiles both oracles and **fails if the
  cross-checks skip**; ruff + mypy; a GUI smoke test under Xvfb; a wheel build
  with a package-contents check.
- [`DECISIONS.md`](DECISIONS.md) — the numbered decision log the code cites.
- [`CONTRIBUTING.md`](CONTRIBUTING.md), this changelog, and a `.pre-commit-config.yaml`.

### Removed

- `GasPlan.tank_liters`, which was declared and validated but never read —
  superseded by the per-cylinder tanks on the gas stack. A field that looks
  like an input and is not is worse than no field.

### Fixed

- **One printed-schedule notation, defined once** in `buhlmann.StopLeg` /
  `stop_legs` and rendered by all three views — the runtime card, the GUI's
  stop table and the contingency cut-table cell
  ([DECISIONS.md #17](DECISIONS.md)). `run` is the runtime you **leave** a
  stop (truncated); the minutes are the **leg**, the ascent to the stop plus
  the hold, so the column adds up to the runtimes. Previously the card showed
  the leg while the stop table and cut table showed the bare hold, so one 3 m
  stop read `4` on the card and `3` in the results table. A gas-switch row is
  an annotation and the legs are not measured from it, which is what lets
  views that show switches and views that don't agree. `deco plan` prints the
  same notation as a line and `--json` carries it as `stops`.
- `report.gas_report` is now overloaded, so callers that pass a `GasPlan` get a
  non-optional `GasReport` back.
- The whole tree passes `ruff check` and `mypy` clean: PEP 585/604 annotations
  throughout, `itertools.pairwise` for successive-pair loops, explicit
  `strict=` on every `zip` over parallel sequences, exception chaining on
  re-raise.

## 2026-07-22

- Per-level start times, since removed again — see
  [DECISIONS.md #6](DECISIONS.md). Off-screen window restore fixed: a geometry
  saved on a detached monitor is pulled back onto a real screen.

## 2026-07-16

- Shared `report.py` layer between the model and both front ends; CLI and GUI
  gas accounting, warnings and totals unified ([DECISIONS.md #8](DECISIONS.md)).

## 2026-07-15

- Safety pass: ppO₂ violations, CNS/OTU clocks, END and gas density warnings;
  strict config loading; gas switches on the wetnotes card.

## 2026-07-14

- Contingency cut-table matrix for a bottom-timer backup; window geometry
  persistence; gas labels.

## 2026-07-13

- Multi-level dive planning, validated against Baker's GFDECO.
- Cross-checks against Subsurface's `deco.cpp`, Baker's `GFDECO` and golden
  MultiDeco/Shearwater schedules; `--last-stop 6`.
- Normal + emergency SAC gas figures; SAC multiplier replaces the old
  solo/`sac_stress` pair (migrated on load); oracles build from Python so they
  work on Windows.

## 2026-07-04

- Tkinter GUI rebranded to eko-deco: framed cards, dark mode, shared
  `dive_plan.json` with the CLI.

## 2026-07-03

- First release: ZHL-16C tissue model, Schreiner equation, Erik Baker gradient
  factors, NDL and deco scheduling, multi-gas switching, CLI.
