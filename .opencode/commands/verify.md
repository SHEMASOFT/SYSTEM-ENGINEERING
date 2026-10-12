---
description: Evaluate verification readiness and missing evidence.
agent: tester
---

# verify

- **id**: CMD-0008
- **version**: 1.0.0
- **purpose**: Evaluate verification readiness and report missing evidence.
- **execution_intent**: ANALYZE
- **risk_level**: low
- **gate**: G5
- **permissions**: READ, ANALYZE, TEST

## Execution

se verify --project $ARGUMENTS

## Arguments

- `--project` (path, required) — Managed project workspace.
