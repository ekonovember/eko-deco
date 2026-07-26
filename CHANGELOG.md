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

- `pyproject.toml`: project metadata, `deco` / `deco-gui` entry points,
  `[gui]` and `[dev]` extras, ruff and mypy configuration, `py.typed`.
- GitHub Actions CI: the stdlib-only suite across Python 3.10–3.14 on Linux,
  macOS and Windows; a job that compiles both oracles and **fails if the
  cross-checks skip**; ruff + mypy; a GUI smoke test under Xvfb; a wheel build
  with a package-contents check.
- [`DECISIONS.md`](DECISIONS.md) — the numbered decision log the code cites.
- [`CONTRIBUTING.md`](CONTRIBUTING.md), this changelog, and a `.pre-commit-config.yaml`.

### Fixed

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
