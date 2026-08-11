# Hermanice — the training profile and the plan actually dived

Two plans for the same site, made in two different planners, plus the
hand-written card that fixes the printed format. Same role as
[`../scenario_1`](../scenario_1) and [`../shearwater`](../shearwater):
**primary evidence, kept verbatim.** Don't reformat or "fix" anything in the
three folders — if a number here disagrees with ours, the interesting question
is which of us is wrong, and that is unanswerable once the source is tidied.

| Folder | What |
|---|---|
| [`training_dive/`](training_dive) | MultiDeco 4.24 export — 32 m / 40 min on EAN32, **GF 5/50**, the deliberately over-conservative practice profile |
| [`actual_plan/`](actual_plan) | [`screens.md`](actual_plan/screens.md) — the Shearwater **Perdix** on-unit planner, photographed 2026-08-08, all five screens verbatim: 33 m / 40 min on EAN32, **GF 40/85**, last stop 3 m, RMV 20. Reconciled in § 2 below |
| [`runtime_convention/`](runtime_convention) | [`card.md`](runtime_convention/card.md) — the hand-written wetnotes card that transcribes [`../scenario_2`](../scenario_2): direction glyph, depth, leg minutes, `(runtime)`, triangles at the gas switches |

> **The photographs themselves are not in the repo.** Every value they carry is
> transcribed here and in [`runtime_convention/card.md`](runtime_convention/card.md),
> screen by screen, and the originals are kept outside the tree
> (`~/eko-deco-evidence/`). Markdown is the evidence of record: it diffs, it
> greps, and it does not cost 4 MB. Transcriptions are **verbatim** — if a
> number here disagrees with ours, that is the finding, not a typo to correct.

Both plans are printed as 90 × 64 mm cards by
[`../../cards/make_hermanice.py`](../../cards/make_hermanice.py), in the
convention the third folder fixes.

---

## 1. The training profile — MultiDeco, GF 5/50

Settings the export prints: ZHL16-C + GF, GF 5/50, `Wysokość = 150m (s)`
(fresh water — the same site and the same environment as `scenario_1|2`, and
the printed ppO₂/ead confirm it: EAN32 at 32 m is 1.31 and O₂ at 6 m is 1.58
only at surface **1.000 bar** with **10⅓ m/bar**), rates 8 / 9 m/min.

```
                            source        eko-deco
  first stop            21 m  3′@44             —
  18 m                   1′@45          2′@42
  15 m                   1′@46          1′@43
  12 m                   1′@47          2′@45
   9 m                   2′@49          3′@48
   6 m                   5′@54          4′@52
   3 m                   9′@63          9′@61
  run / TTS             63 / 23       61.3 / 21.3
  CNS                       39 %           37 %
  OTU                         92           86.5
```

Reproduced with

```bash
deco plan --depth 32 --time 40 --gas 32@24@220 --deco-gas 50@11.3@130 \
  --deco-gas 100@11.3@130 --gf-low 0.05 --gf-high 0.50 \
  --descent-rate 8 --ascent-rate 9 --water fresh --surface-p 1.0 --sac 20
```

**Below 21 m the two schedules are the same dive**: 3 m of stop time apart in
total, distributed differently because MultiDeco has already off-gassed for
2:47 at 21 m before it gets there. CNS and OTU agree to within 6 % (37.1 vs
38.9 and 86.5 vs 92), inside the 10 % this repo holds itself to against
MultiDeco (`test_multideco_scenarios.TestPrintedTotals`).

### The 21 m stop is a switch stop, put there on purpose

**Settled, by the diver: the instructor added the 21 m stop explicitly, so the
gas change happens without rush.** It is a training decision, not an
obligation and not a model difference — which is why nothing in this repo
should try to reproduce it.

Worth recording how far the export alone got, because the same reasoning will
come up on the next export that surprises us. Our GF-5 ceiling on leaving the
bottom is **16.29 m**, rounding to an 18 m first stop; MultiDeco holds 2:47 at
21 m, and 2:47 is exactly the pad that lands the runtime on a whole minute
(41.22 → 44.0), so it was a stop the plan *chose*. The tell that it could not be
the model was the same planner's own EAN28 export at identical settings:

| Export, same site / GF 5/50 / 32 m / 40 min | bottom mix | MultiDeco 1st stop | our GF-5 ceiling |
|---|---|---|---|
| [`../scenario_2`](../scenario_2) | EAN28 | 18 m (0:27 — pure padding) | 17.88 m → 18 m |
| `training_dive/` | EAN32 | **21 m (2:47)** | 16.29 m → 18 m |

EAN32 loads *less* nitrogen than EAN28 over the same profile, so its first stop
cannot be deeper on the same model with the same settings. Ours moves the right
way (17.88 → 16.29 m); MultiDeco's moves the wrong way, so the stop had to come
from outside the model — and 21 m is exactly where EAN50 becomes breathable
(MOD 22.7 m at ppO₂ 1.6, snapped to the 3 m grid). A deliberate switch stop is
precisely what that shape means.

**Everything below 21 m is then a like-for-like comparison**, and it agrees:
3 min of stop time apart in total, no stop out of place.

---

## 2. The plan actually dived — Shearwater Perdix, GF 40/85

Read off the screens: OC, 33 m, 40 min, RMV 20, GF **40/85**, last stop 3 m,
start CNS 0 %. Gases `32/00`, `50/00`, `99/00`.

| Screen | What it shows |
|---|---|
| `201550` | ready-to-plan — `OC · DEPTH 033 · TIME 040 · RMV 20`, `GF: 40/85`, `Last Stop: 3m`, `Start CNS: 0%` |
| `201628` | schedule 1/2 — the `Stp Tme Run Gas Qty` header and the first five rows |
| `201636` | schedule 2/2 — the `3 5 53 99/00 127` row alone |
| `201642` | `Gas Usage. in Liters` — `99/00: 221`, `50/00: 96`, `32/00: 3361` |
| `201651` | `OC Summary` — `Run: 53 minutes`, `Deco: 13 minutes`, `CNS: 31 %` |

**No Deco Setup, OC Gases or Display Setup page was photographed**, which is why
the descent rate, the ppO₂ switch limits, the salinity setting and the altitude
setting are not readable off the screens. The environment was recovered from the
gas column and later confirmed by the diver; the descent rate was not, and is
still fitted (below).

```
Stp  Tme  Run   Gas    Qty          Gas usage (L)     Summary
 33  bot   40  32/00  3275          99/00     221     Run   53 min
 21  asc   42  32/00    86          50/00      96     Deco  13 min
  9  asc   44  50/00    59          32/00    3361     CNS    31 %
  9    1   45  50/00    37
  6    3   48  99/00    94
  3    5   53  99/00   127
```

The per-row `Qty` sums to the per-gas totals exactly (3275 + 86 = 3361;
59 + 37 = 96; 94 + 127 = 221), so the whole gas column is internally consistent.

### This Perdix switches gas at the MOD — and the Predator does not

Read the two `asc` rows again. The 33 → 21 m ascent is billed to `32/00`; the
21 → 9 m ascent is billed to **`50/00`**. So the switch to EAN50 happened at
**21 m** — and 21 m is not a stop: its `Tme` is `asc`, nothing is held there. The
row exists *only* to change gas. 21 m is exactly EAN50's MOD (22.7 m at ppO₂ 1.6
in this environment) snapped down to the 3 m grid.

That is **at-MOD behaviour — our default policy**, and it directly qualifies
what the two Predator plans in [`../shearwater`](../shearwater) showed. On the
Predator's own EAN28 GF 5/50 plan the ascent row reads `15 asc 42 28/00 134`:
the whole 32 → 15 m ascent on the bottom gas, no break at EAN50's 21 m MOD, the
switch happening only at 15 m, the first stop it holds. Same brand, same gas,
opposite convention:

| Unit | EAN50 MOD → grid | Ascent rows | Switched at |
|---|---|---|---|
| Predator (`../shearwater/my_conservative_deco_training_dive`) | 21 m | `15 asc … 28/00` — one row, straight through 21 m | **15 m**, the first held stop |
| Perdix (here) | 21 m | `21 asc … 32/00` then `9 asc … 50/00` — broken at 21 m | **21 m**, the MOD |

**So "Shearwater switches at a stop" is a statement about the Predator, not
about Shearwater.** DECISIONS #27 is written that way for this reason. Which of
the two is a firmware generation, a menu setting neither screen shows, or a
model difference is **not established** — and it is not a difference we need to
resolve to plan a dive, because at-MOD is already our default and it is the one
the newer unit agrees with. It does mean neither of our policies is *wrong*;
they are each right about a different Shearwater.

Note this is a **gas-accounting** difference, not a schedule difference: the
obligation is unaffected, only which cylinder is billed for 12 m of ascent.

### The environment: fresh water at 267 m — **stated**, and the gas column found it first

The unit's altitude and salinity are on no screen photographed here, so they
were backed out of the six printed `Qty` values before being confirmed. Both
numbers are recorded because a method that was checked against a known answer
is worth more than either fact on its own.

Charging every stop leg at its stop depth and every ascent leg at its mean depth
over the real transit time (10 m/min), at RMV 20, the only environments that
reproduce all six printed integers exactly were

> **surface 0.980–0.984 bar · 10.29–10.31 m/bar**

**The diver then confirmed it: fresh water, 267 m above sea level at the time of
the plan.** That is surface **0.9816 bar** on the standard atmosphere and
10⅓ m/bar — inside the fitted box on both axes. At sea level the same arithmetic
overshoots every row by 2–3 %, so "not sea level" was never marginal.

With the environment **stated** rather than fitted, and nothing else tuned, the
five deco and ascent rows come out at:

| Row | computed | printed | Δ |
|---|---|---|---|
| 33 → 21 m ascent | 86.3 L | 86 | +0.3 |
| 21 → 9 m ascent | 58.4 L | 59 | −0.6 |
| 9 m, 1 min | 37.1 L | 37 | +0.1 |
| 6 m, 3 min | 93.7 L | 94 | −0.3 |
| 3 m, 5 min | 127.2 L | 127 | +0.2 |

Two conventions follow from that, and one number is left over:

1. **Ascent rate 10 m/min**, from the two `asc` rows — both are 1.2 min of
   transit, to the litre.
2. **Stop legs are billed at the stop depth for the whole leg.** This Perdix
   does *not* use the convention the Predator in
   [`../shearwater/my_conservative_deco_training_dive`](../shearwater/my_conservative_deco_training_dive)
   used (whole-minute legs at mean depth), which would put the 21 → 9 ascent at
   2 min × mean depth = 148 L against the 59 L printed.
3. **The descent rate is the one free parameter left, and it is ~16 m/min.**
   With the environment fixed, the bottom row's 3275 L needs a **2.0 min**
   descent inside the 40 (16.2 m/min gives 3274.2 L). **10 m/min is excluded**:
   it takes 3.3 min and prints 3234 L, 40 L short — and 10 m/min is exactly what
   the Predator's bottom row pinned in the other folder. No Shearwater document
   states 16 m/min, so this is a fitted *setting*, labelled as such: it is the
   only number below that is not either printed or stated.

### Reconciliation with eko-deco

```bash
deco plan --depth 33 --time 40 --gas 32@24@220 --deco-gas 50@11.3@130 \
  --deco-gas 100@11.3@130 --gf-low 0.40 --gf-high 0.85 \
  --descent-rate 16.2 --ascent-rate 10 --water fresh --altitude 267 --sac 20
```

| | Perdix | eko-deco |
|---|---|---|
| Stops (leg′@run) | `9m 1′@45` `6m 3′@48` `3m 5′@53` | `12m 3′@43` `9m 1′@44` `6m 2′@46` `3m 5′@51` |
| Deco / TTS | 13 min | 11.3 min |
| Run | 53 min | 51.3 min |
| EAN32 | 3361 L | 3361.3 L |
| EAN50 | 96 L | 133 L |
| O₂ | 221 L | 188 L |
| CNS | 31 % | 30.6 % |

The EAN32 total agreeing to the litre is **not** independent evidence — the
descent rate was fitted to that very row, so the match is partly by
construction. What *is* independent is the ±0.6 L on the five rows above, at an
environment nobody tuned. The schedule difference is the familiar pair:

1. **The whole-minute runtime grid.** The Perdix spends 4 min of runtime
   (40 → 44) on 2.4 min of ascent, because each transit is billed a whole
   minute. That is 1.6 of the 1.7 min the two runs differ by. Same finding as
   the Predator dives in [`../shearwater`](../shearwater).
2. **Pass-through stops.** Our 12 m stop is 0.9 min of Baker padding
   (DECISIONS #21); the Perdix ascends straight to 9 m, the first depth it will
   hold at. It then holds 3 min at 6 m where we hold 2 — so the obligation ends
   up in the same place, one stop shallower.

**CNS agrees to half a point (31 % against 30.6 %)** — worth recording, because
the two Predator plans in [`../shearwater`](../shearwater) disagree with us by
+7 and +14 points, and the hypothesis there was that the Predator charges O₂ at
its switch-depth ppO₂ for the whole time it is breathed. This dive breathes O₂
for 8 min against their 7 and 15, so it does not discriminate on its own; but a
Perdix agreeing where a Predator did not is a firmware/model question worth the
[`../shearwater/to_plan_1_cns_without_o2`](../shearwater/to_plan_1_cns_without_o2)
sheet, which is still the decisive experiment.

---

## 3. Provenance, and the one thing still open

Both of the questions this folder opened were closed by the diver, not by
inference — which is the good outcome, and the reason to write predictions down
first:

| Question | Answer | How |
|---|---|---|
| Why does MultiDeco stop 2:47 at 21 m? | A **switch stop the instructor added**, so the gas change is unhurried. Not an obligation; nothing here should reproduce it. | Stated |
| What environment was the Perdix in? | **Fresh water, 267 m** (surface 0.9816 bar). | Stated — and inside the 0.980–0.984 bar / 10.29–10.31 m/bar box the printed gas column had already fitted |

That makes the Perdix schedule `_scenario_provenance` material rather than
`_multideco_provenance` (settings stated, not inferred — the distinction drawn
in [`../../tests/shearwater_golden.json`](../../tests/shearwater_golden.json))
with one caveat: the ppO₂ switch limits and the **descent rate** are still not
printed anywhere, and the descent rate had to be fitted to ~16 m/min.

**Still open**, and both would be settled by the same photographs:

1. **Why the descent is ~16 m/min here** when the Predator's own bottom row
   pinned 10 m/min. Two things would settle it — the unit's Deco Setup /
   planner pages photographed, or one more Perdix plan at a different depth,
   where a fixed *rate* and a fixed *descent time* stop being interchangeable.
2. **Why this Perdix switches gas at the MOD and the Predator switches at a
   stop** (§ 2 above). A Deco Setup page from each unit would show whether this
   is a setting at all. Until then it is recorded as a divergence between two
   units, not as a fact about Shearwater — the distinction DECISIONS #27 turns
   on.
