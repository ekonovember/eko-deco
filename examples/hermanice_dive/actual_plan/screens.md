# Perdix on-unit planner — the five screens, verbatim

Shearwater **Perdix**, OC dive planner, photographed 2026-08-08. The dive
actually made at Hermanice: 33 m / 40 min on EAN32, GF 40/85.

The photographs are kept outside the repo
(`~/eko-deco-evidence/hermanice_dive/actual_plan/`); this file is the evidence of
record. Transcribed **verbatim**, including the layout — a value that disagrees
with eko-deco is a finding, not a typo to fix. The reconciliation and what the
numbers settle are in [`../README.md`](../README.md) § 2.

Every screen carries the same header band:

```
OC   DEPTH  TIME  RMV
     033    040    20
```

## `201550` — ready to plan

```
OC   DEPTH  TIME  RMV
     033    040    20
─────────────────────────
Ready to Plan Dive
GF:              40/85
Last Stop:          3m
Start CNS:          0%
─────────────────────────
Exit                Plan
```

## `201628` — schedule, page 1 of 2

```
Stp  Tme  Run   Gas    Qty
 33  bot   40  32/00  3275
 21  asc   42  32/00    86
  9  asc   44  50/00    59
  9    1   45  50/00    37
  6    3   48  99/00    94
─────────────────────────
Exit                Next
```

## `201636` — schedule, page 2 of 2

```
Stp  Tme  Run   Gas    Qty
  3    5   53  99/00   127
─────────────────────────
Exit                Next
```

## `201642` — gas usage

```
Gas Usage. in Liters
99/00:    221
50/00:     96
32/00:   3361
─────────────────────────
Exit                Next
```

## `201651` — summary

```
OC Summary
 Run:    53 minutes
 Deco:   13 minutes
 CNS:    31 %
─────────────────────────
Exit                Done
```

## What is *not* on these screens

No **Deco Setup**, **OC Gases** or **Display/System Setup** page was
photographed. So the following are **not** readable off the unit and must not be
quoted as if they were:

| Not shown | Status |
|---|---|
| Salinity | Recovered from the gas column, then **confirmed by the diver**: fresh water |
| Altitude | Same: **267 m** (surface 0.9816 bar) |
| Descent rate | **Fitted, ~16 m/min**, and still open — the Predator's own bottom row pinned 10 m/min |
| Ascent rate | 10 m/min, from the two `asc` rows (1.2 min of transit each, to the litre) |
| ppO₂ switch limits | Not established |
| Last stop | 3 m — this one *is* printed, on `201550` |

The gas slots are likewise not photographed, but all three mixes appear in the
schedule and gas-usage screens (`32/00`, `50/00`, `99/00`), so the stack is
established even though the menu page is not.

## The one thing to read off the `Gas` column

`21 asc 42 32/00` followed by `9 asc 44 50/00`: the switch to EAN50 happens at
**21 m**, a depth held for zero minutes — the row exists only to change gas, and
21 m is EAN50's MOD snapped to the 3 m grid. That is **at-MOD** behaviour, which
is *not* what the Predator does on a neighbouring dive. See
[`../README.md`](../README.md) § 2 and DECISIONS #27.
