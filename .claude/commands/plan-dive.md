---
description: Compute a Bühlmann GF decompression schedule with the deco CLI.
argument-hint: --depth 45 --time 25 --gas 21/35 [--deco-gas 50 --gf-low 0.30 --gf-high 0.70 --json]
allowed-tools: Bash(python:*)
---

Run the deco planner with the user's arguments, then summarize the schedule
(stops, total runtime, gas switches, surface ceiling). Restate that this is an
educational model and not validated for real dives.

!`python cli.py plan $ARGUMENTS`
