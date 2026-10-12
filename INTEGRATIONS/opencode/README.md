# OpenCode Adapter

OpenCode is the initial execution environment for building and operating the Master System.
This adapter is **implemented** since v0.6.0 (`se adapter opencode`).

## Mapping

| Master System | OpenCode (V2 discovery paths) |
|---------------|----------|
| commands (`COMMANDS/commands.json`) | `.opencode/commands/*.md` (frontmatter `description` / `agent`) |
| agents (`AGENTS/*/agent.json`) | `.opencode/agents/*.md` (frontmatter `description` / `mode`) |
| skills (`SKILLS/*/SKILL.md`) | `.opencode/skills/<skill>/SKILL.md` (frontmatter validated) |
| gates (`CORE/gates/gates.json`) | checks run before state changes |
| schemas (`SCHEMAS/`) | validation tool calls |
| doctor | a command that runs `SCRIPTS/se.py doctor` |

`coordinator` is generated with `mode: primary` (selectable in the runtime); every other
role is generated with `mode: subagent`, so the primary agent launches them in fresh,
isolated contexts.

## Constraints

- No OpenCode-specific concept may appear in `CORE/` or `SCHEMAS/`.
- The adapter calls the reference CLI or reimplements the contracts; it does not redefine
  them.
- Permission enforcement maps OpenCode tool permissions onto the Master System permission
  model (`READ`, `ANALYZE`, `WRITE_DOCS`, `IMPLEMENT`, `TEST`, `DEPLOY`, `DESTRUCTIVE`).
- Generated output only: `.opencode` is regenerated, never edited.

## Status

IMPLEMENTED — see `DOCS/reference/opencode-adapter.md` and `SCRIPTS/se_core/opencode/README.md`.
