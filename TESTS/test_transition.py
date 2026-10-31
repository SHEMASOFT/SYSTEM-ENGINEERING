"""`se transition` tests: gate-controlled lifecycle advancement."""

from __future__ import annotations

import contextlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core import authority  # noqa: E402

#: The operator token used by the tests below. It must match the temporary file
#: that both `--console-token-file` and `authority.token_path` resolve to.
OPERATOR_TOKEN = "test-operator-token"


@contextlib.contextmanager
def operator_authority():
    """Authorise MANUAL attestation, never touching the real ``~/.config``.

    Yields the argv fragment to append to an attesting call: the temporary file
    is BOTH what ``--console-token-file`` reads and what the patched
    ``authority.token_path`` returns, so verification succeeds in-process.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "token"
        path.write_text(OPERATOR_TOKEN + "\n", encoding="utf-8")
        with mock.patch.object(authority, "token_path", return_value=path):
            yield ("--console-token-file", str(path))


def init_project(root: Path, name="Demo"):
    code, out = support.run_cli(
        "init", "--dir", str(root), "--name", name, "--owner", "owner", "--id", "PRJ-DEMO-001"
    )
    return code, out


def manifest(root: Path):
    return json.loads((root / "PROJECT.json").read_text(encoding="utf-8"))


class TransitionTests(unittest.TestCase):
    def test_valid_transition(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            init_project(project)
            code, out = support.run_cli("transition", "--project", str(project), "--to", "DISCOVERY")
            self.assertEqual(code, 0, out)
            self.assertIn("PASS: lifecycle DRAFT -> DISCOVERY", out)
            self.assertEqual(manifest(project)["lifecycle_state"], "DISCOVERY")
            self.assertEqual(len(manifest(project)["metadata"]["transitions"]), 1)

    def test_invalid_transition_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            init_project(project)
            code, out = support.run_cli("transition", "--project", str(project), "--to", "ACTIVE")
            self.assertEqual(code, 1, out)
            self.assertIn("is not allowed", out)
            self.assertEqual(manifest(project)["lifecycle_state"], "DRAFT")

    def test_gate_fail_blocks_transition(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            init_project(project)
            support.run_cli("transition", "--project", str(project), "--to", "DISCOVERY")
            code, out = support.run_cli("transition", "--project", str(project), "--to", "PLANNING")
            self.assertEqual(code, 1, out)
            self.assertIn("blocked by gate status: FAIL", out)
            self.assertEqual(manifest(project)["lifecycle_state"], "DISCOVERY")

    def test_manual_gate_requires_attestation(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            init_project(project)
            support.run_cli("transition", "--project", str(project), "--to", "DISCOVERY")
            support.run_cli(
                "new", "objective", "--project", str(project),
                "--title", "Objective", "--epistemic-status", "UNKNOWN", "--rationale", "unknown",
            )
            code, out = support.run_cli("transition", "--project", str(project), "--to", "PLANNING")
            self.assertEqual(code, 1, out)
            self.assertIn("requires human attestation", out)
            self.assertEqual(manifest(project)["lifecycle_state"], "DISCOVERY")

            with operator_authority() as auth_args:
                code, out = support.run_cli(
                    "transition", "--project", str(project), "--to", "PLANNING",
                    "--attest", "reviewed", *auth_args,
                )
            self.assertEqual(code, 0, out)
            self.assertEqual(manifest(project)["lifecycle_state"], "PLANNING")
            record = manifest(project)["metadata"]["transitions"][-1]
            self.assertEqual(record["attestation"], "reviewed")

    def test_bypass_attempt_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            init_project(project)
            support.run_cli("transition", "--project", str(project), "--to", "DISCOVERY")
            support.run_cli(
                "new", "objective", "--project", str(project),
                "--title", "Objective", "--epistemic-status", "UNKNOWN", "--rationale", "unknown",
            )
            with operator_authority() as auth_args:
                support.run_cli(
                    "transition", "--project", str(project), "--to", "PLANNING",
                    "--attest", "ok", *auth_args,
                )
            # Jump straight to RELEASED: no such transition exists.
            code, out = support.run_cli("transition", "--project", str(project), "--to", "RELEASED")
            self.assertEqual(code, 1, out)
            self.assertEqual(manifest(project)["lifecycle_state"], "PLANNING")

    def test_nonexistent_state_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            init_project(project)
            code, out = support.run_cli("transition", "--project", str(project), "--to", "BOGUS")
            self.assertEqual(code, 1, out)
            self.assertIn("not a valid state", out)

    def test_nonexistent_project_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out = support.run_cli(
                "transition", "--project", str(Path(tmp) / "nope"), "--to", "DISCOVERY"
            )
            self.assertEqual(code, 1, out)
            self.assertIn("no PROJECT.json", out)

    def test_incoherent_lifecycle_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_project(Path(tmp) / "p")
            support.write_json(project / "PROJECT.json", support.manifest(lifecycle_state="BOGUS"))
            code, out = support.run_cli("transition", "--project", str(project), "--to", "DISCOVERY")
            self.assertEqual(code, 1, out)
            self.assertIn("not a valid state", out)


def reach_manual_gate(project: Path):
    """Move a project to the point where DISCOVERY -> PLANNING needs attestation."""
    init_project(project)
    support.run_cli("transition", "--project", str(project), "--to", "DISCOVERY")
    support.run_cli(
        "new", "objective", "--project", str(project),
        "--title", "Objective", "--epistemic-status", "UNKNOWN", "--rationale", "unknown",
    )


def sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


class TransitionAttestationTests(unittest.TestCase):
    """v1.1: `transition --attest` carries the same guarantees as the `run` actions."""

    def last(self, project: Path):
        return manifest(project)["metadata"]["transitions"][-1]

    def test_bare_attest_records_the_whole_manual_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            reach_manual_gate(project)
            with operator_authority() as auth_args:
                code, out = support.run_cli(
                    "transition", "--project", str(project), "--to", "PLANNING",
                    "--attest", "reviewed", *auth_args,
                )
            self.assertEqual(code, 0, out)
            attested = self.last(project)["conditions_attested"]
            self.assertTrue(attested, "the attested MANUAL set was not recorded")
            for cid in attested:
                self.assertRegex(cid, r"^G\d+\.\d+$")

    def test_named_condition_is_validated_and_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            reach_manual_gate(project)
            with operator_authority() as auth_args:
                code, out = support.run_cli(
                    "transition", "--project", str(project), "--to", "PLANNING",
                    "--attest", "reviewed", "--condition", "G1.5", *auth_args,
                )
            self.assertEqual(code, 0, out)
            self.assertEqual(self.last(project)["conditions_attested"], ["G1.5"])

    def test_unknown_condition_is_refused_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            reach_manual_gate(project)
            before = manifest(project)["lifecycle_state"]
            with operator_authority() as auth_args:
                code, out = support.run_cli(
                    "transition", "--project", str(project), "--to", "PLANNING",
                    "--attest", "reviewed", "--condition", "G9.9", *auth_args,
                )
            self.assertEqual(code, 1, out)
            self.assertIn("not MANUAL conditions", out)
            self.assertEqual(manifest(project)["lifecycle_state"], before)

    def test_attestation_records_actor_condition_revision_and_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            reach_manual_gate(project)
            rev = sha256(project / "PROJECT.json")
            with operator_authority() as auth_args:
                code, out = support.run_cli(
                    "transition", "--project", str(project), "--to", "PLANNING",
                    "--attest", "reviewed", "--by", "alice", *auth_args,
                )
            self.assertEqual(code, 0, out)
            rec = self.last(project)
            self.assertEqual(rec["by"], "alice")           # WHO
            self.assertTrue(rec["conditions_attested"])    # WHAT
            self.assertTrue(rec["at"])                     # WHEN
            self.assertEqual(rec["revision"], rev)         # against WHICH revision
            ctx = rec["context"]["manual_conditions"]      # against WHICH context
            self.assertTrue(ctx)
            self.assertEqual(ctx[0]["status"], "MANUAL")

    def test_transition_is_audited(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            reach_manual_gate(project)
            with operator_authority() as auth_args:
                code, out = support.run_cli(
                    "transition", "--project", str(project), "--to", "PLANNING",
                    "--attest", "reviewed", "--by", "alice", *auth_args,
                )
            self.assertEqual(code, 0, out)
            log = project / "mutation-log.jsonl"
            self.assertTrue(log.exists(), "transition wrote no audit entry")
            entries = [
                json.loads(line)
                for line in log.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(entries[-1]["record_type"], "project")
            self.assertEqual(entries[-1]["record_id"], "PRJ-DEMO-001")
            self.assertEqual(entries[-1]["by"], "alice")

    def test_same_key_replay_does_not_transition_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            reach_manual_gate(project)
            with operator_authority() as auth_args:
                argv = (
                    "transition", "--project", str(project), "--to", "PLANNING",
                    "--attest", "reviewed", "--idempotency-key", "k1", *auth_args,
                )
                code, out = support.run_cli(*argv)
                self.assertEqual(code, 0, out)
                code, out = support.run_cli(*argv)
                self.assertEqual(code, 0, out)
            self.assertIn("replayed", out)
            self.assertEqual(manifest(project)["lifecycle_state"], "PLANNING")
            # DRAFT->DISCOVERY + DISCOVERY->PLANNING, and the replay adds no third.
            self.assertEqual(len(manifest(project)["metadata"]["transitions"]), 2)

    def test_expected_revision_guards_concurrency(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            reach_manual_gate(project)
            rev = sha256(project / "PROJECT.json")
            with operator_authority() as auth_args:
                code, out = support.run_cli(
                    "transition", "--project", str(project), "--to", "PLANNING",
                    "--attest", "reviewed", "--expected-revision", "0" * 64, *auth_args,
                )
                self.assertEqual(code, 1, out)
                self.assertEqual(manifest(project)["lifecycle_state"], "DISCOVERY")
                code, out = support.run_cli(
                    "transition", "--project", str(project), "--to", "PLANNING",
                    "--attest", "reviewed", "--expected-revision", rev, *auth_args,
                )
            self.assertEqual(code, 0, out)
            self.assertEqual(manifest(project)["lifecycle_state"], "PLANNING")


if __name__ == "__main__":
    unittest.main()
