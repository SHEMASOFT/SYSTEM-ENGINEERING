# Hermes Adapter

Implemented (`se adapter hermes`). Hermes reads role definitions from
`AGENTS.md` in the project root and its own MCP roster from `.hermes/mcp.json`.

## Output

```
AGENTS.md                          # role definitions for Hermes
settings.json                      # Hermes settings: routes and defaults
.hermes/mcp.json                   # MCP servers in Hermes's config location
.hermes/skills/<id>/SKILL.md       # the SE skill surface
```

`--dry-run` lists the same files without writing them. Generation is
idempotent: unchanged files are reported as `unchanged`.

## Generate it

```bash
python SCRIPTS/se.py adapter hermes
python SCRIPTS/se.py adapter hermes --dry-run
```

Windows PowerShell:

```powershell
python SCRIPTS\se.py adapter hermes
```

## Mapping

| Master System | Hermes |
|---|---|
| agents (`AGENTS/*/agent.json`) | role sections in `AGENTS.md`; model routes in `settings.json` |
| commands (`COMMANDS/commands.json`) | invoked through the `se` CLI from Hermes sessions |
| skills (`SKILLS/*/SKILL.md`) | `.hermes/skills/<id>/SKILL.md` |
| MCP (`TEMPLATES/mcp/*`) | `.hermes/mcp.json` |

## Model selection

The agent contract wins; otherwise the harness-level selection written by
`se shema-ai model` applies. A single default is written only when every role
resolves to the same `provider/model`. If no model is configured, none is
invented.

## Why it is not in `adapter all`

`adapter all` writes the shared files for Claude Code, Codex, DeepSeek and Pi.
Hermes also writes `AGENTS.md` and `settings.json`, so adding it to that batch
would silently overwrite files belonging to those runtimes. Run
`se adapter hermes` explicitly when you use Hermes; `se setup --harness hermes`
does exactly that, together with the rest of the bootstrap.
