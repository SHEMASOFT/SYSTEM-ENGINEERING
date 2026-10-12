# Claude Code Adapter

Implemented since v0.10.0 (`se adapter claude-code`). Renders the canonical
contracts into the layout Claude Code discovers.

## Output

```
.claude/agents/<role>.md          # subagents: YAML frontmatter name/description + body
.claude/commands/<name>.md        # slash commands (/plan, /implement, ...) using $ARGUMENTS
.claude/skills/<id>/SKILL.md      # byte-identical to the canonical skill
.mcp.json                         # mcpServers: command/args/env, portable
CLAUDE.md                         # generated overview (roles, commands, MCP servers)
```

## Mapping

| Master System | Claude Code |
|---------------|-------------|
| agents (`AGENTS/*/agent.json`) | `.claude/agents/<role>.md` (`name`, `description`; body = purpose, capabilities, restrictions, permissions) |
| commands (`COMMANDS/commands.json`) | `.claude/commands/<name>.md` (`description`; body invokes `se <name> --project $ARGUMENTS`) |
| skills (`SKILLS/*/SKILL.md`) | `.claude/skills/<id>/SKILL.md` (copied verbatim) |
| MCP (`TEMPLATES/mcp/*`) | `.mcp.json` → `mcpServers` (portable: relative args, `{env:...}` preserved for Claude Code to expand) |

## Constraints

- No absolute host paths: entries are project-relative and secrets stay as
  `{env:NAME}` for the runtime to expand.
- Generated output only; regenerate with `se adapter claude-code` after any
  contract change.
- No Claude Code specific concept enters `CORE/` or `SCHEMAS/`.

## Status

IMPLEMENTED — see `DOCS/reference/adapters.md`.
