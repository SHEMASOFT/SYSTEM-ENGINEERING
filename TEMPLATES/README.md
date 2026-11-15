# TEMPLATES

Fill-in templates for core records. They are valid JSON and conform to their respective
schemas, so they can be copied and edited, or loaded and rewritten by tooling.

| Template | Record |
|----------|--------|
| `PROJECT.template.json` | Project manifest (`PROJECT.json`) |
| `objective.template.json` | Objective |
| `requirement.template.json` | Requirement / assumption / constraint / risk / idea / unknown |
| `task.template.json` | Task |
| `artifact.template.json` | Deliverable produced by a task |
| `evidence.template.json` | Evidence |
| `acceptance.template.json` | Acceptance decision |
| `decision.template.json` | Decision / ADR |
| `release.template.json` | Release |
| `discovery.template.json` | Discovery report (`discovery.json`) |
| `gitignore.template` | `.gitignore` seeded by `se init` (not JSON) |

## LLM configuration

`se-llm-config.template.json` documents the shape of the single file that sets the
default model for every agent when no per-agent `llm_config` and no `SE_LLM_*`
environment variable is present. Copy it over the committed default at
`SCRIPTS/se_core/llm/se-llm-config.json`, the location the runtime actually reads,
and set `provider`, `model` and `provider_options`.

The configuration lives under `SCRIPTS/` and never at the repository root: the root
layout is governed by the `root_hygiene` check of `se doctor`.

Placeholder values (`PRJ-EXAMPLE-001`, `OBJ-0001`, `1970-01-01T00:00:00Z`, ...) are
intentionally obvious so they are never mistaken for real data. The acceptance template
uses `result: DEFERRED` so it can never be mistaken for an automatic acceptance.
