---
description: "SHEMA-AI Unified Interface: Model config, Install, Sync, Uninstall, Doctor."
agent: shema-ai-coordinador
---

# shema-ai

- **id**: CMD-0026
- **version**: 1.0.0
- **purpose**: SHEMA-AI Unified Interface: Model config, Install, Sync, Uninstall, Doctor.
- **execution_intent**: ANALYZE
- **risk_level**: low
- **gate**: None
- **permissions**: READ, ANALYZE

## Execution

se shema-ai --project $ARGUMENTS

## Arguments

- `--json` (boolean, optional) — Emit a machine-readable se.report/1 envelope instead of human-readable output.
