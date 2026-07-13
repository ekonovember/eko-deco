# GitHub Copilot instructions — deco

When you start `copilot` in this folder, Copilot CLI auto-loads this file **plus**
`CLAUDE.md`, `AGENTS.md`, and `.github/instructions/**`. It also auto-discovers the
`deco-buhlmann` skill under `.claude/skills/`.

**Full project guide:** [`../CLAUDE.md`](../CLAUDE.md) — module map, commands,
conventions, and safety scope. It is the single source of truth.

## Quick facts

- Educational Bühlmann ZHL-16C + gradient-factor dive calculator. **Not for real
  dives** — keep that disclaimer in any schedule/NDL/ceiling output.
- Python 3.10+ (works on 3.14). Core (`buhlmann.py`, `cli.py`)
  is dependency-free; only `app.py` needs matplotlib/tkinter. Don't add deps to the core.
- CLI: `python cli.py {plan|ndl|tissues} … [--json]`.
- Run tests after any model-math change: `python -m unittest tests.test_buhlmann -v`.
- Windows: set `PYTHONUTF8=1` for correct `Bühlmann` / subscript output.

## Skills, commands, agents

- Skill `deco-buhlmann` → `.claude/skills/deco-buhlmann/SKILL.md` (auto-discovered by Copilot CLI).
- Slash commands → `.claude/commands/` (`/plan-dive`, `/ndl`, `/tissues`, `/run-tests`).
- Subagent `dive-planner` → `.claude/agents/dive-planner.md`.
