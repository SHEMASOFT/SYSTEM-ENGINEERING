# Runtime adapters

SE keeps runtime specifics out of `CORE/` and `SCHEMAS/`. An adapter renders the
canonical contracts — `AGENTS/*/agent.json`, `COMMANDS/commands.json`,
`SKILLS/*/SKILL.md` and `TEMPLATES/mcp/*` — into the files a runtime discovers.
Generation is deterministic (fixed order, LF, no timestamps), idempotent, and
never edits the canonical sources. MCP entries are rendered **portable**: no
absolute host paths.

| Runtime | Command | Output | Status |
|---|---|---|---|
| **OpenCode** | `se adapter opencode` | `.opencode/agents/`, `commands/`, `skills/`, `mcp/`, `AGENTS.md`, `adapter-manifest.json` | IMPLEMENTED (audited by `se doctor`) |
| **Claude Code** | `se adapter claude-code` | `.claude/agents/`, `.claude/commands/`, `.claude/skills/`, `.mcp.json`, `CLAUDE.md` | IMPLEMENTED |
| **Codex** | `se adapter codex` | `.codex/config.toml`, `.codex/agents/<role>.toml`, `.codex/prompts/`, `AGENTS.md` | IMPLEMENTED (config is a fragment: see below) |
| all | `se adapter all` | both of the above at one output root | IMPLEMENTED |

`--output <dir>` (default: the repository root) and `--dry-run` apply to every
adapter.

## Mapping

| Canonical | OpenCode | Claude Code | Codex |
|---|---|---|---|
| agent (`AGENTS/*/agent.json`) | `.opencode/agents/<role>.md` (`mode`) | `.claude/agents/<role>.md` (`name`, `description`) | `[agents.<role>]` + `.codex/agents/<role>.toml` (`developer_instructions`) |
| command (`COMMANDS/commands.json`) | `.opencode/commands/<name>.md` | `.claude/commands/<name>.md` | `.codex/prompts/<name>.md` |
| skill (`SKILLS/*/SKILL.md`) | `.opencode/skills/<id>/SKILL.md` | `.claude/skills/<id>/SKILL.md` (byte-identical) | — |
| MCP (`TEMPLATES/mcp/*`) | `opencode.jsonc` → `mcp.servers` | `.mcp.json` → `mcpServers` | `[mcp_servers.<id>]` in `.codex/config.toml` |
| instructions | `AGENTS.md` | `CLAUDE.md` | `AGENTS.md` |

Runtime differences that the adapter must respect:

- **Claude Code** registers MCP servers in `.mcp.json` with `command`/`args`/`env`
  and expands `${VAR}` in the file; agents and commands are Markdown with YAML
  frontmatter.
- **Codex** reads configuration from `~/.codex/config.toml`, so the generated
  `.codex/config.toml` is a **fragment** to merge (or pass with `--config`); agent
  roles are declared under `[agents.<role>]` and point at a per-role TOML with
  `developer_instructions`. Codex has no skill loader, so skills are not adapted.

## Selection

Per project, not per repository: generate the runtime your environment uses.
`se adapter all` is for a polyglot checkout where more than one runtime reads the
same project. Regenerate after any contract change; the outputs are generated
artifacts, never edited by hand.

## See also

- `INTEGRATIONS/opencode/README.md`, `INTEGRATIONS/claude-code/README.md`,
  `INTEGRATIONS/codex/README.md` — per-runtime notes.
- `DOCS/reference/work-modes.md` — when to run which mode.
