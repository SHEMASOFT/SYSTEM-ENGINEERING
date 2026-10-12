---
description: Check requirement coverage and scaffold tasks; with --json derive an ordered READ-ONLY plan envelope (se.plan/1).
agent: planner
---

# plan

- **id**: CMD-0006
- **version**: 1.0.0
- **purpose**: Check requirement coverage and report or scaffold tasks; with --intent/--json derive a deterministic, structured, READ-ONLY plan envelope (se.plan/1) from the canonical TASK set and gates G2/G3.
- **execution_intent**: ANALYZE
- **risk_level**: low
- **gate**: G3
- **permissions**: READ, ANALYZE

## Execution

se plan --project $ARGUMENTS

## Arguments

- `--project` (path, required) — Managed project workspace.
- `--create-tasks` (boolean, optional) — Scaffold missing tasks. Cannot be combined with --intent/--json.
- `--intent` (path, optional) — Explicit intent file (se.intent/1 intent payload) used to derive the plan.
- `--json` (boolean, optional) — Emit a machine-readable se.plan/1 envelope (READ-ONLY derivation).
