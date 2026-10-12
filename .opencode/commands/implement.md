---
description: Report the next actionable tasks.
agent: implementer
---

# implement

- **id**: CMD-0007
- **version**: 1.0.0
- **purpose**: Report the next actionable tasks after checking the plan gate.
- **execution_intent**: REPORT
- **risk_level**: medium
- **gate**: G4
- **permissions**: READ, ANALYZE

## Execution

se implement --project $ARGUMENTS

## Arguments

- `--project` (path, required) — Managed project workspace.
