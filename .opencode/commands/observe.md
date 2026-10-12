---
description: "Observe execution state: IN_PROGRESS tasks, evidence, artifacts, receipts (READ-ONLY)."
agent: implementer
---

# observe

- **id**: CMD-0023
- **version**: 1.0.0
- **purpose**: Read-only view of execution progress including IN_PROGRESS tasks, collected evidence, produced artifacts, and execution receipts.
- **execution_intent**: ANALYZE
- **risk_level**: low
- **gate**: None
- **permissions**: READ, ANALYZE

## Execution

se observe --project $ARGUMENTS

## Arguments

- `--project` (path, required) — Managed project workspace.
- `--json` (boolean, optional) — Emit a machine-readable se.observe/1 envelope.
