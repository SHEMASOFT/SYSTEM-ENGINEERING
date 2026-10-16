# Architecture Decision Records

ADRs conform to `SCHEMAS/decision.schema.json`. They are the recorded decisions for the
Master System itself (`project_id: PRJ-SYSTEM-ENGINEERING`).

| ADR | Decision |
|-----|----------|
| [ADR-0001](ADR-0001-python-reference-implementation.json) | Python 3 reference implementation |
| [ADR-0002](ADR-0002-json-schema-and-json.json) | JSON Schema 2020-12 + JSON data (not YAML) |
| [ADR-0003](ADR-0003-file-per-artifact-storage.json) | File-per-artifact JSON storage |
| [ADR-0004](ADR-0004-tool-independence.json) | Tool independence via an adapter layer |
| [ADR-0005](ADR-0005-gate-transition-mapping.json) | Gate-to-transition mapping |
| [ADR-0006](ADR-0006-first-class-objective-artifact-acceptance.json) | OBJECTIVE / ARTIFACT / ACCEPTANCE as first-class records |
| [ADR-0007](ADR-0007-criticality-unknown-no-silent-default.json) | Criticality `unknown`; no silent default |
| [ADR-0008](ADR-0008-discovery-schema.json) | Discovery report schema |
| [ADR-0009](ADR-0009-transition-gate-controller.json) | `transition` as a gate controller |
| [ADR-0010](ADR-0010-record-creation-and-init-seeding.json) | Record creation from templates and init seeding |
| [ADR-0011](ADR-0011-non-exhaustive-related-links.json) | `related_*` links are non-exhaustive (notes, not failures) |
| [ADR-0012](ADR-0012-deferred-requirements-gate-treatment.json) | Deferred/REJECTED requirements are out of scope (RESOLVED in MASTER-006) |
| [ADR-0013](ADR-0013-mutation-audit-log.json) | Mutation audit via `mutation-log.jsonl` |
| [ADR-0014](ADR-0014-state-semantics-policy.json) | Minimal-governance state semantics (task graph is guidance) |
| [ADR-0015](ADR-0015-opencode-adapter-architecture.json) | OpenCode adapter architecture (generation + execution, adapter-only bridge) |
| [ADR-0016](ADR-0016-master-system-distribution.json) | MASTER SYSTEM as pinned versioned distribution layer |
| [ADR-0017](ADR-0017-generation-pipeline.json) | Contract-to-OpenCode generation pipeline with drift detection |
| [ADR-0018](ADR-0018-precedence-and-naming.json) | Precedence rules + prefixed naming + collision check |
| [ADR-0019](ADR-0019-agent-lifecycle.json) | Agent lifecycle bound to Master System releases |
| [ADR-0020](ADR-0020-contract-layer.json) | Canonical contract layer for agents and commands |
| [ADR-0021](ADR-0021-plan-identity.json) | Plan identity (EPI-1) as a deterministic convention |
| [ADR-0022](ADR-0022-readonly-aggregation-minimum-context.json) | Read-only aggregation surface + minimum-context/on-demand policy |
| [ADR-0023](ADR-0023-auto-01-health-specification.json) | AUTO-01 Health specification for read-only health aggregation |
| [ADR-0024](ADR-0024-intent-plan-envelopes.json) | Intent and plan envelopes |
| [ADR-0025](ADR-0025-workflow-node-context-budget.json) | Per-node context budget in the workflow schema |
| [ADR-0026](ADR-0026-workflow-checkpoint-recovery.json) | Workflow checkpoint recovery (`--resume-from`) |
| [ADR-0027](ADR-0027-internal-memory-replacing-engram.json) | Internal memory replacing Engram (semantic, in-repo) |

These files are also validated by the test suite as real DECISION artifacts, exercising the
decision schema in practice.
