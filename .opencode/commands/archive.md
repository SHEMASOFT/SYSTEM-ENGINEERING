---
description: Create a verified archive bundle of the project.
agent: coordinator
---

# archive

- **id**: CMD-0020
- **version**: 1.0.0
- **purpose**: Create a tamper-evident archive (.tar.gz) containing all project files with SHA-256 hashes, embedded archive-manifest.json with record counts, and pre-archive validation. READ-ONLY (does not mutate project records).
- **execution_intent**: READ
- **risk_level**: low
- **gate**: None
- **permissions**: READ, ANALYZE

## Execution

se archive --project $ARGUMENTS

## Arguments

- `--project` (path, required) — Managed project workspace.
- `--output` (path, optional) — Output archive path (default: <cwd>/<project_id>-<version>-<date>.tar.gz).
- `--by` (string, optional) — Author of archive.
- `--force` (boolean, optional) — Archive even if validation fails.
- `--json` (boolean, optional) — Emit machine-readable se.report/1 envelope.
