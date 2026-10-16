---
description: Restore a project from an archive bundle.
agent: shema-ai-coordinador
---

# restore

- **id**: CMD-0021
- **version**: 1.0.0
- **purpose**: Restore a project from a verified archive bundle; verifies SHA-256 hashes against embedded manifest, extracts all files, and runs se validate on the restored project. Does not overwrite without --force.
- **execution_intent**: CREATE
- **risk_level**: medium
- **gate**: None
- **permissions**: READ, ANALYZE, WRITE_DOCS

## Execution

se restore --project $ARGUMENTS

## Arguments

- `archive` (path, required) — Path to archive .tar.gz file.
- `--target` (path, optional) — Target directory (default: <cwd>/restored).
- `--force` (boolean, optional) — Overwrite existing target / ignore hash mismatches.
- `--json` (boolean, optional) — Emit machine-readable se.report/1 envelope.
