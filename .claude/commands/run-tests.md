---
description: Run the deco unittest suite.
allowed-tools: Bash(python:*)
---

Run the test suite and report pass/fail. On failure, show the failing assertions
and point at the relevant code in `src/deco/buhlmann.py`.

`-t .` is required: it is what makes `tests/__init__.py` put `src/` on the
path, so the suite runs with nothing installed.

!`python -m unittest discover -s tests -t . -v`
