---
description: Trace the dependency graph of a project record (read-only).
agent: shema-ai-coordinador
---

# trace

- **id**: CMD-0027
- **version**: 1.0.0
- **purpose**: Walk the dependency graph between project records: forward (what the record references) or in reverse (what references it), bounded by depth and node cap.
- **execution_intent**: ANALYZE
- **risk_level**: low
- **gate**: None
- **permissions**: READ, ANALYZE

## Execution

se trace --project $ARGUMENTS

## Arguments

- `record_id` (string, required) — Record ID to trace (e.g. REQ-0001, TASK-0005).
- `--project` (path, required) — Managed project workspace.
- `--kind` (string, optional) — Force the record kind; required for SDD/ODD/RDD/RUN, which carry no identifier prefix.
- `--depth` (integer, optional) — Traversal depth (default: 3).
- `--cap` (integer, optional) — Maximum number of nodes to visit (default: 100).
- `--direction` (string, optional) — Traversal direction: forward, reverse or both (default: forward).
- `--json` (boolean, optional) — Emit a machine-readable se.trace/1 envelope.
