---
description: Apply a controlled, audited mutation to a record.
agent: shema-ai-coordinador
---

# update

- **id**: CMD-0004
- **version**: 1.0.0
- **purpose**: Apply a controlled mutation to an existing record (validated, atomic, reference-safe, audited).
- **execution_intent**: MUTATE
- **risk_level**: medium
- **gate**: None
- **permissions**: READ, ANALYZE, WRITE_DOCS

## Execution

se update --project $ARGUMENTS

## Arguments

- `record` (string, required) — Record type (objective|requirement|task|artifact|evidence|acceptance|decision).
- `record_id` (string, required) — Record id to mutate.
- `--project` (path, required) — Managed project workspace.
- `--set` (array, optional) — Fields to set (key=value).
- `--add` (array, optional) — Array fields to add.
- `--remove` (array, optional) — Array fields to remove.
- `--by` (string, optional) — Actor performing the action.
