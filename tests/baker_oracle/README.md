# Erik Baker's GFDECO (test-only oracle)

`gfdeco.f` is Erik C. Baker's original **Gradient Factor Decompression Program
in FORTRAN** — the published reference implementation that defined the GF
convention used by Shearwater, MultiDeco/V-Planner and most technical dive
computers: GF-low anchored at the **rounded first stop**, a **static** linear
slope to GF-high at the surface, Schreiner-equation ramps, whole-minute stops.

License: **"DISTRIBUTE FREELY - CREDIT THE AUTHOR"** (see LICENSE). Credit:
Erik C. Baker. Source mirrored from https://github.com/hsorbo/gfdeco
(unmodified).

Model specifics of Baker's program (differ from eko-deco defaults — the
cross-check patches eko-deco to match for the comparison):

* **ZH-L16B** nitrogen a-coefficients (eko-deco uses ZH-L16C)
* water vapour pressure **0.567 msw = 0.0567 bar** (respiratory quotient 0.9;
  eko-deco uses Buhlmann's 0.0627)
* everything else matches eko-deco defaults: initial saturation
  `(P_surf − P_H2O) × 0.79`, sea-level barometric 10.1325 msw
  (= 1.01325 bar with 10 msw/bar), Schreiner ramps, 3 m stops.

```
./build.sh    →  ./gfdeco      (needs gfortran; binary is gitignored)
```

Used only by `tests/test_baker_crosscheck.py` via `tests/baker_deco.py`,
which generates `GFDECO.IN`/`GFDECO.SET` in a temp dir and parses
`GFDECO.OUT`. The test module skips itself when gfortran is unavailable.
