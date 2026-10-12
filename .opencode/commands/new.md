---
description: Create a record from its template.
agent: coordinator
---

# new

- **id**: CMD-0003
- **version**: 1.0.0
- **purpose**: Create a record (objective, requirement, task, artifact, evidence, acceptance, decision) from its template.
- **execution_intent**: CREATE
- **risk_level**: low
- **gate**: None
- **permissions**: READ, ANALYZE, WRITE_DOCS

## Execution

se new --project $ARGUMENTS

## Arguments

- `record` (string, required) — Record type (objective|requirement|task|artifact|evidence|acceptance|decision).
- `--project` (path, required) — Managed project workspace.
- `--type-flags` (array, optional) — Type-specific creation flags.
