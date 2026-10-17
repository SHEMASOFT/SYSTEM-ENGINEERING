# Policy: Release

A release (`SCHEMAS/release/release.schema.json`) must include:

1. `version` (semantic) and `scope`.
2. `changes` traceable to tasks and requirements.
3. `verification` and linked `evidence`.
4. `known_issues`.
5. `deployment_method`.
6. `rollback` — no release is approved without a rollback procedure.
7. `approval` by the accountable owner.

Gate rules:

- G6 (acceptance) and G7 (release) must pass before a project is `RELEASED`.
- G7 requires an APPROVED release with rollback, deployment method and evidence.
- A release without rollback must not be deployed.

Versioning: while the Master System is `0.x`, breaking changes may occur between minor
versions. See `DOCS/versioning.md`.
