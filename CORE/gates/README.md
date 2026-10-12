# CORE / Gates

Source of truth: [`gates.json`](gates.json).

Nine gates `G0`–`G8` guard the lifecycle transitions. Each gate declares:

- `from_state` / `to_state` — the transition it guards;
- `required_artifacts` — record types that must exist;
- `conditions` — explicit checks. Each condition is either `automated: true` (the
  reference implementation evaluates it) or `automated: false` (manual attestation by a
  human or responsible agent).

The gates are intentionally **not bureaucratic**: only applicable checks run. A gate
whose automated conditions cannot be evaluated in a given environment is reported as
`WARN` (not `PASS`). Manual conditions are reported as `MANUAL` and never auto-passed.

Mapping:

| Gate | Transition | Meaning |
|------|------------|---------|
| G0 | DRAFT → DISCOVERY | Project intake (criticality may be `unknown`) |
| G1 | DISCOVERY → PLANNING | Discovery valid + an OBJECTIVE exists (may be UNKNOWN) |
| G2 | PLANNING → ACTIVE | Requirements ready, traceable to objectives |
| G3 | PLANNING → ACTIVE | Plan ready |
| G4 | ACTIVE → VERIFICATION | Implementation ready, with ARTIFACTs |
| G5 | VERIFICATION → ACCEPTANCE | Verification passed |
| G6 | ACCEPTANCE → RELEASED | Acceptance decision recorded |
| G7 | ACCEPTANCE → RELEASED | Release defined |
| G8 | RELEASED → OPERATING | Operation ready |

Traceability enforced by gates (v0.2.0):

- G1.4 — at least one OBJECTIVE exists.
- G2.5 — every factual OBJECTIVE is covered by a REQUIREMENT.
- G4.4 — every DONE deliverable TASK produced at least one ARTIFACT.
- G6.2 — an ACCEPTANCE record with result `ACCEPTED` exists.

Out-of-scope requirements (ADR-0012):

- G2.3 and G5.1 ignore REQUIREMENTs whose status is `DEFERRED` or `REJECTED`.
- Such requirements must carry a rationale and remain in the graph for traceability.

Run `python SCRIPTS\se.py gate --project <dir> --gate G3` to evaluate a gate.
Manual conditions are reported as `MANUAL` and never auto-passed.
