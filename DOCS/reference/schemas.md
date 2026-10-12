# Schemas

Schemas are **JSON Schema 2020-12** documents under `SCHEMAS/`. `SCHEMAS/index.json` maps
logical names to paths and is the tooling entry point.

| Name | Path |
|------|------|
| project | `SCHEMAS/project/project.schema.json` |
| objective | `SCHEMAS/objective/objective.schema.json` |
| requirement | `SCHEMAS/requirement/requirement.schema.json` |
| task | `SCHEMAS/task/task.schema.json` |
| artifact | `SCHEMAS/artifact/artifact.schema.json` |
| evidence | `SCHEMAS/evidence/evidence.schema.json` |
| acceptance | `SCHEMAS/acceptance/acceptance.schema.json` |
| decision | `SCHEMAS/decision/decision.schema.json` |
| release | `SCHEMAS/release/release.schema.json` |
| discovery | `SCHEMAS/discovery/discovery.schema.json` |
| agent | `AGENTS/_contract/agent.schema.json` |
| domain | `DOMAINS/_contract/domain.schema.json` |

Properties:

- **Versioned** via `schema_version` (`"1"`) and the repository `VERSION`.
- **Self-contained** — no cross-schema `$ref` resolution required, so validation is
  hermetic.
- **Strict but extensible** — `additionalProperties: false` plus an optional free-form
  `metadata` object.
- **Conditional rules** via `if`/`then` (e.g. a BLOCKED task must have a reason and a
  resolution path).

Validate:

```powershell
python SCRIPTS\se.py validate
python SCRIPTS\se.py validate --project .workspaces\demo
```
