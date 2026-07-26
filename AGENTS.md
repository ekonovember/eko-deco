# AGENTS.md

Agent instructions for the **deco** project live in [`CLAUDE.md`](./CLAUDE.md).

That file is the single source of truth — module map, commands, conventions, and
the safety scope (warnings, no printed disclaimer). GitHub Copilot CLI and Claude Code both read
`CLAUDE.md` automatically when you start them in this folder; this `AGENTS.md`
exists so any other AGENTS.md-aware tool is pointed to the same place.

Two companions worth reading before you change anything:

- [`DECISIONS.md`](./DECISIONS.md) — numbered, stable decision log. Code
  comments cite it (`see DECISIONS.md #7`). Read it before "fixing" something
  that looks wrong; it is probably intentional and the entry says why.
- [`CONTRIBUTING.md`](./CONTRIBUTING.md) — setup, the checks CI runs, house rules.
