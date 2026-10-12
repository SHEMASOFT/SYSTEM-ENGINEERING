# Codex Adapter

Implemented since v0.10.0 (`se adapter codex`). Codex reads its configuration
from `~/.codex/config.toml`, so the adapter generates a **fragment** plus the
project files Codex already understands.

## Output

```
AGENTS.md                     # project instructions: roles + commands overview
.codex/config.toml            # fragment: [mcp_servers.*] and [agents.*]
.codex/agents/<role>.toml     # per-role: developer_instructions (+ model when declared)
.codex/prompts/<name>.md      # custom prompts: the SE commands
```

## Mapping

| Master System | Codex |
|---------------|-------|
| agents (`AGENTS/*/agent.json`) | `[agents.<role>]` (`description`, `config_file`) + `.codex/agents/<role>.toml` (`developer_instructions`, `model` when the contract declares one) |
| commands (`COMMANDS/commands.json`) | `.codex/prompts/<name>.md` |
| MCP (`TEMPLATES/mcp/*`) | `[mcp_servers.<id>]` (`command`, `args`, `cwd`, `[mcp_servers.<id>.env]`) |
| instructions | `AGENTS.md` |

## Constraints

- The configuration is a fragment: merge `.codex/config.toml` into
  `~/.codex/config.toml`, or pass the file with `--config`. The adapter never
  writes into your home directory.
- MCP entries are portable (project-relative args + `cwd = "."`); no host paths.
- Codex has no skill loader, so `SKILLS/` is not adapted.
- Generated output only; regenerate with `se adapter codex` after any contract
  change.

## Status

IMPLEMENTED — see `DOCS/reference/adapters.md`.
