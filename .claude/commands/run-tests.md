---
description: Run the deco unittest suite.
allowed-tools: Bash(python:*)
---

Run the test suite and report pass/fail. On failure, show the failing assertions
and point at the relevant code in `buhlmann.py`.

!`python -m unittest discover -s tests -v`
