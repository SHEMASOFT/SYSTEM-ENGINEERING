"""C1: a MANUAL gate requires the SE-CONSOLE operator token, not just --attest.

`--attest "<any string>"` used to satisfy a MANUAL gate on its own, and `--by`
defaults to the manifest owner, so a caller could self-approve with no identity,
no secret and no separation of duties. This module pins the fix: possession of
the operator token is the proof of authority, and `--by` is audit metadata only.

The real ``~/.config/se-console/token`` is never touched: every test patches
``se_core.authority.token_path`` to a temporary file (support.run_cli invokes
``se_core.cli.main`` in-process, so the patch is live).
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core import authority  # noqa: E402

TOKEN = "test-operator-token-that-must-never-be-recorded"


def init_project(root: Path):
    return support.run_cli(
        "init", "--dir", str(root), "--name", "Demo", "--owner", "owner", "--id", "PRJ-DEMO-001"
    )


def manifest(root: Path):
    return json.loads((root / "PROJECT.json").read_text(encoding="utf-8"))


def reach_manual_gate(project: Path):
    """Move a project to the point where DISCOVERY -> PLANNING needs attestation."""
    init_project(project)
    support.run_cli("transition", "--project", str(project), "--to", "DISCOVERY")
    support.run_cli(
        "new", "objective", "--project", str(project),
        "--title", "Objective", "--epistemic-status", "UNKNOWN", "--rationale", "unknown",
    )
    return project


@contextlib.contextmanager
def stored_token(value: str | None = TOKEN):
    """Patch the stored-token path to a temporary file (None = empty file)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "token"
        path.write_text("" if value is None else value + "\n", encoding="utf-8")
        with mock.patch.object(authority, "token_path", return_value=path):
            yield path


class AttestAuthorityTests(unittest.TestCase):
    def setUp(self):
        # The ambient environment must never sponsor a token by accident.
        base = {k: v for k, v in os.environ.items() if k != "SE_CONSOLE_TOKEN"}
        patcher = mock.patch.dict(os.environ, base, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    # 1 ---------------------------------------------------------------- no token
    def test_attest_without_token_is_refused_and_state_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = reach_manual_gate(Path(tmp) / "p")
            before = manifest(project)
            with stored_token():
                code, out = support.run_cli(
                    "transition", "--project", str(project), "--to", "PLANNING",
                    "--attest", "reviewed",
                )
            self.assertEqual(code, 1, out)
            self.assertIn("requires the SE-CONSOLE operator token", out)
            self.assertIn("REJECTED:", out)
            after = manifest(project)
            self.assertEqual(after["lifecycle_state"], "DISCOVERY")
            self.assertEqual(len(after["metadata"]["transitions"]), len(before["metadata"]["transitions"]))

    # 2 -------------------------------------------------------------- wrong token
    def test_attest_with_wrong_token_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = reach_manual_gate(Path(tmp) / "p")
            with stored_token():
                os.environ["SE_CONSOLE_TOKEN"] = "not-the-operator-token"
                code, out = support.run_cli(
                    "transition", "--project", str(project), "--to", "PLANNING",
                    "--attest", "reviewed",
                )
            self.assertEqual(code, 1, out)
            self.assertIn("verification failed", out)
            self.assertIn("REJECTED:", out)
            self.assertEqual(manifest(project)["lifecycle_state"], "DISCOVERY")

    # 3 ---------------------------------------------------------------- env token
    def test_correct_token_via_environment_is_recorded_as_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = reach_manual_gate(Path(tmp) / "p")
            with stored_token():
                os.environ["SE_CONSOLE_TOKEN"] = TOKEN
                code, out = support.run_cli(
                    "transition", "--project", str(project), "--to", "PLANNING",
                    "--attest", "reviewed",
                )
            self.assertEqual(code, 0, out)
            self.assertEqual(manifest(project)["lifecycle_state"], "PLANNING")
            record = manifest(project)["metadata"]["transitions"][-1]
            self.assertEqual(record["operator_proof"]["method"], "env")
            self.assertEqual(len(record["operator_proof"]["token_fingerprint"]), 12)
            self.assertTrue(record["operator_proof"]["verified_at"])
            # The secret itself is never recorded anywhere in the project.
            raw = (project / "PROJECT.json").read_text(encoding="utf-8")
            self.assertNotIn(TOKEN, raw)

    # 4 --------------------------------------------------------------- file token
    def test_correct_token_via_file_is_recorded_as_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = reach_manual_gate(Path(tmp) / "p")
            with stored_token() as token_file:
                code, out = support.run_cli(
                    "transition", "--project", str(project), "--to", "PLANNING",
                    "--attest", "reviewed", "--console-token-file", str(token_file),
                )
            self.assertEqual(code, 0, out)
            record = manifest(project)["metadata"]["transitions"][-1]
            self.assertEqual(record["operator_proof"]["method"], "file")

    # 5 --------------------------------------------------------------- flag token
    def test_correct_token_via_flag_is_recorded_as_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = reach_manual_gate(Path(tmp) / "p")
            with stored_token():
                code, out = support.run_cli(
                    "transition", "--project", str(project), "--to", "PLANNING",
                    "--attest", "reviewed", "--console-token", TOKEN,
                )
            self.assertEqual(code, 0, out)
            record = manifest(project)["metadata"]["transitions"][-1]
            self.assertEqual(record["operator_proof"]["method"], "flag")
            self.assertNotIn(TOKEN, out)

    # 6 --------------------------------------------- no MANUAL gate, no token at all
    def test_transition_without_manual_conditions_needs_no_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            init_project(project)
            absent = Path(tmp) / "never-created" / "token"
            with mock.patch.object(authority, "token_path", return_value=absent):
                code, out = support.run_cli(
                    "transition", "--project", str(project), "--to", "DISCOVERY"
                )
            self.assertEqual(code, 0, out)
            self.assertIn("PASS: lifecycle DRAFT -> DISCOVERY", out)
            self.assertFalse(absent.exists(), "a non-MANUAL transition touched the token store")

    # 7 ------------------------------------------------------------- actor_source
    def test_actor_source_distinguishes_flag_from_manifest_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = reach_manual_gate(Path(tmp) / "p")
            with stored_token():
                os.environ["SE_CONSOLE_TOKEN"] = TOKEN
                code, out = support.run_cli(
                    "transition", "--project", str(project), "--to", "PLANNING",
                    "--attest", "reviewed",
                )
            self.assertEqual(code, 0, out)
            self.assertEqual(
                manifest(project)["metadata"]["transitions"][-1]["actor_source"],
                "manifest-owner",
            )

        with tempfile.TemporaryDirectory() as tmp:
            project = reach_manual_gate(Path(tmp) / "p")
            with stored_token():
                os.environ["SE_CONSOLE_TOKEN"] = TOKEN
                code, out = support.run_cli(
                    "transition", "--project", str(project), "--to", "PLANNING",
                    "--attest", "reviewed", "--by", "alice",
                )
            self.assertEqual(code, 0, out)
            self.assertEqual(
                manifest(project)["metadata"]["transitions"][-1]["actor_source"],
                "flag",
            )

    # 8 ------------------------------------------ one token, one literal path
    def test_token_path_matches_the_console_reference(self):
        auth_file = support.REPO_ROOT / "SE-CONSOLE" / "console" / "auth.py"
        spec = importlib.util.spec_from_file_location("se_console_auth_reference", auth_file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(authority.token_path(), module.token_path())
        self.assertEqual(
            authority.token_path(),
            Path.home() / ".config" / "se-console" / "token",
        )

    # 9 -------------------------------------------------- empty/unreadable token
    def test_empty_or_unreadable_token_file_fails_closed(self):
        for label, make_path in (
            ("empty", lambda p: p.write_text("", encoding="utf-8")),
            ("directory", lambda p: p.mkdir()),
        ):
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory() as tmp:
                    project = reach_manual_gate(Path(tmp) / "p")
                    path = Path(tmp) / "token"
                    make_path(path)
                    with mock.patch.object(authority, "token_path", return_value=path):
                        code, out = support.run_cli(
                            "transition", "--project", str(project), "--to", "PLANNING",
                            "--attest", "reviewed", "--console-token", TOKEN,
                        )
                    self.assertEqual(code, 1, out)
                    self.assertIn("verification failed", out)
                    self.assertEqual(manifest(project)["lifecycle_state"], "DISCOVERY")
                    self.assertNotIn("Traceback", out)


if __name__ == "__main__":
    unittest.main()
