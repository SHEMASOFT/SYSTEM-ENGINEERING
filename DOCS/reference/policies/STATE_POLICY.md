# STATE POLICY

Documentary formalization of DESIGN-03 (ARCH-CONVERGENCE-001 · Durable Engineering State).
Decision D03: **DEFER MEMORY + FORMALIZE STATE POLICY + KEEP CURRENT**. This document is **POLICY**:
it describes the **existing** model; it introduces no infrastructure, no new record types, no runtime,
no state machine. Classifications marked POLICY state normative interpretation of the existing
mechanisms as verified during D03; EXISTING/CURRENT facts are those observable in the repository;
DEFERRED and UNKNOWN items are explicitly listed.

Status taxonomy used throughout: `CURRENT / EXISTING` · `VERIFIED` · `DEFERRED` · `UNKNOWN` · `POLICY`.

---

## 1. General principle

- **One canonical source per state class.** Every durable fact belongs to exactly one canonical
  source; everything else is a derived view, a cache, or ephemeral context.
- **Agent chat/context is NOT a source of truth.** It is transient and may be lost; it must be
  reconstructible from canonical sources when durable.
- **Durable memory does not require a separate subsystem** when the information already persists in
  existing records and documentation. This is the current state of SYSTEM-ENGINEERING.
- Durable data must not be duplicated merely for agent convenience.

## 2. Taxonomy — eight regions

Classification keys: CANONICAL · DERIVED · SUPPORTING · EPHEMERAL · UNKNOWN.
Persistence keys: PERSISTENT · RECONSTRUCTIBLE · DERIVED · VERIFIABLE · EPHEMERAL.

### 2.1 PROJECT KNOWLEDGE
- **Existence (CURRENT)**: Yes. `PROJECT.json` (manifest) + per-type records + project `docs/`
  (including SDD when present).
- **Source of truth**: `PROJECT.json` and the per-type records (`objectives`, `requirements`,
  `decisions`, `artifacts`, `evidence`, `acceptances`, `releases`, `discovery`).
- **Classification (POLICY)**: records = CANONICAL; `docs/`/SDD = SUPPORTING (human narrative,
  not authoritative for gates).
- **Persistence**: PERSISTENT. **Reconstructibility**: the graph is RECONSTRUCTIBLE from records;
  untracked narrative discussion is not. **Verifiability**: VERIFIABLE (schemas + `se validate` +
  `se doctor`).
- **Ownership (POLICY)**: human project owner; agents act as producers.

### 2.2 TASK STATE
- **Existence (CURRENT)**: Yes. `tasks/*.json`; status per `CORE/tasks/task-states.json`
  (enforcement `guidance` — ADR-0014); `related_requirements`, `dependencies`, `subtasks`.
- **Source of truth**: the TASK record.
- **Classification (POLICY)**: CANONICAL. **Persistence**: PERSISTENT. **Reconstructibility**:
  RECONSTRUCTIBLE via record graph. **Verifiability**: VERIFIABLE.
- **Ownership**: agent + human owner (record `owner`).
- Partial work must be held in TASK status + EVD + docs, not only in session context.

### 2.3 WORKFLOW STATE
- **Existence (CURRENT)**: **No persistent region**. The only durable process flow is the project
  `lifecycle_state` on `PROJECT.json`.
- **Source of truth**: `PROJECT.json.lifecycle_state` (definitions in `CORE/lifecycle/`).
- **Classification (POLICY)**: **NOT REQUIRED** as a separate region today. ARCH-WORKFLOW-001
  remains DECISION PENDING (no implementation); promotion criteria C1/C2/C3 unchanged.
- Do not create Workflow State.

### 2.4 EXECUTION STATE
- **Existence (CURRENT)**: No parallel Execution State. Covered by `mutation-log.jsonl`
  (accountability, outside the graph — ADR-0013) + EVD records (outcome) + EEX-1 receipt and
  EDG-1 digests (Design-01 conventions, advisory, no runtime).
- **Source of truth**: mutation-log (operation identity) and EVD (result); EEX-1/EDG-1 when produced.
- **Classification (POLICY)**: mutation-log = CANONICAL ACCOUNTABILITY; EVD = CANONICAL.
- Do not create an execution record or state store.

### 2.5 CHECKPOINT STATE
- **Existence (CURRENT)**: Yes, as `CHECKPOINT-###-REPORT/AUDIT.md` documents (SK-0001 procedure).
  Not a record type.
- **Source of truth**: records (facts); the checkpoint holds the **closure/human attestation** plus
  evidence references.
- **Classification (POLICY)**: SUPPORTING but durable; the attestation is the non-reconstructible part.
- **Persistence**: PERSISTENT. **Verifiability**: partial (procedure SK-0001; content references EVD).
- **Ownership**: human attestation + auditor.

### 2.6 EVIDENCE
- **Existence (CURRENT)**: Yes. `evidence/*` records linked to tasks/requirements/artifacts;
  produced by `se verify` / `se review`; gates G5/G6 consume them.
- **Source of truth**: EVD records + digests (EDG-1).
- **Classification (POLICY)**: CANONICAL. **Persistence**: PERSISTENT. **Verifiability**: VERIFIABLE.
- **Ownership**: producer + reviewer attestation (AG-0009).

### 2.7 AGENT CONTEXT
- **Existence (CURRENT)**: Yes (harness session). 
- **Source of truth**: none — EPHEMERAL. Projected derived context = generated `AGENTS.md`.
- **Boundary (POLICY)**: agent context ≠ project knowledge ≠ engineering state; chat is never a
  source of truth.

### 2.8 REPOSITORY STATE
- **Existence (CURRENT)**: working tree (observed), generated `.opencode/` (derived), adapter
  `content_hashes` (derived/observed), manifest pins (authoritative).
- **Classification (POLICY)**: working tree = OBSERVED; generated artifacts = DERIVED
  (regenerable, drift-checked); `MASTER-SYSTEM-MANIFEST.json`, `SYSTEM.json`, `VERSION` =
  AUTHORITATIVE (version); **GIT STATE = UNKNOWN** where the current evidence (no git repository)
  does not allow asserting a concrete state.
- Do not add repository-state infrastructure.

## 3. Canonical sources (verified inventory)

| Mechanism | Classification | Basis |
|---|---|---|
| `PROJECT.json` + per-type records | CANONICAL | ADR-0003, ADR-0006 |
| `mutation-log.jsonl` | CANONICAL ACCOUNTABILITY | ADR-0013 (outside graph) |
| `MASTER SYSTEM/MANIFEST.json`, `SYSTEM.json`, `VERSION`, `CHANGELOG` | CANONICAL | distribution/version |
| `CORE/*`, `SCHEMAS/*`, `POLICIES/*`, `COMMANDS/*`, `DOMAINS/*`, `AGENTS/*`, `SKILLS/*`, `TEMPLATES/*` | CANONICAL (definitions/contracts) | framework source |
| `AGENTS.md` (project) | DERIVED | adapter generator |
| `.opencode/` + `adapter-manifest.json` | DERIVED (cache) | generator idempotent + content_hashes |
| `MASTER-SYSTEM-MANIFEST.json` (per project) | DERIVED (pin) | copy of the distribution pin |
| `docs/`, SDD, `CHECKPOINT-###-*`, `WORK-###-*`, `ARCH-*.md`, `DOCS/*.md` narrative | SUPPORTING | human-readable, not authoritative facts |
| Chat / session / subagent context / tool outputs | EPHEMERAL | harness-owned |
| Git state | UNKNOWN | no git repository observed |

This classification is not altered except on existing documented evidence to the contrary.

## 4. Workflow state

- **WORKFLOW STATE = NOT REQUIRED** currently. Do not create workflow state.
- ARCH-WORKFLOW-001 keeps its current (DECISION PENDING) status; it is not modified.
- The only durable project-level flow is `lifecycle_state` on `PROJECT.json`.

## 5. Execution state

- No parallel Execution State exists. The relevant information is covered by:
  `mutation-log` + EVD + `EEX-1` + `EDG-1`, per DESIGN-01 (EXECUTION_INTEGRITY.md).
- Do not create a new execution record or state store.

## 6. Memory / handoff

- **NO NEW MEMORY LAYER REQUIRED.** Durable memory is already the existing records + evidence +
  mutation-log. Handoff is achieved through persistent mechanisms (records, generated `AGENTS.md`,
  checkpoint documents) and generated documentation; no Handoff Engine.
- Chat is never a source of truth.
- Do not create a Memory Engine.

## 7. Interruption / recovery (nine scenarios)

Scope: what must/should survive and what is reconstructible. No recovery runtime is designed.

| # | Scenario | Requirement | Rationale |
|---|---|---|---|
| 1 | PC shutdown | MUST SURVIVE | all persisted-on-disk state (records, docs, logs, checkpoints) |
| 2 | Session termination | MUST SURVIVE | records / evidence / docs |
| 3 | OpenCode termination | MUST SURVIVE | records / evidence / docs |
| 4 | Agent change | MUST SURVIVE | project knowledge (records) + `AGENTS.md` so another agent can continue |
| 5 | Harness change | MUST SURVIVE (model); `.opencode/` CAN RECONSTRUCT | portable record/schema format + manifest pin; adapter regenerable |
| 6 | Context compaction | MUST SURVIVE (durable state); session context CAN RECONSTRUCT | reconstructible from canonical sources |
| 7 | Partial task execution | MUST SURVIVE | TASK record + status + partial EVD + docs |
| 8 | Evidence without checkpoint | MUST SURVIVE (evidence); checkpoint CAN RECONSTRUCT | checkpoint derives from EVD, **except the human attestation** |
| 9 | Checkpoint without agent context | MUST SURVIVE (checkpoint); agent context CAN RECONSTRUCT | from checkpoint + records + `AGENTS.md` |

**Human attestation may be unrecoverable** (gate/acceptance/release decisions) — that is why
CHECKPOINT and ACC records carry the attestation. Nothing here requires a recovery runtime.

## 8. Repository state

- **GIT STATE = UNKNOWN** wherever current evidence allows no concrete claim. No git state is
  invented; checkpoint "GIT STATE" sections report UNKNOWN in that case.
- Generated `.opencode/` is DERIVED (regenerable, idempotent, drift-checked).
- No repository-state engine.

## 9. Relation with DESIGN-01 (Execution Integrity)

- **EPI-1 (Plan Identity)**: convention over the canonical task-set; belongs to PROJECT/TASK
  planning; not a new durable state.
- **EEX-1 (Execution Receipt)**: convention for execution facts; covered by EXECUTION + EVIDENCE;
  not a new durable store.
- **EDG-1 (Digest Semantics)**: convention for content digests; belongs to EVIDENCE/REPOSITORY.
- These are conventions from DESIGN-01; **they are not converted into new durable state**.

## 10. Durability rule

1. A durable datum must persist in its corresponding canonical source.
2. Derived representations may be regenerated.
3. Agent context may be lost and must be reconstructible from canonical sources.
4. Do not duplicate durable information solely for agent convenience.

## 11. Cost

- No new runtime is introduced by this policy: no DB, no vector store, no memory retrieval, no
  synchronization daemon, no state engine. Runtime cost added by this policy: **zero**.
- No benchmarks are asserted. Detailed metrics remain **UNKNOWN / REQUIRES VERIFICATION**.

## 12. Gaps (not implemented; not features)

1. Prior lack of a unified documentary state policy — **resolved documentally by this document**.
2. Historical attestation debt (missing checkpoint files for some early checkpoints) — **not
   resolved here**.
3. GIT STATE — **UNKNOWN** where applicable.
   These gaps are not transformed into features.

## 13. Architecture creep barrier

Reaffirmed: NO Memory Engine, State Engine, Workflow Engine, Recovery Engine, Persistence Layer or
Context Engine, except on future evidence that clears ACB-01…10.

## 14. Status

- Policy: this document (FORMALIZE STATE POLICY).
- Existing mechanisms described above: CURRENT / EXISTING.
- Verified at authorship: `se validate`, `se doctor`, and the test suite (see §15).
- Deferred: MEMORY LAYER (DEFER MEMORY); workflow promotion (ARCH-WORKFLOW-001 PENDING).
- Unknown: git state; runtime/performance metrics.
- No runtime is marked IMPLEMENTED by virtue of being documented.

## 15. Verification

Editorial verification of this document follows the existing documentary mechanisms
(`_doc_delta_warnings`); no schema change is produced. After writing:
- `se validate` (schemas/agents/domains),
- `se doctor` (baseline 16 PASS / 2 WARN: git_repo, self_containment),
- existing test suite (no regressions expected),
- exact diff: **only `DOCS/STATE_POLICY.md` created**.

Change control (expected and fulfilled): SYSTEM-ENGINEERING = 1 documented file only;
managed projects = 0; external projects = 0; Code = 0; Schemas = 0; Commands = 0; Agents = 0;
Skills = 0; Gates = 0; Adapter = 0; `.opencode` = 0; Version = 0; Commit = 0; Push = 0;
Release = 0.