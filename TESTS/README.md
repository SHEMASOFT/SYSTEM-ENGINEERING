# TESTS

Hermetic tests for the Master System itself. No network, no external APIs, no
production infrastructure; temporary directories only.

Run all tests:

```powershell
python TESTS\run_tests.py
```

or

```powershell
python -m unittest discover -s TESTS -p "test_*.py"
```

| Test | Covers |
|------|--------|
| `test_schemas.py` | PROJECT / REQUIREMENT / TASK / DECISION / EVIDENCE / RELEASE schemas |
| `test_objective.py` | OBJECTIVE schema, epistemic status, project reference |
| `test_artifact.py` | ARTIFACT schema, produced_by, orphan reference |
| `test_acceptance.py` | ACCEPTANCE schema, authority, evidence, orphan reference |
| `test_discovery.py` | DISCOVERY schema and unknown representation |
| `test_criticality.py` | `unknown` valid, invalid rejected, no silent default |
| `test_traceability.py` | Direct and reverse chain traversal |
| `test_lifecycle.py` | Lifecycle states, transitions, BLOCKED as a condition |
| `test_task_states.py` | Task states and transitions |
| `test_gates.py` | Gate model integrity + gate evaluation (G0-G8) |
| `test_agents.py` | 12 agent definitions, schema validity, no DESTRUCTIVE |
| `test_domains.py` | Domain pack contract, software FULL, others MINIMAL |
| `test_doctor.py` | Doctor results, summary consistency, failure on empty dir |
| `test_commands.py` | init/explore/plan/release/review/gate/doctor behaviour |
| `test_init.py` | init seeding, idempotency, no-overwrite |
| `test_new.py` | record creation from templates, validation, no-overwrite |
| `test_update.py` | controlled mutation: positive P1–P17 and adversarial N1–N16 |
| `test_deferred.py` | ADR-0012 DEFERRED/REJECTED semantics |
| `test_transition.py` | gate-controlled lifecycle transitions and bypass prevention |
| `test_review.py` | references, project_id, duplicates, bidirectional consistency, coverage |
| `test_invalid_input.py` | Rejection of malformed and invalid input |

`support.py` provides fixture builders, `run_cli`, and path setup.
