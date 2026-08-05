# Decisions

Why this planner does what it does, where it deliberately disagrees with other
implementations, and which shortcuts it knowingly takes. Each entry is stable
and numbered — code comments cite them (`see DECISIONS.md #7`), so **numbers are
never reused or renumbered**. Superseded entries stay, marked as such.

A decision belongs here when someone reading the code would otherwise be
tempted to "fix" it. Ordinary implementation choices do not.

---

## #1 — The core stays dependency-free, forever

`deco.buhlmann`, `deco.report`, `deco.dive_config` and `deco.cli` import
nothing outside the standard library. Only `deco.app` (the GUI) may import
third-party packages, and it is an optional extra (`pip install eko-deco[gui]`).

**Why.** The model is the interesting part and it should be runnable on any
Python that exists — a stock system interpreter, a locked-down machine, a boat
laptop — with no install step at all. It also keeps the audit surface for
decompression math down to code in this repository.

**Consequence.** The test suite is `unittest`, not pytest, and CI runs it with
no install. Adding a dependency to the core is a breaking change to the
project's premise, not a convenience.

---

## #2 — The Baker / Shearwater / MultiDeco gradient-factor convention

GF-Low is anchored at the **rounded first stop depth** and held static; the GF
line runs from there to GF-High at the surface. NDLs are evaluated at GF-High.
Air is 21/79. Depth converts at a flat 10 msw/bar.

**Why.** These are the numbers a diver's computer and desk planner show. The
point of this project is a model you can hold against a Shearwater or MultiDeco
schedule and understand the difference, so it follows their convention rather
than picking a locally "nicer" one.

**Consequence.** eko-deco disagrees with Subsurface, which re-anchors the GF
line dynamically as the ascent proceeds. That disagreement is *pinned by tests*
(`tests/test_baker_crosscheck.py` against Baker's original Fortran, ≤ 1 min per
stop). Do not "fix" the planner toward Subsurface's anchor — see #3.

---

## #3 — Known, deliberate differences from Subsurface

`tests/test_subsurface_crosscheck.py` compares against Subsurface's unmodified
`deco.cpp` to machine precision, with these constants aligned in the test
because they differ on purpose:

| | eko-deco | Subsurface |
|---|---|---|
| Air | 21 / 79 | 20.9 / 79.1 |
| Surface saturation fN₂ | 0.79 | 0.781 |
| Depth conversion | 10 msw/bar | salinity-based 9.8968 |
| Surface pressure | 1.01325 bar | 1.013 bar |
| GF-Low anchor | static, rounded first stop | dynamic, smooth, surface+1 bar floor |

**Why.** Each one is where the Shearwater convention (#2) and the Subsurface
convention genuinely differ. Erasing them would make the cross-check pass by
making the model something other than what it claims to be.

**Consequence.** If the cross-check fails after a model change and the change
was not *about* one of these five rows, the change is almost certainly wrong.

---

## #4 — The planner plans what it is given; warnings are the safety surface

A profile that breathes air below its MOD, a hypoxic mix with no travel gas, a
level shallower than the ceiling, a gas over the density ceiling — all of these
are planned and then **flagged**, never silently corrected and never refused.

**Why.** GFDECO behaves this way and it is the right behaviour for a tool you
use to *understand* a dive: refusing to plan teaches nothing, and silently
"fixing" the profile hides the very thing worth seeing.

**Consequence.** `ppo2_violations`, `ceiling_violations`, the density ceiling,
CNS/OTU and END are **load-bearing**. Every front end and every output path
must surface them. A new renderer that drops the warnings is a safety
regression, not a cosmetic one. See also #5.

---

## #5 — No printed disclaimer

Output carries no "educational use only / not for real dives" boilerplate. It
was removed from every output path deliberately.

**Why.** Repo owner's decision. A disclaimer printed on every schedule is
banner blindness within a day; the warnings from #4 are specific, actionable
and about *this* dive.

**Consequence.** The warnings are now the only caveat a user sees, which raises
the bar under #4 rather than lowering it. Do not reintroduce a disclaimer.

---

## #6 — Runtime is cumulative; levels are contiguous

A `Level` is depth + **cumulative runtime** — minutes since leaving the
surface, at the *end* of that level, descent included. Levels follow one
another with no gap: the transit to a level runs at the standard rate and its
time is billed to that level's runtime. A runtime too short to cover the
transit is an error.

**Why.** This is how MultiDeco, GFDECO and Subsurface all take a profile, so
the same numbers typed into any of them describe the same dive.

**Consequence.** There is no per-level arrival time. An earlier version had one
(`Level.start`, "arrive at depth at minute N and wait at the previous depth
until then"); it was removed because no other planner has the concept and it
made every level two numbers to reconcile instead of one. To loiter shallow
before descending, add a level for the shallow depth. Config files with a
legacy `start_min` migrate by dropping it.

---

## #7 — Rock bottom is the reserve from the worst moment, and is approximate

`emergency_gas_liters` counts, per gas: `problem_minutes` at max depth (billed
to the gas breathed there — the bottom gas) plus the **real planned ascent and
deco** at the emergency SAC (`sac × sac_multiplier`), following each gas only
as far as the next switch. Gas already breathed on the way down is normal
`need`, not reserve. With `divers > 1`, the problem minutes and the ascent up
to the *first* gas switch are multiplied (a buddy sharing your supply); past
that switch each diver is back on their own cylinder.

**Why.** This is standard minimum-gas: what you must still have in the cylinder
at the worst moment of the dive. Billing the entire decompression to back gas
would produce reserves of hundreds of bar and be useless.

**Known limitation.** The emergency ascent is taken from the **last** level. On
a deep-first multi-level profile (a deep level followed by shallower ones) that
mixes two moments and can **understate** the true worst case at the deep level.
It is a single-square / shallowest-last approximation, not a guaranteed
absolute worst case, and it is documented as such in
`emergency_gas_liters`' docstring.

**Consequence.** The front-end emergency column is `need + emergency_gas_liters`
— the reserve held *on top of* the normal need — while `rock_bottom_liters` is
just the bottom gas's `emergency_gas_liters`. Two different numbers with two
different jobs; keep them distinct.

---

## #8 — One shared report layer, so the CLI and the GUI cannot drift

Everything user-facing that is *computed* — warnings, cylinder accounting,
`PlanResult` — lives in `deco.report`, above the model and below both front
ends. `cmd_plan` computes a `PlanResult` once and hands it to the JSON and text
renderers; the GUI uses the same functions.

**Why.** The two front ends had drifted before: the same dive showed different
litres in the console and in the app because each did its own arithmetic.

**Consequence.** A front end may format numbers. It may not derive them. Gases
are keyed in that layer by the frozen `Gas` value, never by its rounded label,
so two mixes that render identically keep separate accounting.

---

## #9 — Loading a config is strict; the GUI's first launch is not

`dive_config.load(strict=True)` raises on a missing, unparsable or semantically
invalid file — that is what the CLI uses, so a typo'd path exits 2. The lenient
default falls back to `default_config()` and is for the GUI's first launch.
Normalization happens *inside* that boundary, so a file that parses as JSON but
is semantically corrupt cannot slip through as a silent default.

**Why.** Silently planning a *different dive* than the one asked for is the
worst possible failure mode for this tool.

---

## #10 — UI preferences never touch the dive

`dive_plan.json` is the dive and only the dive: it is the file you hand a buddy
or commit next to a trip report. Dark mode and window geometry live in a
separate per-user `ui_settings.json` under the user's config directory.

**Consequence.** `dive_plan.json` stays diffable and shareable; a preference
change never shows up as a change to the plan.

---

## #11 — Where `dive_plan.json` lives

`dive_config.default_path()` resolves, in order: `$DECO_CONFIG`, then
`./dive_plan.json` if the working directory has one, then the per-user config
directory (`$XDG_CONFIG_HOME/eko-deco/`, `%APPDATA%` on Windows).

**Why.** Running either front end from a checkout or a dive folder should share
that folder's dive between CLI and GUI — that is the whole point of the shared
config. An installed `deco` run from an arbitrary directory should not scatter
`dive_plan.json` files across the filesystem.

---

## #12 — The oracles are compiled, vendored and license-fenced

`tests/subsurface_oracle/` holds Subsurface's **unmodified** `deco.cpp`
(GPL-2.0, pinned commit) and `tests/baker_oracle/` holds Erik Baker's original
`gfdeco.f`. Both are compiled on demand by the tests and driven from Python.

**Why.** "Agrees with the reference" is worth nothing as a claim in a README
and everything as a test that runs the reference.

**Consequence — this is a hard rule.** The Subsurface tree is GPL-2.0 and this
project is MIT. Compare outputs freely; **never** copy code, comments, or
constants-with-structure out of it into an MIT-licensed file. Model bugs get
fixed clean-room, from Bühlmann's and Baker's published papers plus the numeric
disagreement. The oracles are never imported at runtime.

---

## #13 — src layout, with the suite still runnable uninstalled

The package lives in `src/deco/`. Tests put `src/` on `sys.path` from
`tests/__init__.py`, so `python -m unittest discover -s tests -t .` works in a
fresh checkout with nothing installed.

**Why.** src layout keeps the tests honest about what is actually packaged
(you cannot accidentally import a module the wheel does not ship), while the
bootstrap preserves #1's promise that the suite needs no install.

**Consequence.** `-t .` (top-level dir) is required for discovery, because that
is what makes `tests/__init__.py` import first.

---

## #14 — No auto-formatter

`ruff check` is enforced in CI. `ruff format` (or black) is not used.

**Why.** Alignment carries meaning here: the ZHL-16C coefficient tables, the
schedule columns, the wetnotes card, the cross-check fixture tables. A
formatter flattens all of it into something correct and less readable.

**Consequence.** Line length is 96 and layout is a human decision. The one
place that exemption is written down is the per-file `E501` ignore for
`tests/test_subsurface_crosscheck.py`, whose CASES table is one dive per line.

## #15 — Water type and altitude are settings, not constants

`DivePlan.surface_p` and `DivePlan.msw_per_bar` have always existed, but only
the library could reach them: the config, the CLI and the GUI all planned every
dive at sea level in salt water. They are now first-class settings —
`surface_p_bar` / `msw_per_bar` in `dive_plan.json`, `--water` / `--msw-per-bar`
/ `--altitude` / `--surface-p` on the CLI, a water dropdown plus altitude and
surface-pressure boxes in the GUI.

**Why.** Two real MultiDeco plans (`examples/scenario_1`, `examples/scenario_2`)
are fresh-water dives at 150 m, and eko-deco could not express either. This is
not cosmetic: lower surface pressure means the same tissue loading sits closer
to its surfacing ceiling, so altitude *lengthens* deco, and fresh water is less
pressure per metre, so it shortens it. Both move ppO₂, MOD, END, density,
CNS/OTU and gas volumes as well as the schedule.

**The constants.** `WATER_TYPES` is `salt` 10.0 (EN 13319, the default) and
`fresh` 10 ⅓ m/bar. The fresh figure is the old "1 atm = 10.33 m of water"
value, chosen because it is what real MultiDeco fresh-water plans were measured
to print: the ppO₂ and ead figures in those two exports admit only surface
0.9986–1.0059 bar with 10.327–10.378 m/bar, and MultiDeco (Baker-derived) uses
1.0 bar. The textbook column of a bar is 10.20 m; pass `--msw-per-bar 10.197`
for it. Altitude → surface pressure uses the standard-atmosphere barometric
formula (`surface_p_at_altitude`).

**What this does NOT do.** It does not model acclimatisation. The tissues start
the dive equilibrated at the plan's surface pressure, which describes a diver
who has been at altitude for many hours, not one who drove up that morning.
`surface_p_at_altitude`'s docstring says so; a same-day altitude dive needs
margin the model does not add.

**One caveat about MultiDeco.** Those two exports print fresh-water pressures
but their *schedules* match eko-deco's sea-level salt defaults far better than
the fresh-water constants do — MultiDeco appears to apply water type and
altitude to what it displays and not to its model. We follow the physics, so
eko-deco's fresh-water plan differs from MultiDeco's on the same settings.
`tests/test_multideco_scenarios.py` pins both halves of that, and
`tests/test_planner_diff.py` pins the stronger statement: **no single
configuration reproduces both halves**. Set the environment MultiDeco prints
and its schedule stops matching (21–31 % of each dive's own TTS, against 6 % at
our defaults); keep the one its schedule implies and its printed pressures stop
matching. Both dives say this independently, which matters because they are
different dives — different bottom mix and very different conservatism. The
tempting "improvement" is to chase one half and silently lose the other.

## #16 — A separate deco SAC

`GasPlan.sac_deco` is an optional second consumption rate, applied to gas
breathed off one of the plan's designated deco mixes (`GasPlan.sac_for`).
`None` — the default — keeps the previous single-rate behaviour.

**Why.** Hanging on a stop is not working the bottom, and every planner people
cross-check against models the two separately. Backing the rates out of the
`examples/` exports shows MultiDeco billed the bottom gas at ~19.25 L/min and
the deco cylinders at ~16; with one rate our deco-gas litres are ~20 % high
against real plans, which is the wrong direction for a gas figure.

**Scope.** It follows the *role*, not the mix: membership is the plan's
`deco_gases`, so a mix carried as both bottom and deco gas bills at the deco
rate wherever it is breathed — MultiDeco's simplification too. The emergency
reserve on a deco gas scales with it (`sac_for` × `sac_multiplier`), but **rock
bottom does not move**: that is back gas by definition, and a regression test
pins it.

## #17 — One printed-schedule notation, defined once

`buhlmann.StopLeg` / `stop_legs` define what the numbers on a printed schedule
mean, and every renderer uses them: the runtime card
(`report.wetnotes_rows`), the GUI's stop table, and the contingency cut-table
cell (`ContingencyCell.text`).

* **`run` is the runtime at which you LEAVE that depth**, truncated to whole
  minutes (`runtime_min`). Not when you arrive, and not a stopwatch restarted
  at each stop — the ascent is flown off one runtime clock.
* **`leg` is the ascent to the stop plus the hold on it**, measured from the
  previous stop, and from leaving the bottom for the first stop.
* **TTS rounds UP** while runtimes truncate. Deliberately opposite directions:
  a runtime is a clock reading, a TTS is a budget you must not underestimate.

**Why the leg and not the hold.** The planner produces whole-minute holds with
fractional ascents on top, so the runtime advances further than the hold does —
a 3-minute hold at 3 m moves the clock by 3 ⅓. Printing the hold beside the
runtime reads as a contradiction underwater ("3 minutes" against a clock that
advanced 4), and a diver adding the column up surfaces one ascent early on
every stop. MultiDeco prints the leg for the same reason, verified against both
exports in `examples/`.

**Why measured from the previous stop, not from the previous printed row.**
The first version measured each leg against whatever row the renderer happened
to print above it. That reconciles within one view but makes views disagree:
the card prints a gas-switch row, the GUI's stop table does not, so the same
6 m stop read "2" on one and "3" on the other. A gas-switch row is an
**annotation** — it carries the runtime the switch happens at, and the clock is
not measured from it. The legs still sum to the runtime in every view.

**Scope.** Rendering only; the planner's stop durations are unchanged and
`StopLeg.hold` still carries the exact one. The CLI's segment table stays a raw
dump with explicit ascent rows and untruncated runtimes — a different artifact,
for reading the model rather than diving the plan — but `deco plan` also prints
the card notation as a line, and `--json` carries it as `stops`.
`tests/test_report.py` pins that all three views print identical numbers.

## #18 — Divergences are enumerated, not noticed

`tests/planner_diff.py` keeps a registry of every model constant and planner
setting, and `registry_gaps()` introspects `buhlmann` and fails the suite if
anything is missing from it. Comparing against a reference export grades each
entry `DIVERGES`, `UNDETERMINED`, `SETTING`, `JOINT_OK` or `MATCH`.

**Why.** The fresh-water environment behind DECISIONS #15 was found because
someone happened to notice a printed ppO2 we could not reproduce and went
looking. That is not a process. Everything about a cross-check is easy except
knowing what you forgot to compare, so the list of things that *could* differ
has to be maintained mechanically or it silently rots.

**Why `UNDETERMINED` is a distinct verdict.** "We found no difference" and "the
evidence cannot show a difference" are the same output and completely different
claims. A dive on nitrox says nothing about whether we and another planner
agree on the composition of air; a plan with no gas volumes says nothing about
consumption. Folding those into MATCH is how a divergence survives a green
cross-check, so the harness refuses to.

**Identifiability.** A printed ppO2 inverts to a region of (surface pressure,
metres per bar) — the grid search returns the region, because printed values
are rounded and a point estimate would be a fiction. A printed *schedule*
inverts to nothing: it is a joint function of the halftimes, the a/b sets,
P_H2O, the GF convention and the environment at once, so those get `JOINT_OK`
— the group agrees, no member is separately identified. Claiming more would be
the same error in the other direction.

**Evidence is per dive, and error is relative.** Two things the first cut got
wrong, both from treating two exports as interchangeable when they are
different dives — EAN36 at GF 40/85 against EAN28 at GF 5/50. Their printed
values were pooled into one list, so each dive's conclusion was partly credited
to the other's data; they are partitioned now, and each one pins the
environment on its own. Combining them is still allowed — both were shot at the
same site — but through `intersect()` and an explicit claim
(`COMBINED_ENVIRONMENT_EVIDENCE`), never by accident. And schedule error is
judged relative to each dive's own TTS as well as in absolute minutes: 8
minutes of deco against 26 means "minutes out" silently penalises the longer
dive. Relatively, both agree to **6 %** of their own TTS at our defaults and
diverge by 21–31 % at MultiDeco's printed environment — the same conclusion as
the absolute numbers gave, but now actually comparable between the two.

**Consequence.** Adding a constant to `buhlmann` without registering it fails
the suite. That is deliberate friction, and it is the only thing making "we can
detect all possible differences" a checkable claim.

## #19 — Every algorithm input is binding, in all three front ends

Every field of `DivePlan` and `GasPlan` is settable from the config file, the
CLI and the GUI, and `tests/test_input_coverage.py` enumerates them by
reflection and fails if one is not.

**Why.** "Supported" had three different meanings. `ppo2_switch_tol` was
reachable from nothing at all. `P_H2O` was not a parameter — a module global
that the cross-check tests monkeypatched, so the water-vapour constant, which
genuinely differs between planners (Bühlmann 0.0627, Schreiner/Baker/MultiDeco
0.0567), could not be set on a dive. And the GUI *read* the ascent/descent
rates, the stop interval and the ppO₂ window from `dive_plan.json` and wrote
them back untouched: present in the file, invisible in the app, unchangeable
there. A hand-edited `ascent_rate` reshaped every schedule with nothing on
screen even hinting at it.

**Binding, not merely present.** The test does not check that a flag parses or
a key exists; it sets a distinctive value through each front end and asserts it
arrives in the `DivePlan`/`GasPlan` the planner is handed. Fields carried as
gas-stack roles (`travel_gases`, `deco_gases`) are checked the same way through
the role mechanism.

**Consequence.** A new plan field fails the suite until it is wired everywhere
and given a probe value — the same deliberate friction as the constant registry
(#18). `GasPlan.tank_liters` was deleted rather than wired: it was declared and
validated but never read, superseded by the per-cylinder tanks on the gas
stack, and a field that looks like an input and is not is worse than no field.

**Not everything is a per-dive knob.** The GUI groups the rates, the stop
interval, the ppO₂ window, the switch tolerance and P_H₂O into an "Algorithm &
rates" panel, collapsed by default. Visible and editable, without implying they
are things to fiddle with per dive.

## #20 — The defaults are the planners divers carry, not Bühlmann's book

`P_H2O` defaults to Schreiner's **0.0567**, not Bühlmann's 0.0627, and
`PLANNER_PROFILES` names the constant sets that reproduce each reference
planner (`--planner multideco|shearwater|gfdeco|subsurface|buhlmann`).

**Why.** Every planner in this family runs the same Bühlmann + GF model and
still prints different schedules, because each picks different values for a
handful of constants nobody thinks of as choices. Of those, the water-vapour
pressure is the one that moves a schedule most, and MultiDeco, Shearwater and
Erik Baker's GFDECO all use 0.0567. Only Subsurface uses 0.0627. Defaulting to
the book meant that reproducing a plan a diver was actually holding needed a
flag nobody would think to pass — and repeatedly did not: every card in this
repo's history was generated at the wrong constant while the docs cheerfully
explained which flag would have fixed it. A default that is right in theory and
wrong in every practical comparison is the wrong default.

**It is also the conservative direction.** Alveolar inert gas is
`(P_amb - P_H2O) * f`, so a *lower* vapour pressure means *more* inert gas
inspired, more loading and longer deco. Switching to 0.0567 lengthens
schedules; it cannot shorten one.

**Consequence.** `tests/test_subsurface_crosscheck.py` now passes
`SUBSURFACE_P_H2O` (0.0627) explicitly on every plan and tissue call, because
that oracle hardcodes `WV_PRESSURE 0.0627` — the cross-check compares the
*model*, not a constant we deliberately set differently. The Baker oracle
already passed 0.0567. Both still agree to their pinned tolerances.

**What a profile is not.** It sets constants, not conventions: it will not make
eko-deco pad the first stop the way MultiDeco does, and it does not chase a
planner's display quirks (see #15 on MultiDeco showing fresh water it does not
compute in). It closes the gap that is a number; the rest stays visible in
`tests/planner_diff.py` so the remaining differences can be argued about with
evidence rather than guessed at.

## #21 — Baker's stop discretisation: hold to the second, pad the runtime

At each stop the planner holds until the ceiling permits the next one —
resolved at `STOP_RESOLUTION` (1 s), not in whole-minute lumps — and then pads
so the **runtime lands on a whole minute**. A consequence of the padding is
that the diver stops at the rounded GF-low ceiling even where the ascent has
already cleared it: a *pass-through* stop.

**Why.** This is what Erik Baker's own Fortran does, which settles it, because
this repo's stated convention is his. GFDECO on `examples/scenario_1`'s profile
prints segment times of **0.4, 0.7 and 2.7 minutes** at 9/6/3 m, landing its
RUN TIME on exactly 43, 44, 47 — sub-minute holds, whole-minute runtimes, and a
stop at 9 m. MultiDeco (Baker's code) does the same; its `0:27` first stops are
that padding. eko-deco used to round each *hold* up to a whole minute and add
the real ascent on top, so its runtimes drifted ~0.33 min per stop and it
skipped any stop whose obligation had evaporated during the ascent.

**Evidence.** Against GFDECO, TTS now matches **exactly (0.00 min) on all seven
cross-check cases**; `TTS_TOL` went from 2.0 to 0.05 and `STOP_TOL` from 2.0 to
1.0 — the residual being only that GFDECO prints its STOP TIME column rounded
up while ours is the true fractional hold. Against the two real MultiDeco
exports, exact stop runtimes went from 11/24 to **16/24** and total runtime
error from 18 min to 9.

The old `STOP_TOL = 2.0  # covers GFDECO's >=1 min pass-through stops` says the
behaviour was known and absorbed by tolerance instead of implemented.

**What it costs.** Divergence from **Subsurface**, whose planner trial-ascends
past those stops and rounds holds up: our first stop is now up to two intervals
deeper than its, and on the deepest trimix case our TTS is 4.7 min shorter.
Those schedule-level bands were widened deliberately and are documented in the
cross-check as a *sanity* check between two conventions — what stays pinned to
machine precision there is the shared physics (tissues, M-values, the GF line,
NDLs), which did not move. DECISIONS #3 and CLAUDE.md already state that
following Baker over Subsurface is the intent; this makes it true of the
scheduler and not just of the anchor.

**A no-deco dive gets no stops.** The padding is gated on whether the dive
requires decompression at all, tested with the **GF-high** ceiling — the one
that decides whether the diver may surface. 18 m for 30 min on air has a 5 m
GF-low ceiling and a 0 m GF-high one, and it is an NDL dive. Without that gate
the rounding invents a stop on every no-deco profile.

**Performance.** Whole-minute steps first, then the final minute walked at
1 s — the same answer as stepping by seconds throughout, at a sixtieth of the
tissue updates, which matters because a contingency matrix plans dozens of
schedules.
