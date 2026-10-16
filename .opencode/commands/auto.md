---
description: "Deterministic decision engine: consumes health aggregation and emits a machine-readable next-action decision (se.auto/1)."
agent: shema-ai-coordinador
---

# auto

- **id**: CMD-0017
- **version**: 1.0.0
- **purpose**: Convert structured health status into a deterministic, auditable decision about the next AUTO pipeline step. READ-ONLY; no mutations, no LLM, no autonomous execution.
- **execution_intent**: ANALYZE
- **risk_level**: low
- **gate**: None
- **permissions**: READ, ANALYZE

## Execution

se auto --project $ARGUMENTS

## Arguments

- `--project` (path, required) — Managed project workspace.
- `--json` (boolean, optional) — Emit a machine-readable se.auto/1 envelope instead of human-readable output.
