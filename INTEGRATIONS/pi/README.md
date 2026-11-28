# Pi Adapter

Implemented (`se adapter pi`). Pi reads role instructions from `AGENTS.md` in
the project root (written by the Codex adapter), so this adapter only renders
the Pi-specific surface.

## Output

```
settings.json                      # Pi settings: routes and defaults
.pi/mcp.json                       # MCP servers in Pi's own config location
.pi/skills/<id>/SKILL.md           # the SE skill surface
```

`--dry-run` lists the same files without writing them. Generation is
idempotent: unchanged files are reported as `unchanged`.

## Generate it

```bash
python SCRIPTS/se.py adapter pi
python SCRIPTS/se.py adapter pi --dry-run
```

Windows PowerShell:

```powershell
python SCRIPTS\se.py adapter pi
```

## Mapping

| Master System | Pi |
|---|---|
| agents (`AGENTS/*/agent.json`) | model routes in `settings.json`; role text in the root `AGENTS.md` |
| commands (`COMMANDS/commands.json`) | invoked through the `se` CLI from Pi sessions |
| skills (`SKILLS/*/SKILL.md`) | `.pi/skills/<id>/SKILL.md` |
| MCP (`TEMPLATES/mcp/*`) | `.pi/mcp.json` |

## Model selection

A route is resolved from the agent contract (`llm_config`) or from the
harness-level selection written by `se shema-ai model`. Nothing is invented: an
unconfigured route stays unset. A process-wide default is written only when
**every** role resolves to the same `provider/model`.

## Relationship with `adapter all`

`se adapter all` covers Claude Code, Codex, DeepSeek and Pi at one output root.
Codex writes the shared `AGENTS.md` and Pi writes `settings.json`; `se adapter pi`
also writes `settings.json`. Hermes is left out because it would overwrite both
files with different content — generate it separately with `se adapter hermes`.
