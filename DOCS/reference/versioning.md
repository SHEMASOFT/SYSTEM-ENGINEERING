# Versioning

The Master System follows semantic versioning. Current version: **0.11.0**
(see [`VERSION`](../../VERSION); status: FOUNDATION / DEVELOPMENT).

While the version is `0.x`:

- the API, schemas and models may change between minor versions;
- `schema_version` in artifacts guards data compatibility independently of the system
  version;
- breaking changes require an ADR and updated tests.

`master_system_version` is recorded in every project manifest so a project can state which
system version it conforms to. MASTER-003 introduced new required gate conditions and new
records (OBJECTIVE, ARTIFACT, ACCEPTANCE), so the version was bumped to `0.2.0` and the
managed pilot project was migrated (see the MASTER-003 validation record).

v1.0 is **not** claimed. Reaching v1.0 requires real-world validation of the system on
actual projects.

## Compatibility rules

- Adding an optional field or a new domain pack is a minor change.
- Adding a required field, changing an enum value, or changing a gate condition is a
  breaking change (major while `>=1.0`, minor while `0.x`).
- Schema changes must update `SCHEMAS/`, templates, tests and docs together.
