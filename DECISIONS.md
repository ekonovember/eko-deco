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
