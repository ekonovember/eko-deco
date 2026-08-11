# Shearwater plans — real exports, kept as evidence

Same role as [`../scenario_1`](../scenario_1) and [`../scenario_2`](../scenario_2),
which hold two real MultiDeco 4.24 exports: **primary evidence, kept verbatim**.
Once a scenario here is filled in, its schedule is transcribed into
[`../../tests/shearwater_golden.json`](../../tests/shearwater_golden.json) and the
suite pins eko-deco against it.

**Don't reformat or "fix" anything in these folders.** They are the source. If a
number here disagrees with ours, the interesting question is *which of us is
wrong*, and that question is unanswerable once the source has been tidied.

## What we already have

Two Shearwater Predator on-unit plans, photographed 2026-08-07. **They do not
have folders here** — a capture that is pinned by a test belongs in the test.
Both live in [`../../tests/shearwater_golden.json`](../../tests/shearwater_golden.json):
the schedules as `SW Predator …` entries, and everything else the screens
printed (settings, gas quantities, CNS, and what the gas column settles) in the
`_predator_provenance` block beside them. The originals are in
`~/eko-deco-evidence/`.

| Dive | What it settled |
|---|---|
| 32 m / 40 min EAN32, GF 40/85, last stop 3 m | first evidence of the pass-through-stop and gas-switch divergences; CNS 38 % vs our 30.7 % |
| 32 m / 40 min EAN28, GF 5/50, last stop 3 m | bottom time **includes the descent**; rates are 10/10 m/min on a whole-minute grid; gas volumes use 1.000 bar + 10 m/bar; the switch happens **at a stop**, not at a MOD; CNS 51 % vs our 36.7 % — see DECISIONS #27 |

A third capture, a Shearwater **Perdix**, is in
[`../hermanice_dive`](../hermanice_dive): no test pins it yet, so it keeps its
folder until one does.

## The queue — plan these next

Six sheets, in priority order. Each names exactly what to set, what to
photograph, **and what eko-deco predicts before you plan it** — a prediction
written down in advance is a test; a comparison made afterwards is a fit.

| # | Folder | The one thing it changes | What it settles |
|---|---|---|---|
| 1 ⭐ | [`to_plan_1_cns_without_o2`](to_plan_1_cns_without_o2) | O₂ slot **off** | whether the whole CNS gap is the O₂ clock. Decisive, two minutes' work. |
| 2 | [`to_plan_2_last_stop_6m`](to_plan_2_last_stop_6m) | last stop **6 m** | the `last_stop_depth` rule, and the one CNS case where we predict *agreement* |
| 3 | [`to_plan_3_trimix_45m`](to_plan_3_trimix_45m) | 45 m on **21/35**, GF 30/80, last stop 6 m | helium — our thinnest cross-check — and it fills the only skipped test in the suite |
| 4 | [`to_plan_4_salinity`](to_plan_4_salinity) | salinity **Fresh**, twice | whether water type reaches Shearwater's *model* or only its display |
| 5 | [`to_plan_5_ndl_edge`](to_plan_5_ndl_edge) | 24 m, time 11 then 12 | the NDL convention — every dive we have compared so far is a deco dive |
| 6 | [`to_plan_6_gf_45_95`](to_plan_6_gf_45_95) | GF **45/95** | whether the pass-through divergence is really confined to low GF-Low |

Sheets 1, 2, 5 and 6 are the same 32 m dive with a single setting moved, on
purpose: one change at a time is what makes a difference *attributable*. Sheets
1 and 2 together are worth more than the other four combined.

**Opportunistic, no planning session needed:** the on-unit planner works from
your *current* tissue loading, so a plan made on the boat during a surface
interval is a **repetitive-dive** capture — the one thing in the model with no
external cross-check at all (DECISIONS #26). If you get the chance, shoot the
planner output plus the surface-interval time, and export dive 1 from
Shearwater Cloud so its real profile is on the record.

## How to shoot a case

1. Set the unit as the sheet says, **changing only what it names**.
2. Photograph, in this order: **Deco Setup** (GF + last stop) · **OC Gases**
   (every slot, including the off ones) · **Display/System Setup** (units,
   altitude, salinity if the unit has it) · ready-to-plan · **every** schedule
   page · gas usage · summary. Any filenames; they sort by time anyway.
3. Drop them in the folder. Note anything you had to change from the sheet.

**The photographs do not stay in the repo, and neither does the sheet once a
test pins it.** Each capture is transcribed — every screen, verbatim, including
whatever disagrees with us — into the golden fixture that asserts it
(`tests/shearwater_golden.json`: the schedule as an entry, the settings and the
printed totals as a provenance block). The originals move to
`~/eko-deco-evidence/`, and the folder here goes away.

Text is the evidence of record: it diffs, it greps, it survives a `git clone` on
a phone tether, and a transcription that had to be written screen by screen is
one somebody actually read. Photos are the *source*, not the *archive* — and a
folder restating what a test already asserts is a second copy that can drift
from it.

A setting we have to guess turns a scenario from evidence into an inference —
the difference between the two classes of fixture already in
`shearwater_golden.json` (`_scenario_provenance`, settings printed, versus
`_multideco_provenance`, settings inferred, the four we trust least).

Then it's mine: I transcribe, add the golden entry, and report where we agree
and where we don't.

A plain square air dive at GF 30/70 is the least useful thing to capture — we
already match MultiDeco and GFDECO on those to within a minute.

## Why the settings matter this much

The schedule is a function of every one of them. Two known traps:

- **Salinity.** Shearwater offers Fresh / EN13319 / Salt. EN13319 is the
  default and is *not* the same as our 10.0 msw/bar salt-water constant. Getting
  this wrong shifts every pressure in the plan and would look like a model
  disagreement. **Still open for the model.** What *is* settled is the display:
  every printed gas volume on the GF 5/50 Predator capture reconciles
  exactly at surface 1.000 bar and 10 m/bar, which is a display convention (as
  it is in MultiDeco) and says nothing about the tissue math.
- ~~**What "bottom time" counts.**~~ **Answered: it includes the descent.** The
  Predator's bottom row prints 3259 L where 40 min *at* 32 m would be 3360 —
  the 101 L deficit is a 3.2 min descent at 10 m/min inside the 40. Same
  convention as us, MultiDeco, GFDECO and Subsurface. That dive also pins the
  planner's descent **and** ascent rate at 10 m/min, and shows it working on a
  whole-minute grid (a 17 m ascent billed as 2 min).
