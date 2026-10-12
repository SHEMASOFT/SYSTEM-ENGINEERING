# CORE / Artifacts

Source of truth: [`artifact-types.json`](artifact-types.json).

Terminology (resolves the MASTER-002 ambiguity):

- **record** — any persisted typed JSON file in a project workspace.
- **ARTIFACT** (entity type) — a concrete **deliverable produced by executing tasks**,
  distinct from REQUIREMENT (a need), TASK (work) and EVIDENCE (proof).
  The file name `artifact-types.json` is historical; this file defines core record types.

Core record types and their schemas:

| Type | Schema | Storage |
|------|--------|---------|
| PROJECT | `SCHEMAS/project/project.schema.json` | `PROJECT.json` |
| OBJECTIVE | `SCHEMAS/objective/objective.schema.json` | `objectives/<id>.json` |
| REQUIREMENT | `SCHEMAS/requirement/requirement.schema.json` | `requirements/<id>.json` |
| TASK | `SCHEMAS/task/task.schema.json` | `tasks/<id>.json` |
| ARTIFACT | `SCHEMAS/artifact/artifact.schema.json` | `artifacts/<id>.json` |
| EVIDENCE | `SCHEMAS/evidence/evidence.schema.json` | `evidence/<id>.json` |
| ACCEPTANCE | `SCHEMAS/acceptance/acceptance.schema.json` | `acceptances/<id>.json` |
| DECISION | `SCHEMAS/decision/decision.schema.json` | `decisions/<id>.json` |
| RELEASE | `SCHEMAS/release/release.schema.json` | `releases/<id>.json` |
| DISCOVERY | `SCHEMAS/discovery/discovery.schema.json` | `discovery.json` |

Common metadata fields (where applicable): `artifact_id`, `project_id`, `type`, `version`,
`status`, `created_at`, `updated_at`, `owner`, `author`, `source`, `related_tasks`,
`related_requirements`, `related_decisions`.

## Epistemic status vs lifecycle status

OBJECTIVE separates two independent dimensions:

- `status` — lifecycle of the objective (`PROPOSED`, `ACTIVE`, `ACHIEVED`, `ABANDONED`).
- `epistemic_status` — how the objective statement is known (`OBJECTIVE`, `FACT`,
  `ASSUMPTION`, `UNKNOWN`). `FACT` requires linked evidence; `ASSUMPTION` and `UNKNOWN`
  require a rationale.

A project's `criticality` may be `unknown`; the system never substitutes a factual default.

Domain-specific artifacts extend these via domain packs; they are **not** forced into the
same metadata model beyond the common core.
