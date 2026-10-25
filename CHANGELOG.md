# Changelog

Notable changes, newest first. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project is
pre-1.0, so anything may still move.

## [Unreleased]

### Changed — the first stop is checked on arrival, as Baker does (DECISIONS #36)

- **After a short deep bounce the first stop sat above the GF-Low line.** The
  first stop was the GF-Low ceiling *on leaving the bottom*, rounded; on a
  short deep dive the slow compartments keep loading on the way up and the
  ceiling rises behind the diver. 51 m / 5 min air, GF 30/70: ceiling 5.8 m on
  leaving (stop 6 m), 7.7 m on arriving there — a GF of 0.38 held where 0.30
  was set. Erik Baker's GFDECO runs a *projected ascent* for exactly this and
  deepens the stop; eko-deco now does the same, so the GF anchor equals
  GFDECO's first stop exactly on all nine cross-check cases (it used to be
  allowed a 3 m step of slack).
- Effect: only short deep bounces move — 51 m / 5 min air GF 30/70 goes from
  `6/6 3/1` to `9/5 6/1 3/1` (TTS 7.3 either way), 54 m / 5 min air GF 20/85
  from `9/5 6/1 3/1` (TTS 7.3) to `12/5 9/1 6/1 3/1` (TTS 8.3). Ordinary deco
  dives are unchanged: 40 m / 25 min air GF 30/70 is still
  `18/3 15/2 12/4 9/6 6/10 3/24`, RT 74; 50 m / 20 min Tx 21/35 + EAN50 + O₂
  still RT 45. No deep stops were added: the stop moves only as deep as the
  model's own GF-Low ceiling demands.

### Fixed — repetitive dives: the contingencies were planned on clean tissues (DECISIONS #35)

A code review found residual nitrogen reaching dive 2's plan and none of the
backups planned beside it. `PlanResult.start_tissues` now records the loading
a dive began with, and every derived figure starts from it.

- **The cut table of dive 2 printed dive 1's schedules.** 45 m / 25 min
  Tx 21/35 + EAN50 + O₂ at GF 30/70, repeated after 30 min: the plan's TTS is
  41′, the cut-table cell for the very same depth and time said 29′, and
  flown on the real tissues it surfaces at SurfGF 94 % on GF-High 70 %. CLI
  (`--contingency`) and the GUI's cut-table card both fixed.
- **"Lost bottom gas" on dive 2 was re-flown from clean tissues.** 30 m /
  40 min Tx 21/35 + EAN32 travel + EAN50, twice with 45 min between: the
  bailout said TTS 28′ on both dives; on dive 2 it is 44′. CLI (`Lost bottom
  gas`, `bailout_bottom_gas` in `--json`) and the GUI's bottom-gas column.
- **The GUI's "lost EAN50 / lost O₂ / all" columns on dive 2 were planned
  clean.** On the 45 m dive above, lost EAN50 printed TTS 41′ where the truth
  is 59′, surfacing at SurfGF 96 % on GF-High 70 % — on the runtime card and
  in the per-scenario gas usage. The scenarios moved out of the GUI into
  `report.lost_gas_scenarios`, which plans every column from the result's
  own loading.
- **Rock bottom on a multi-level repeat dive was understated.** The
  worst-moment search re-plans the dive cut short at each level end, and those
  re-plans started clean: air, 40 m to 30 min then 12 m to 40, GF 30/70, SAC
  20, 60 min interval — 6912 L reported, 7487 L real (−7.7 %), on the one
  number DECISIONS #7 allows to err only upward. `report.gas_report` now
  **requires** `start_tissues=` (a keyword with no default — pass `None` for a
  first dive), like the whole `DivePlan` it already required;
  `reserve_candidates`, `emergency_gas_liters` and `rock_bottom_liters` take it
  as an optional keyword.
- **The CLI took a fraction as a percentage.** `--gas 0.32` planned a 0.32 %
  O₂ mix labelled "EAN0" (TTS 78 min, one hypoxic ⚠), and `--deco-gas 1`
  — "1 = oxygen" — a silent EAN1 with a 1590 m MOD, the deco computed with no
  oxygen at all and no warning. A config file has refused the same typo since
  DECISIONS #9. The CLI now refuses any mix under 5 % O₂ (exit 2), with the
  likely meaning in the message: `gas '0.32': 0.32 % oxygen — did you mean 32?`.
- The GUI's **Profile** chart drew dive 2's ceiling from clean tissues (0.02 m
  where the real ceiling was 1.36 m, 40 m / 25 min air after 45 min). Plot
  only — no printed figure used it.

### Changed — the ppO₂ tolerance is the Perdix's 0.04, not 0.05 (DECISIONS #37)

- `ppo2_switch_tol` defaults to **0.04** (CLI, config, GUI, library): the bottom
  gas is flagged above **1.44** bar, as a Perdix flashes "more than 0.04 above"
  OC Mod. PPO2 1.40 — EAN32 at 35 m (1.444) now warns. The deco threshold
  becomes 1.64 (Perdix: 1.61 + 0.04 = 1.65). No schedule in the golden or
  cross-check suites changed; configs that store `ppo2_switch_tol` keep their
  own value.

### Fixed — the review's remaining input, density, JSON and wording gaps (DECISIONS #38–#40)

- **Environment and rates are now bounded.** `DivePlan` checked only `> 0`,
  so a unit slip planned a believable-but-wrong schedule: `--p-h2o 0.627`
  (typo ×10) cut a 40/25 air+EAN50 TTS from 27.3 to 11.3 min, `--surface-p
  1013` (mbar as bar) planned a 4-min dive that sprayed absurd warnings,
  `--msw-per-bar 1` crashed with "Stop exceeded 24h", and `--ascent-rate 100`
  was accepted in silence. Construction now rejects anything outside a loose
  band (p_h2o 0.03–0.08, surface_p 0.5–1.2, msw_per_bar 9–11, ascent ≤ 30,
  descent ≤ 60 m/min) — DECISIONS #38.
- **The density warning named only the bottom gas.** A travel mix can be the
  dense one: 120 m Tx10/70 with 21/35 travel is 6.6 g/L on the bottom but
  6.85 g/L on the travel gas breathed at 66 m — the warning named the bottom
  gas. It now names the densest mix actually breathed, at the depth it is
  breathed there (DECISIONS #39).
- **The cut-table JSON reported the stop hold, not the printed leg.** The
  wetnotes text shows the `StopLeg` leg (ascent to the stop plus the hold);
  `--json`'s contingency `stops` reported the raw hold, so the same stop read
  one number in JSON and another in the card. The JSON now carries
  `leg_min`/`run_min`/`hold_min`, the same notation as the main `stops`.
- **"Ascend on a buddy's gas to the shallowest mix's MOD" named the wrong mix.**
  Coming up you first reach the *deepest* MOD of the remaining gases (EAN50 at
  22 m, not O₂ at 6 m), and with nothing but air on the stack it pointed at a
  mix that does not exist. The line now names the first breathable mix, or says
  nothing else is on the stack (DECISIONS #40).
- DECISIONS #7 now records rock bottom's known optimism: the `problem_minutes`
  are added on the bottom but the ascent/deco that follows is not lengthened by
  them, so the reserve errs slightly low on a deco dive.

### Fixed — six holes in the safety surface (DECISIONS #33)

A technical-diver audit of the whole tool found the model, the schedules and
the gas arithmetic sound, and the *warnings* — which are the only caveat the
output carries, and the thing every agent instruction here says to relay —
leaking in six places. A hazard that renders as an ordinary statistic is
outside the safety surface however prominently it is printed.

- **A "no stops" verdict was never re-checked during the ascent.** 66 m for
  5 min on air at GF 85/85 planned *zero stops* and surfaced at SurfGF 95 %
  against GF-High 85 %, with 1.07 m of ceiling left: the ceiling at the end of
  the bottom is 0.00 m, but the slow compartments keep loading through the long
  ascent and it rises behind the diver. Only GF-Low >= 0.80 on a short deep
  bounce does it — but nothing asserted the planner's contract, so the corner
  that broke it broke silently. `report.surfacing_warnings` now checks the
  finished tissues against the plan's own GF-High. A post-hoc check on the
  result; the scheduler is untouched.
- **CNS % and OTU are warnings now, not statistics.** A 40 m / 60 min EAN32
  dive plans at CNS 172 % and flagged nothing. Tiers: CNS 80 % advisory,
  100 % (NOAA single exposure), OTU 300 (Repex daily dose).
- **A repetitive series accumulates the oxygen clocks.** The tissues were
  carried through the surface intervals; CNS and OTU were not, so a three-dive
  day printed "CNS 10 %" on dive 3 with a day total near 22 %. `deco plan` with
  several `--dive` flags now prints a **Day total** block (and `day_totals` in
  `--json`): OTU summed — it is a *daily* dose by definition — and CNS carried
  across the intervals, decaying with a 90 min half-time.
- **Gas density warns at the 5.2 g/L working limit**, not only at the 6.2 g/L
  hard ceiling. Air crosses 5.2 at about 31 m and 6.2 only at about 39 m, so
  the whole band where Anthony & Mitchell say to add helium was unflagged —
  including this repo's own 30 m `dive_plan.json`.
- **"Lost bottom gas: NOT survivable on this stack"** is gone. It appeared on
  an ordinary 30 m twinset dive carrying EAN50 and O2, where you simply ascend
  to 21 m and take the 50 %. The line now states what the model actually found
  — no schedule can be planned *from depth* — and points at the shallowest
  mix's MOD.
- **A deco gas used as travel gas says so.** New `PlanResult.notices` (`·`
  lines beside the `⚠` ones, `notices` in `--json`): things the planner chose
  on the diver's behalf, kept separate from hazards so the warnings stay worth
  reading.

### Added — a coverage gate on the core

- `coverage>=7.5` in the `[dev]` extra, configured in `pyproject.toml` (branch
  coverage, shared by CI and a laptop so the two measure the same thing).
- A **CI job gating the stdlib-only core** — `buhlmann`, `report`, `toxicity`,
  `contingency`, `dive_config`, `cli` — at **92 %**, a ratchet set just under
  where it stands (94 %) so it catches a regression rather than posing as a
  target. `app` and `cards` are reported, not gated: chasing a percentage
  through Tk event handlers buys less than one more cross-check. The job
  installs `[gui]` and both compilers so nothing skips out of the measurement.

### Fixed — an impossible gas mix constructed silently (DECISIONS #34)

- **`Gas(0.50, 0.60)` — 110 % of a gas — passed validation.** The guard
  (`if self.fN2 < -1e-9`) read the `fN2` property, which clamps at zero to
  absorb float slop, so the clamp made the guard unreachable. The mix built as
  "Trimix 50/60" and went on to quote a density, a MOD and an END, all derived
  from a molar mass summing 110 % of a mole; `deco plan --gas 50/60` planned
  the dive. Validation now asserts on the raw sum, keeping the same slop
  tolerance. Found by reading the uncovered lines in a coverage pass — the line
  was uncovered because it was dead, which a coverage *number* cannot tell you.

### Added — tests for the paths a coverage pass showed were unexercised

- The **hypoxic** half of the ppO2 warning: live code (it fires when a hypoxic
  bottom mix is given with nothing to travel on) that had never been rendered
  by a test.
- `Gas` validation — all three raises, plus the float slop the clamp exists for,
  so the tolerance and the guard are pinned against each other.
- `cards.gas_line`, `cards.bars_from_plan`, `save_sheet` (the A4 imposition that
  reaches the printer) and the path that renders warnings **onto** the card.
  `cards.py` coverage 69% -> 93%.
- The bailout-unplannable handler, and `compartment_ab`'s zero-loading guard.

Core modules now sit at 94-100 % branch coverage (`buhlmann` and `report` 98 %,
`contingency` 100 %); 500 tests.

### Fixed

- `worst_ppo2_violations` keyed its reduction by `repr(gas)` — the one thing
  DECISIONS #8 forbids. EAN20.6 and EAN21.4 both print "EAN21", so two distinct
  mixes collapsed into one banner line under one of their names. Keyed by the
  frozen `Gas` value now.
- The one-line card summary names the mix wherever it changes. Its `bar` column
  is the pressure of the cylinder *in use*, so it jumps stack at each switch
  (124 back-gas -> 196 on the 50 %); the framed card has a gas column to say
  which, that line did not.

### Fixed — documentation caught up with the code

- **The README's two screenshots were 25 commits stale** — they predated the
  Emergency gas frame, the turn pressure and the cut-table sliders that both
  the README and `CLAUDE.md` describe, and still showed the removed
  `Emergency × 1.50` multiplier. Regenerated from a fixed, reproducible dive.
- **Test counts corrected everywhere** (README said 174/258/284, CONTRIBUTING
  said 200; it is 480) and re-framed: the count is always `Ran 442 tests`, and
  it is the *skip* line that tells you what your machine lacks.
- **Repetitive dives** and the **printable card PDF** were missing from the
  README's feature list entirely.
- Module lists in `CONTRIBUTING.md`, `.github/copilot-instructions.md`,
  `.github/instructions/python.instructions.md`, `.claude/agents/dive-planner.md`
  and the `deco-buhlmann` skill now name `deco.toxicity`, `deco.contingency`
  and `deco.cards`.
- **CI proves two more claims.** The GUI job now also runs the input-coverage
  suite's widget arm — the thing that makes DECISIONS #19's "every input binds"
  checkable — and the wheel check asserts `cards.py`, `toxicity.py` and
  `contingency.py` really ship.

### Changed — oxygen clocks and the cut table move out of the model

- **`deco.toxicity`** (`cns_otu`) and **`deco.contingency`**
  (`contingency_schedules`, `ContingencyCell`) are now their own stdlib-only
  modules. Both are downstream analyses of a *planned* dive rather than parts
  of the model — nothing in the planner calls either — and `buhlmann.py` drops
  from 1,644 to 1,502 lines. `b.cns_otu` / `b.contingency_schedules` are no
  longer attributes of `deco.buhlmann`; import the new modules instead. Every
  printed and JSON figure is unchanged. DECISIONS #32.
- **The constant registry follows them.** `planner_diff` walks all three
  modules, so a new constant in either cannot escape the "everything is
  enumerated" guard.

### Changed — the runtime card ships with the package

- **`cards/make_cards.py` is now `deco.cards`**, so `pip install eko-deco[gui]`
  gives you a planner that can print the card it plans. `deco.app` and
  `deco.cards` are the two modules allowed to import matplotlib; the model, the
  report layer, the config layer and the CLI stay standard library only.
  `python -m deco.cards` renders the example into the current directory (it
  used to write next to the module). `cards/` remains the workspace — the
  format reference, the vendor citation, and the `make_scenario.py` driver.
  DECISIONS #31.
- **Fixed: `cards/make_scenario.py` could not run.** It still passed
  `--sac-multiplier`, removed when the emergency SAC became an absolute rate,
  so every invocation exited 2.

### Changed — the GUI stops re-planning the dive on every keystroke

- **Typing in a settings box costs one recompute, not one per character.**
  Continuous inputs (entries, the cut-table sliders) now coalesce into a single
  recompute 150 ms after you stop; discrete actions — adding a level, switching
  dive, toggling dark mode — are immediate as before. Typing `232` into a fill
  pressure used to run the whole model, chart and both cards three times.
  DECISIONS #30.
- **The worst-moment reserve scan runs once per plan instead of once per
  cylinder.** A three-level dive with three mixes re-planned the same truncated
  dives six times over; `report.compute_plan_result` is ~2.4× faster on that
  profile. Every printed and JSON figure is unchanged, byte for byte.

### Fixed — a mistyped config key is refused instead of planning a different dive

- **Unknown top-level keys in `dive_plan.json` are now an error.** Levels, gases
  and repeats already refused them (DECISIONS #9, #24); the object carrying the
  gradient factors, the SAC, the ppO₂ window, the rates and the environment did
  not. `{"gf_hi": 95}` planned at GF-high 70, exited 0, and `save()` wrote the
  typo back out — so the file kept advertising a setting nothing honoured. The
  message names the near miss (`gf_hi (did you mean gf_high?)`). DECISIONS #29.
- **`deco plan` no longer calls a valid-JSON config "not readable JSON".** A
  mistyped key, an out-of-range mix or a level missing its runtime now report
  themselves, instead of sending you looking for a missing comma.

### Changed — gas estimates on every plan; the emergency reserve is a block you switch

- **The baseline SAC/RMV is always in force.** Every plan reports gas now —
  CLI, GUI, agent and card alike. `deco plan` without `--sac` falls back to
  20 L/min (`report.DEFAULT_SAC`, the config's own `sac_normal` default) and
  says so: `SAC 20 L/min assumed — pass --sac`, plus `"sac_assumed": true` in
  `--json`. Previously no `--sac` meant no litres at all.
- **The emergency reserve is an optional block** — `--no-emergency`, the
  config's `"emergency": false`, or its own checkbox in the GUI's new
  *Emergency gas* frame (which greys its inputs out when unticked). Off, every
  emergency figure disappears: no `(emrg)` column, no `MIN GAS` line on the
  wetnotes card, no `rock_bottom_l` / `liters_emergency` keys in the JSON. In
  the report layer those fields are `None`, never `0.0` — absent, not "none
  needed".
- **The emergency SAC is an absolute rate.** `sac_multiplier` / `--sac-multiplier`
  are replaced by `sac_emergency` / `--sac-emergency` in litres per minute, one
  stressed rate for every mix (a deco SAC splits the planned dive only, not the
  emergency). `0` = twice the working SAC, so an unset plan is unchanged.
  Configs migrate on load — both `sac_multiplier` and the older `sac_stress`
  resolve to a rate and are dropped.
- **Two divers now share the whole emergency ascent, deco stages included.**
  The sharing used to stop at the first gas switch; it does not, because the
  diver who lost their gas may have no stage of their own. Reserves on deco
  cylinders double accordingly — an 11 L stage at 200 bar often reads `SHORT!`
  for a pair, which is a real finding about a real rig.
- **Turn pressure is its own switch inside the emergency block, with a rule to
  pick.** `--turn-pressure` / `--no-turn-pressure` (config `turn_pressure`, a
  checkbox in the GUI) shows or hides it; `--turn-rule rock-bottom|thirds`
  (config `turn_rule`, a dropdown) picks how it is sized — half the gas above
  minimum gas, so you surface exactly on the reserve, or the cave rule's ⅔ of
  the fill. When thirds leaves **less than rock bottom** on surfacing, the CLI,
  the Results tab and the wetnotes card all say so; `turn_reserve_bar` and
  `turn_below_rock_bottom` carry it in the JSON and the report layer.
- See [DECISIONS.md](DECISIONS.md) #28 for the reasoning; #7 and #16 are
  annotated where this supersedes them.

### Added — the Hermanice pair, and the hand-written card convention

- **`examples/hermanice_dive/`** — the two plans for one site kept side by side:
  a MultiDeco 4.24 export of the GF 5/50 training profile (32 m / 40 min EAN32)
  and the **Shearwater Perdix** planner screens for the dive actually made
  (33 m / 40 min EAN32, GF 40/85), transcribed verbatim. Its `README.md`
  reconciles both against eko-deco.
  Two findings worth the folder, both since **confirmed by the diver**, which is
  the point of writing the inference down first. The Perdix's six printed gas
  quantities pinned its unphotographed environment to surface 0.980–0.984 bar
  and 10.29–10.31 m/bar; it was in fact **fresh water at 267 m** (0.9816 bar) —
  inside the box on both axes, and the five deco/ascent rows then reproduce to
  **±0.6 L** with nothing tuned. And MultiDeco's 21 m first stop on the training
  profile, which is *deeper* than the same planner's stop on a more heavily
  loaded EAN28 dive at identical settings and so could not come from the model,
  turns out to be a **switch stop the instructor added** for an unhurried gas
  change. Left open: the Perdix's descent rate, ~16 m/min here against the
  10 m/min the Predator's own bottom row pinned — fitted, and labelled as such.
- **The hand-written card convention, in `cards/README.md`** — read off a
  diver's own wetnotes card and reconciled row by row against the export it
  copies: a direction glyph per row (down / level / up), depth, leg minutes, the
  leave-at runtime **in brackets**, and a margin **triangle** at each gas-switch
  row. The bracket is what separates two numeric columns where there is no room
  for a header; the glyph is what a planner export does not give you, because
  `Wynurz.do` / `Przyst. na` in words does not survive being copied onto a
  slate. No dive-specific card generator is kept — the engine stays, plans do
  not.

### Added — a second real Shearwater plan, and what it corrected

- **A second Shearwater Predator plan** — 32 m / 40 min on EAN28 at **GF 5/50**,
  the same dive as the MultiDeco export in `examples/scenario_2`. Transcribed,
  reconciled, and added to `tests/shearwater_golden.json`, which now carries both
  Predator captures whole: the schedules as entries and everything else the
  screens printed — settings read off the unit, per-row gas quantities, CNS, and
  what the gas column settles — in a `_predator_provenance` block beside them.
- **A planning queue for the Predator**, `examples/shearwater/to_plan_1…6/`:
  six sheets, each changing one setting from the last capture and carrying
  eko-deco's prediction *written down before the plan is made*. In order: no O₂
  (settles the CNS gap), last stop 6 m, 45 m trimix (fills the only skipped
  test), salinity fresh-vs-salt, the NDL edge, GF 45/95. Replaces the three
  generic `scenario_N` templates, whose open questions are either answered now
  or absorbed into a specific sheet.
- **Reference rates in the GUI.** The Descent and ascent fields carry a hover
  info box listing what each planner we cross-check against actually uses
  (18/10 ours · 10/10 Shearwater · 8/9 MultiDeco), with where each number was
  read off, plus the same values inline beside the fields.

### Changed — the evidence of record is the test, not a photograph

- **Captured plans are transcribed, screen by screen, and the images are kept
  outside the repo** (`~/eko-deco-evidence/`). A transcription diffs, greps and
  clones; 22 MB of JPEG does none of those, and writing one out screen by screen
  is what makes somebody read the screen. The photos remain the *source* — they
  are no longer the *archive*.
- **And once a test pins a capture, the transcription lives in the test.** The
  two Predator folders are gone: their schedules were already asserted by
  `tests/shearwater_golden.json`, so the settings and printed totals moved in
  beside them and the prose restating it went away. A page that repeats what a
  fixture asserts is a second copy that can drift from it. What survives outside
  the fixture is only what a fixture cannot hold: the *findings*, in
  [DECISIONS.md #27](DECISIONS.md), and the forward-looking capture queue.
  `examples/hermanice_dive/` keeps its folder for exactly one reason — no test
  covers it yet, because the golden schema has no water/altitude fields and the
  dive is fresh water at 267 m.
- Transcribing the Perdix screens this way immediately found something the
  prose had missed — see below. That is the argument for the change, not a
  side effect of it.

### Fixed — a claim, not code

- `--gas-switch`'s help and [DECISIONS.md #25](DECISIONS.md) said switching at
  MOD is "what MultiDeco, **Shearwater** and Baker's GFDECO do". Two photographed
  Predator plans disprove the Shearwater half: it switches only at a stop it
  actually holds. Default and behaviour unchanged; the claim is corrected and
  the evidence recorded in [DECISIONS.md #27](DECISIONS.md), together with two
  open divergences it exposes — pass-through stops cost ~1 min at GF-Low 5 where
  neither reference planner charges them, and the Predator's CNS reads
  **higher** than ours by ~1 point per O₂ minute.
- **…and then the correction was itself corrected, before it could be relied
  on.** The Perdix plan in `examples/hermanice_dive` breaks its ascent at 21 m —
  held for zero minutes — purely to change gas, and bills the 21 → 9 m ascent to
  EAN50. 21 m is EAN50's MOD on the 3 m grid, so that is **at-MOD, our own
  default**, on the same brand and the same mixes as the Predator that does the
  opposite. "Shearwater switches at a stop" is a statement about *the Predator*;
  the two units disagree with each other and we match the newer one. Recorded in
  [DECISIONS.md #27](DECISIONS.md) as an open divergence between units — not
  resolved by guessing which is firmware and which is a menu nobody
  photographed.

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
