---
description: Reconstruct the minimum relevant context (AUTO-02).
agent: coordinator
---

# context

- **id**: CMD-0015
- **version**: 1.0.0
- **purpose**: Read-only, deterministic, on-demand reconstruction of the smallest sufficient context for a project or focused entity (LEVEL 0 identity by default; work/authority/trace/deep require an explicit scope). Composes existing read-only functions; grants no authority; emits a se.report/1 envelope with --json.
- **execution_intent**: READ
- **risk_level**: low
- **gate**: None
- **permissions**: READ, ANALYZE

## Execution

se context --project $ARGUMENTS

## Arguments

- `--project` (path, required) — Managed project workspace.
- `--scope` (string, optional) — Context level: identity (default) | work | authority | trace | deep.
- `--focus` (string, optional) — Optional focus id (TASK-xxxx/REQ-xxxx/OBJ-xxxx/... or the project id)
- `--json` (boolean, optional) — Emit a machine-readable se.report/1 envelope instead of human-readable output.
