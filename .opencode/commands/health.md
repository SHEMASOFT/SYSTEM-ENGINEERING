---
description: Aggregate health status from existing checks (doctor, validate, capabilities, review).
agent: shema-ai-coordinador
---

# health

- **id**: CMD-0016
- **version**: 1.0.0
- **purpose**: Aggregate health status from existing read-only checks (doctor, validate, capabilities --check, review) into a single deterministic, machine-readable health envelope (operation=health).
- **execution_intent**: READ
- **risk_level**: low
- **gate**: None
- **permissions**: READ, ANALYZE

## Execution

se health --project $ARGUMENTS

## Arguments

- `--project` (path, required) — Managed project workspace.
- `--json` (boolean, optional) — Emit a machine-readable se.report/1 envelope instead of human-readable output.
