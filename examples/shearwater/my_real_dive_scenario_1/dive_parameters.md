# Scenario — Shearwater Predator, 32 m / 40 min on EAN32

Transcribed from nine photographs taken 2026-08-07. Every setting below was
**read off the unit**, not inferred.

> **The photographs are not in the repo.** Every value they carry is transcribed
> below, screen by screen; the originals are kept outside the tree
> (`~/eko-deco-evidence/shearwater/my_real_dive_scenario_1/`). Markdown is the
> evidence of record here — it diffs and greps, and 13 MB of JPEG does neither.
> The transcription is verbatim: a number that disagrees with ours is the
> finding, not a typo to fix.

## Source

| | |
|---|---|
| Planner | Shearwater **Predator**, on-unit dive planner (OC mode) |
| Screens | `194533` Deco Setup · `194543` OC Gases · `194551` Display Setup · `194618` planner entry · `194830` depth entry · `194845` ready-to-plan · `194852` schedule · `194858` gas usage · `194904` summary |

## Settings, as shown on the unit

| Setting | Value | Screen |
|---|---|---|
| Conserv. (GF) | **40 / 85** | Deco Setup |
| Last Stop | **3 m** | Deco Setup |
| Gas On/Off | Off | Deco Setup |
| OC Only | On | Deco Setup |
| Units | Meters | Display Setup |
| Altitude | **SeaLvl** | Display Setup |
| Start CNS | 0 % | ready-to-plan |
| RMV | **20 L/min** | planner header |

### OC gases

| Slot | Mix | Note |
|---|---|---|
| 1 | `99/00` | O₂ — Shearwater writes pure O₂ as 99 % |
| A2 | `50/00` | EAN50 (`A` = currently active) |
| 3 | `32/00` | EAN32 — the bottom gas |
| 4, 5 | `00/00` | unset |

**Not shown on any screen, so not established:** descent rate, ascent rate,
salinity setting, and the ppO₂ limits used for gas switching. The Predator's
planner does not display them here. Ascent 10 m/min is Shearwater's documented
default and is consistent with the runtimes below (see the reconciliation).

## Profile

| | Value |
|---|---|
| Bottom depth | 32 m |
| Time | 40 min |
| Bottom gas | EAN32 (`32/00`) |

**Whether the 40 min includes the descent is not established from the photos.**
The reconciliation below was run both ways; it does not change the conclusion.

## Result, as printed

```
Stp  Tme  Run   Gas    Qty
 32  bot   40  32/00  3259
  6  asc   43  32/00   174
  6    2   45  99/00    64
  3    5   50  99/00   130
```

| Gas usage (L) | |
|---|---|
| `99/00` | 194 |
| `50/00` | **0** — EAN50 was never breathed |
| `32/00` | 3433 |

| Summary | |
|---|---|
| Run | 50 min |
| Deco | 10 min |
| CNS | 38 % |

Note the `Tme` column is the **leg** — the difference of consecutive runtimes,
ascent included (43→45 = 2, 45→50 = 5). That is exactly `buhlmann.StopLeg.leg`,
so this schedule is directly comparable with ours without re-bookkeeping
(DECISIONS #17).

## Reconciliation with eko-deco

Planned at the same settings (GF 40/85, last stop 3 m, EAN32 bottom, EAN50 + 99 %
O₂ deco, ascent 10 m/min, sea level, RMV 20):

| | Predator | eko-deco |
|---|---|---|
| Stops | `6 m 2′@45` · `3 m 5′@50` | `12 m 1′@43` · `9 m 1′@44` · `6 m 2′@46` · `3 m 5′@51` |
| Deco / TTS | 10 min | 11.3 min |
| Run | 50 min | 51.3 min |
| EAN32 | 3433 L | 3394 L (−1.1 %) |
| O₂ | 194 L | 194 L (**exact**) |
| EAN50 | 0 L | 142 L |
| CNS | 38 % | 32.3 % |

**The decompression obligation is identical.** The 6 m and 3 m legs match
exactly — 2′ and 5′ — and the O₂ volume matches to the litre. Everything below
is a difference in *convention*, not in the model, with one exception.

1. **The 12 m and 9 m stops are Baker's runtime padding, not obligation.**
   They are 1.00 and 0.70 min — precisely what it takes to land the runtime on
   the next whole minute — and at both the GF-high ceiling was already clear of
   the next stop (3.86 m and 3.28 m against stops at 9 m and 6 m). This is the
   pass-through behaviour of DECISIONS #21, read off `gfdeco.f` and pinned to
   GFDECO to 0.00 min. Our GF-40 ceiling on leaving the bottom is 9.32 m, which
   rounds to a 12 m first stop; the Predator ascends straight to the first stop
   it will actually hold at. The two conventions cost 1.7 min of runtime here
   and agree on every minute that is genuinely owed.

2. **The EAN50 difference follows from that.** The Predator only switches gas
   *at a stop*, and its first stop is 6 m, where 99 % O₂ beats EAN50 — so EAN50
   is never the best gas anywhere and reads 0 L. We cross EAN50's 21 m switch
   depth during the ascent and take it there. Note this is not resolved by
   `--gas-switch at-first-stop` either: our first stop is 12 m, so that policy
   still picks up EAN50. What the Predator does is "switch only at stops",
   which is a third behaviour neither of our two policies expresses.

3. **CNS is the one genuine disagreement: 38 % against our 32.3 %, a 15 % gap.**
   That is outside the 10 % tolerance we hold ourselves to against the MultiDeco
   exports (`test_multideco_scenarios.TestOxygenToxicity`), so it is not
   explained by integration-step differences. Planning the dive with the 40 min
   read as time *at* depth rather than runtime moves us only to 33.6 %, so the
   bottom-time question does not account for it either. **Open — worth a proper
   look.** Whose CNS clock is right is not established by this one data point.
