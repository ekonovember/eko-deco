---
description: Ratio Deco schedule with GUE standard gases (educational estimate + Bühlmann cross-check).
argument-hint: --depth 51 --time 25 [--avg-depth 45 --gf-low 0.30 --gf-high 0.80 --json]
allowed-tools: Bash(python:*)
---

Run the Ratio Deco utility. Report the standard bottom/deco gases, the ratio and
total deco time, the stop list, and the Bühlmann cross-check. Stress that Ratio
Deco is a coarse mental-math approximation — not a validated schedule.

!`python cli.py ratio $ARGUMENTS`
