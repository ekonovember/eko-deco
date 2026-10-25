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
| `src/deco/buhlmann.py` | **The model and the planner** — 16 compartments, the Schreiner equation, GF ceilings, multi-level scheduling, gas management, and the printed-schedule notation every view shares. Too much to summarise in a cell: see **[The model module](#the-model-module-srcdecobuhlmannpy)** below. **Keep dependency-free.** | stdlib only |
| `src/deco/toxicity.py` | Oxygen-toxicity clocks: `cns_otu` (NOAA single-exposure CNS % via `_CNS_RATE`, + Repex OTU from `OTU_THRESHOLD_PPO2`/`OTU_EXPONENT`), the **reporting thresholds** `CNS_WARN_PCT` 80 / `CNS_LIMIT_PCT` 100 / `OTU_DAILY_LIMIT` 300 (tiers, not model constants — they enter no schedule and no export can pin them) and `cns_after_interval` (`CNS_HALFTIME_MIN` 90 min, the surface decay that lets a day's CNS be a sum — DECISIONS #33). Split out of `buhlmann` (DECISIONS #32) because it is a *downstream analysis of a planned dive*, not part of the model: it reads a segment list and integrates two published dose curves, touching no tissue compartment, and nothing in the planner calls it. | stdlib only |
| `src/deco/contingency.py` | The bottom-timer **cut table**: `contingency_schedules` (square @ max depth on the fixed `CONTINGENCY_TIME_STEP` × `CONTINGENCY_DEPTH_STEP` 3 min × 3 m grid, rows = bottom-time variants × columns = depth variants, step counts before/after per axis; the grid stays rectangular so renderers can align columns — an unplannable cell keeps its place with `segments=None`) and `ContingencyCell.text()`, the shared wetnotes cell format `depth:min … · TTS′`. Split out of `buhlmann` (DECISIONS #32): it sits *above* the planner, calling `plan_dive` once per cell. | stdlib only |
| `src/deco/cli.py` | CLI front end: `plan`, `ndl`, `tissues` (+ `--json`); `plan --load/--save` a config; `mix@tank@bar` gas suffix (a 4th `@` field is rejected); per-cylinder gas; `plan --contingency [TB[:TA[:DB[:DA]]]]` (step counts) prints the cut-table matrix (and a `contingency` key in `--json`). `--dive DEPTH:RUNTIME[:SI]` (repeatable) plans a repetitive series and `--dive-index N` prints one of it; `--gas-switch at-mod|at-first-stop`. The schedule table has a cumulative `run` column and an EAD column; every plan prints ppO₂/density/ceiling/surfacing/CNS-OTU warnings and `·` **notices** (what the planner chose on the diver's behalf, e.g. a deco gas used as travel gas), CNS/OTU, END + density of the bottom gas, SurfGF, the gas-stack table, the one-line backup schedule and whether losing the bottom gas is survivable (also `warnings`/`cns_pct`/`otu`/`end_m`/`gas_density_g_l`/`surf_gf`/`gas_stack`/`backup_line`/`bailout_bottom_gas` and a `stops` list in the card notation, each with `ead_m` and `end_bar`, in `--json` — a series returns a `dives` array plus `day_totals` (accumulated CNS/OTU) and prints a **Day total** block, a single dive the unchanged flat shape; no disclaimer key). `cmd_plan` computes a `report.PlanResult` once, then `_plan_json`/`_plan_text` render it (no re-derivation). `--level DEPTH:RUNTIME` (cumulative runtime at the END of the level, transit included). `--water salt|fresh` / `--msw-per-bar` / `--altitude M` / `--surface-p BAR` / `--p-h2o` / `--ppo2-switch-tol` / `--planner NAME` set the environment and model (explicit values win over the preset/altitude; a non-default environment gets its own header line), `--sac-deco` the deco-cylinder SAC. **Gas is always reported**: `--sac` defaults to `report.DEFAULT_SAC` and the output flags it as assumed (`sac_assumed` in `--json`); `--no-emergency` drops the reserve from the text *and* omits its JSON keys, `--sac-emergency` is the absolute stressed rate, `--no-turn-pressure` / `--turn-rule rock-bottom|thirds` control the turn pressure alone (DECISIONS #28). `--save` writes levels as pure depth/time periods (gas is automatic by role — no per-level references or inline mixes). CLI GF default is 30/**70** (matches the config/GUI; the library `DivePlan` default stays 30/80). Loading a config is **strict** — missing/corrupt file = error exit 2, never a silent default plan — and other CLI flags are ignored with a stderr note. Same-mix cylinders aggregate (volumes add, volume-weighted fill). | buhlmann, dive_config, report |
| `src/deco/report.py` | Shared stdlib-only layer between `buhlmann` and both front ends: everything user-facing that is *computed* lives here once so the CLI and GUI cannot drift. `DEFAULT_FILL_BAR`, `water_name` (msw/bar → salt/fresh/custom label), `wetnotes_rows` (the printed runtime-card rows, built on `buhlmann.stop_legs`), `runtime_min` (re-exported from `buhlmann`; a runtime truncated to whole minutes — MultiDeco's convention, verified against a real export; every rendered runtime goes through it), `warning_lines` (+ its parts `surfacing_warnings`, `oxygen_clock_warnings`, `plan_notices` — see DECISIONS #33: the surfacing check is **post-hoc on the finished tissues**, because the planner decides "no stops" from the ceiling at the end of the bottom and the slow compartments keep loading through the ascent behind it), `SeriesTotals`/`series_totals` (a day's accumulated CNS/OTU — OTU is a *daily* dose by definition, CNS carries decaying across the intervals), `backup_line` (the whole schedule on one line, for a slate or a message), `GasStackRow`/`gas_stack_table` (MOD/END/EAD/density per mix, each quoted at its OWN MOD — the deepest it would ever be breathed), `leg_pressures` (cylinder bar leaving each stop, index-aligned to `stop_legs`; the one gas figure an SPG can check), `Bank`/`aggregate_banks` (same-mix cylinders → one bank), `DEFAULT_SAC` (20 L/min — the baseline every gas estimate falls back to, kept equal to the config schema's `sac_normal`), `CylinderNeed`/`GasReport`/`gas_report` (per-mix need/have/emergency/SHORT + rock bottom — it takes the whole `DivePlan`, never loose environment scalars, so a caller cannot omit the water/altitude or the deco stack and get a plausible wrong number: DECISIONS #24; with `GasPlan.emergency` False, `liters_emergency` and `rock_bottom_l` are **None, never 0.0** — absent, not "none needed" — and `GasReport.emergency` is the one flag a renderer asks, DECISIONS #28; `turn_pressure_bar` follows `GasPlan.turn_rule` and is None when not wanted, `turn_reserve_bar` = `2 × turn − fill` is what surfaces, and `turn_below_rock_bottom` flags a thirds turn that leaves less than minimum gas — every view prints that flag, card included), `PlanResult`/`compute_plan_result` (+ `surf_gf`, `gas_stack`, `backup`, `leg_bars`, `bailout`, and `start_tissues` — the loading the dive began with, which every contingency derived from it must start from too: DECISIONS #35), `lost_gas_scenarios` (the lost-deco-gas columns + the bailout, planned here rather than in the GUI) and `compute_series_result` (one `PlanResult` per dive of a day, tissues carried through the surface intervals — a series is a list of ordinary results, not a new kind of thing). **Gases are keyed by the frozen `Gas` value, never its rounded `repr`** — two mixes that render the same label keep separate accounting. **Keep dependency-free.** | buhlmann |
| `src/deco/dive_config.py` | Shared JSON dive config (`load`/`save`/`normalize`/`to_buhlmann`) read by the GUI and written by `plan --save`. `load(strict=True)` raises on a missing/corrupt file (CLI); the lenient default falls back to `default_config()` (GUI first launch) — normalization happens *inside* that strict/lenient boundary so a semantically corrupt file can't slip through as a silent default. `save()` is atomic (temp file + `os.replace`). Where the file lives is `default_path()`: `$DECO_CONFIG`, else `./dive_plan.json` if the cwd has one, else the per-user config dir (`user_config_path()`) — there is no module-level `DEFAULT_PATH` any more (DECISIONS #11). Public `normalize(cfg)` (front ends use it instead of `_merged`). Levels are pure depth/time periods (`depth_m` + cumulative `runtime_min`) and gas is chosen automatically by role. Legacy per-level gas references (`gas_id` or inline mixes), legacy `"Level"`-role gases and legacy `start_min` arrival times are dropped on load. **Unknown keys, unknown gas roles, missing level fields and out-of-range mixes are refused, not defaulted** — `{"depth": 40}` used to normalize to 30 m and a role of `Bottum` to `Deco` (DECISIONS #9, #24). **A config with no usable gas is refused, not defaulted**: an explicit `"gases": []` stays empty and `to_buhlmann` raises (CLI exit 2) rather than planning on Air with a deco stage the file never named — an absent `gases` key still gets defaults (DECISIONS #24). `repeats` holds the dives after the first (`surface_interval_min` + `levels`, both required — a guessed interval would invent residual nitrogen); `series_of` returns the whole day as `(interval, levels)` per dive and `levels` stays dive 1, so every config predating repetitive dives means the same dive (DECISIONS #26). Adds `surface_p_bar`/`msw_per_bar` (environment), `gas_switch_policy` and `sac_deco` (`null` = one rate); a config predating them still loads as sea-level salt water with a single SAC. `emergency` (bool) + `sac_emergency` (absolute L/min) replace `sac_multiplier`, which — like the older `sac_stress` — migrates to a rate on load and is dropped; a config naming neither keeps the old behaviour (twice `sac_normal`). `turn_pressure` (bool) + `turn_rule` (`rock-bottom`/`thirds`) size the turn pressure. DECISIONS #28. | buhlmann |
| `dive_plan.json` | The full dive: `levels` (depth + cumulative runtime — pure depth/time periods; gas is chosen automatically by role, so levels carry no mix of their own), GF, gas stack (per-gas tank + fill pressure + `enabled` toggle + role Bottom/Travel/Deco; a disabled gas is never planned; legacy per-level gas references and `"Level"`-role gases are dropped on load), SAC + optional deco SAC + emergency SAC multiplier, problem time + `divers` (emergency team size), water type + surface pressure (`msw_per_bar`/`surface_p_bar`), ascent/descent/stop rates + ppO2 window, `contingency` cut-table step counts on the fixed 3 min × 3 m grid (`time_before`/`time_after`/`depth_before`/`depth_after`, 0 disables a direction; legacy `time_delta_min`/`depth_delta_m` migrate on load). Agent-editable. | — |
| `src/deco/app.py` | Tkinter + matplotlib GUI. **`recompute` builds ONE `report.PlanResult` per dive via `compute_series_result` — the same objects `deco plan` renders — and `_write_readout`/`_write_runtime` render its fields; the GUI formats, it never derives** (DECISIONS #24: deriving inline is how it came to print sea-level density on an altitude dive and to ignore the deco SAC entirely). Layout: left settings (GF row + 'Last stop 6 m' switch on top, then the **environment** row — water dropdown (salt/fresh/custom) writing m/bar, plus altitude writing surface pressure (both one-way: the numeric fields are the stored truth and stay hand-editable, so a constant from another planner survives a round trip), then the **dive series** row (a dive picker + `+ dive` / `- dive` and a surface-interval field shown on dives 2+ only — settings are shared across the day, only the profile repeats, DECISIONS #26) and an editable **Levels** list (depth / cumulative **runtime**, + Add level — two fields only, read/written via `_row_levels`/`_level_row_dict`; levels are contiguous so the transit is part of the runtime) and the editable gas list w/ tank+bar, then SAC + an optional deco SAC (0 = same rate), then a separate **Emergency gas** frame whose LabelFrame *is* the on/off checkbox — emergency SAC (L/min, 0 = twice the SAC) / problem minutes / a '2 divers' checkbox / a 'Turn pressure' checkbox + rule dropdown (rock-bottom or thirds, with a hover box explaining both), its inputs greyed out (ttk `disabled` state) when the box is unticked and every emergency figure gone from the Results tab and the wetnotes card when it is off (DECISIONS #28), then a collapsed **Algorithm & rates** panel (descent/ascent rate, stop interval, free last-stop depth, the whole ppO₂ window incl. the switch tolerance, the gas-switch policy, and P_H₂O — every remaining plan input, none of it config-passthrough any more; the rate fields carry `RATE_REFERENCE` as a `_Tooltip` hover box plus an inline one-liner, listing what each cross-checked planner uses and where the number was read off — 18/10 ours, 10/10 Shearwater, 8/9 MultiDeco) (stored as `divers` 1/2), then four **Contingency (cut table)** sliders — bottom-time steps −/+ and depth steps −/+ on the fixed 3 min × 3 m grid, persisted in the config's `contingency` block, 0 disables a direction); the rest is a two-tab notebook — **Results** (stops + lost-deco-gas scenario table, per-scenario gas usage as **have / need (emergency)** — tank×bar carried vs litres required at the normal SAC, with the rock-bottom emergency reserve (`buhlmann.emergency_gas_liters`: problem minutes @ max depth + the real ascent/deco to the next switch at `GasPlan.sac_emergency`, an absolute L/min rate) **added on top of the normal need** in parentheses (the `(emrg)` figure = need + reserve); `SHORT!` flags a shortfall at the normal SAC and a second `SHORT!` inside the emergency parens when even need-plus-reserve is exceeded — plus bar left at both the normal and emergency need, and the gas plan whose columns are **need / have / (emrg)**) + a printable **Runtime** wetnotes card — one framed card per lost-gas scenario — including a **lost bottom gas** column when that is survivable at all — rows from `report.wetnotes_rows` so the STOP column always adds up to the RUN column (DECISIONS #17), plus a `bar` column (`report.leg_pressures`) and the one-line backup schedule in the footer, then the bottom-timer **CUT TABLE** matrix card from `contingency.contingency_schedules` (bottom-time rows × depth columns, each cell `ContingencyCell.text()` — stops + TTS rounded UP, `no deco`/`n/a`; `*` marks the planned row/column) — with PNG export, and **Profile** (the depth/time chart with the deco ceiling overlaid via `buhlmann.ceiling_profile`). Dark mode in the **Settings** menu. **Continuous inputs are debounced**: entry traces and the cut-table sliders call `_schedule_recompute()` (150 ms, cancels any pending job), discrete actions — add/remove level or gas row, switch dive, dark mode, the initial build — call `recompute()` directly, and `recompute()` stays synchronous because the tests run without a mainloop (DECISIONS #30). Loads/saves `dive_plan.json`; dark mode + window geometry (saved on close, restored on start; 1x1 unmapped geometries never persisted) live in `ui_settings.json` next to the per-user config dir (never mix UI prefs into the dive config — DECISIONS #10). `--install-launcher` (`deco-gui --install-launcher`) registers a per-user Linux `.desktop` + icon whose `Exec` is `<python> -m deco.app` (so it survives moving the checkout), so GNOME docks show the `<//>` tile (window icon alone is ignored there; keep iconphoto images ≤128 px — Tk 8.6 silently writes an empty `_NET_WM_ICON` above that). Built as small per-card methods (`_card_header`/`_cards_warnings`/`_card_series`/`_cards_stops`/`_card_gas`/`_card_gas_stack`/`_card_dive`/`_card_environment`/`_card_gas_plan`), each taking the `PlanResult` and returning lines — `_write_readout` chooses the order and holds no arithmetic. Safety surfacing: ppO₂/ceiling/density warnings as ⚠ cards **at the top of Results and on every wetnotes card** (DECISIONS #4), CNS/OTU + END/density + the config-driven rates/ppO₂ limits in the DIVE/GAS cards, silent-fallback notices (no Bottom gas, invalid mix row), gas-switch rows (`gas` in the stop column) on the wetnotes card, same-mix cylinders aggregated via `_cylinders_by_mix`, and a strict config load on startup (a corrupt file shows "⚠ config unreadable — defaults", never a silent default plan). | matplotlib, tkinter, dive_config |
| `tests/` | `unittest` suites: `test_buhlmann.py`, `test_toxicity.py`, `test_contingency.py`, `test_cli.py`, `test_report.py`, `test_dive_config.py`, `test_app_levels.py`, `test_cards_format.py` (the printed card carries the planner's own numbers; skips without matplotlib), `test_input_coverage.py` (every plan input binds in config+CLI+GUI), `test_multideco_scenarios.py`, `test_planner_diff.py`, `test_subsurface_crosscheck.py`, `test_baker_crosscheck.py`, `test_shearwater_golden.py`. `tests/__init__.py` puts `src/` on `sys.path`, which is why discovery needs `-t .` (DECISIONS #13). | stdlib |
| `tests/planner_diff.py` | **Constant/variable divergence harness.** `registry()` is every model constant and planner setting we have, each tagged with the observables that could pin it; `registry_gaps()` introspects every module in `CONSTANT_MODULES` (`buhlmann`, `toxicity`, `contingency`) and a test **fails if anything is unregistered**, so a new constant cannot be added invisibly. `Evidence` holds what a reference export prints (ppO₂, ead, density, schedule deltas, CNS/OTU, gas litres, stated settings); `infer_environment` inverts printed pressures to a feasible (surface_p, msw_per_bar) box by grid search; `compare()` returns one verdict per tunable — `DIVERGES` / `UNDETERMINED` (nothing in the evidence touches it — never confuse with agreement) / `SETTING` (the export states it; just pass it) / `JOINT_OK` (only identifiable as a group, and the group agrees) / `MATCH`. Run `python -m tests.planner_diff` for a report on the bundled exports. Add a new planner by writing one `Evidence`. | stdlib |
| `tests/python_oracles.py`, `tests/test_python_oracles.py` | **Third-party Python oracles** — `decotengu` + `decodaitengu`, `pip install -e ".[dev]"`, GPL-3, **test-only and never vendored** (nothing in `src/deco` imports them). Four implementations make "who is wrong" answerable: our ceiling matches decodaitengu to 0.03 mbar (vs a 5.4 mbar MultiDeco gap), the 4.0/5.0 min first compartment splits two-two, and decodaitengu's slow-compartment helium `a` is a different model so it is a **nitrogen** oracle only (DECISIONS #22; what those numbers do and do not establish — and the qualifiers to quote them with — is #23). Skips when absent, like g++/gfortran. | decotengu, decodaitengu |
| `tests/subsurface_oracle/` | **GPL-2.0, test-only.** Unmodified Subsurface `core/deco.cpp` (pinned commit in `upstream/UPSTREAM.txt`) + stub headers; `build.sh` compiles `libsubsurface_deco.so`. Never import at runtime, never copy code out of it (license boundary — see its README). | g++ |
| `tests/subsurface_deco.py` | ctypes wrapper around the oracle `.so` (auto-builds it); `SubsurfaceDeco.plan()` is a small planner-style schedule loop of ours, the model calls are native Subsurface code. | stdlib + oracle |
| `tests/baker_oracle/` | Erik Baker's original `gfdeco.f` ("distribute freely — credit the author"), the reference for the Shearwater/MultiDeco GF convention. ZH-L16B + WV 0.0567 bar + surface 1.000 bar — the test patches eko-deco to match. `build.sh` compiles the `gfdeco` binary. | gfortran |
| `tests/baker_deco.py` | Runner for the GFDECO binary: writes `GFDECO.IN`/`.SET` in a temp dir, parses the schedule from `GFDECO.OUT`. | stdlib + oracle |
| `tests/shearwater_golden.json` | Golden schedules from real planners: 4 MultiDeco schedules (transcribed from `multideco_screenshots/`, incl. the lost-gas scenario columns; settings inferred — see `_multideco_provenance` in the file) + 8 from the two real exports in `examples/scenario_1|2/` (settings printed, not inferred: each dive plus its three lost-gas columns — `_scenario_provenance`) + **2 real Shearwater Predator on-unit plans** (settings read off the unit, transcribed in `examples/shearwater/*/dive_parameters.md`; wide stop tolerances with the reason recorded per entry, not tuned) + Shearwater Cloud templates to fill. Unfilled entries show up as skipped tests. | — |
| `examples/*.json` | Ready-to-run command snippets. | — |
| `examples/scenario_1/`, `examples/scenario_2/` | **Real MultiDeco 4.24 exports** (Polish UI, `data.txt`) kept verbatim as evidence: a 32 m/40 min fresh-water dive at 150 m on EAN36 GF 40/85 and on EAN28 GF 5/50, each with its plan, gas volumes and lost-gas table. Transcribed into `tests/shearwater_golden.json` (8 schedules) and `tests/test_multideco_scenarios.py` (everything else the exports print). **Don't reformat or 'fix' them** — they are the source. | — |
| `examples/shearwater/`, `examples/hermanice_dive/` | **Real Shearwater on-unit plans, transcribed.** Two Predator plans (32 m/40 min, GF 40/85 and GF 5/50) and a Perdix plan (33 m/40 min EAN32, fresh water at 267 m) plus the MultiDeco export of the same site and the hand-written wetnotes card that fixes the printed format. **Neither the photographs nor a redundant folder are kept** — every screen is transcribed verbatim, the originals live outside the tree in `~/eko-deco-evidence/`, and once a test pins a capture the transcription moves into the fixture that asserts it (`tests/shearwater_golden.json`: schedules as entries, settings + printed totals in `_predator_provenance`) and the folder is deleted. A folder still here is one no test covers yet — currently only the Perdix, which needs water/altitude fields the fixture does not have. Markdown is the evidence of record: it diffs and greps, and transcribing screen by screen is what makes somebody read the screen (it is how the Perdix's at-MOD gas switch was found). `examples/shearwater/to_plan_1…6/` is the **capture queue** — one setting changed per sheet, each carrying eko-deco's prediction *written down before the plan is made*, because a prediction in advance is a test and a comparison afterwards is a fit. Don't reformat or "fix" a transcription: a number that disagrees with ours is the finding. See DECISIONS #27. | — |
| `src/deco/assets/` | Packaged window/taskbar icons (`icon.png`, `icon.ico`) — package data, ship in the wheel. | — |
| `src/deco/cards.py` | **Layout engine** for print-ready 90 × 64 mm wetnotes **runtime cards**: renders a card spec to an exact-size PDF (+ PNG) and imposes several 4× on A4 with crop marks — it computes nothing, you feed it numbers from `deco.cli`. **Inside the package** (DECISIONS #31): the printed card is a product surface, so it ships in the wheel under `[gui]` rather than sitting beside the repo where `pip install` could not reach it. `rows_from_scenarios`/`gas_line`/`bars_from_plan` build a card straight from `deco plan --json` (the optional grey `bar` column is the planned column's end-of-stop pressure — one column, not one per scenario, or the runtimes lose the width that makes them readable), so a cell cannot drift from the schedule; the spec's **`warnings` key is required** — `draw_card` raises rather than print a schedule with no caveat on it (DECISIONS #4); `fit_size` auto-fits the type so a 7-stop trimix schedule still fits the card. `EXAMPLE` at the bottom is the spec shape (placeholder numbers, not a dive plan); `python -m deco.cards` renders it into the **current directory**. Follow this format for any new printed/exported schedule. | matplotlib |
| `cards/` | The card **workspace**, not the engine — the engine moved to `src/deco/cards.py`. `make_scenario.py` is a driver: it plans the two `examples/scenario_*` dives through `deco plan --json` and feeds the result to `deco.cards`. **Never commit a dive-specific card here** — cards are remade per dive and the PDFs/PNGs are gitignored. [`cards/README.md`](cards/README.md) is the **reference for the printed runtime format** (columns `DEPTH · GAS · STOP · RUN`, ascent order, RUN = when you leave the stop, TTS last, contingencies as parallel columns) with the sources it was verified against — chiefly the two real exports in `examples/` — plus the **hand-written** convention read off a diver's own card (direction glyph per row, depth, leg minutes, the runtime in brackets, a margin triangle at each gas switch). **No PDFs are committed**: generated cards and third-party manuals are both gitignored, and `cards/reference/README.md` cites the vendor MultiDeco-X1 manual by URL + SHA-256 instead of redistributing it (© HHS Software; never copy text out of it). | matplotlib (dev) |
| `pictures/` | Branding + README screenshots: `logo.png`, `app_ui.png`/`app_profile.png`, `social_preview.png` (upload manually under GitHub Settings → Social preview — no API for it), `gen_assets.py` regenerates the icons (into `src/deco/assets/`) and the social card (dev-only: matplotlib + Pillow). | — |
| `pyproject.toml` | Packaging (`eko-deco`, entry points `deco` / `deco-gui`, extras `[gui]`/`[dev]`) **and** the ruff + mypy configuration. | — |
| `DECISIONS.md` | Numbered, stable decision log. Code cites it (`see DECISIONS.md #7`). Read it before "fixing" something intentional; add an entry when you make a choice a future reader would question. | — |
| `CONTRIBUTING.md`, `CHANGELOG.md` | Setup + house rules; notable changes. | — |
| `.github/workflows/ci.yml` | CI: core suite on 3.10–3.14 × Linux/macOS/Windows, a cross-check job that **fails if the oracles skip**, ruff + mypy, a GUI smoke test under Xvfb, and a wheel build. | — |

### The model module (`src/deco/buhlmann.py`)

1,500 lines and five concerns, so here it is by section rather than as one
paragraph. Line numbers drift; the banner comments in the file are the index.

| Section | What lives there | The part that bites |
|---|---|---|
| **Constants & environment** | `N2_*`/`HE_*` ZHL-16C tables, `P_ATM`, `MSW_PER_BAR`, `WATER_TYPES` (`salt` 10.0 / `fresh` 10⅓), `surface_p_at_altitude`/`altitude_at_surface_p`, `PLANNER_PROFILES` | **`P_H2O` defaults to Schreiner 0.0567** (MultiDeco/Shearwater/GFDECO), not Bühlmann's 0.0627 (Subsurface's, passed explicitly by that cross-check). The environment is a *setting*, not a constant (#15). `--planner NAME` selects a whole constant set so a plan can sit beside another tool's without flag-hunting (#20) |
| **`Gas`** | frozen `fO2`/`fHe`, `mod`/`ppo2`/`min_depth`, `end` (equivalent narcotic depth, O₂-narcotic convention), `density` (`DENSITY_MAX_G_L` 6.2, Anthony & Mitchell) | Keyed by **value, never by `repr`** — EAN20.6 and EAN21.4 both print "Air" and must keep separate accounting (#8) |
| **`Tissues` & ceilings** | 16-compartment N₂/He loading, `_schreiner`, `update_tissues`, `compartment_ab`, `ceiling`, `gf_at`, `surface_gf` | `surface_gf` is Shearwater's SurfGF — a closed-form inversion of `ceiling`, returned **raw** so a >1.0 violation stays visible instead of being clamped away |
| **The planner** (~570 lines) | `DivePlan`, `Level`, `DiveSegment`, `plan_multilevel` (`plan_dive` = one level), `_ascend`, `_move`, `bailout_schedule`, `ndl`, `surface_interval`/`tissues_after` | A `Level` is depth + **cumulative** runtime and nothing else; levels are contiguous, the transit is billed to the level's runtime, and a runtime too short to cover it is an error, as in MultiDeco. **Stops follow Baker's discretisation in his order** (#21) — pad onto the grid *first*, then whole increments. `bailout_schedule` returns `None` when nothing is breathable at depth: a finding, not a missing feature. Repetitive dives are `plan_multilevel(start_tissues=…)` after `surface_interval` (#26) |
| **Printed notation** | `runtime_min`, `StopLeg`, `stop_legs`, `max_depth`, `average_depth`, `_bottom_phase_end` | **One definition, rendered by every view** (#17). `run` = the runtime you LEAVE that depth, truncated; `leg` = ascent to the stop + hold, measured from the previous stop and from leaving the bottom for the first; TTS rounds UP. A gas-switch row is an annotation the legs are NOT measured from |
| **Safety checks** | `ppo2_violations`/`worst_ppo2_violations` (reduced per **`Gas` value**, never `repr` — #8), `ceiling_violations` | A designated deco gas is judged against `ppo2_deco` 1.6 **wherever** it is breathed; the bottom/travel gas uses `ppo2_bottom` 1.4 going down or held on a level. The planner plans what it is given — air below its MOD, a hypoxic mix with no travel gas — but never silently: **front ends must surface these** (#4, #5) |
| **Ceiling profile & TTS** | `ceiling_profile` (time series for plotting), `time_to_surface` | The profile re-derives the first stop exactly as the planner does, so the curve agrees with the schedule drawn under it |
| **Gas management** | `GasPlan`, `segment_gas_liters`, `levels_of`, `reserve_candidates`, `emergency_gas_liters`, `rock_bottom_liters`, `TURN_RULES` | The reserve is taken from **the worst moment, evaluated at every level end** (#7, #28) — not the last one, which understated minimum gas by 48 % on a 45→18 m profile. `reserve_candidates` depends only on the profile, never on the gas, so `report.gas_report` builds it **once**; `test_report` pins the call count because nothing user-visible would change if it regressed. `GasPlan.divers` > 1 shares **the whole ascent, deco stages included**. `emergency` False means the block was not asked for, and the figures are then `None`, never `0.0` |

`DivePlan` carries **every** algorithm input, including `p_h2o` and
`ppo2_switch_tol` — all settable from the config, CLI and GUI, with
`tests/test_input_coverage.py` failing if one is not (#19), and its defaults
pinned against the config's and the CLI's (#29 era, `TestDefaultsAgree`).
`__post_init__` rejects GF-low > GF-high, out-of-range GFs and an unknown
switch policy.

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
python -m deco.cli plan --depth 60 --time 25 --gas 10/70 --travel-gas 35/25 --deco-gas 50 --sac 18 --sac-emergency 27 --tank-size 24
# Gas is reported even with no --sac (20 L/min assumed, and it says so); the
# emergency block can be dropped entirely
python -m deco.cli plan --depth 40 --time 25 --gas air --deco-gas 50 --no-emergency
# Turn pressure: hide it, or size it by the cave rule instead of rock bottom
python -m deco.cli plan --depth 40 --time 25 --gas air@24@232 --deco-gas 50 --sac 20 --turn-rule thirds
python -m deco.cli plan --depth 40 --time 25 --gas air@24@232 --deco-gas 50 --sac 20 --no-turn-pressure
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
# Repetitive dives: each --dive is DEPTH:RUNTIME[:SURFACE_INTERVAL] (minutes on
# the surface BEFORE that dive); residual loading is carried through
python -m deco.cli plan --dive 30:25 --dive 30:25:60 --dive 24:30:90 --gas air --deco-gas 50
# …and one dive out of a series. Needs a config whose `repeats` holds a dive 2
# — the checkout's own dive_plan.json is a single dive, so this errors there.
python -m deco.cli plan dive_plan.json --dive-index 2
# Hold every deco switch until the first stop (the team convention) instead of
# taking each mix at its MOD
python -m deco.cli plan --depth 40 --time 25 --gas air --deco-gas 50 --gas-switch at-first-stop
# Separate deco-cylinder SAC (MultiDeco/Shearwater plan the two rates apart)
python -m deco.cli plan --depth 40 --time 25 --gas air --deco-gas 50 --sac 20 --sac-deco 16
# Contingency cut table (bottom-timer backup): square @ max depth on a 3 min × 3 m
# grid, time rows −TB/+TA steps × depth columns −DB/+DA steps
python -m deco.cli plan --depth 40 --time 25 --gas air --deco-gas 50 --contingency          # counts from config (1:1:1:1)
python -m deco.cli plan --depth 40 --time 25 --gas air --deco-gas 50 --contingency 0:2:0:1  # explicit TB[:TA[:DB[:DA]]]
# Tests: 500 total. Skips are environment, not failure — count them before
# assuming something is wrong:
#   1  everything installed, with a display (the unfilled Shearwater Cloud
#      fixture, which is a fixture waiting to be filled)
#  45  headless: + the 44 GUI / card-rendering tests (Tk + matplotlib)
#  +38 with no toolchain: 26 compiled cross-checks (19 Subsurface via g++,
#      7 Baker GFDECO via gfortran) and 12 python-oracle ones (pip extras).
# The compiled cross-checks BUILD the reference implementations, so they skip
# rather than error where there is no compiler.
python -m unittest discover -s tests -t . -v
# Individual oracles: native Subsurface deco.cpp / Baker's GFDECO Fortran
python -m unittest tests.test_subsurface_crosscheck -v
python -m unittest tests.test_baker_crosscheck -v
# Which constants differ from a reference planner, and which the evidence
# cannot speak to at all (UNDETERMINED != agrees)
python -m tests.planner_diff
# Lint + types (config in pyproject.toml; both are clean and CI enforces them)
pip install -e ".[dev]" && ruff check . && mypy
# Coverage. Branch coverage, config in pyproject.toml. CI gates the STDLIB-ONLY
# core (buhlmann/report/toxicity/contingency/dive_config/cli) at >= 92 % — a
# ratchet under where it stands (94 %), not a target; app/cards are reported,
# not gated. Install [gui] and the compilers first or the number is measured
# against a partial run. READ THE UNCOVERED LINES, don't chase the percentage:
# an untested line and a dead one look identical here, and DECISIONS #34 was
# the dead one.
python -m coverage run -m unittest discover -s tests -t . && python -m coverage report
```

Gas syntax: `air`, `o2`, `ean32` / `nx32` / `32`, trimix `21/35` (fO₂/fHe %).

Gas planning: each cylinder has a tank size + fill pressure (`mix@tank@bar`, e.g.
`air@24@232`). One baseline SAC/RMV (`sac_normal`, always in force — every plan
reports gas), and an emergency block that can be switched off as a whole
(`emergency`): an absolute emergency SAC (`sac_emergency` L/min, 0 = twice the
baseline), a problem time (`problem_minutes`), a diver count (`divers`) and the
turn pressure — shown or not (`turn_pressure`) and sized by `turn_rule`
(`rock-bottom`: half the gas above the reserve, surfacing exactly on it;
`thirds`: ⅔ of the fill, flagged when a third does not cover rock bottom).
The library helper `emergency_gas_liters` is the *rock-bottom reserve* for
a problem striking at the worst moment — the end of the bottom phase (deepest
loading → longest deco). It counts only the reserve from that moment: the
problem minutes at max depth (billed to the gas breathed there, i.e. the bottom
gas) plus the real planned ascent + deco at the emergency SAC (SAC ×
multiplier), following each gas only to the next switch. The gas already
breathed on the way down is the normal-SAC `need`, not part of the reserve.
With `divers` = 2 the team shares the supply (buddy out of gas) for **the whole
emergency ascent, deco stages included** — the diver who lost their gas may have
no stage to switch to, so every litre on the way up doubles (DECISIONS #28). The front-end **emergency column** (`(emrg)` / the parenthesised
figure = `report.CylinderNeed.liters_emergency`) is the *total* to carry: the
normal `need` PLUS that reserve held on top (`need + emergency_gas_liters`), so
`SHORT!` in the parens means the fill can't cover need-plus-reserve. **Rock
bottom** is standard *minimum gas* — it is exactly the bottom gas's
`emergency_gas_liters` (problem + the real ascent/deco to the first switch, ×
divers) — **not** the whole deco billed to back gas (that would be hundreds of
bar deep). The GUI also shows the lost-deco-gas contingencies (`report.lost_gas_scenarios`):
one schedule per lost deco gas plus an all-lost worst case (any N of deco gases),
with per-scenario usage as have / need (emergency) — carried (tank × fill pressure)
vs need at the normal SAC, with the emergency total (need + rock-bottom reserve) in parentheses; SHORT!
flags a normal-SAC shortfall and a second SHORT! inside the parens an emergency one. The full dive
(`levels`, GF, last stop, gas stack, SAC, multiplier, problem time, divers,
ascent/descent/stop rates + ppO2 window) lives in `dive_plan.json`, shared by the CLI (`plan dive_plan.json`
/ `--load` / `--save`) and the GUI (Save / Reload). Save / `--save` captures **every**
value for an exact round-trip; the GUI preserves fields it has no control for.

## Conventions

- **Zero runtime deps in `deco.buhlmann`, `deco.toxicity`, `deco.contingency`,
  `deco.report`, `deco.dive_config` and `deco.cli`.** Only `deco.app` and
  `deco.cards` may import matplotlib/tkinter, and both are behind the `[gui]`
  extra. Do not add dependencies to the core (DECISIONS #1, #31).
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
  DECISIONS #15). `P_H2O` is the module-level *default* only: it is bound into
  `DivePlan.p_h2o` at import time, so assigning to the global afterwards
  reaches nothing — pass `p_h2o=` (which is what the cross-checks do).
  Ascent gas switches snap
  to stop depths (`switch_depth`, ppO₂ overshoot ≤ `ppo2_switch_tol` 0.05 bar
  — that's what puts O₂ at the 6 m stop despite its 5.9 m MOD).
- **Warnings are load-bearing, and every hazard must reach them.** A hazard
  rendered as an ordinary statistic is outside the safety surface however
  prominently it is printed — that was the whole finding of DECISIONS #33, which
  moved the surfacing check (SurfGF vs GF-High, residual ceiling), the oxygen
  clocks (CNS/OTU tiers) and the 5.2 g/L working density limit into
  `report.warning_lines`. Anything new that can hurt a diver goes there too, not
  into a printed line beside it. `PlanResult.notices` is the separate channel for
  what the planner *chose* rather than what is dangerous; never mix the two.
  `ppo2_violations`, `ceiling_violations` and the
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
  `tests/planner_diff.registry()` with the observables that could pin it — in `buhlmann`, `toxicity` or `contingency` alike, since `CONSTANT_MODULES` walks all three —
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
- **Do not report the cross-checks as "eko-deco is correct"** (DECISIONS #23).
  They establish "on this observable, we are not the outlier", and several are
  measured with constants aligned first — GFDECO with our N₂ `a` table patched
  to ZH-L16B and surface 1.000 bar (it validates the *planner*, not the
  tables), decodaitengu with compartment 1 aligned to its 4.0 min variant (a
  *nitrogen* ceiling). The oracles do not all agree with each other either:
  compartment 1 splits two–two, decodaitengu's slow-compartment helium
  three–one, Subsurface's anchor and scheduler by design. The two open
  MultiDeco rows are **unattributed** — the 12 m one is not "a compartment" —
  and `TestExportedRuntimeDeltas` pins all 36 cells (25 identical, 11 recorded
  deltas) so neither closing nor opening one can happen silently. Never fit a
  coefficient to close a row.
- Add a CLI flag → update `src/deco/cli.py` argparse, `README.md`, and the Commands block above.
- Keep `README.md`, the skill (`.claude/skills/deco-buhlmann/SKILL.md`) and this file consistent.
- **Made a choice a future reader would want to undo?** Add a numbered entry to
  [`DECISIONS.md`](DECISIONS.md) and cite it from the code (`see DECISIONS.md #N`).
  Numbers are stable — never reuse or renumber them.
- User-visible change → a line in `CHANGELOG.md` under `[Unreleased]`.
- Before you claim done: `python -m unittest discover -s tests -t .`,
  `ruff check .`, `mypy`. Touching the core? Add `python -m coverage run -m
  unittest discover -s tests -t . && python -m coverage report` — CI gates the
  stdlib-only modules at 92 %, and a new uncovered branch there is worth
  looking at before it is worth explaining.

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
