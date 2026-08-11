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

**Including the printed card**, which for a long time was the one output that
did not. The GUI's runtime card and `cards/make_cards.py` rendered a schedule
with no warnings on it — on the single artifact that leaves the screen and goes
in the water, and the one with no disclaimer (#5). Both carry them now, and the
card spec's `warnings` key is **required**: `draw_card` raises `KeyError`
rather than silently printing a schedule with no caveat, so the next renderer
cannot repeat it by omission. Pass `[]` when the plan really is clean.

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

**The worst moment is found, not assumed.** Every level end is a candidate:
the dive is re-planned as if it had ended at each level (`levels_of` +
`plan_multilevel`, exact because levels are contiguous, so cutting the profile
short cannot change the tissue history before the cut) and the largest reserve
wins. A square dive has one candidate and its figure is unchanged.

*This used to take the ascent from the **last** level, with a "Known
limitation" paragraph here saying it "can understate the true worst case". It
understated it by 48 % on 45 m for 25 min followed by 18 m to 45 — 14 bar of
minimum gas where the deep level needs 27. An approximation whose error
direction is optimistic does not belong in the one number whose entire job is
to be pessimistic, and writing the caveat down is not the same as being right.
Fixed 2026-08-06; `tests/test_buhlmann.TestReserveWorstMoment` pins it.*

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

**What "semantically invalid" covers**, after an audit found the boundary was
only as strict as the shapes it happened to inspect. A mistyped key used to be
an *absent* key, and an absent key got a default: `{"depth": 40}` normalized to
the default **30 m**. An unrecognised gas role was coerced to `Deco` — so a
mistyped `Bottom` left the dive with no bottom gas and `to_buhlmann` took the
first mix in the list instead, changing both the bottom gas and the deco stack
from one letter. And `o2: 0.32`, a fraction typed where percent belongs, became
a 0.32 % hypoxic mix the planner would schedule. Unknown keys, unknown roles,
missing level fields and out-of-range mixes are all refused now (#24). The
coercion had a test asserting it was intended; that test is now the regression
test for refusing.

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

**Why the leg and not the hold.** Because the leg is the only quantity that
reconciles with the runtime beside it. Whatever the planner's discretisation,
`leg` sums to `run` down the column and `hold` does not, so a diver adding the
STOP column up with holds surfaces one ascent early per stop. MultiDeco prints
the leg for the same reason, verified against both exports in `examples/`.

*This paragraph used to argue it from "the planner produces whole-minute holds
with fractional ascents on top". That stopped being true at #21, which inverted
it — the legs are whole minutes now and the holds are the fractional part
(0.44, 1.67, 2.67 …). The conclusion was right for a reason that had expired
underneath it, which is the failure mode this log is supposed to prevent, so:
when an entry changes the mechanics another entry reasons about, go and fix the
other entry.*

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

**In Baker's order, which is not the obvious one.** Reading `gfdeco.f`'s
`DECOMPRESSION_STOP` directly: he pads the runtime onto the next grid point
*first*, then adds whole increments while the ceiling still blocks the next
stop —

    Round_Up_Operation = ANINT(Run_Time/mst + 0.5) * mst
    Segment_Time       = Round_Up_Operation - Run_Time      ! the pad
    700 <apply>; IF ceiling > next stop THEN Segment_Time = mst; GOTO 700

— so a stop is *pad + k × min_stop_time* and never a sub-minute remainder.
That is where GFDECO's 0.4 / 0.7 / 2.7 minute segments come from. Holding to
the true obligation and rounding afterwards gives the same answer everywhere
except when the obligation lands exactly on the pad, where it charges a whole
extra minute the diver does not owe — and with a fixed ascent time and a
one-second search that boundary is reachable, not theoretical. Doing it Baker's
way also removes the sub-minute search entirely: nothing is resolved finer than
the grid.

**`min_stop_time` is a setting.** Baker's `Minimum_Deco_Stop_Time` is a
parameter, not a constant; his comment records that at 0.1 min with a 0.2 msw
step "a near continuous decompression schedule can be computed". Ours is a
`DivePlan` field wired through the config, CLI and GUI like every other input
(#19). Measured on `examples/scenario_2`: TTS 26.33 min at 1.0, 25.83 at 0.5,
25.33 at 0.1.

**The first stop depth rounds Baker's way too.**
`ANINT(ceiling/step + 0.5) * step` is `floor(x/s) + 1` — the *strictly* next
step, not a ceiling. A ceiling of exactly 6 m rounds to 9, not 6. It only bites
when the ceiling lands precisely on a step, and Baker's choice is the
conservative one: never hold *at* the ceiling, where supersaturation equals the
GF-adjusted M-value with nothing in hand.

## #22 — Four oracles, so "outlier" is a finding and not a guess

The cross-checks now run against four independent implementations: Subsurface's
C++ and Erik Baker's Fortran (vendored, compiled on demand) plus **decotengu**
and **decodaitengu** (`pip`, test-only). `tests/python_oracles.py` adapts them;
`tests/test_python_oracles.py` uses them.

**Why more.** Two oracles can tell you that you disagree with something. They
cannot tell you *who is wrong*. The MultiDeco comparison kept producing
differences of a few millibar with no way to attribute them. With four, the
question is answerable by majority, and the answers came immediately:

* **Our ceiling is right.** decodaitengu agrees with us to **0.03 mbar** on a
  nitrox profile across every gradient factor. The gap to MultiDeco at the
  12 m stop of `examples/scenario_2` is **5.4 mbar** — 180× larger. That row is
  MultiDeco's difference, not our arithmetic, and adjusting a coefficient to
  chase it would have been wrong.
* **Compartment 1 splits two–two.** We, Subsurface (`buehlmann_N2_t_halflife[]
  = { 5.0, ... }`) and GFDECO (`Nitrogen_Half_Time(1)/5.0/`) use Bühlmann's
  5.0 min "1b"; both Python libraries use the 4.0 min "1a", with the matching
  1.51 min helium compartment. A consistent choice on each side, not an error,
  and now pinned so a change on either side is visible.
* **decodaitengu's helium is a different model.** Its `a` values track ours to
  the fourth decimal for the fast compartments and then diverge progressively —
  −0.011 at #10, −0.058 at #12, **−0.162 at #16**. Bühlmann's published helium
  values plateau near 0.51–0.53 for the slow tissues; theirs keep falling.
  Ours matches Subsurface's `buehlmann_He_a[]` and decotengu exactly. So it is
  used here as a **nitrogen** oracle only; trimix goes to Subsurface and
  GFDECO, which share our table.

**Licensing.** Both are GPL-3 and both are **pip test dependencies, not
vendored code** — nothing in `src/deco` imports them, nothing is copied out of
them, and the wheel does not carry them. That is a cleaner boundary than the
vendored oracles need, and it is why they are in the `[dev]` extra rather than
in the tree.

**Skipping.** They skip exactly like g++/gfortran do when absent, so the
stdlib-only promise holds. CI installs them and the "did an oracle silently
skip?" guard now covers all four.

---

## #23 — What the cross-checks establish, and what they do not

Four oracles (#22) support one kind of claim and not another:

> **They support:** "on this observable, eko-deco is not the outlier."
> **They do not support:** "eko-deco is correct."

Every agreement below is measured on a *named observable*, several of them with
constants deliberately aligned first. State results that way, and resist
compressing them into "the libraries agree with us except MultiDeco" — that
sentence is wrong in three separate places, and it was written once already.

**What each check actually covers, and what it patches to get there.**

| Oracle | Pins | Aligned first |
|---|---|---|
| Subsurface (C++) | tissue loading, M-values, the GF line, NDLs — to machine precision | nothing; the schedule-level bands are wide *by design* (#3, #21) |
| Baker GFDECO (Fortran) | the **scheduler**: TTS 0.00 min on all seven cases | our N₂ `a` table → ZH-L16**B**, `surface_p` → 1.000 bar |
| decotengu | the coefficient tables; schedules only loosely (stop depths a superset, totals within 6 min) | its engine binary-searches the exact hold — a different discretisation |
| decodaitengu | the **ceiling**, to 0.03 mbar, **nitrogen only** | our compartment 1 → its 4.0 min "1a" variant |

So the GFDECO number validates the *planner*, not the tables, and the
decodaitengu number is a nitrogen ceiling with compartment 1 held equal. Quote
them with those qualifiers attached or they overstate.

**Nobody is a four-way match.** Three splits exist among the oracles
themselves, none of which involves MultiDeco:

* **compartment 1** — 5.0 min "1b" for us, Subsurface and GFDECO; 4.0 min "1a"
  for both Python libraries. Two–two.
* **slow-compartment helium `a`** — decodaitengu drifts to −0.162 at #16 while
  the other three share Bühlmann's table. Three–one.
* **anchor and scheduler** — Subsurface re-anchors the GF line dynamically and
  trial-ascends past stops, so our first stop runs up to two intervals deeper
  and our TTS 4.7 min shorter on the deepest trimix case. Deliberate (#2, #3).

**The two MultiDeco rows are open, and one of them is not attributed at all.**
Against the two real exports, 25 of 36 stop runtimes are identical
(`tests/test_multideco_scenarios.TestExportedRuntimeDeltas` pins every cell).
The residual is two distinct things:

* **scenario 2, the 12 m row (+1 min, all four columns).** After the 1:40 hold
  our GF ceiling is 5.4 mbar from the 9 m step, where decodaitengu is 0.03 mbar
  from ours — 180× closer. That establishes *our ceiling arithmetic is not what
  is off there*. It does **not** identify a compartment: the compartment-3
  `a`-value was the standing hypothesis and this evidence is what retired it.
  MultiDeco's internals are unpublished, so the cause stays unattributed.
* **scenario 1, the 3 m row (−1 min).** MultiDeco holds 3:40 where we hold
  3:00 — stop discretisation, a different mechanism, in the opposite direction,
  and with nobody established as right. The opposite signs (−0.77 min on one
  dive, +0.23 on the other) are also the evidence that there is no bias to
  correct.

**Consequence.** Do not fit a coefficient to close either row — that is exactly
the move #22 was added to prevent. If a future comparison closes one, the delta
map in the test changes and the reason belongs here. And when reporting to
anyone what the cross-checks show, the honest sentence is:

> On the observables we can compare, eko-deco agrees with three independent
> implementations within a set of differences enumerated by name. Two rows
> across the two MultiDeco exports remain unexplained — one where our ceiling
> is demonstrably not the outlier, one where nobody's is established — and
> MultiDeco cannot be inspected to close either.

---

## #24 — A front end renders a `PlanResult`; it does not derive one

`report.compute_plan_result` is the only place a user-facing figure is
computed, and both front ends read its fields. `deco.cli` already worked this
way (#8); `deco.app` did not, and this entry records making it so and the two
classes of bug that were waiting in the gap.

**What was wrong.** `_write_readout` called `b.plan_multilevel` itself and then
re-derived density, CNS/OTU, END, the final ceiling, ppO₂, MOD, the hypoxic
depth and the whole gas accounting inline — all of it at **sea-level salt**,
because the environment arguments were optional and it passed none:

* a dive planned at 1500 m in fresh water printed **density 6.37 g/L** on the
  GAS card — above the 6.2 g/L ceiling — while the ⚠ density warning, which
  *was* environment-aware and saw the true 5.99, stayed silent. Two
  contradictory statements about the same gas on the same screen, one of them
  on the safety surface #4 and #5 designate as the only caveat the user gets.
* `gas_report` was called without `deco_gases`, so `GasPlan.sac_deco` never
  matched a cylinder: a deco SAC the user had typed, saved and could see in its
  spinbox changed **no number anywhere**. On 40 m/25 min air + EAN50 at SAC
  20/12 the GUI showed EAN50 714 L where the CLI showed 428 L, from one config.

**The fix, in the order that matters.** First the API: `gas_report` takes the
whole `DivePlan` instead of three optional scalars, so omitting the environment
is a `TypeError` rather than a plausible wrong number. Then the caller:
`recompute` builds one `PlanResult` and `_write_readout` / `_write_runtime`
render it. A front end may format — pick a width, truncate a runtime, choose a
label — but the moment it computes, the two front ends can disagree, and they
did.

**And the God function is gone.** `_write_readout` was 252 lines with nine
parameters, and routing a `PlanResult` into the top of it would have left the
next person the same invitation to derive one more number inline. It is now a
list of card builders (`_card_header`, `_cards_warnings`, `_cards_stops`,
`_card_gas`, `_card_dive`, `_card_environment`, `_card_gas_plan`), each taking
`res` and returning lines, with the method itself deciding only the ORDER. It
holds no arithmetic, which is what makes #8 true by construction instead of by
everyone remembering. (The warning cards moved above the stops table while
doing it: on the tab whose job is the safety surface, they go first.)

**Rendering is not enough to test.** `tests/test_input_coverage.py` passed on
`sac_deco` throughout: the value *did* reach the `GasPlan`. #19's "binding, not
merely present" has to extend to the rendered output, so
`tests/test_app_levels.TestReadoutAgreesWithTheReportLayer` asserts the
readout's own strings against a freshly computed `PlanResult` — the numbers on
screen, not the objects behind them.

**Related, same principle.** A config with no usable gas — `{"gases": []}`, or
every entry unticked — used to fall back to the default stack and then to
`AIR`, planning a dive on mixes the file never mentioned. `dive_config`
now keeps an explicit empty list empty and `to_buhlmann` raises; the CLI turns
that into exit 2. An absent `gases` key still gets defaults: that is a partial
hand-edit, not a gasless dive.

## #25 — Where a deco gas is taken is a setting, and the default stays at MOD

`DivePlan.gas_switch_policy` is `"at-mod"` (default) or `"at-first-stop"`.

At MOD is what MultiDeco and Baker's GFDECO do, and what every
cross-check in this repo is measured against, so it stays the default: changing
it would move our schedules away from the tools they are pinned to for a reason
no diver asked for.

At first stop exists because teams really plan it that way. A gas switch flown
mid-ascent is a valve and regulator drill done while moving, negatively buoyant
and task-loaded; the convention is to arrive at the first stop, settle, then
switch. It is a procedure choice, not a model one, and the planner's job is to
cost it rather than to have an opinion about it.

**It can only lengthen the deco.** The richer mix starts working later, so the
obligation is never smaller. `tests/test_buhlmann.TestGasSwitchPolicy` sweeps 42
dives and asserts exactly that, because a policy that ever came out *faster*
would mean the switch depth was feeding back into the schedule the wrong way.

**On the standard 1-minute stop grid it usually changes nothing.** Baker's
padding (#21) rounds each stop onto a whole minute and absorbs the difference;
at `min_stop_time` 0.1 the same dives show 0.2–0.4 min. That is not a reason to
distrust the setting — it is the same reason our stop times match GFDECO — but
it does mean a user who flips it and sees an unchanged TTS is seeing the truth,
not a broken control.

Only **deco** gases are held back. Bottom and travel mixes are what got the
diver down; they are not a switch made on the way up. And an NDL ascent has no
first stop to hold to, so `first_stop=None` falls back to at-MOD rather than
suppressing every switch to the surface.

**Correction (#27):** the claim above that *Shearwater* switches at MOD is too
broad. Two photographed **Predator** plans show it switching only at a stop it
actually holds — a third behaviour neither policy expresses. A **Perdix**, on a
neighbouring dive with the same mixes, does switch at the MOD, so the two units
disagree with each other and at-MOD is not unsupported. The default is unchanged
and the reason for it is unchanged; only the list of who does what is corrected.

## #26 — A dive series shares its settings and repeats only the profile

Repetitive dives are `config["repeats"]`: a list of
`{"surface_interval_min", "levels"}` after the existing top-level `levels`,
which stays dive 1.

**Why not a `dives` array replacing `levels`.** That is the tidier schema and it
was the first plan. But `levels` is read by the CLI, the GUI, `levels_of`, and a
dozen tests, and every existing `dive_plan.json` uses it — so a rename buys
symmetry and pays for it in migration risk across the whole surface. `repeats`
is strictly additive: every config written before repetitive dives existed
describes exactly the same dive afterwards, and nothing that reads `levels`
had to change. The wart is that dive 1 is spelled differently from dives 2+;
`dive_config.series_of` exists so no caller has to care.

**Only the profile repeats.** Gases, GF, SAC, rates and the environment are
shared across the day, because that is how a day's diving is actually planned:
one rig, one set of settings, several profiles. A per-dive gas stack would be a
different feature (twinset in the morning, single in the afternoon) and can be
added later without moving what is here.

**A surface interval is required on a repeat, never guessed.** Same rule as #9
and #24: defaulting it would invent residual nitrogen the file never stated, and
the whole point of the feature is that the second dive's deco comes from the
first dive's loading. Dive 1 has no interval at all — nothing precedes it — so
the GUI hides the field rather than showing it reading zero.

**The model needed almost nothing.** `plan_multilevel` already took
`start_tissues`; `surface_interval` is one `update_tissues` call at surface
pressure. No tables, no pressure groups — the compartments carry the residual,
which is what every dive computer does and what makes a repetitive dive just a
dive that did not start clean.

## #27 — Pass-through stops and the gas switch: two references disagree with us at low GF-Low

Two Shearwater Predator plans photographed on 2026-08-07
(transcribed in `tests/shearwater_golden.json`, `_predator_provenance` and the
two `SW Predator` entries) put a real computer's schedule beside
ours for the first time. The obligation matches minute for minute. Two
conventions do not, and both are recorded here rather than "fixed", because
both are choices we made on purpose and can now name a price for.

**1. Pass-through stops cost ~1 min, and at GF-Low 5 two references skip them.**
#21 holds a stop at the rounded GF-Low ceiling even where the ascent has already
cleared it, read off `gfdeco.f` and pinned to GFDECO at 0.00 min. On the
32 m/40 min EAN28 GF 5/50 dive our GF-5 ceiling on leaving the bottom is 17.98 m
(18.03 m at surface 1.000 bar — the first stop lands on 18 m or 21 m on 13 mbar
of surface pressure, which is its own warning about that GF), so we hold at 18 m
and then 15 m. The Predator ascends straight to 15 m. So does the MultiDeco 4.24
export of the *same dive* (`examples/scenario_2`, golden entry
`MD 32m/40min EAN28 +EAN50+O2 GF5/50`) — neither has a stop above 15 m.

Replaying our own tissue model on a 1-minute grid with the GF line anchored at
21 m and the pass-through stops suppressed reproduces the Predator's schedule
exactly — `15m 1′ 12m 3′ 9m 4′ 6m 5′ 3m 10′`, run 65, deco 25, SurfGF 48 %. The
model, the GF line and the stop grid all agree; only this rule differs.

**We keep it.** It is Baker's, it is what the GFDECO cross-check pins, and it
errs long. But the note in #21 that it "usually" costs nothing is only true at
ordinary GF-Lows, where the ceiling still blocks on arrival. At GF-Low 5 the
ceiling relaxes faster than the diver ascends and the rule becomes a visible
1 min of deep padding that no reference planner charges. A future option to
suppress it would be legitimate; fitting the ceiling to close the gap would not.

**2. The *Predator* switches gas at a stop, not at a MOD — but a Perdix does
not.** #25 says at-MOD is "what MultiDeco, Shearwater and Baker's GFDECO do".
For the Predator that is disproved: on the GF 5/50 dive EAN50's MOD is 21.9 m
and the printed `15 asc 42 28/00 134` row bills the *whole* 32 → 15 m ascent to
the bottom gas. On the GF 40/85 dive the first stop is 6 m, where O₂ beats
EAN50, and EAN50 reads 0 L for the dive. The Predator's rule is "switch only at
a stop the diver actually holds", which is neither of our policies —
`at-first-stop` switches at our first stop, and our first stop can be a
pass-through the Predator never makes.

**The generalisation to the brand does not survive**, and it was corrected
before it could be relied on. The Shearwater **Perdix** plan in
[`examples/hermanice_dive`](examples/hermanice_dive) breaks its ascent at 21 m —
a depth it holds for zero minutes — purely to change gas, and bills the 21 → 9 m
ascent to EAN50. 21 m is EAN50's MOD snapped to the 3 m grid. That is **at-MOD,
i.e. our default**, on the same brand, the same mixes and a neighbouring dive.

So the two units disagree with each other, and we match the newer one. Whether
that is firmware, a menu setting on no photographed screen, or a model
difference is **not established** and is recorded as open rather than guessed.
The default stays `at-mod`: it is what the MultiDeco exports show, what every
cross-check is measured against, and what the Perdix does. The difference is gas
accounting, not schedule — the obligation is identical either way.

What changes is the claim, not the code — #25's sentence is corrected here and
in the `--gas-switch` help, and it is corrected to name a *unit*, not a brand.

**3. CNS is a genuine open disagreement, and it is the O₂ clock.** The Predator
reads 38 % where we read 30.7 %, and 51 % where we read 36.7 %. Split by gas,
the gap is +7.3 and +14.3 points over 7 and 15 minutes of O₂ — **+0.98 points
per O₂ minute in both dives**. Charging O₂ at a flat 2.0 %/min and leaving every
other gas at our own rates reproduces both totals to the displayed integer;
2.0 %/min is the NOAA-interpolated rate at ppO₂ 1.584, i.e. the 6 m stop, so the
Predator behaves as if it charges O₂ at its switch-depth ppO₂ for the whole time
it is breathed, where we integrate at the actual depth (~4× slower at 3 m).

**Nothing is changed on two data points and one fitted parameter.** The decisive
plan is one with no O₂ at all (EAN50 shallowest): if CNS matches there, the
whole disagreement is the O₂ clock. Until then this is recorded, not modelled —
and it is recorded loudly, because ours is the *lower* number and the diver's
own computer is the one they will be reading.
