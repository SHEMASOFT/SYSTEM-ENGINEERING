---
description: Validate schemas, agents, domains and an optional project.
agent: shema-ai-coordinador
---

# validate

- **id**: CMD-0012
- **version**: 1.0.0
- **purpose**: Validate schemas, agents, domains and (optionally) a project.
- **execution_intent**: ANALYZE
- **risk_level**: low
- **gate**: None
- **permissions**: READ, ANALYZE

## Execution

se validate --project $ARGUMENTS

## Arguments

- `--project` (path, required) — Managed project workspace.
- `--json` (boolean, optional) — Emit a machine-readable se.report/1 envelope instead of human-readable output.
