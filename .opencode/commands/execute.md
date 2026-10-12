---
description: Execute tasks in topological order with authorization, evidence, fail-closed.
agent: implementer
---

# execute

- **id**: CMD-0022
- **version**: 1.0.0
- **purpose**: Execute actionable tasks respecting authorized_actions, create evidence on completion, create artifacts for deliverable tasks, fail-closed on first failure, produce execution receipts.
- **execution_intent**: IMPLEMENT
- **risk_level**: medium
- **gate**: G3
- **permissions**: READ, ANALYZE, IMPLEMENT

## Execution

se execute --project $ARGUMENTS

## Arguments

- `--project` (path, required) — Managed project workspace.
- `--task` (string, optional) — Execute a single task by ID (default: all actionable tasks in topological order).
- `--dry-run` (boolean, optional) — Simulate execution without mutating state.
- `--force` (boolean, optional) — Re-execute already DONE tasks.
- `--continue-on-error` (boolean, optional) — Continue executing remaining tasks after a failure (default: fail-closed).
- `--json` (boolean, optional) — Emit a machine-readable se.execute/1 envelope.
