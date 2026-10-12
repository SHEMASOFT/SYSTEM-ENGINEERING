---
description: Create or repair a managed project workspace.
agent: coordinator
---

# init

- **id**: CMD-0001
- **version**: 1.0.0
- **purpose**: Create or repair a managed project workspace (seeds .gitignore and discovery.json without overwriting).
- **execution_intent**: CREATE
- **risk_level**: low
- **gate**: G0
- **permissions**: READ, ANALYZE, WRITE_DOCS

## Execution

se init --project $ARGUMENTS

## Arguments

- `--dir` (path, required) — Target directory for the project workspace.
- `--name` (string, optional) — Project display name.
- `--owner` (string, optional) — Project owner identity.
- `--domains` (array, optional) — Domain pack slugs.
- `--criticality` (string, optional) — Project criticality (low|medium|high|critical|unknown).
- `--id` (string, optional) — Project id (PRJ-XXXX).
- `--force` (boolean, optional) — Repair or force re-run without overwriting seeded files.
