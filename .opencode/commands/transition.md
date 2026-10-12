---
description: Advance the project lifecycle through its gates.
agent: coordinator
---

# transition

- **id**: CMD-0005
- **version**: 1.0.0
- **purpose**: Advance the project lifecycle through its gates; requires human attestation for MANUAL conditions.
- **execution_intent**: CONTROL
- **risk_level**: high
- **gate**: varies
- **permissions**: READ, WRITE_DOCS

## Execution

se transition --project $ARGUMENTS

## Arguments

- `--project` (path, required) — Managed project workspace.
- `--to` (string, required) — Target lifecycle state.
- `--attest` (boolean, optional) — Human attestation for MANUAL gate conditions.
- `--by` (string, optional) — Actor performing the action.
