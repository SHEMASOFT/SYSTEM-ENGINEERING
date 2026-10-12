---
description: "Capability governance: registry, policy check and resolution."
agent: coordinator
---

# capabilities

- **id**: CMD-0014
- **version**: 1.0.0
- **purpose**: Inspect the capability registry and declarative provider mapping, validate declared capability policies (skills, agents, project profiles, tasks) and resolve a deterministic capability plan (system, project and/or task scope).
- **execution_intent**: ANALYZE
- **risk_level**: low
- **gate**: None
- **permissions**: READ, ANALYZE

## Execution

se capabilities --project $ARGUMENTS

## Arguments

- `--check` (boolean, optional) — Validate declared capability policies (canonical skills/agents plus optional project/task).
- `--project` (path, optional) — Managed project workspace for policy check / resolved plan.
- `--task` (string, optional) — Task artifact id (TASK-xxxx) within --project for plan / check.
- `--json` (boolean, optional) — Emit a machine-readable se.report/1 envelope instead of human-readable output.
