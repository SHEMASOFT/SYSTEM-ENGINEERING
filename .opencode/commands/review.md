---
description: Static review of schema, references and coverage.
agent: reviewer
---

# review

- **id**: CMD-0009
- **version**: 1.0.0
- **purpose**: Static review: schema validity, references, project_id, duplicates, coverage gaps and informational link notes.
- **execution_intent**: ANALYZE
- **risk_level**: low
- **gate**: G6
- **permissions**: READ, ANALYZE

## Execution

se review --project $ARGUMENTS

## Arguments

- `--project` (path, required) — Managed project workspace.
- `--json` (boolean, optional) — Emit a machine-readable se.report/1 envelope instead of human-readable output.
