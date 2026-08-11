# To plan 4 — salinity: fresh vs salt, same dive

The last open trap in [`../README.md`](../README.md). MultiDeco applies water
type to what it *displays* but not to its *model* (DECISIONS #15). Whether
Shearwater does the same has never been answerable. It is answerable with two
plans that differ in one dropdown.

**First check the unit has the setting at all.** Look in System / Display Setup
for `Salinity` (Fresh / EN13319 / Salt). Older Predator firmware may not offer
it — if it does not, say so and this sheet is closed as "not applicable", which
is itself worth recording.

## Set on the unit

Plan the dive **twice**, changing nothing but salinity:

| | Run A | Run B |
|---|---|---|
| Salinity | **as it is now** (note which) | **Fresh** |
| Conserv. (GF) | 5 / 50 | 5 / 50 |
| Last Stop | 3 m | 3 m |
| OC gases | `28/00`, `50/00`, `99/00` | same |
| Depth / Time / RMV | 32 / 40 / 20 | same |

Put the setting back afterwards.

## Shoot

The salinity screen for **each** run (this is the whole point — a plan without
its salinity screen proves nothing), plus schedule pages, gas usage and summary
for both.

## What we predict, written down first

Our fresh-water plan of this dive, at 10⅓ m/bar:

| | salt (10.0 m/bar) | fresh (10⅓ m/bar) |
|---|---|---|
| Stops | `18m 2′` `15m 2′` `12m 3′` `9m 4′` `6m 5′` `3m 10′` | `18m 2′` `15m 2′` `12m 2′` `9m 5′` `6m 5′` `3m 9′` |
| TTS | 26.3 min | 25.3 min |
| CNS | 36.7 % | 35.6 % |

So **if salinity reaches Shearwater's model**, run B should come out about a
minute shorter than run A and shuffle a minute between the 12 m and 9 m stops.

- **Both runs identical** → display-only, exactly like MultiDeco. Our
  `--water fresh` is then *more* than Shearwater does, and any future
  fresh-water comparison must be run at the salt constant or it will look like
  a model disagreement when it is not.
- **Run B ~1 min shorter** → it is in the model, and `--water fresh` is directly
  comparable. Also tells us which constant: 10⅓ m/bar (fresh) vs 9.9 (Salt) vs
  10.0 (EN13319) are separable from the printed gas volumes, since those
  reconcile exactly at 1.0 bar + 10 m/bar today.
