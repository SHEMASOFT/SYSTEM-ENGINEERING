---
description: Evaluate a single gate against a project.
agent: coordinator
---

# gate

- **id**: CMD-0013
- **version**: 1.0.0
- **purpose**: Evaluate a single gate against a project.
- **execution_intent**: ANALYZE
- **risk_level**: low
- **gate**: None
- **permissions**: READ, ANALYZE

## Execution

se gate --project $ARGUMENTS

## Arguments

- `--project` (path, required) — Managed project workspace.
- `--gate` (string, required) — Gate id to evaluate (G0..G8).
- `--json` (boolean, optional) — Emit a machine-readable se.report/1 envelope instead of human-readable output.
