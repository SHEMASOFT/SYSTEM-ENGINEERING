---
description: "Manage deterministic multi-agent workflows (DAG + gates): create, execute, list."
agent: coordinator
---

# orchestrate

- **id**: CMD-0024
- **version**: 1.0.0
- **purpose**: Create workflow definitions from nodes/edges/gates, execute them with topological ordering and gate enforcement, and list workflows in a project.
- **execution_intent**: CONTROL
- **risk_level**: medium
- **gate**: varies
- **permissions**: READ, ANALYZE, WRITE_DOCS

## Execution

se orchestrate --project $ARGUMENTS

## Arguments

- `--project` (path, required) — Managed project workspace.
- `subcommand` (string, required) — create | execute | list
- `--workflow` (string, optional) — Workflow ID (WF-xxxx) for execute/list.
- `--name` (string, optional) — Workflow name for create.
- `--nodes` (path, optional) — Path to nodes.json for create.
- `--edges` (path, optional) — Path to edges.json for create.
- `--gates` (path, optional) — Path to gates.json for create.
- `--dry-run` (boolean, optional) — Validate and plan execution without running (execute subcommand).
- `--json` (boolean, optional) — Emit a machine-readable se.report/1 envelope.
