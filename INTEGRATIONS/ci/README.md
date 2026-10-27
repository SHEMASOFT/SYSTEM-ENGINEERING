# CI governance adapter

Platform-neutral adapter that lets any CI provider run SYSTEM-ENGINEERING (SE)
governance over a product repository. GitHub Actions is the first reference
provider; the scripts are provider-independent.

**SE decides; the provider enforces.** These scripts produce verdicts. They do
not protect branches, merge pull requests or attest manual conditions.

## Why this exists

A product repository can keep its SE artifacts (`PROJECT.json`, SDD/ODD, gates
evidence) next to its code. On every pull request the adapter:

1. verifies that the SE release pinned by `PROJECT.json` is the one checked out;
2. runs the canonical `se validate` for the project;
3. evaluates every gate the canonical lifecycle declares for the current state;
4. publishes `se doctor` findings as information;
5. aggregates one verdict and a GitHub Step Summary.

The adapter never duplicates gate conditions, never evaluates them itself and
never mutates project state.

## Model: SE decides, GitHub enforces

| Decision | Owner |
|---|---|
| Which gate applies to a lifecycle transition | `CORE/lifecycle/lifecycle.json` (`transitions[].gates`) |
| Whether a gate condition passes | `SCRIPTS/se_core/gates.py` via `se gate` |
| Whether a manual condition is attested | A human, through `se transition --attest` |
| Whether a pull request can be merged | GitHub: protected branch + required status check |

A green run on an unprotected branch prevents nothing. To enforce governance,
the product repository must:

- protect the target branch (no direct pushes);
- mark the `se-governance` job as a **required status check**;
- optionally require CODEOWNERS review for the paths that carry SE artifacts.

That configuration lives in the product repository. It is not, and cannot be,
provided by SE.

## Files

```
INTEGRATIONS/ci/
  README.md                     this contract
  scripts/
    se_ci_common.py             argv-safe subprocess, envelope parsing, report schema
    se_ci_version.py            release/tag verification (no signature verification)
    se_ci_validate.py           wraps `se validate --project ... --json`
    se_ci_gate.py               resolves + evaluates the declared gates
    se_ci_doctor.py             wraps `se doctor --json` as non-blocking information
    se_ci_report.py             aggregates step reports into one verdict
  workflows/
    se-governance.yml           GitHub Actions reference workflow (copy to product)
    README.md                   install and enforcement checklist
  fixtures/                     generic, non-sensitive projects used by the tests
  tests/                        hermetic regression suite
```

Nothing here changes `CORE/`, `SCHEMAS/`, `COMMANDS/commands.json`, `SCRIPTS/`
or the lifecycle model.

## Exit codes

Every script uses the same contract:

| Code | Name | Meaning |
|---|---|---|
| `0` | `PASS` | Verified and compliant (or informational, for `doctor`) |
| `1` | `FAIL` | Mandatory validation failed (the evidence is in the envelope) |
| `2` | usage | Invalid arguments (argparse) |
| `3` | `OPERATIONAL_ERROR` | Verification was impossible: missing project, engine, dependency, ambiguous gate, unresolved release |
| `4` | `MANUAL_PENDING` | Human attestation is required; CI did not attest |

`3` deliberately means **"I could not check"**, not "non-compliant". It is
never reported as `PASS`. `4` is also never reported as `PASS`: a workflow can
only call governance verified when no mandatory approval is pending.

The adapter derives the verdict from the `se.report/1` envelope, not from the
exit code alone, because SE uses `1` for validation failures and some
operational errors. If the envelope and the exit code disagree, the adapter
fails closed with `3`.

## Machine-readable output

Each step writes `se-ci.report/1`:

```json
{
  "schema": "se-ci.report/1",
  "interface_version": "1.0.0",
  "step": "gate",
  "status": "PASS | FAIL | MANUAL_PENDING | OPERATIONAL_ERROR | INFO",
  "exit_code": 0,
  "blocking": false,
  "project": "/path/to/product",
  "summary": "human-readable verdict",
  "findings": [{"severity": "FAIL", "code": "G2.G2.1", "message": "..."}],
  "manual_conditions": [{"id": "G1.5", "gate": "G1", "description": "..."}],
  "gates": [{"id": "G0", "status": "PASS", "exit_code": 0, "conditions": []}],
  "evidence": {"command": ["se", "gate", "..."], "exit_code": 0},
  "details": {}
}
```

`se_ci_report.py` writes `se-ci.summary/1` with the aggregate status and the
step summaries. Both schemas are additive-only within `interface_version`.
`blocking` is `true` for `FAIL`, `MANUAL_PENDING` and `OPERATIONAL_ERROR`.

Every script accepts `--json` (stdout) and `--output PATH` (also written when
the step fails, so the summary can explain what happened).

## Step contracts

### `se_ci_version.py`

1. `PROJECT.json.master_system_version` must be `X.Y.Z`.
2. The SE checkout's `VERSION` must equal it.
3. A local tag must publish it (`vX.Y.Z` preferred, then `X.Y.Z`).
4. With `--require-exact-tag`, `HEAD` must be the commit that tag points to.
5. With `--remote origin`, the same tag must exist on that remote.

It fails with `3` when any of these cannot be resolved. It reuses the tag
naming contract of `se_core.upgrade.find_tag_for_version`; a regression test
asserts parity with the canonical function so the two cannot drift silently.

**Guarantee limit (explicit):** this proves *tag existence and version
agreement*. A tag is a mutable ref; the adapter performs **no signature
verification** and makes **no claim of cryptographic integrity or trusted
provenance**. `se upgrade` remains the canonical upgrade mechanism.

### `se_ci_validate.py`

Runs `se validate --project <product> --json`. A `FAIL` is exit `1`; the
engine's warnings (`WARN`) stay **informational and non-blocking**, matching
SE's own semantics. Missing `jsonschema` is detected before execution and
reported as operational (`3`), not as a product validation failure.

### `se_ci_gate.py`

Gate applicability is read from the canonical transition, never guessed:

```text
PROJECT.json.lifecycle_state
  -> CORE/lifecycle/lifecycle.json transitions[from = state].gates
  -> `se gate --gate <id>` for every declared gate
```

- A state with exactly one outgoing transition uses that transition.
- A state with several outgoing transitions requires `--to`; without it the
  result is `AMBIGUOUS_TRANSITION` (`3`), never a guessed gate.
- A transition that declares no gate (today `OPERATING -> ARCHIVED`) is
  `NO_APPLICABLE_GATE` (`3`). It is not modified or waived by this increment.
- A missing/invalid `lifecycle_state` is `STATE_MISSING` / `STATE_INVALID` (`3`).
- Any `FAIL` or `WARN` condition makes the gate non-PASS. If no gate has
  `FAIL`/`WARN` but at least one condition is `MANUAL`, the result is
  `MANUAL_PENDING` (`4`).
- There is no flag to evaluate a subset of gates: a PASS always means **every**
  gate declared for the transition passed. A subset could otherwise be
  mistaken for full governance verification.

Two transitions declare two gates (`PLANNING -> ACTIVE`: G2+G3;
`ACCEPTANCE -> RELEASED`: G6+G7). **Both are evaluated.** A PASS requires all
of them to pass.

### `se_ci_doctor.py`

Runs `se doctor --json` against the SE engine and publishes WARN and FAIL
findings in a separate section. It always exits `0` unless the doctor could not
be executed or parsed (`3`). This adapter does not reinterpret existing doctor
semantics, and no doctor finding blocks by itself. If an adopter needs a
specific security/environment condition to block, it must be declared and
tested as an explicit adapter policy in a later increment.

### `se_ci_report.py`

Reads `<step>.json` files from `--input-dir`. Missing expected steps are
`OPERATIONAL_ERROR`, so a crashed step cannot yield a green aggregate.
Precedence: `OPERATIONAL_ERROR` > `FAIL` > `MANUAL_PENDING` > `PASS`. `INFO`
from doctor never changes the verdict.

## Manual attestation policy

Manual conditions are reported, never satisfied. The adapter does not accept an
attestation flag and does not write to the project. When a manual condition is
pending:

- the gate step and the aggregate exit `4`;
- the summary says **HUMAN APPROVAL REQUIRED** and **governance is not verified**;
- the merge stays blocked if the check is required.

The human path remains the existing one: `se transition --attest ... --by ...`
from a trusted environment, or the SE console. CI cannot stand in for that
signature.

## Security

- `permissions: contents: read` in the reference workflow. No secrets, no write
  scopes, no pull-request comments, no artifact uploads.
- Commands are executed as an argv list with no shell. Paths are resolved and
  validated; `--project` never reaches a shell string.
- The adapter writes only the `--output` files requested by the caller.
- No fixture contains product code, credentials or private project paths.
- The engine is checked out at a release tag, not at a moving branch. If the
  required release cannot be resolved, the workflow fails before validating.
- Cross-repository checkout of a **private** SE engine requires a read-only
  token (`SE_REPOSITORY_TOKEN` in the template) because the default
  `GITHUB_TOKEN` is scoped to the product repository. Public engines need no
  secret. Fork pull requests do not receive repository secrets.

## Using it from another CI provider

Run the same scripts with the same arguments and publish their Markdown/JSON:

```bash
python SCRIPTS/.../se_ci_version.py  --project . --se-root /opt/se --json --output reports/version.json
python SCRIPTS/.../se_ci_validate.py --project . --se-root /opt/se --json --output reports/validate.json
python SCRIPTS/.../se_ci_gate.py     --project . --se-root /opt/se --json --output reports/gate.json
python SCRIPTS/.../se_ci_doctor.py   --se-root /opt/se --json --output reports/doctor.json
python SCRIPTS/.../se_ci_report.py   --input-dir reports
```

The provider adapter is responsible for: checking out the product, checking out
the pinned SE release, failing the job when the aggregate exit code is non-zero,
and enforcing the required check. Governance logic stays in SE.

## Tests

```bash
python -m unittest discover -s INTEGRATIONS/ci/tests -p "test_*.py"
```

The suite is hermetic: fixtures are copied to a temporary directory and their
`master_system_version` is aligned with the engine under test. It covers valid
and invalid states, ambiguous gate resolution, missing dependencies, unresolved
releases, failed validation, pending manual conditions, report aggregation and
the absence of shell execution. Version tests create temporary git repositories
and skip only when `git` is unavailable.

## Known limitations

- `OPERATING -> ARCHIVED` has no gate; this adapter fails operationally rather
  than waiving it. Closing that gap requires a lifecycle decision, not an
  adapter change.
- The reference workflow targets `ubuntu-latest`. The scripts are tested on
  Windows and Linux, but additional provider templates (GitLab CI, CodeBuild)
  are intentionally out of scope for this increment.
- A tag proves publication, not integrity: no signing or provenance
  attestation is implemented.
- The adapter runs `se validate` against the pinned engine as well as the
  product, so the engine checkout must be a coherent release. That is the
  intended "pin, don't float" behavior.
