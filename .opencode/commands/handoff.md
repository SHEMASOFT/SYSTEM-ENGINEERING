---
description: Create or load a HANDOFF.json artifact for project continuity.
agent: shema-ai-coordinador
---

# handoff

- **id**: CMD-0019
- **version**: 1.0.0
- **purpose**: Explicit handoff artifact capturing project state, context snapshot, blockers, and deterministic next-actions for seamless context transfer across sessions or agents. READ-ONLY (create does not mutate project records; load is pure read).
- **execution_intent**: READ
- **risk_level**: low
- **gate**: None
- **permissions**: READ, ANALYZE, WRITE_DOCS

## Execution

se handoff $ARGUMENTS

## Arguments

- `--project` (path, required) — Managed project workspace.
- `subcommand` (string, required) — create | load
- `--scope` (string, optional) — Context level for create: identity|work|authority|trace|deep (default: trace).
- `--focus` (string, optional) — Optional focus id for context snapshot (create).
- `--file` (path, optional) — Path to HANDOFF.json (load; default: <project>/HANDOFF.json).
- `--by` (string, optional) — Author of handoff (create).
- `--force` (boolean, optional) — Overwrite existing HANDOFF.json (create).
- `--json` (boolean, optional) — Emit machine-readable se.report/1 envelope.
