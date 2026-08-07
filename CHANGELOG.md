# Changelog

Notable changes, newest first. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project is
pre-1.0, so anything may still move.

## [Unreleased]

### Added — repetitive dives

- **A dive series.** `config["repeats"]` holds the dives after the first, each
  with the surface interval before it; `buhlmann.surface_interval` off-gasses at
  the surface and the next dive is planned from that loading. CLI:
  `--dive DEPTH:RUNTIME[:SI]` (repeatable) and `--dive-index N`; `--json` returns
  a `dives` array for a series and the unchanged flat shape for a single dive.
  GUI: a dive picker above the Levels list with `+ dive` / `- dive` and a
  surface-interval field, plus a DIVE SERIES summary card. Settings are shared
  across the day; only the profile repeats
  ([DECISIONS.md #26](DECISIONS.md)).

### Added — readouts

- **SurfGF**, the gradient factor actually surfaced at (`buhlmann.surface_gf`),
  beside the existing final-ceiling depth in both front ends and as `surf_gf` in
  `--json`. Baker's whole-minute padding usually surfaces the diver under their
  own GF-High, and that headroom is what a changed plan gets judged against.
- **Per-stop cylinder pressure** — the bar remaining as you leave each stop
  (`report.leg_pressures`), on the CLI stop line, the GUI runtime card and the
  printed wetnotes card, and as `stops[].end_bar` in `--json`. The one gas
  figure an SPG can be checked against underwater.
- **A gas-stack table**: MOD / END / EAD / density for every mix, each quoted at
  its own MOD rather than at the bottom depth. EAD is new to the output
  throughout (it was always computable, never printed).
- **A one-line backup schedule** (`report.backup_line`), for a slate, a log or a
  message; on every wetnotes card, so the existing Copy button carries it.
- **Losing the bottom gas** (`buhlmann.bailout_schedule`): the ascent re-flown on
  the remaining stack from the end of the bottom phase, as a scenario column in
  the GUI and a line on the CLI. It reports **not survivable** rather than
  inventing a schedule when nothing else is breathable at depth — which on most
  deep dives is the honest answer.

### Added — planning

- `--gas-switch at-mod|at-first-stop` (config `gas_switch_policy`, and a GUI
  control): hold every deco switch until the first stop, the team convention of
  arriving before switching. Default is unchanged at-MOD
  ([DECISIONS.md #25](DECISIONS.md)).

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

- `report.environment_note` — one line stating a dive's water type and surface
  pressure, and that a non-default environment means the schedule will no
  longer match a planner set to sea-level salt water. Shown by the CLI header
  and as a GUI card, because the two `examples/` exports print fresh-water
  pressures yet compute at sea-level salt, so choosing the physics costs ~2 min
  of agreement with MultiDeco on the same dive. The GUI's DIVE card also gained
  water/surface rows: the environment was the one input the readout stayed
  silent about.
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
- **`cards/`** — the print-ready 90 × 64 mm wetnotes runtime-card engine, now
  fed by the planner rather than by hand: `rows_from_scenarios` builds a card's
  rows straight from `deco plan --json` and `gas_line` derives the switch
  depths from the same plan, so a cell cannot end up holding a raw *hold*
  copied out of the segment table. `fit_size` auto-fits the type to the row
  count — the layout was drawn around three stops and a real trimix schedule
  has seven, which used to write the TTS row over the summary.
  `tests/test_cards_format.py` pins that a card cell equals
  `buhlmann.stop_legs` and that the card, the GUI's runtime card and the
  contingency cut table all print the same numbers.
  **No PDFs are committed**: generated cards are gitignored, and the vendor
  MultiDeco-X1 manual is cited by URL + SHA-256 in `cards/reference/README.md`
  instead of being redistributed.
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

### Added — two more cross-check oracles

- **`decotengu` and `decodaitengu`** join Subsurface and Baker's GFDECO as
  cross-check oracles ([DECISIONS.md #22](DECISIONS.md)) — pip test
  dependencies in the `[dev]` extra, never vendored, never imported by
  `src/deco`. Four independent implementations make "who is wrong" answerable,
  and it paid immediately: our ceiling agrees with decodaitengu to **0.03 mbar**
  where the MultiDeco gap is 5.4 — so that difference is MultiDeco's, not ours;
  the 4.0 vs 5.0 min first compartment splits two-two (we side with Subsurface
  and GFDECO); and **decodaitengu's slow-compartment helium `a` values diverge
  progressively from Bühlmann's published table, reaching −0.162 at #16**, so
  it is used as a nitrogen oracle only. All three findings are pinned.

### Fixed — an audit of the decision log, where it documented instead of fixing

- **Minimum gas was up to 48 % low on a deep-first multi-level dive.** The
  emergency reserve was taken from the *last* level, with a "Known limitation"
  paragraph in [DECISIONS.md #7](DECISIONS.md) saying it "can understate the
  true worst case". On 45 m/25 min → 18 m/45 min it reported **14 bar** where
  the deep level needs **27**. `emergency_gas_liters` now evaluates every level
  end — re-planning the dive as if it had ended there — and returns the worst.
  Square dives are unchanged. It takes the `DivePlan` now, like `gas_report`.
- **The printed runtime card carried no warnings.** The GUI's wetnotes card and
  `cards/make_cards.py` rendered a schedule with nothing on it, on the one
  artifact that goes in the water and the one with no disclaimer
  ([#4, #5](DECISIONS.md)). Both print them now, per lost-gas scenario, and the
  card spec's `warnings` key is **required** — `draw_card` raises rather than
  print a caveat-free schedule.
- **Config typos silently changed the dive.** `{"depth": 40}` became the
  default 30 m; an unrecognised gas role was coerced to `Deco`, so a mistyped
  `Bottom` changed both the bottom gas and the deco stack; `o2: 0.32` became a
  0.32 % hypoxic mix. Unknown keys, unknown roles, missing level fields and
  out-of-range mixes are refused ([#9](DECISIONS.md)). *The coercion had a test
  asserting it was intended — that test now asserts the refusal.*
- `deco.app._write_readout` (252 lines, 9 parameters) is a list of small card
  builders that each take a `PlanResult` and return lines; the method decides
  card order and holds no arithmetic. Warning cards moved above the stops table.
- [DECISIONS.md #17](DECISIONS.md)'s rationale had been false since #21 — it
  argued from "whole-minute holds with fractional ascents on top", which #21
  inverted. The conclusion was right for an expired reason.

### Fixed — the GUI was deriving numbers instead of rendering them

- **The GUI ignored the deco SAC entirely.** `report.gas_report` was called
  without the plan's deco stack, so `GasPlan.sac_deco` matched no cylinder: a
  deco rate the user typed, saved and could see on screen changed no figure
  anywhere. On 40 m/25 min air + EAN50 at SAC 20/12 the GUI showed EAN50
  **714 L** where the CLI showed **428 L** from the same config
  ([DECISIONS.md #24](DECISIONS.md)).
- **The GUI's GAS and DIVE cards computed at sea-level salt** regardless of the
  dive's water and altitude — density, CNS/OTU, END, ppO₂, MOD, the hypoxic
  depth and the final ceiling. At 1500 m in fresh water the card printed
  density **6.37 g/L**, above the 6.2 g/L ceiling, while the ⚠ density warning
  (environment-aware, seeing the true 5.99) stayed silent.
- `recompute` now builds **one `PlanResult`** — the same object `deco plan`
  renders — and the readout and wetnotes card render its fields. The lost-gas
  card's back-gas litres are billed through `GasPlan.sac_for` and the dive's
  environment like every other litre, instead of by hand at the raw SAC.
- **`gas_report` now takes the whole `DivePlan`** rather than optional
  `surface_p` / `msw_per_bar` / `deco_gases` scalars: omitting the environment
  is a `TypeError` instead of a wrong number. *(API change: pass the plan.)*
- Gas switches on the wetnotes card and the profile chart are detected by
  comparing frozen `Gas` values, not their rounded labels ([DECISIONS.md
  #8](DECISIONS.md)) — two mixes that both print `Air` now get their switch
  row. GUI stop tables key on the stop's own depth rather than `round(depth)`,
  which would have merged 6.0 m and 6.5 m at a 0.5 m stop interval.

### Fixed — a config with no gas is refused, not defaulted

- **A config with no usable gas is refused instead of becoming a dive on Air.**
  `{"gases": []}` used to fall back to the default stack — planning on Air with
  an EAN50 deco stage that appeared in no file the user had seen — and
  unticking every gas did the same. `dive_config.to_buhlmann` raises; the CLI
  exits 2. An absent `gases` key still gets defaults.

### Fixed — docs and comments naming things that do not exist

- `--p-h2o`'s help text said "Default 0.0567 (Buhlmann)" *and* that the
  planners use 0.0567 (Schreiner) — one number, two attributions. It and
  `DivePlan.p_h2o`'s comment now state the post-[#20](DECISIONS.md) default
  correctly, and note that the default is bound at import time.
- Docs named functions that do not exist: `cards.table_from_plans` (it is
  `rows_from_scenarios`) and `Gas.trimix` (it is `Gas(0.21, 0.35)`).

### Documented — the limits of the cross-checks

- **[DECISIONS.md #23](DECISIONS.md) states what the four oracles establish and
  what they do not.** They support "on this observable, eko-deco is not the
  outlier"; they do not support "eko-deco is correct" — the GFDECO agreement is
  measured with our N₂ `a` table patched to ZH-L16B and surface 1.000 bar, and
  the decodaitengu ceiling with compartment 1 aligned to its 4.0 min variant, so
  both need their qualifiers carried. There is no four-way match on everything:
  compartment 1 splits two–two, decodaitengu's slow helium three–one, and
  Subsurface's anchor and scheduler differ by design. The two open MultiDeco
  rows are recorded as *unattributed* — the 12 m one is not a compartment, and
  the compartment-3 hypothesis it retired is named so nobody re-opens it.
- `tests/test_multideco_scenarios.TestExportedRuntimeDeltas` pins **all 36 stop
  runtimes** of both exports across all four lost-gas columns: 25 identical, 11
  recorded deltas. The golden fixture's 2 min per-stop tolerance lets a
  one-minute drift pass silently; this asserts the delta itself, so agreement
  can only change deliberately.

### Changed — the planner's stop discretisation

- **eko-deco now uses Erik Baker's own stop rule** ([DECISIONS.md
  #21](DECISIONS.md)): hold to the second rather than in whole-minute lumps,
  then pad so the **runtime** lands on a whole minute — which means stopping at
  the rounded GF-low ceiling even where the ascent has already cleared it (a
  *pass-through* stop). Verified against his Fortran: GFDECO holds 0.4 / 0.7 /
  2.7 min at 9/6/3 m to land its runtime on 43 / 44 / 47.
  **TTS now matches GFDECO exactly (0.00 min) on all seven cross-check cases**
  — `TTS_TOL` tightened from 2.0 to 0.05 — and against the two real MultiDeco
  exports exact stop runtimes went from 11/24 to 16/24, total error 18 min to
  9. Every printed leg is now a whole number of minutes, as MultiDeco prints
  them. The cost is a documented, deliberate widening of the *schedule-level*
  Subsurface bands (its planner skips those stops); the shared physics there
  stays pinned to machine precision.
- Reading `gfdeco.f` directly settled three further details. The pad is applied
  **before** the whole-minute increments, not after the obligation is resolved —
  the two differ when the obligation lands exactly on the pad, and Baker's order
  removes the sub-minute search entirely. The first stop depth uses
  `ANINT(ceiling/step + 0.5)`, the *strictly* next step, so a ceiling of exactly
  6 m rounds to 9. And **`min_stop_time` is now a setting**
  (`buhlmann.DivePlan.min_stop_time`, `--min-stop-time`, `min_stop_time` in the
  config, a GUI box): Baker parameterises it, noting that a small value yields
  "a near continuous decompression schedule" — measured on scenario 2, TTS goes
  26.33 → 25.83 → 25.33 min at 1.0 / 0.5 / 0.1.

### Changed — model default

- **`P_H2O` now defaults to Schreiner's 0.0567**, not Bühlmann's 0.0627
  ([DECISIONS.md #20](DECISIONS.md)). MultiDeco, Shearwater and Baker's GFDECO
  all use 0.0567; only Subsurface uses 0.0627. Reproducing a plan a diver is
  actually holding no longer needs a flag nobody would think to pass. Lower
  vapour pressure means more inspired inert gas, so this **lengthens**
  schedules — it is the conservative direction. `buhlmann.P_H2O_BUHLMANN` and
  `P_H2O_SCHREINER` name both values, and the Subsurface cross-check passes
  0.0627 explicitly since its oracle hardcodes it.
- **`--planner multideco|shearwater|gfdeco|subsurface|buhlmann`** selects a
  named constant set (`buhlmann.PLANNER_PROFILES`) so a schedule can be planned
  in another tool's convention deliberately, instead of by hunting individual
  flags. Individual flags still override.

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
