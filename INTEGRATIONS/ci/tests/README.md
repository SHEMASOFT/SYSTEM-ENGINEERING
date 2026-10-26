# Adapter tests

The suite is hermetic and uses only the Python standard library plus `git` for
the version tests.

```bash
python -m unittest discover -s INTEGRATIONS/ci/tests -p "test_*.py"
```

From the repository root. The same command runs on Linux and Windows.

The suite is also part of the master system run: `TESTS/run_tests.py` discovers
every `INTEGRATIONS/*/tests` directory, so `python TESTS/run_tests.py` (and the
CI "Tests" step that calls it) covers it without a per-integration step. Run the
command above to isolate this suite while debugging it.

## What is covered

| Area | Cases |
|---|---|
| `se_ci_validate.py` | valid fixture, schema-invalid fixture, missing project, missing `jsonschema`, envelope/exit consistency |
| `se_ci_gate.py` | single gate PASS, two declared gates, manual condition (exit 4, never PASS), validation failure, ambiguous transition, missing/invalid state, transition without gate (`OPERATING`), no gate-subset bypass |
| `se_ci_version.py` | resolved release, version mismatch, missing tag, exact-tag enforcement, expected-ref mismatch, unreachable remote, tag not published on the remote, invalid declared version, parity with `se_core.upgrade.find_tag_for_version` |
| `se_ci_doctor.py` | informational outcome with WARN/FAIL findings, separated findings, missing engine |
| `se_ci_report.py` | all-pass, validation failure, manual pending, operational precedence, missing expected step, doctor isolation, malformed report, Markdown boundary text |
| Common | default `--project` from the working directory, `PROJECT.json` as `--project`, no shell execution |

Fixtures live in `../fixtures/`. They are generic projects; **no private
product code, credentials or private project paths are used**. Tests copy each
fixture to a temporary directory and rewrite `master_system_version` to the
engine's `VERSION`, so a version bump does not silently break the suite. The
`project-version-unresolved` fixture is intentionally not rewritten.

## Version tests

`VersionTests` builds temporary git repositories with a `VERSION` file and a
release tag. They skip only when `git` is not on `PATH`.

## Cross-platform validation

The suite is run on Windows and Linux as part of the increment's evidence. The
GitHub Actions reference workflow itself is not executed by this repository's
CI (it is a template under `INTEGRATIONS/ci/workflows/`); it must be copied to a
product repository and observed in a real run before claiming a green workflow.
