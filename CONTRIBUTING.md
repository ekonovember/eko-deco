# Contributing

Thanks for looking. This is a small project with strong opinions; most of them
are written down in [`DECISIONS.md`](DECISIONS.md) and it is worth two minutes
before you change model math.

## Getting set up

```bash
git clone git@github.com:ekonovember/eko-deco.git
cd eko-deco

# Run the suite with nothing installed — this must always work.
python -m unittest discover -s tests -t . -v

# Or set up a full dev environment (GUI + linters).
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev,gui]"
```

Python 3.10+. The core needs no third-party packages; `[gui]` adds matplotlib
and `[dev]` adds ruff and mypy.

## The checks CI runs

```bash
python -m unittest discover -s tests -t .   # 442 tests
ruff check .
mypy
```

Optionally `pip install pre-commit && pre-commit install` to run the first two
on every commit.

The count is always `Ran 442 tests`; the **skip** line is what varies, and a
skip means this machine lacks something, never that data is missing. Two
modules compile the reference implementations — Subsurface's `deco.cpp` with
**g++**, Erik Baker's `GFDECO` with **gfortran** — and two more want the
`[dev]` extra's Python oracles; the GUI and card-rendering tests want Tk and
matplotlib. Expect 1 skip with everything installed, 45 without a display, and
38 more without the compilers and extras. On Windows, install MSYS2/MinGW-w64
or run the suite under WSL.

## House rules

**Zero dependencies in the core.** `deco.buhlmann`, `deco.toxicity`,
`deco.contingency`, `deco.report`, `deco.dive_config` and `deco.cli` are
standard library only. Only `deco.app` and `deco.cards` — the two that draw —
may import matplotlib and tkinter, and both sit behind the `[gui]` extra. This
is [DECISIONS.md #1](DECISIONS.md) (and #31) and it is not negotiable.

**Warnings are load-bearing.** The planner deliberately plans bad profiles and
flags them rather than refusing (#4). Any new output path must carry
`ppo2_violations`, `ceiling_violations` and the density warnings. Dropping them
is a safety regression.

**Compute once, in `deco.report`.** Front ends format numbers; they never
derive them (#8). If the CLI and the GUI could disagree about a figure, the
figure belongs in `report.py`.

**Never copy from `tests/subsurface_oracle/`.** It is GPL-2.0; this project is
MIT. Compare outputs, never source (#12).

**Touching model math means touching tests.** NDL tests tolerate ±5–6 min
against published Bühlmann tables. The Subsurface cross-check pins tissue
loading and ceilings to machine precision: if it breaks after your change, the
change is very probably wrong. If it is *deliberately* divergent, update the
test **and** add a `DECISIONS.md` entry saying why.

**Style.** `from __future__ import annotations`, full type hints, frozen or
plain `@dataclass`, module docstrings, comments only where the math is
non-obvious — and then cite the equation or source. Line length 96. There is no
auto-formatter on purpose (#14): alignment in the coefficient tables and the
schedule output is deliberate.

**Units, always.** Depth in msw, pressure in bar absolute, time in minutes, gas
fractions 0–1.

## When you add a CLI flag

Update, in the same commit: `src/deco/cli.py`, `README.md`, the Commands block
in `CLAUDE.md`, and the skill (`.claude/skills/deco-buhlmann/SKILL.md`) if the
flag is one an agent would reach for. The agent instructions are documentation with a job — a
stale module map is a bug.

## Decisions

If you find yourself writing "this looks wrong but it's intentional" in a code
comment, that is a `DECISIONS.md` entry. Add it with the next free number;
numbers are never reused, and superseded entries stay in place marked as
superseded.

## Commits

Present tense, one concern per commit ("Add per-level start times and fix
off-screen window restore" is two commits). Say *why* in the body when the
what is not self-evident.
