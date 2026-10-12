# Core Model

Sources of truth: `CORE/lifecycle/lifecycle.json`, `CORE/gates/gates.json`,
`CORE/tasks/task-states.json`, `CORE/artifacts/artifact-types.json`, and `SCHEMAS/`.

## Project lifecycle

Nine states: `DRAFT`, `DISCOVERY`, `PLANNING`, `ACTIVE`, `VERIFICATION`, `ACCEPTANCE`,
`RELEASED`, `OPERATING`, `ARCHIVED`. `BLOCKED` is a **condition**, not a state.

Transitions are guarded by gates:

| Transition | Gates |
|------------|-------|
| DRAFT -> DISCOVERY | G0 |
| DISCOVERY -> PLANNING | G1 |
| PLANNING -> ACTIVE | G2, G3 |
| ACTIVE -> VERIFICATION | G4 |
| VERIFICATION -> ACCEPTANCE | G5 |
| ACCEPTANCE -> RELEASED | G6, G7 |
| RELEASED -> OPERATING | G8 |
| OPERATING -> ARCHIVED | — |

## Task states

`PENDING`, `READY`, `IN_PROGRESS`, `BLOCKED`, `VERIFYING`, `DONE`, `CANCELLED`.
`BLOCKED` requires a `blocked_reason` and a `resolution_path`.

## Records

- **PROJECT** — identity and lifecycle manifest (`PROJECT.json`).
- **OBJECTIVE** — a goal the project exists to achieve. Separates lifecycle `status`
  (`PROPOSED`, `ACTIVE`, `ACHIEVED`, `ABANDONED`) from `epistemic_status`
  (`OBJECTIVE`, `FACT`, `ASSUMPTION`, `UNKNOWN`). `FACT` requires evidence;
  `ASSUMPTION`/`UNKNOWN` require a rationale.
- **REQUIREMENT** — typed as `REQUIREMENT`, `ASSUMPTION`, `CONSTRAINT`, `RISK`, `IDEA` or
  `UNKNOWN`; carries priority and acceptance criteria. Status `DEFERRED`/`REJECTED` marks a
  requirement as **out of scope**: it is exempt from the "must be approved" (G2.3) and
  "must have evidence" (G5.1) rules, must carry a rationale, and does not block lifecycle
  progression (ADR-0012).
- **TASK** — objective, scope, inputs, dependencies, `authorized_actions`, restrictions,
  acceptance criteria, verification and evidence. Supports `parent_task`/`subtasks`.
- **ARTIFACT** — a concrete **deliverable** produced by executing tasks (`kind`, `location`,
  `produced_by`, `related_evidence`). Distinct from REQUIREMENT (need), TASK (work) and
  EVIDENCE (proof).
- **EVIDENCE** — first-class proof (see `POLICIES/evidence.md`).
- **ACCEPTANCE** — an explicit acceptance **decision** (`result`, `decided_by`,
  `authority`, `evidence`, `gate`). Distinct from the acceptance **criteria** declared on a
  requirement or task. Requires human authority; never auto-approved.
- **DECISION** — context, problem, options, decision, reason, consequences, affected
  components.
- **RELEASE** — version, scope, changes, verification, known issues, deployment, rollback,
  approval, evidence, acceptances.
- **DISCOVERY** — `discovery.json`, validating findings, assumptions, unknowns, constraints
  and risks separately (`SCHEMAS/discovery/discovery.schema.json`).

### Terminology

The generic name for a persisted typed JSON file is a **record**. The word `ARTIFACT`
(upper case) denotes the deliverable entity only. This resolves the ambiguity found in
MASTER-002.

## Traceability

Target chain:

```
OBJECTIVE -> REQUIREMENT -> TASK -> ARTIFACT -> EVIDENCE -> ACCEPTANCE -> RELEASE
```

Link fields (canonical direction):

| From | Field | To |
|------|-------|----|
| OBJECTIVE | `related_requirements` | REQUIREMENT |
| TASK | `related_requirements` | REQUIREMENT |
| ARTIFACT | `produced_by` | TASK |
| EVIDENCE | `related_requirements` / `related_tasks` / `related_artifacts` | REQUIREMENT / TASK / ARTIFACT |
| ACCEPTANCE | `evidence` / `related_requirements` | EVIDENCE / REQUIREMENT |
| RELEASE | `evidence` / `acceptances` | EVIDENCE / ACCEPTANCE |
| any record | `project_id` | PROJECT |

Reverse traceability (`RELEASE -> ACCEPTANCE -> EVIDENCE -> ARTIFACT -> TASK ->
REQUIREMENT -> OBJECTIVE -> PROJECT`) is derived by scanning these fields; `se review`
validates that every reference resolves and that every record's `project_id` matches the
manifest. See `TESTS/test_traceability.py`.

## State semantics

Status-like fields are classified by what they represent, and governed accordingly
(ADR-0014). Governance is applied only where a gate or a decision depends on it.

| Record | Field | Values | Class | Governance |
|--------|-------|--------|-------|------------|
| PROJECT | `lifecycle_state` | DRAFT…ARCHIVED | S5 lifecycle | `se transition` + gates |
| OBJECTIVE | `status` | PROPOSED/ACTIVE/ACHIEVED/ABANDONED | S2 informational | controlled (`--by`) |
| OBJECTIVE | `epistemic_status` | OBJECTIVE/FACT/ASSUMPTION/UNKNOWN | S4 epistemic | schema (FACT⇒evidence) |
| REQUIREMENT | `status` | PROPOSED/APPROVED/IMPLEMENTED/VERIFIED/REJECTED/DEFERRED | S3 decisional | controlled (`--by`); DEFERRED/REJECTED⇒rationale |
| REQUIREMENT | `type` | REQUIREMENT/… | S4 epistemic | controlled (`--by`) |
| TASK | `status` | PENDING/READY/IN_PROGRESS/BLOCKED/VERIFYING/DONE/CANCELLED | S1 process | **guidance** (not enforced; `BLOCKED`⇒reason) |
| ARTIFACT | `status` | PLANNED/IN_PROGRESS/COMPLETE/SUPERSEDED/DISCARDED | S2 informational | normal mutation |
| EVIDENCE | `result` | PASS/FAIL/WARN/INFO | S2 informational | normal mutation (G5.2 reads FAIL) |
| ACCEPTANCE | `result` | ACCEPTED/REJECTED/CONDITIONAL/DEFERRED | S3 decisional | controlled (`--by`); schema (evidence+authority) |
| DECISION | `status` | PROPOSED/ACCEPTED/SUPERSEDED/DEPRECATED/REJECTED | S3 decisional | normal mutation (author + mutation log) |
| RELEASE | `status` | PLANNED/CANDIDATE/APPROVED/RELEASED/ROLLED_BACK | S3 decisional | controlled (`--by`); G7 reads it |
| DISCOVERY | — | (no status field) | — | — |

Classification: **S1** process state, **S2** informational, **S3** decisional, **S4**
epistemic, **S5** lifecycle.

Governance mapping (minimal governance): process state → transition control *only when a
gate depends on the outcome*; human decision → authority/evidence control; epistemic state →
evidence control; descriptive data → normal mutation; project lifecycle → lifecycle gates.

`CORE/tasks/task-states.json` documents the intended task workflow but is **guidance**: a
task status may be set to any schema-valid value through `se update` (BLOCKED still requires
a reason). Gate integrity is outcome-based — G4 requires evidence and artifacts for DONE
deliverable tasks — so skipping intermediate states does not bypass a gate.

## Mutation

Records are created with `se new` and changed with `se update` (`--set`/`--add`/`--remove`).
An update is governed: identity fields are immutable, unknown fields are rejected, the
resulting record is schema-validated and its references must resolve, writes are atomic,
and the original is preserved on any failure. Controlled fields (requirement
`status`/`type`, objective `status`/`epistemic_status`, acceptance `result`/`authority`,
release `status`) require an explicit human `--by`. Each success is appended to
`mutation-log.jsonl` (ADR-0013). Epistemic rules are enforced by the schemas: an objective
may only become `FACT` with linked evidence, and `DEFERRED`/`REJECTED` requirements require
a rationale. The project lifecycle itself is never changed by `se update` — only
`se transition` may do that.

## Gates

Each gate declares conditions that are `automated` (evaluated by tooling) or manual
(`manual_attestation`). A gate passes only if no automated condition fails; a manual
condition is reported as `MANUAL` and is never auto-passed. See `CORE/gates/README.md`.
