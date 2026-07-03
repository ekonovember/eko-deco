---
applyTo: "**/*.py"
---

# Python conventions — deco

- Target Python 3.10+ (verified on 3.14).
- **Keep `buhlmann.py`, `cli.py`, `ratio_deco.py` dependency-free** (stdlib only).
  Only `app.py` may import `matplotlib` / `tkinter`.
- Use `from __future__ import annotations`, type hints, and `@dataclass`. Match the
  existing concise style; comment only non-obvious math (cite the equation/source).
- Units: depth = msw, pressure = bar absolute, time = minutes, gas fractions 0..1.
- After changing model math or constants, run and (if needed) extend the tests:
  `python -m unittest tests.test_buhlmann -v`. NDL tests tolerate ±5–6 min vs
  published Bühlmann tables.
- Educational software — never present output as safe for real dives.
