---
description: Validate the Master System installation and environment.
agent: shema-ai-coordinador
---

# doctor

- **id**: CMD-0011
- **version**: 1.0.0
- **purpose**: Validate the Master System installation and environment.
- **execution_intent**: ANALYZE
- **risk_level**: low
- **gate**: None
- **permissions**: READ, ANALYZE

## Execution

se doctor --project $ARGUMENTS

## Arguments

- `--json` (boolean, optional) — Emit a machine-readable se.report/1 envelope instead of human-readable output.
