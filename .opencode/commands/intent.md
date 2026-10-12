---
description: Normalize an explicit structured intent into a READ-ONLY se.intent/1 envelope.
agent: coordinator
---

# intent

- **id**: CMD-0018
- **version**: 1.0.0
- **purpose**: Validate and normalize an explicit structured intent (objetivo, contexto/proyecto, alcance, restricciones, criterio de éxito) from a file or an existing OBJECTIVE artifact, emitting a deterministic se.intent/1 envelope. READ-ONLY; no mutations, no LLM.
- **execution_intent**: ANALYZE
- **risk_level**: low
- **gate**: None
- **permissions**: READ, ANALYZE

## Execution

se intent --project $ARGUMENTS

## Arguments

- `--project` (path, required) — Managed project workspace.
- `--file` (path, optional) — Explicit intent JSON file (objective, context, scope, restrictions, success_criteria).
- `--objective` (string, optional) — Derive the intent from an existing OBJECTIVE artifact (OBJ-xxxx).
- `--json` (boolean, optional) — Emit a machine-readable se.intent/1 envelope instead of human-readable output.
