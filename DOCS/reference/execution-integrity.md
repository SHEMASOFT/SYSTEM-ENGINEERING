# EXECUTION INTEGRITY

Documentary implementation of DESIGN-01 (ARCH-CONVERGENCE-001). Status: **DESIGN CLOSED — READY FOR
IMPLEMENTATION (documentation/convention only)**. EPI-1, EEX-1 and EDG-1 are conventions; **they are
not runtime-implemented**. No Plan Engine, Receipt Engine, Execution Engine, Evidence Engine or
Digest Engine is introduced; the architecture extends existing mechanisms only.

Scope of this document: EPI-1 (plan identity), EEX-1 (execution receipt in `EVD.metadata.execution`),
EDG-1 (digest semantics for `checksum`), G5/G6 scope of evidence, consent/authority, cost, and the
architecture creep barrier (ACB-01…10 PASS for DESIGN-01).

---

## 1. EPI-1 — Plan Identity

**Convention / pure function.** No PLAN record, no PLAN schema, no runtime.

```
PLAN_ID = sha256(
  canonical_json({
    project_id,
    tasks: [ { id, type, title, objective, scope, parent_task,
               subtasks, dependencies, related_requirements,
               authorized_actions, acceptance_criteria,
               verification, capability_policy } ··· ]
  })
)
```

### Normative rules

- **Canonical task-set:** all TASK records in the project's `tasks/` with `status != CANCELLED`. Any
  narrower scope must be defined by a DECISION/RELEASE; the default rule is deterministic.
- **Ordering:** `tasks` array sorted by `id` (lexicographic); set-arrays
  (`related_requirements`, `dependencies`, `subtasks`, `authorized_actions`, `acceptance_criteria`)
  sorted lexicographically.
- **Serialization:** compact JSON (no whitespace), keys sorted, empty arrays serialized `[]`,
  UTF-8, no BOM.
- **Included fields (semantic projection):** `id`, `type`, `title`, `objective`, `scope`,
  `parent_task`, `subtasks`, `dependencies`, `related_requirements`, `authorized_actions`,
  `acceptance_criteria`, `verification`, `capability_policy`.
- **Excluded fields:** `status`, `evidence`, `metadata`, `timestamps` (`created_at`, `updated_at`),
  `owner`.
- **Empty plan:** the function is computable, but an empty plan is **not approvable** (G3.1
  `tasks_present`) and no execution receipt may reference it as an approved plan.
- **Invalid records:** if any TASK in the set fails schema validation (`se validate`), `PLAN_ID` is
  **UNDEFINED**; it is not computed.
- **Digest:** `sha256` over the exact canonical bytes, hex, lowercase, 64 characters — the same
  content-digest capability already present in `SCRIPTS/se_core/opencode/generator.py` (referenced,
  **not modified**).

### Stability and relations

- Irrelevant metadata changes (status, evidence, owner, timestamps, free `metadata`) do not change
  the identity. Structural changes (add/remove task or modify an included field) produce a different
  identity and invalidate prior attestations.
- **TASK → plan:** each task belongs to the plan by the selection rule above.
- **EVD → plan:** `EVD.metadata.execution.plan` (EEX-1) holds the `PLAN_ID` of the plan under which
  the evidence was produced.
- **CHECKPOINT → plan:** a checkpoint AUDIT/REPORT (SK-0001) may cite `plan_ref` (and the verified
  EVD ids) as claims; this is a documentation convention, no structural change.

---

## 2. EEX-1 — Execution Receipt (`EVD.metadata.execution`)

**Convention.** The schema already accepts it: `EVD.metadata` is a free object
(`SCHEMAS/evidence/evidence.schema.json`). No EXECUTION record, no new schema, no migration.

| Field | Cardinality | Rule |
|---|---|---|
| `plan` | **REQUIRED** | `^[0-9a-f]{64}$`, equal to the EPI-1 digest of the executed plan. No plan → omit the whole envelope. |
| `task` | **REQUIRED** | `^TASK-\d{4}$`; must belong to the referenced plan's task-set. |
| `actor` | **REQUIRED** | Non-empty; must equal `EVD.collected_by`. |
| `operation` | **REQUIRED** | Non-empty; the real action performed; for test/log/review EVDs it should mirror `EVD.command`. |
| `finished_at` | **REQUIRED** | ISO-8601; bounds the execution window. |
| `result` | **REQUIRED** | Must equal `EVD.result` (consistency; otherwise a review finding). |
| `started_at` | OPTIONAL | CONDITIONAL REQUIRED if `finished_at` is present (temporal pairing). |
| `inputs` | OPTIONAL | Array `[{path, digest}]`; digests CONDITIONAL REQUIRED when reproducibility is claimed. |
| `outputs` | OPTIONAL | Array `[{path, digest}]`; digests CONDITIONAL REQUIRED when reproducibility is claimed. |
| `exit` | OPTIONAL | `DONE | BLOCKED | CANCELLED | NOTED`; align with final task states. |

**Minimum receipt:** `plan`, `task`, `actor`, `operation`, `finished_at`, `result`.

### Execution Receipt ≠ mutation-log.jsonl

| | Execution Receipt (EEX-1) | mutation-log.jsonl (ADR-0013) |
|---|---|---|
| Role | Epistemic evidence of an execution | Accountability/audit of record mutations |
| Location | Inside the schema-validated EVD record | Project-level append-only JSONL, unvalidated |
| Traceability graph | Participates (it is part of the EVD) | Outside the graph |
| Writer | The actor authoring the EVD at collection time | The tool (`se update`) on each successful mutation |
| Consistency | `result` must equal `EVD.result` | None; not evidence |

The receipt does not substitute the mutation log and the mutation log does not substitute the
receipt. A `se update` touching an EVD writes to the log but does not edit the receipt; the receipt is
written when the EVD is authored.

### The EVD remains the epistemic source

The claim lives in `EVD.result`, `type`, `command`, `checksum`, `location`. The receipt is metadata
about how the evidence came to exist: it contextualizes and enables independent reproduction
(`verification-review`, SK-0002) via digests; it does not itself prove anything. Gates `se verify` /
`se review` ignore `metadata`, so the receipt cannot displace the EVD's epistemic position.

### Backward compatibility

Existing EVDs without a receipt remain valid and pass gates (envelope optional). The `execution` key
inside `metadata` is a reserved convention applied forward; pre-existing uses are not modified. No
migration is required.

---

## 3. EDG-1 — Digest Semantics

**Convention + documentation.** Requirement class: **A (documentation) + B (convention)**.
**C (validation improvement)** is optional/deferred. **D (gate participation) is NO.** **E: none.**

```
checksum = SHA-256(raw bytes at location)
```

### Rules

- **Algorithm:** SHA-256 over the raw bytes of the file addressed by `location`; hex lowercase, 64
  characters.
- **No normalization:** no BOM stripping, no line-ending translation, no re-encoding. Reproducibility
  means byte-identical content (the same principle as the generator's deterministic output).
- **Missing `location`:** a checksum cannot be asserted; it is not fabricated and is treated as
  absent for gate-supporting purposes.
- **Changed content:** re-computing produces a mismatch → informational detection, not an auto-fix.
  Remedies: update `checksum` (via `se update --set checksum=...`, which is an editable,
  non-controlled field) or re-create the record.
- **Invalid checksum:** a value that is not 64 lowercase hex (or a non-sha256 algorithm) is treated
  as absent for verification; never guessed.
- **Optional:** `checksum` remains optional in both schemas
  (`SCHEMAS/evidence/evidence.schema.json`, `SCHEMAS/artifact/artifact.schema.json`). The existing
  ART/EVD checksum fields remain compatible with this semantics when declared. Recording one is
  **RECOMMENDED** for EVDs supporting gates G4/G5, not required.
- **Not authenticity:** a checksum alone is not an authenticity guarantee. It proves byte integrity
  at collection time, nothing about origin or authority.
- **Verification responsibility:** recorded by the authoring actor at collection time; verified by
  independent re-computation during review (`se review` / verification-review, SK-0002) as an
  informational check. There is no runtime verification in the toolchain today.
- **Reproducibility:** digest + `EVD.command`/`operation` + input/output digests enable re-executing
  and comparing bytes. Strong verification/reproduction remains conditioned on evidence and on the
  applicable verification mechanism (`POLICIES/evidence.md`).

No new gate is created; the existing `checksum` continues to be compatible with this semantics.

---

## 4. G5 / G6 — documentable claims

Both gates are documented as **PARTIAL**.

**G5 (VERIFICATION PASSED → ACCEPTANCE)** supports record-level claims only:
- Existential: every REQUIREMENT is linked to at least one EVD (G5.1).
- Declared outcome: no EVD has `result: FAIL` (G5.2).
- Attestation: a human attests the review (G5.3).

**G6 (ACCEPTANCE → RELEASED)** supports record-level claims only:
- Existence of a `uat` EVD with `result: PASS` (G6.1).
- Existence of an ACCEPTANCE record with `result: ACCEPTED` created by a human authority,
  never auto-approved (G6.2).
- Owner attestation (G6.3).

**Not guaranteed (UNKNOWN / REQUIRES VERIFICATION):** authenticity of the evidence, reproducibility,
effective authority beyond the contractual mechanism, actual execution. Gates G5/G6 are **not
modified and not extended**; deeper claims require evidence and the applicable verification mechanism
(SK-0002 independent reproduction) to move from UNKNOWN to VERIFIED.

---

## 5. Consent / Authority — KEEP CURRENT

No new authority system. Authority continues through the existing mechanism:

- `ACCEPTANCE` first-class records (never auto-approved, G6.2).
- Controlled fields requiring `--by` (`commands.py` CONTROLLED_FIELDS).
- Manual gates requiring `--attest` (`se transition`).
- Capability governance CP-020: `authorized_actions` + resolved `capability_plan`.

An execution receipt documents the actor and operation; it does not confer authority.

---

## 6. Cost

The conventions are **opt-in at authorship time** and add no runtime operations by themselves
(documentation/convention only; nothing in the toolchain executes them). Therefore:

- **runtime cost = INFERRED / practically zero for unused paths.**

This is a design property, not a benchmark. Real metrics for TOKEN, LATENCY, TOOL CALLS, STATE SIZE,
MAINTENANCE and CONTEXT OVERHEAD remain **UNKNOWN / REQUIRES VERIFICATION** (no instrumented runtime
evidence).

---

## 7. Architecture creep barrier

ACB-01…10 **PASS for DESIGN-01** (recorded in the design closure). The document does not introduce a
Plan Engine, a Receipt Engine, an Execution Engine, an Evidence Engine or a Digest Engine. Every
mechanism here extends existing ones: the task-set (plan identity), `EVD.metadata`
(execution receipt), and the existing `checksum` fields (digest semantics).

---

## 8. Documentary status

DESIGN CLOSED — READY FOR IMPLEMENTATION, with implementation authorized **only** for
documentation/conventions. EPI-1, EEX-1 and EDG-1 are conventions and are **not** marked as runtime
IMPLEMENTED. Related decision record: `DOCS/adr/ADR-0021-plan-identity.json` (EPI-1).