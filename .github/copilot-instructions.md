# GitHub Copilot instructions — deco

When you start `copilot` in this folder, Copilot CLI auto-loads this file **plus**
`CLAUDE.md`, `AGENTS.md`, and `.github/instructions/**`. It also auto-discovers the
`deco-buhlmann` skill under `.claude/skills/`.

**Full project guide:** [`../CLAUDE.md`](../CLAUDE.md) — module map, commands,
conventions, and safety scope. It is the single source of truth.
**Why things are the way they are:** [`../DECISIONS.md`](../DECISIONS.md) — a
numbered decision log the code cites (`see DECISIONS.md #7`). Check it before
changing model math, output, or the dependency policy.

## Quick facts

- Bühlmann ZHL-16C + gradient-factor dive calculator. Output carries no printed
  disclaimer (removed deliberately, DECISIONS #5) — the ppO2/density/ceiling
  **warnings** are the safety surface instead (DECISIONS #4), so every
  schedule/NDL/ceiling path must show them.
- Python 3.10+ (works on 3.14). src layout: the package is `src/deco/`.
  The core (`deco.buhlmann`, `deco.toxicity`, `deco.contingency`,
  `deco.report`, `deco.dive_config`, `deco.cli`) is dependency-free; only
  `deco.app` and `deco.cards` need matplotlib/tkinter, both behind the `[gui]`
  extra. Don't add deps to the core (DECISIONS #1, #31).
- CLI: `deco {plan|ndl|tissues} … [--json]` (or `python -m deco.cli …`).
  GUI: `deco-gui`.
- Run the suite after any model-math change:
  `python -m unittest discover -s tests -t .` — the `-t .` matters, it is what
  puts `src/` on the path.
- `ruff check .` and `mypy` are clean and CI enforces both.
- Windows: set `PYTHONUTF8=1` for correct `Bühlmann` / subscript output.

## Skills, commands, agents

- Skill `deco-buhlmann` → `.claude/skills/deco-buhlmann/SKILL.md` (auto-discovered by Copilot CLI).
- Slash commands → `.claude/commands/` (`/plan-dive`, `/ndl`, `/tissues`, `/run-tests`).
- Subagent `dive-planner` → `.claude/agents/dive-planner.md`.
