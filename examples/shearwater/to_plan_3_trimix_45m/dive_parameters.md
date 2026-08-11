# To plan 3 — trimix 45 m, GF 30/80, last stop 6 m

**Fills the only skipped test in the suite** and pins the helium side of the
model, which is our thinnest ice: nitrogen is cross-checked four ways, helium
is not, and the Python oracles disagree three-to-one on slow-compartment helium
`a` (DECISIONS #22). `tests/shearwater_golden.json` has been carrying an
unfilled fixture for exactly this dive since before any of these photos existed.

## Set on the unit

This is a different dive, so more changes than the other sheets:

| Setting | Value |
|---|---|
| Conserv. (GF) | **30 / 80** |
| Last Stop | **6 m** |
| OC gases | `21/35` (trimix), `50/00`, `99/00` |
| Depth / Time / RMV | **45 / 25 / 20** |
| Start CNS | 0 % |

If the unit refuses any of it, **change the sheet, not the plan** — I will
follow what you actually planned. A 45 m trimix plan at some other GF is still
worth far more than no helium data at all.

## Shoot

Deco Setup · OC Gases (the trimix slot, so the He fraction is on the record) ·
ready-to-plan · every schedule page · gas usage · summary.

## What we predict, written down first

| | eko-deco |
|---|---|
| Stops | `24m 3′@28` `21m 1′@29` `18m 1′@30` `15m 1′@31` `12m 1′@32` `9m 3′@35` `6m 13′@48` |
| TTS / Run | 23.6 / 48.6 min |
| CNS | 42.8 % (13.3 O₂ minutes → ~41 % under the O₂-clock hypothesis) |

Three things to watch:

1. **The deep stops.** Ours are 1-minute pass-throughs at 21/18/15/12 m. If the
   Predator holds at 24 m and then goes straight to 9 m, that is the same
   divergence as DECISIONS #27 showing up at an ordinary GF-Low — which would
   mean it is not a low-GF curiosity at all, and matters much more.
2. **The gas switch.** EAN50's MOD is 21.9 m and there *is* a stop at 21 m here,
   so at-MOD and switch-at-a-stop coincide — the gas column should read `50/00`
   from 21 m in both. If it reads `21/35` down to 18 m, there is a third rule we
   have not found yet.
3. **The total.** If TTS matches within a minute on a 35 % helium mix, our
   helium half-times and coefficients are doing the right thing at 45 m. That
   is currently unevidenced by anything outside the Python oracles.
