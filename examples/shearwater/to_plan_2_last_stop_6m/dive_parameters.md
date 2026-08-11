# To plan 2 — the same dive with **last stop 6 m**

Two answers for one plan: it pins `last_stop_depth` against a dive we already
have a 3 m twin of, and it is the case where the CNS hypothesis predicts we
**agree** — which is a harder test than predicting a gap.

## Set on the unit

As for the GF 5/50 Predator capture (`tests/shearwater_golden.json`,
`_predator_provenance`),
**change one thing**:

| Setting | Value | |
|---|---|---|
| Last Stop | **6 m** | ← the only change (Deco Setup) |
| Conserv. (GF) | 5 / 50 | unchanged |
| OC gases | `28/00`, `50/00`, `99/00` all on | unchanged |
| Depth / Time / RMV | 32 / 40 / 20 | unchanged |

**Put it back to 3 m afterwards** — every other sheet here assumes 3 m.

## Shoot

Deco Setup (showing `Last Stop 6 m`) · ready-to-plan · schedule pages · gas
usage · summary.

## What we predict, written down first

| | eko-deco |
|---|---|
| Stops | `18m 2′@42` `15m 2′@44` `12m 3′@47` `9m 4′@51` `6m 15′@66` |
| TTS / Run | 26.6 / 66.6 min |
| CNS | **54.8 %** |
| O₂ minutes | 15.3, **all of them at 6 m** |

The last stop absorbs what was 5′@6 m + 10′@3 m into a single 15′@6 m hang, so
the whole dive is ~the same length as the 3 m version — that alone is worth
having, because it says the `last_stop_depth` rule costs nothing here.

**The CNS prediction is the interesting half.** Our clock and the "Predator
charges O₂ at its switch-depth ppO₂" hypothesis both put every O₂ minute at
6 m, i.e. 2.0 %/min, so they cannot disagree:

- **Predator reads ≈ 53–55 %** → the hypothesis survives a test it could have
  failed. Combined with sheet 1 that is enough to change our O₂ clock with
  confidence.
- **Predator reads ≈ 40 % or ≈ 70 %** → the hypothesis is dead and the O₂ clock
  is something else entirely.
