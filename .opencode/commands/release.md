---
description: Create and optionally approve a release artifact.
agent: devops
---

# release

- **id**: CMD-0010
- **version**: 1.0.0
- **purpose**: Create and optionally approve a release artifact.
- **execution_intent**: CREATE
- **risk_level**: high
- **gate**: G7
- **permissions**: READ, WRITE_DOCS, DEPLOY

## Execution

se release --project $ARGUMENTS

## Arguments

- `--project` (path, required) — Managed project workspace.
- `--version` (string, required) — Release version (semver).
- `--scope` (string, optional) — Release scope.
- `--approve` (boolean, optional) — Approve the release.
- `--by` (string, optional) — Actor performing the action.
