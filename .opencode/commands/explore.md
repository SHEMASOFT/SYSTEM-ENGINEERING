---
description: Scan the project and produce a discovery report.
agent: explorer
---

# explore

- **id**: CMD-0002
- **version**: 1.0.0
- **purpose**: Scan the project and produce a discovery report.
- **execution_intent**: READ
- **risk_level**: low
- **gate**: G1
- **permissions**: READ, ANALYZE

## Execution

se explore --project $ARGUMENTS

## Arguments

- `--project` (path, required) — Managed project workspace.
- `--force` (boolean, optional) — Repair or force re-run without overwriting seeded files.
