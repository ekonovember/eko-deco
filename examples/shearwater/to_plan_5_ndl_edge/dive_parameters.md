# To plan 5 — the no-deco edge

Cheapest sheet here: two plans, one number. It pins **where the NDL sits**, i.e.
that the no-stop limit is taken at GF-High and that the descent counts as
bottom time — both of which we assert everywhere and have never checked against
a real unit.

Everything we have compared so far is a deco dive. If our NDL convention is off
by a minute, none of those plans would show it.

## Set on the unit

No settings change at all — your current state, only the planner numbers move:

| Setting | Value |
|---|---|
| Conserv. (GF) | 5 / 50 (unchanged) |
| Last Stop | 3 m |
| OC gases | `28/00` (deco gases may stay on; they will not be used) |
| Depth | **24 m** |
| RMV | 20 |

Plan it at **Time = 11**, then again at **Time = 12**. If 11 already shows a
stop, walk down (10, 9, …) until it does not; if 12 shows none, walk up. What we
want is the **largest time with no deco stop** and the first time that has one.

## Shoot

Ready-to-plan and the schedule/summary for the last clean run and the first
deco run. Both, or the edge is not pinned.

## What we predict, written down first

At GF 5/50, 24 m on EAN28, descent counted inside the time:

| | eko-deco |
|---|---|
| Last no-stop runtime | **11 min** |
| First deco runtime | **12 min** → `9m 0.5′` `6m 0.7′` `3m 0.7′`, TTS 4.3 |

- **Edge at 11/12** → our NDL convention matches a real Shearwater. Done.
- **Edge 2–3 min later** (13/14) → the Predator's bottom time may not include
  the descent after all on a short dive, or its NDL is taken somewhere other
  than GF-High. Both are worth knowing and both are invisible on a 40 min dive.

If you would rather do this at 30 m, our edge there is **7 min clean / 8 min
first stop** — same test, shorter plans.
