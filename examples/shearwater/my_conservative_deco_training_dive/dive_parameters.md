# Scenario — Shearwater Predator, 32 m / 40 min on EAN28, GF 5/50

Transcribed from the seven photos in this folder (2026-08-07). The conservative
training profile: an extreme GF-Low deliberately chosen to stress the deep end
of the GF line. Same depth/time/RMV as
[`../my_real_dive_scenario_1`](../my_real_dive_scenario_1) and as the MultiDeco
export in [`../../scenario_2`](../../scenario_2), so the three are directly
comparable.

## Source

| | |
|---|---|
| Planner | Shearwater **Predator**, on-unit dive planner (OC mode) |
| Screens | `221032` main display at the surface on EAN50 · `221053` depth entry · `221114` ready-to-plan · `221120` schedule 1/2 · `221129` schedule 2/2 · `221134` gas usage · `221141` summary |

> **The photographs are not in the repo.** Every value they carry is transcribed
> here, screen by screen; the originals are the unmodified contents of the phone
> export (`Photos-1-001.zip`, unpacked byte-identical) and are kept outside the
> tree (`~/eko-deco-evidence/shearwater/my_conservative_deco_training_dive/`).
> Markdown is the evidence of record — verbatim, and a number that disagrees
> with ours is the finding, not a typo to fix.

## Settings, as shown on the unit

| Setting | Value | Screen |
|---|---|---|
| Conserv. (GF) | **5 / 50** | main display (`Conserv. 05/50`) **and** ready-to-plan (`GF: 5/50`) |
| Start CNS | 0 % | ready-to-plan |
| Bottom depth | **32 m** | planner header (`032`) |
| Bottom time | **40 min** | planner header (`040`) |
| RMV | **20 L/min** | planner header |
| Mode | OC | planner header |

The surface screen also reads `GasPO2 .50` at depth `.0` with EAN50 selected —
ppO₂ 0.50 at the surface, i.e. the unit's surface pressure is **1.00 bar to two
decimals**, not 1.013.

**Not shown on any screen:** last-stop depth, salinity, descent/ascent rates,
ppO₂ switch limits. Three of those are recovered from the numbers below;
salinity is not.

## Result, as printed

```
Stp  Tme  Run   Gas    Qty
 32  bot   40  28/00  3259
 15  asc   42  28/00   134
 15    1   43  50/00    50
 12    3   46  50/00   132
  9    4   50  50/00   152
  6    5   55  99/00   160
  3   10   65  99/00   260
```

| Gas usage (L) | |
|---|---|
| `99/00` | 420 |
| `50/00` | 334 |
| `28/00` | 3393 |

| Summary | |
|---|---|
| Run | 65 min |
| Deco | 25 min |
| CNS | **51 %** |

`Tme` is the **leg** (runtime difference, travel to the stop included) — the
same quantity as `buhlmann.StopLeg.leg`, DECISIONS #17.

## What the gas column pins down

Every `Qty` is reproduced exactly by `RMV × minutes × (1.0 + depth/10)`, with
the *stop* legs charged at the stop depth for the whole leg and the *ascent* leg
charged at its average depth over a whole number of minutes:

| Row | Check | Printed |
|---|---|---|
| 3 m, 10 min | 20 × 10 × 1.3 | 260 ✓ |
| 6 m, 5 min | 20 × 5 × 1.6 | 160 ✓ |
| 9 m, 4 min | 20 × 4 × 1.9 | 152 ✓ |
| 12 m, 3 min | 20 × 3 × 2.2 | 132 ✓ |
| 15 m, 1 min | 20 × 1 × 2.5 | 50 ✓ |
| ascent 32→15, run 40→42 | 20 × 2 × 3.35 | 134 ✓ |
| bottom, 40 min incl. 3.2 min descent @ 10 m/min | 20 × (2.6×3.2 + 4.2×36.8) | 3258 vs 3259 |

Three things follow, and they answer two of the open questions in
[`../README.md`](../README.md):

1. **The gas arithmetic uses surface 1.000 bar and exactly 10 m/bar.** Whether
   the *model* uses the same is still not established — this is a display
   convention, as it is in MultiDeco.
2. **Bottom time includes the descent.** 3259 L is 101 L short of 40 min at
   32 m; that deficit is a 3.2 min descent at 10 m/min inside the 40. Read as
   time *at* depth the row would print 3360. Same convention as ours, MultiDeco,
   GFDECO and Subsurface.
3. **Descent and ascent are 10 m/min, and the planner works on a whole-minute
   grid** — the 17 m ascent is billed as 2 min (1.7 rounded up), which is also
   why `Run` steps 40 → 42.

## Reconciliation with eko-deco

```
deco plan --depth 32 --time 40 --gas ean28 --deco-gas 50 --deco-gas 99 \
          --gf-low 0.05 --gf-high 0.50 --sac 20 --descent-rate 10 --planner shearwater
```

| | Predator | eko-deco |
|---|---|---|
| Stops (leg′@run) | `15m 1′@43` `12m 3′@46` `9m 4′@50` `6m 5′@55` `3m 10′@65` | `18m 2′@42` `15m 2′@44` `12m 3′@47` `9m 4′@51` `6m 5′@56` `3m 10′@66` |
| Deco / TTS | 25 min | 26.3 min |
| Run | 65 min | 66.3 min |
| EAN28 | 3393 L | 3349 L |
| EAN50 | 334 L | 451 L |
| O₂ (99 %) | 420 L | 422 L |
| CNS | 51 % | 38 % |

**The obligation below 15 m is identical** — 3′, 4′, 5′, 10′ at 12/9/6/3 m,
minute for minute, and the O₂ volume matches to 2 L. Everything else is one of
three things.

### 1. Pass-through stops — worth 1 min, and this is the profile that shows them

Our GF-5 ceiling on leaving the bottom is **17.98 m** at surface 1.01325 bar and
**18.03 m** at 1.000 — so the first stop lands on 18 m or 21 m depending on
13 mbar of surface pressure, which is worth knowing on its own: at GF-Low 5 the
first-stop depth is on a knife edge. The Predator ascends straight through both
to 15 m, the first depth it will actually hold at.

Replaying our own tissue model on a 1-minute grid with the GF line anchored at
21 m and no pass-through stops reproduces the Predator's schedule **exactly** —
`15m 1′` `12m 3′` `9m 4′` `6m 5′` `3m 10′`, run 65.9 → 65, deco 25.9 → 25,
SurfGF 48 %.

So the GF line, the tissue model and the stop grid all agree; only the
pass-through rule differs. Same finding as
[`../my_real_dive_scenario_1`](../my_real_dive_scenario_1), but this is the
sharper case: at GF-Low 5 the ceiling relaxes *faster than the diver ascends*
(17.0 m by the time you reach 15 m, still above the stop you are standing on),
so the pass-through stops at 21 m and 18 m are pure padding. DECISIONS #21 and
`gfdeco.f` are why we hold them; the Predator does not.

### 2. The gas switch happens at the first stop, not at the MOD

EAN50's MOD is 21.9 m at ppO₂ 1.6. The Predator stays on EAN28 down to **15 m**
— visible in the `28/00 134` ascent row, which covers the whole 32 → 15 m
ascent. This is the discriminating shape the README asks for, and it says
Shearwater switches **at a stop**, not on passing the MOD.

That is the whole EAN28/EAN50 volume difference: we take EAN50 at 21 m, so we
bill 11 m of the ascent to it that the Predator bills to the bottom gas.

Note this contradicts the `--gas-switch` help text in `cli.py`, which claims
`at-mod` is "what MultiDeco and Shearwater do". On this evidence Shearwater does
not. `at-first-stop` is closer but not the same rule — our first stop is a
pass-through at 21 m, so that policy switches at 21 m too, and it also costs an
extra minute at 9 m. "Switch only at a stop the diver actually holds" is a third
behaviour neither policy expresses (the same conclusion `my_real_dive_scenario_1`
reached from the other direction).

### 3. CNS: 51 % against our 38 % — and the gap is entirely the O₂ clock

Two Predator plans from the same day now disagree with us on CNS in the same
direction, and together they localise it. Splitting our own clock by gas:

| | O₂ minutes | our non-O₂ CNS | our O₂ CNS | our total | Predator |
|---|---|---|---|---|---|
| `my_real_dive_scenario_1` (EAN32, GF 40/85) | 2′@6 m + 5′@3 m | 23.98 % | 6.73 % | 30.7 % | 38 % |
| this dive (EAN28, GF 5/50) | 5′@6 m + 10′@3 m | 21.20 % | 15.45 % | 36.7 % | 51 % |

The gap is +7.3 and +14.3 points for 7 and 15 minutes of O₂ — **+0.98 points per
O₂ minute in both dives**. Charging O₂ at a flat **2.0 %/min** and leaving
everything else at our own rates reproduces both totals to the displayed
integer (38.0 and 51.2). 2.0 %/min is exactly the NOAA-interpolated rate at
ppO₂ 1.584 — the 6 m stop — so the Predator appears to charge O₂ at its
**switch-depth ppO₂ for the whole time it is breathed**, where we integrate at
the actual depth (183 min limit at 3 m, i.e. 0.55 %/min, ~4× slower).

Solving the two dives for a per-depth O₂ rate instead gives 1.75 %/min at 6 m
(limit 57 min) and 2.11 %/min at 3 m (limit 47 min) — i.e. the Predator's 3 m
O₂ rate is nowhere near NOAA's 1.3-bar row, which is the thing to explain.

**Not resolved from two data points.** The decisive experiment is one plan with
**no O₂ at all** (EAN50 as the shallowest deco gas): if the CNS then matches
ours, the whole disagreement is the O₂ clock and nothing else. A second useful
one is the same dive with **last stop 6 m**, which changes the O₂ depth mix
without changing the switch depth.
