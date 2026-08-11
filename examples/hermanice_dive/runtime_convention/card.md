# The hand-written runtime card — the printed format, fixed by hand

Transcription of a hand-written wetnotes card photographed 2026-08-05
(`IMG-20260805-WA0006.jpg`, since moved out of the repo — see
[`../README.md`](../README.md) § Provenance). It is a **by-hand transcription of
the MultiDeco 4.24 export in [`../../scenario_2`](../../scenario_2)**: 32 m /
40 min on EAN28, GF 5/50, fresh water at 150 m.

This card is the reference for the printed runtime convention that
[`../../../cards/make_hermanice.py`](../../../cards/make_hermanice.py) renders.
It is evidence of **how a diver actually writes a schedule down**, which is a
different question from how a planner prints one.

## The card, as written

Ruled graph paper, one vertical rule down the left. Column header `RT` over the
third column. Filled triangles (`▼`) in the right margin against two rows.

```
                    RT
    ↓   32     4    (4)
    —   32    36   (40)
    ↑   21     1   (41)
    ↑   18     1   (41)   ▼
    —   18     1   (42)
    —   15     2   (44)
    —   12     2   (46)
    —    9     5   (51)
    —    6     5   (56)   ▼
    —    3    10   (66)
```

## The convention

| Element | Meaning |
|---|---|
| `↓` | descent — transit **down** to that depth |
| `↑` | ascent — transit **up** to that depth |
| `—` | level — time **held** at that depth (bottom or stop) |
| col 1 | depth, m |
| col 2 | **leg** minutes: time on that row, transit included |
| col 3 | `RT` — cumulative **runtime in brackets**, the time you LEAVE that depth |
| `▼` | a **gas switch** happens on this row |

Three things this fixes, and they are the reason the folder exists:

1. **The runtime is bracketed and the leg is not.** Two numeric columns that
   could be confused are made unconfusable by punctuation rather than by a
   header — on a wetnotes card there is no room for headers.
2. **Every row carries a direction glyph**, so a transit row and a held row are
   distinguishable at a glance underwater. This is the part a printed planner
   export does *not* give you: MultiDeco says `Wynurz.do` / `Przyst. na` in
   words, which does not survive being copied onto a slate.
3. **The gas switch is a margin mark, not a row.** The switch is an annotation
   against the row it happens on — it is not measured from, and it does not get
   its own line. Same rule as `buhlmann.StopLeg` and DECISIONS #17.

## Reconciliation with the source export

Every row matches [`../../scenario_2/data.txt`](../../scenario_2/data.txt)
exactly, including the two rows that share runtime `(41)`:

| Card row | `data.txt` row |
|---|---|
| `↓ 32 4 (4)` | `Zanurz. do 32m (4) Nitrox 28` |
| `— 32 36 (40)` | `Poziom 32m 35:59 (40) Nitrox 28` |
| `↑ 21 1 (41)` | `Wynurz.do 21m (41) Nitrox 28` |
| `↑ 18 1 (41) ▼` | `Wynurz.do 18m (41) **Nitrox 50**` ← the switch |
| `— 18 1 (42)` | `Przyst. na 18m 0:27 (42) Nitrox 50` |
| `— 15 2 (44)` | `Przyst. na 15m 2:00 (44) Nitrox 50` |
| `— 12 2 (46)` | `Przyst. na 12m 2:00 (46) Nitrox 50` |
| `— 9 5 (51)` | `Przyst. na 9m 5:00 (51) Nitrox 50` |
| `— 6 5 (56) ▼` | `Przyst. na 6m 5:00 (56) **Oxygen**` ← the switch |
| `— 3 10 (66)` | `Przyst. na 3m 10:00 (66) Oxygen` |

Two details worth keeping:

- **The two `(41)` rows are correct, not a slip.** The export really does print
  `(41)` twice — the 21 → 18 m transit is under a minute, so the truncated
  runtime does not advance. The diver copied it faithfully rather than
  "fixing" it, which is the right instinct and the same one this repo applies
  to the exports themselves.
- **`36` against the export's `35:59`, and `1` against `0:27`.** The card rounds
  legs to whole minutes; the runtime column is what stays exact. That is the
  same priority `report.runtime_min` encodes — the runtime is the number you
  act on, the leg is the number you sanity-check it with.
