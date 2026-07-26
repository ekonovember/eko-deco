## What and why

<!-- What changes, and what it is for. Link an issue if there is one. -->

## Checks

- [ ] `python -m unittest discover -s tests -t .` passes
- [ ] `ruff check .` and `mypy` are clean
- [ ] Core (`buhlmann` / `report` / `dive_config` / `cli`) still imports nothing
      outside the standard library

## If this touches the model

- [ ] Tests added or adjusted for the new behaviour
- [ ] The Subsurface and Baker cross-checks still pass (needs `g++` + `gfortran`)
- [ ] Any deliberate divergence has a `DECISIONS.md` entry

## If this touches output

- [ ] ppO₂ / ceiling / density warnings still surface on every schedule
      ([DECISIONS.md #4](../DECISIONS.md))

## If this adds a CLI flag

- [ ] `src/deco/cli.py`, `README.md` and the Commands block in `CLAUDE.md` all updated
