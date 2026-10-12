# Minimum Context / On-Demand Context Policy

Status: **POLICY (design-only, adopted in ADR-0022).** This document defines how future
read-only automation (AUTO-02 and siblings) must select and emit context. It introduces no
runtime, no engine, no schema, and no store. It is doctrinal interpretation layered on the
existing rule: **one canonical source per state class; chat/memory is never a source of truth**
(`DOCS/STATE_POLICY.md`).

Principle: **MINIMUM CONTEXT, ON DEMAND — automate operations, not authority.**

---

## 1. Principle

The default output of any read-only aggregation is the **smallest set of persisted facts
sufficient to answer the requested operation**. It must never return "everything" by default.
Broader context is requested explicitly.

This is an architectural rule about **what is sent to the model**, not a promise of a measured
saving (see §7).

## 2. Non-negotiable constraints

AUTO-02 (and any read-only aggregation):

- MUST NOT run automatically on every session (it is always available, never auto-executed).
- MUST NOT load all of SYSTEM-ENGINEERING.
- MUST NOT load all of a project.
- MUST NOT load every Requirement/Task/Evidence/Artifact/Decision.
- MUST NOT turn the persisted state into a dump.
- MUST NOT replace the Agent's reasoning.
- MUST NOT create a parallel memory or a second source of truth.
- MUST NOT mutate anything.

It operates as a **deterministic, selective query over persisted state**.

## 3. Context levels

| Level | Name | Adds | Selection basis |
|---|---|---|---|
| 0 | IDENTITY | project identity, lifecycle_state, current/next gate + status, `blocked`, version, master_system_version | always |
| 1 | WORK | objective(s), active/selected task, its dependencies, blockers | selected task (or explicit focus) |
| 2 | AUTHORITY | `authorized_actions`, capability resolution, applicable restrictions | selected task + resolved capability plan |
| 3 | TRACE | relevant requirements, artifacts, evidence, decisions, acceptance state | transitive link closure of the selected task |
| 4 | DEEP | expanded sets of Requirements/Tasks/Evidence/Artifacts/Decisions | explicit request only |

**Refinement on the proposed levels (justified):** levels alone are ambiguous because
"relevant" is not defined. This policy binds each level above 0 to a **deterministic selector**:
the focused object (a task id, or a requirement/objective id) and its **bounded transitive link
closure** using the existing `REFERENCE_TARGETS` direction. If no focus is given, LEVEL 1 selects
the single active task (`IN_PROGRESS` > `READY` > `PENDING`), or the task at the head of the
current gate; if none exists, LEVEL 1 returns an empty set with an explicit `warning`, never a
full dump. This keeps relevance computable and reproducible rather than guessed.

## 4. Selection principle

```
DEFAULT = smallest sufficient context
```

The operation returns the minimum data sufficient for the requested question/operation.
Never return "all" by default. Lists are **reference-first**: id + the minimal fields needed for
the operation (status, relations, timestamps), not full record bodies. Full bodies are LEVEL 4.

## 5. Requesting broader context

Broader context is requested explicitly by scope, conceptually:

```
scope=identity   # LEVEL 0 (default)
scope=work       # LEVEL 1
scope=authority  # LEVEL 2
scope=trace      # LEVEL 3
scope=deep       # LEVEL 4 (explicit)
```

plus an optional `focus=<ID>` (TASK/REQ/OBJ). No CLI is implemented in this phase. The scope
name is the stable selector; levels are a convenience label.

## 6. Never included automatically

The following MUST NOT appear in a minimum/default context:

- the whole `CORE/` (lifecycle, gates, permissions, registries);
- full history (checkpoint/work/arch narrative, CHANGELOG);
- unrelated documents;
- all Requirements, all Tasks, all Evidence, all Artifacts, all Decisions;
- logs and the full `mutation-log.jsonl`;
- full bodies of unrelated artifacts when metadata/reference suffices;
- data belonging to any other project (any project other than the focused one).

## 7. Token impact — measured vs expected

- **Measured:** NONE. There is **NO EMPIRICAL TOKEN MEASUREMENT** yet. No percentage saving is
  claimed or promised.
- **Expected behavior (INFERRED):** a default-minimum envelope emits far fewer tokens than
  loading the project or running several full commands whose outputs are read in full.
- **Architectural benefit (design):** the model receives only what the operation needs, keeping
  context focused and reproducible; breadth is opt-in.
- **Evidence status:** token/runtime metrics remain **UNKNOWN / REQUIRES VERIFICATION**.

The decision is architectural: minimize context sent to the model; do not promise a figure.

## 8. Source of truth

The canonical files and project state remain the single source of truth:

- `PROJECT.json` + per-type records (`objectives/`, `requirements/`, `tasks/`, `artifacts/`,
  `evidence/`, `decisions/`, `acceptances/`, `releases/`, `discovery.json`);
- `mutation-log.jsonl` (accountability, outside the graph);
- `CORE/`, `SCHEMAS/`, `POLICIES/`, `COMMANDS/`, `AGENTS/`, `SKILLS/`, `DOMAINS/`, `TEMPLATES/`.

No SQLite, no new store, no cache-as-truth is created in this phase. A future SE-CONSOLE remains
a **consumer** of deterministic operations; it is never the source of truth.

## 9. Authority

Unchanged. The policy adds no authority and removes none. It reads state and prints; it never
approves, never transitions, never converts UNKNOWN into VERIFIED, never self-attests. Gate and
acceptance authority stay with the existing mechanisms (`se gate`/`se transition` with human
attestation; `ACCEPTANCE` records; controlled fields requiring `--by`).

## 10. Verification and status

- Policy: this document (adopted via ADR-0022).
- Existing mechanisms referenced: read-only, CURRENT.
- Runtime: **partially implemented** — B1 (AUTO-16 `--json` serialization on the five read-only
  inspection commands) and B2 (AUTO-02 `se context`, LEVEL 0–4 with bounded closure) are
  implemented and tested; see `SE-AUTOMATION-001B-B2-REPORT.md`.
- Deferred: B3 (AUTO-07/08 skill + adapter conformance) under separate authorization.

## References

`DOCS/adr/ADR-0022-readonly-aggregation-minimum-context.json` · `DOCS/STATE_POLICY.md` ·
`DOCS/EXECUTION_INTEGRITY.md` · `DOCS/CAPABILITY_GOVERNANCE.md` ·
`SE-AUTOMATION-001A` (AUTO-01..AUTO-16) · `SE-SKILL-RECON-001`.
