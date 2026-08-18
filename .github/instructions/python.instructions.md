---
applyTo: "**/*.py"
---

# Python conventions — deco

- Target Python 3.10+ (verified on 3.14). src layout: the package is `src/deco/`,
  imported as `from deco import buhlmann as b`.
- **Keep `deco.buhlmann`, `deco.toxicity`, `deco.contingency`, `deco.report`,
  `deco.dive_config` and `deco.cli` dependency-free** (stdlib only). Only
  `deco.app` and `deco.cards` — the two that draw — may import `matplotlib` /
  `tkinter`, and both sit behind the `[gui]` extra. See `DECISIONS.md` #1, #31.
- Use `from __future__ import annotations`, type hints, and `@dataclass`. Match the
  existing concise style; comment only non-obvious math (cite the equation/source).
  Modern annotations only — `list[str]`, `X | None`, never `typing.List`/`Optional`.
- Units: depth = msw, pressure = bar absolute, time = minutes, gas fractions 0..1.
- After changing model math or constants, run and (if needed) extend the tests:
  `python -m unittest discover -s tests -t . -v`. NDL tests tolerate ±5–6 min vs
  published Bühlmann tables; the Subsurface cross-check is machine-precision — if
  it breaks, the change is probably wrong (`DECISIONS.md` #3).
- `ruff check .` and `mypy` must stay clean; both run in CI. There is no
  auto-formatter on purpose (`DECISIONS.md` #14) — alignment is deliberate.
- No printed disclaimer in output; the ppO2/density/ceiling warnings replace it
  and must be surfaced by every renderer (`DECISIONS.md` #4, #5).
- Numbers are computed once in `deco.report` and only formatted by front ends
  (`DECISIONS.md` #8).
