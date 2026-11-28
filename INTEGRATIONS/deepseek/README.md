# DeepSeek Harness Adapter

Implemented (`se adapter deepseek`). DSH reads project instructions from
`AGENTS.md`/`CLAUDE.md` plus their `.local.md` overlays, skills from
`<projectRoot>/.dsh/skills`, and agent presets **only** from Cordis patch lists —
never from a scanned preset directory.

Because of that last constraint the adapter does not write one file per agent.
It renders a single **patch overlay** that declares one preset per SE role, and
the operator applies it with `--patch`.

## Output

```
AGENTS.local.md                    # project instructions: roles, commands, MCP roster
.dsh/se.patch.yml                  # Cordis patch: one agent preset per SE role
.dsh/skills/<id>/SKILL.md          # the SE skill surface (frontmatter kept first)
```

`AGENTS.local.md` is used instead of `AGENTS.md` so it never collides with the
file the Codex adapter writes at the same output root.

## Apply it

```bash
# 1. Generate the layer (project root by default)
python SCRIPTS/se.py adapter deepseek

# 2a. Apply the overlay for one run
dsh --patch .dsh/se.patch.yml

# 2b. Or make it permanent for a profile
cat .dsh/se.patch.yml >> "$DSH_HOME/profiles/<profile>/cordis.patch.yml"
```

Windows PowerShell:

```powershell
python SCRIPTS\se.py adapter deepseek
dsh --patch .dsh/se.patch.yml
```

## Mapping

| Master System | DeepSeek Harness |
|---------------|------------------|
| agents (`AGENTS/*/agent.json`) | one `@deepseek-ai/dsh-agent-preset` row in `.dsh/se.patch.yml`; the role contract is the preset's `persona` prefix |
| commands (`COMMANDS/commands.json`) | listed in `AGENTS.local.md`; invoked through the `se` CLI |
| skills (`SKILLS/*/SKILL.md`) | `.dsh/skills/<id>/SKILL.md` (frontmatter first, provenance after it) |
| MCP (`TEMPLATES/mcp/*`) | listed in `AGENTS.local.md`; mounted by hand on the profile's `mcp-manager` row (`config.servers`) |
| instructions | `AGENTS.local.md` |

## Roles and the coordinator

DSH has no "primary agent" selector like OpenCode. `shema-ai-coordinador` is
rendered as **one preset among the twelve**, with `order` set by role name. To
drive a session as the coordinator, select its preset in DSH; the other eleven
roles are the subagents it delegates to.

## Model selection

DSH 0.2.2-rc.3 binds a model per agent only on launcher and delegation rows
(`agent-loop.agents[].provider/model`, `tool-subagent.agentOptions`). A preset
declares identity, tools and prompt — never a route.

The adapter therefore:

- records each role's resolved model as a `# model: provider/model` comment in
  `.dsh/se.patch.yml` and in the `AGENTS.local.md` roster;
- writes an `agent-default-model` row **only** when every role resolves to the
  same non-empty `provider/model`, because a deployment default is process-wide
  and would misroute a mixed roster;
- invents nothing when no model is configured: it tells you to run
  `se shema-ai model` or declare `llm_config` on the agent contract.

## MCP servers

DSH mounts MCP servers on the profile's `mcp-manager` row (`config.servers`).
The adapter only lists them in `AGENTS.local.md`; it does not mutate your DSH
profile. Add the entries you want, for example:

```yaml
- id: mcp-manager
  config:
    servers:
      se-memory-server:
        command: node
        args: [SCRIPTS/se_core/mcp/launch.mjs, SCRIPTS/se_core/mcp/memory_server.py]
```

## Constraints

- Generated output only; regenerate with `se adapter deepseek` after any
  contract change. Never edit `.dsh/` or `AGENTS.local.md` by hand.
- A DSH preset **replaces** the complete child plugin list. This adapter renders
  the persona, the project instruction file and the SE skill surface; add the
  tool rows your deployment grants instead of expecting them here.
- Paths are portable (project-relative); no host paths.
- Deterministic and idempotent: fixed order, LF, no timestamps.

## Verify

```bash
python SCRIPTS/se.py adapter deepseek --dry-run   # plan only
python SCRIPTS/se.py adapter deepseek             # write
```

The generated patch must be valid YAML; `TESTS/test_adapter_deepseek.py`
parses it on every run.

## Status

IMPLEMENTED — see `DOCS/reference/adapters.md` and
`DOCS/reference/deepseek-harness-install.es.md` (Spanish, step by step).
