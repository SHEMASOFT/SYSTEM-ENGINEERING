"""Regression tests for the platform-neutral SE CI governance adapter.

Run from the repository root:

    python -m unittest discover -s INTEGRATIONS/ci/tests -p "test_*.py"

The suite is hermetic: fixtures are copied to a temporary directory and their
``master_system_version`` is aligned with the engine under test, so a version
bump does not silently break the tests. No fixture contains product code,
credentials or references to private projects.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
CI_DIR = TESTS_DIR.parent
ROOT = CI_DIR.parents[1]
SCRIPTS_DIR = CI_DIR / "scripts"
FIXTURES = CI_DIR / "fixtures"
ENGINE_SCRIPTS = ROOT / "SCRIPTS"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
if str(ENGINE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(ENGINE_SCRIPTS))

import se_ci_doctor  # noqa: E402
import se_ci_gate  # noqa: E402
import se_ci_version  # noqa: E402
from se_ci_common import (  # noqa: E402
    EXIT_MANUAL_PENDING,
    EXIT_OPERATIONAL,
    EXIT_VALIDATION,
    STATUS_MANUAL_PENDING,
    STATUS_OPERATIONAL_ERROR,
    STATUS_PASS,
    OperationalError,
)

UNSET = object()


def current_version() -> str:
    return (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def parse_json(process: subprocess.CompletedProcess) -> dict:
    try:
        return json.loads(process.stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover - diagnostic aid
        raise AssertionError(
            f"stdout is not JSON (exit {process.returncode}):\n"
            f"STDOUT:\n{process.stdout}\nSTDERR:\n{process.stderr}"
        ) from exc


class AdapterTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="se-ci-test-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def fixture(self, name: str, version=UNSET) -> Path:
        destination = self.root / name
        shutil.copytree(FIXTURES / name, destination)
        if version is UNSET:
            version = current_version()
        if version is not None:
            manifest = destination / "PROJECT.json"
            data = json.loads(manifest.read_text(encoding="utf-8"))
            data["master_system_version"] = version
            manifest.write_text(
                json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n"
            )
        return destination

    def script(self, name: str, *arguments, cwd=None, env=None):
        command = [sys.executable, str(SCRIPTS_DIR / name), *[str(item) for item in arguments]]
        run_env = dict(os.environ)
        run_env.setdefault("PYTHONUTF8", "1")
        run_env.setdefault("PYTHONIOENCODING", "utf-8")
        if env:
            run_env.update(env)
        return subprocess.run(
            command,
            cwd=str(cwd or ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=run_env,
            shell=False,
        )

    def make_engine(self, version: str, *, tag: bool = True, extra_commit: bool = False) -> Path:
        engine = Path(tempfile.mkdtemp(prefix="engine-", dir=self.root))
        (engine / "SCRIPTS").mkdir(parents=True)
        (engine / "SCRIPTS" / "se.py").write_text("", encoding="utf-8")
        (engine / "VERSION").write_text(version + "\n", encoding="utf-8", newline="\n")
        self.git(engine, "init", "-q")
        (engine / "marker.txt").write_text("engine\n", encoding="utf-8")
        self.git(engine, "add", "marker.txt")
        self.git(engine, "-c", "user.email=ci@example.invalid", "-c", "user.name=CI", "commit", "-q", "-m", "init")
        if tag:
            self.git(engine, "tag", f"v{version}")
        if extra_commit:
            (engine / "marker.txt").write_text("engine changed\n", encoding="utf-8")
            self.git(engine, "add", "marker.txt")
            self.git(engine, "-c", "user.email=ci@example.invalid", "-c", "user.name=CI", "commit", "-q", "-m", "after tag")
        return engine

    @staticmethod
    def git(cwd: Path, *arguments: str) -> str:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
        )
        if completed.returncode != 0:
            raise AssertionError(
                f"git {' '.join(arguments)} failed:\n{completed.stderr}\n{completed.stdout}"
            )
        return completed.stdout.strip()


class ValidateTests(AdapterTest):
    def test_valid_fixture_passes(self):
        project = self.fixture("project-valid")
        process = self.script("se_ci_validate.py", "--project", project, "--json")
        report = parse_json(process)
        self.assertEqual(process.returncode, 0)
        self.assertEqual(report["status"], STATUS_PASS)
        self.assertEqual(report["schema"], "se-ci.report/1")
        self.assertFalse(report["blocking"])

    def test_invalid_fixture_fails_validation(self):
        project = self.fixture("project-invalid")
        process = self.script("se_ci_validate.py", "--project", project, "--json")
        report = parse_json(process)
        self.assertEqual(process.returncode, EXIT_VALIDATION)
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(report["blocking"])
        self.assertTrue(
            any("owner" in item["message"] for item in report["findings"]),
            report["findings"],
        )

    def test_missing_project_is_operational(self):
        missing = self.root / "does-not-exist"
        process = self.script("se_ci_validate.py", "--project", missing, "--json")
        report = parse_json(process)
        self.assertEqual(process.returncode, EXIT_OPERATIONAL)
        self.assertEqual(report["status"], STATUS_OPERATIONAL_ERROR)
        self.assertEqual(report["findings"][0]["code"], "PROJECT_PATH")

    @unittest.skipUnless(shutil.which("git"), "git is required to materialize fixtures")
    def test_missing_dependency_is_operational(self):
        project = self.fixture("project-valid")
        blocker = self.root / "blocker"
        blocker.mkdir()
        (blocker / "jsonschema.py").write_text(
            "raise ImportError('simulated missing jsonschema')\n", encoding="utf-8"
        )
        env = {"PYTHONPATH": os.pathsep.join([str(blocker), str(ENGINE_SCRIPTS)])}
        process = self.script(
            "se_ci_validate.py", "--project", project, "--json", env=env
        )
        report = parse_json(process)
        self.assertEqual(process.returncode, EXIT_OPERATIONAL)
        self.assertEqual(report["findings"][0]["code"], "MISSING_DEPENDENCY")


class GateTests(AdapterTest):
    def test_single_declared_gate_passes(self):
        project = self.fixture("project-valid")
        process = self.script("se_ci_gate.py", "--project", project, "--json")
        report = parse_json(process)
        self.assertEqual(process.returncode, 0)
        self.assertEqual(report["status"], STATUS_PASS)
        self.assertEqual([gate["id"] for gate in report["gates"]], ["G0"])
        self.assertEqual(report["details"]["transition"]["gates"], ["G0"])

    def test_manual_condition_is_never_pass(self):
        project = self.fixture("project-manual")
        process = self.script("se_ci_gate.py", "--project", project, "--json")
        report = parse_json(process)
        self.assertEqual(process.returncode, EXIT_MANUAL_PENDING)
        self.assertEqual(report["status"], STATUS_MANUAL_PENDING)
        self.assertTrue(report["blocking"])
        self.assertEqual(
            [condition["id"] for condition in report["manual_conditions"]], ["G1.5"]
        )
        self.assertNotEqual(report["gates"][0]["status"], STATUS_PASS)
        self.assertTrue(
            any("human attestation" in item.lower() for item in [report["summary"]])
        )

    def test_validation_failure_precedes_manual(self):
        project = self.fixture("project-invalid")
        process = self.script("se_ci_gate.py", "--project", project, "--json")
        report = parse_json(process)
        self.assertEqual(process.returncode, EXIT_VALIDATION)
        self.assertEqual(report["status"], "FAIL")

    def test_every_declared_gate_is_evaluated(self):
        project = self.fixture("project-planning")
        process = self.script("se_ci_gate.py", "--project", project, "--json")
        report = parse_json(process)
        self.assertEqual(process.returncode, EXIT_VALIDATION)
        self.assertEqual([gate["id"] for gate in report["gates"]], ["G2", "G3"])
        self.assertEqual(report["details"]["transition"]["gates"], ["G2", "G3"])

    def test_transition_without_gate_is_operational(self):
        project = self.fixture("project-operating")
        process = self.script("se_ci_gate.py", "--project", project, "--json")
        report = parse_json(process)
        self.assertEqual(process.returncode, EXIT_OPERATIONAL)
        self.assertEqual(report["status"], STATUS_OPERATIONAL_ERROR)
        self.assertEqual(report["findings"][0]["code"], "NO_APPLICABLE_GATE")

    def test_missing_state_is_operational(self):
        project = self.fixture("project-state-missing")
        process = self.script("se_ci_gate.py", "--project", project, "--json")
        report = parse_json(process)
        self.assertEqual(process.returncode, EXIT_OPERATIONAL)
        self.assertEqual(report["findings"][0]["code"], "STATE_MISSING")

    def test_invalid_state_is_operational(self):
        project = self.fixture("project-valid")
        manifest = project / "PROJECT.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["lifecycle_state"] = "SOMEWHERE"
        manifest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        process = self.script("se_ci_gate.py", "--project", project, "--json")
        report = parse_json(process)
        self.assertEqual(process.returncode, EXIT_OPERATIONAL)
        self.assertEqual(report["findings"][0]["code"], "STATE_INVALID")

    def test_no_gate_subset_can_be_mistaken_for_a_full_pass(self):
        project = self.fixture("project-planning")
        process = self.script(
            "se_ci_gate.py", "--project", project, "--gate", "G2", "--json"
        )
        self.assertEqual(process.returncode, 2, process.stdout + process.stderr)

    def test_ambiguous_transition_fails_closed(self):
        lifecycle = {
            "states": [{"id": "PLANNING"}, {"id": "ACTIVE"}, {"id": "CANCELLED"}],
            "transitions": [
                {"from": "PLANNING", "to": "ACTIVE", "gates": ["G2", "G3"]},
                {"from": "PLANNING", "to": "CANCELLED", "gates": ["G9"]},
            ],
        }
        with self.assertRaises(OperationalError) as caught:
            se_ci_gate.resolve_transition(lifecycle, "PLANNING")
        self.assertEqual(caught.exception.code, "AMBIGUOUS_TRANSITION")

        target, gates = se_ci_gate.resolve_transition(lifecycle, "PLANNING", "ACTIVE")
        self.assertEqual((target, gates), ("ACTIVE", ["G2", "G3"]))

    def test_missing_transition_and_missing_gates_fail_closed(self):
        no_transition = {"states": [{"id": "OPERATING"}]}
        with self.assertRaises(OperationalError) as caught:
            se_ci_gate.resolve_transition(no_transition, "OPERATING")
        self.assertEqual(caught.exception.code, "TRANSITION_MISSING")

        no_gate = {
            "states": [{"id": "OPERATING"}, {"id": "ARCHIVED"}],
            "transitions": [{"from": "OPERATING", "to": "ARCHIVED", "gates": []}],
        }
        with self.assertRaises(OperationalError) as caught:
            se_ci_gate.resolve_transition(no_gate, "OPERATING")
        self.assertEqual(caught.exception.code, "NO_APPLICABLE_GATE")


@unittest.skipUnless(shutil.which("git"), "git is required for version tests")
class VersionTests(AdapterTest):
    def test_resolved_release_passes(self):
        engine = self.make_engine("1.2.3")
        project = self.fixture("project-valid", version="1.2.3")
        process = self.script(
            "se_ci_version.py", "--project", project, "--se-root", engine, "--json"
        )
        report = parse_json(process)
        self.assertEqual(process.returncode, 0)
        self.assertEqual(report["status"], STATUS_PASS)
        self.assertEqual(report["details"]["tag"], "v1.2.3")
        self.assertEqual(report["details"]["provenance_guarantee"], "tag-existence-only (no signature verification)")

    def test_version_mismatch_is_operational(self):
        engine = self.make_engine("1.2.4")
        project = self.fixture("project-valid", version="1.2.3")
        process = self.script(
            "se_ci_version.py", "--project", project, "--se-root", engine, "--json"
        )
        report = parse_json(process)
        self.assertEqual(process.returncode, EXIT_OPERATIONAL)
        self.assertEqual(report["findings"][0]["code"], "VERSION_MISMATCH")

    def test_unpublished_release_is_operational(self):
        engine = self.make_engine("1.2.3", tag=False)
        project = self.fixture("project-valid", version="1.2.3")
        process = self.script(
            "se_ci_version.py", "--project", project, "--se-root", engine, "--json"
        )
        report = parse_json(process)
        self.assertEqual(process.returncode, EXIT_OPERATIONAL)
        self.assertEqual(report["findings"][0]["code"], "RELEASE_UNRESOLVED")

    def test_exact_tag_is_enforced(self):
        engine = self.make_engine("1.2.3")
        project = self.fixture("project-valid", version="1.2.3")
        process = self.script(
            "se_ci_version.py",
            "--project",
            project,
            "--se-root",
            engine,
            "--require-exact-tag",
            "--json",
        )
        self.assertEqual(process.returncode, 0, process.stdout)

        engine = self.make_engine("1.2.3", extra_commit=True)
        process = self.script(
            "se_ci_version.py",
            "--project",
            project,
            "--se-root",
            engine,
            "--require-exact-tag",
            "--json",
        )
        report = parse_json(process)
        self.assertEqual(process.returncode, EXIT_OPERATIONAL)
        self.assertEqual(report["findings"][0]["code"], "HEAD_NOT_TAGGED")

    def test_expected_ref_must_match(self):
        engine = self.make_engine("1.2.3")
        project = self.fixture("project-valid", version="1.2.3")
        process = self.script(
            "se_ci_version.py",
            "--project",
            project,
            "--se-root",
            engine,
            "--expected-ref",
            "v9.9.9",
            "--json",
        )
        report = parse_json(process)
        self.assertEqual(process.returncode, EXIT_OPERATIONAL)
        self.assertEqual(report["findings"][0]["code"], "REF_MISMATCH")

    def test_unreachable_remote_is_operational(self):
        engine = self.make_engine("1.2.3")
        project = self.fixture("project-valid", version="1.2.3")
        process = self.script(
            "se_ci_version.py",
            "--project",
            project,
            "--se-root",
            engine,
            "--remote",
            "origin",
            "--json",
        )
        report = parse_json(process)
        self.assertEqual(process.returncode, EXIT_OPERATIONAL)
        self.assertIn(
            report["findings"][0]["code"], {"GIT_FAILED", "RELEASE_UNPUBLISHED"}
        )

    def test_remote_must_publish_the_tag(self):
        engine = self.make_engine("1.2.3")
        remote = self.root / "remote.git"
        self.git(self.root, "init", "--bare", "-q", str(remote))
        self.git(engine, "remote", "add", "origin", str(remote))
        project = self.fixture("project-valid", version="1.2.3")
        process = self.script(
            "se_ci_version.py",
            "--project",
            project,
            "--se-root",
            engine,
            "--remote",
            "origin",
            "--json",
        )
        report = parse_json(process)
        self.assertEqual(process.returncode, EXIT_OPERATIONAL)
        self.assertEqual(report["findings"][0]["code"], "RELEASE_UNPUBLISHED")

        self.git(engine, "push", "-q", "origin", "v1.2.3")
        process = self.script(
            "se_ci_version.py",
            "--project",
            project,
            "--se-root",
            engine,
            "--remote",
            "origin",
            "--json",
        )
        self.assertEqual(process.returncode, 0, process.stdout)

    def test_fixture_with_unresolved_version(self):
        engine = self.make_engine("99.99.99", tag=False)
        project = self.fixture("project-version-unresolved", version=None)
        process = self.script(
            "se_ci_version.py", "--project", project, "--se-root", engine, "--json"
        )
        report = parse_json(process)
        self.assertEqual(process.returncode, EXIT_OPERATIONAL)
        self.assertEqual(report["findings"][0]["code"], "RELEASE_UNRESOLVED")

    def test_invalid_declared_version_is_operational(self):
        engine = self.make_engine("1.2.3")
        project = self.fixture("project-valid", version="not-a-version")
        process = self.script(
            "se_ci_version.py", "--project", project, "--se-root", engine, "--json"
        )
        report = parse_json(process)
        self.assertEqual(process.returncode, EXIT_OPERATIONAL)
        self.assertEqual(report["findings"][0]["code"], "VERSION_DECLARED")

    def test_resolver_matches_canonical_engine_function(self):
        from se_core.upgrade import find_tag_for_version as canonical

        samples = [
            (["v1.2.3"], "1.2.3"),
            (["1.2.3"], "1.2.3"),
            (["v1.2.3", "1.2.3"], "1.2.3"),
            (["v1.2.4"], "1.2.3"),
            ([], "1.2.3"),
            (["refs/tags/v1.2.3"], "1.2.3"),
        ]
        for tags, version in samples:
            self.assertEqual(
                se_ci_version.find_tag_for_version(tags, version),
                canonical(tags, version),
                (tags, version),
            )


class DoctorTests(AdapterTest):
    def test_doctor_is_informational(self):
        process = self.script(
            "se_ci_doctor.py", "--se-root", ROOT, "--json"
        )
        report = parse_json(process)
        self.assertEqual(process.returncode, 0, process.stdout)
        self.assertIn(report["status"], {"PASS", "INFO"})
        self.assertFalse(report["blocking"])
        self.assertFalse(report["details"]["blocking"])

    def test_doctor_failures_are_separated_from_the_verdict(self):
        envelope = {
            "details": {
                "summary": {"PASS": 1, "WARN": 1, "FAIL": 1},
                "checks": [
                    {"id": "runtime", "status": "PASS", "detail": "ok"},
                    {"id": "self_containment", "status": "WARN", "detail": "warn"},
                    {"id": "secrets", "status": "FAIL", "detail": "fail"},
                ],
            }
        }
        status, summary, findings, details = se_ci_doctor.summarize(envelope)
        self.assertEqual(status, "INFO")
        self.assertEqual(details["failures"], 1)
        self.assertFalse(details["blocking"])
        self.assertEqual(
            sorted(item["severity"] for item in findings), ["FAIL", "WARN"]
        )
        self.assertIn("informational", summary)

    def test_missing_engine_is_operational(self):
        process = self.script(
            "se_ci_doctor.py", "--se-root", self.root / "missing", "--json"
        )
        report = parse_json(process)
        self.assertEqual(process.returncode, EXIT_OPERATIONAL)
        self.assertEqual(report["status"], STATUS_OPERATIONAL_ERROR)


class ReportTests(AdapterTest):
    def write_step(self, step, status, exit_code, **extra):
        payload = {
            "schema": "se-ci.report/1",
            "interface_version": "1.0.0",
            "step": step,
            "status": status,
            "exit_code": exit_code,
            "blocking": exit_code != 0,
            "project": None,
            "summary": f"{step} {status}",
            "findings": [],
            "manual_conditions": [],
            "gates": [],
            "evidence": {},
            "details": {},
        }
        payload.update(extra)
        path = self.root / f"{step}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def report(self, *expected):
        arguments = ["--input-dir", self.root]
        if expected:
            arguments.extend(["--expect", ",".join(expected)])
        return self.script("se_ci_report.py", *arguments, "--json")

    def test_all_mandatory_steps_pass(self):
        for step in ("version", "validate", "gate"):
            self.write_step(step, "PASS", 0)
        self.write_step("doctor", "INFO", 0)
        process = self.report()
        summary = parse_json(process)
        self.assertEqual(process.returncode, 0)
        self.assertEqual(summary["status"], "PASS")
        self.assertEqual(summary["exit_code"], 0)

    def test_validation_failure_is_reported(self):
        self.write_step("version", "PASS", 0)
        self.write_step("validate", "FAIL", 1, findings=[{"severity": "FAIL", "code": "X", "message": "bad"}])
        self.write_step("gate", "FAIL", 1)
        self.write_step("doctor", "INFO", 0)
        process = self.report()
        summary = parse_json(process)
        self.assertEqual(process.returncode, EXIT_VALIDATION)
        self.assertEqual(summary["status"], "FAIL")

    def test_manual_pending_is_not_a_success(self):
        self.write_step("version", "PASS", 0)
        self.write_step("validate", "PASS", 0)
        self.write_step(
            "gate",
            "MANUAL_PENDING",
            4,
            manual_conditions=[
                {"id": "G1.5", "gate": "G1", "description": "review"}
            ],
        )
        self.write_step("doctor", "INFO", 0)
        process = self.report()
        summary = parse_json(process)
        self.assertEqual(process.returncode, EXIT_MANUAL_PENDING)
        self.assertEqual(summary["status"], "MANUAL_PENDING")
        self.assertEqual(summary["manual_conditions"][0]["id"], "G1.5")
        self.assertNotEqual(summary["status"], "PASS")

    def test_operational_failure_has_precedence(self):
        self.write_step("version", "PASS", 0)
        self.write_step("validate", "OPERATIONAL_ERROR", 3)
        self.write_step("gate", "MANUAL_PENDING", 4)
        self.write_step("doctor", "INFO", 0)
        process = self.report()
        summary = parse_json(process)
        self.assertEqual(process.returncode, EXIT_OPERATIONAL)
        self.assertEqual(summary["status"], "OPERATIONAL_ERROR")

    def test_missing_expected_step_is_operational(self):
        self.write_step("version", "PASS", 0)
        process = self.report()
        summary = parse_json(process)
        self.assertEqual(process.returncode, EXIT_OPERATIONAL)
        self.assertEqual(summary["status"], "OPERATIONAL_ERROR")
        self.assertTrue(
            any(item["code"] == "MISSING_STEP" for item in summary["operational_findings"])
        )

    def test_doctor_info_does_not_change_the_verdict(self):
        for step in ("version", "validate", "gate"):
            self.write_step(step, "PASS", 0)
        self.write_step("doctor", "INFO", 0)
        process = self.report()
        self.assertEqual(process.returncode, 0)
        self.assertEqual(parse_json(process)["status"], "PASS")

    def test_malformed_step_report_is_operational(self):
        self.write_step("version", "PASS", 0)
        self.write_step("validate", "PASS", 0)
        self.write_step("gate", "PASS", 0)
        (self.root / "doctor.json").write_text("{not json", encoding="utf-8")
        process = self.report()
        summary = parse_json(process)
        self.assertEqual(process.returncode, EXIT_OPERATIONAL)
        self.assertEqual(summary["status"], "OPERATIONAL_ERROR")

    def test_status_and_exit_code_must_agree(self):
        self.write_step("version", "PASS", 0)
        self.write_step("validate", "PASS", 1)
        self.write_step("gate", "PASS", 0)
        self.write_step("doctor", "INFO", 0)
        process = self.report()
        summary = parse_json(process)
        self.assertEqual(process.returncode, EXIT_OPERATIONAL)
        self.assertEqual(summary["status"], "OPERATIONAL_ERROR")
        self.assertTrue(
            any(item["code"] == "BAD_STEP_REPORT" for item in summary["operational_findings"])
        )

    def test_unknown_step_status_is_not_pass(self):
        self.write_step("version", "PASS", 0)
        self.write_step("validate", "WARN", 1)
        self.write_step("gate", "PASS", 0)
        self.write_step("doctor", "INFO", 0)
        process = self.report()
        summary = parse_json(process)
        self.assertEqual(process.returncode, EXIT_OPERATIONAL)
        self.assertEqual(summary["status"], "OPERATIONAL_ERROR")

    def test_step_name_must_match_its_report(self):
        self.write_step("version", "PASS", 0)
        self.write_step("validate", "PASS", 0)
        self.write_step("gate", "PASS", 0)
        self.write_step("doctor", "INFO", 0)
        (self.root / "validate.json").write_text(
            (self.root / "gate.json").read_text(encoding="utf-8"), encoding="utf-8"
        )
        process = self.report()
        self.assertEqual(process.returncode, EXIT_OPERATIONAL)
        self.assertEqual(parse_json(process)["status"], "OPERATIONAL_ERROR")

    def test_markdown_explains_manual_and_enforcement_boundary(self):
        self.write_step("version", "PASS", 0)
        self.write_step("validate", "PASS", 0)
        self.write_step(
            "gate",
            "MANUAL_PENDING",
            4,
            manual_conditions=[{"id": "G1.5", "gate": "G1", "description": "review"}],
        )
        self.write_step("doctor", "INFO", 0)
        output = self.root / "summary.md"
        process = self.script("se_ci_report.py", "--input-dir", self.root, "--output", output)
        self.assertEqual(process.returncode, EXIT_MANUAL_PENDING)
        markdown = output.read_text(encoding="utf-8")
        self.assertIn("HUMAN APPROVAL REQUIRED", markdown)
        self.assertIn("not verified", markdown)
        self.assertIn("branch protection", markdown)
        self.assertIn("informational", markdown.lower())


class CommonTests(AdapterTest):
    def test_project_defaults_to_working_directory(self):
        project = self.fixture("project-valid")
        process = self.script("se_ci_gate.py", "--json", cwd=project)
        self.assertEqual(process.returncode, 0, process.stdout)
        self.assertEqual(parse_json(process)["status"], STATUS_PASS)

    def test_project_accepts_the_manifest_file(self):
        project = self.fixture("project-valid")
        process = self.script(
            "se_ci_gate.py", "--project", project / "PROJECT.json", "--json"
        )
        self.assertEqual(process.returncode, 0, process.stdout)

    def test_scripts_never_use_shell_true(self):
        for path in SCRIPTS_DIR.glob("*.py"):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("shell=True", source, path.name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
