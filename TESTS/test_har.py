"""`se har` / `se resume` tests: durable Human Action Requests.

A HAR is the artifact that holds a pending human decision. The wait is the
artifact, the state is the source of truth, and an answer is a durable record
that later rehydrates the execution context via `se resume`.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402


def init_project(root: Path, name="Demo"):
    code, out = support.run_cli(
        "init", "--dir", str(root), "--name", name, "--owner", "owner", "--id", "PRJ-DEMO-001"
    )
    return code, out


def har_create(project: Path, *extra):
    return support.run_cli("har", "create", "--project", str(project), *extra)


class HarLifecycleTests(unittest.TestCase):
    def test_create_records_open_har(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            init_project(project)
            code, out = har_create(
                project, "--requested-action", "Approve prod deploy",
                "--condition", "G3.1", "--condition", "G3.2,G3.3", "--by", "alice",
            )
            self.assertEqual(code, 0, out)
            self.assertIn("PASS: created HAR-0001", out)
            code, out = support.run_cli("har", "show", "HAR-0001", "--project", str(project))
            self.assertEqual(code, 0, out)
            har = json.loads(out[out.index("{"):])
            self.assertEqual(har["state"], "OPEN")
            self.assertEqual(har["project_id"], "PRJ-DEMO-001")
            self.assertEqual(har["conditions"], ["G3.1", "G3.2", "G3.3"])
            self.assertEqual(har["owner"], "alice")

    def test_ids_increment(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            init_project(project)
            har_create(project, "--requested-action", "one")
            har_create(project, "--requested-action", "two")
            code, out = support.run_cli("har", "list", "--project", str(project))
            self.assertEqual(code, 0, out)
            self.assertIn("HAR-0001", out)
            self.assertIn("HAR-0002", out)

    def test_state_is_durable_across_processes(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            init_project(project)
            har_create(project, "--requested-action", "persist me")
            self.assertTrue((project / ".se" / "state.db").exists())
            code, out = support.run_cli("har", "list", "--project", str(project))
            self.assertEqual(code, 0, out)
            self.assertIn("persist me", out)

    def test_invalid_condition_refused_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            init_project(project)
            code, out = har_create(project, "--condition", "BAD", "--requested-action", "x")
            self.assertEqual(code, 1, out)
            self.assertIn("invalid condition format", out)
            code, out = support.run_cli("har", "list", "--project", str(project))
            self.assertIn("No HARs found", out)

    def test_missing_project_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out = har_create(Path(tmp) / "nope", "--requested-action", "x")
            self.assertEqual(code, 1, out)
            self.assertIn("no PROJECT.json", out)

    def test_show_unknown_har_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            init_project(project)
            code, out = support.run_cli("har", "show", "HAR-9999", "--project", str(project))
            self.assertEqual(code, 1, out)
            self.assertIn("not found", out)


class HarStateTests(unittest.TestCase):
    def test_answer_moves_open_to_answered(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            init_project(project)
            har_create(project, "--requested-action", "decide")
            code, out = support.run_cli(
                "har", "answer", "HAR-0001", "--project", str(project),
                "--answer", "approved", "--by", "alice",
            )
            self.assertEqual(code, 0, out)
            code, out = support.run_cli("har", "show", "HAR-0001", "--project", str(project))
            har = json.loads(out[out.index("{"):])
            self.assertEqual(har["state"], "ANSWERED")
            self.assertEqual(har["answer"], "approved")
            self.assertEqual(har["answered_by"], "alice")
            self.assertTrue(har["answered_at"])

    def test_cannot_answer_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            init_project(project)
            har_create(project, "--requested-action", "decide")
            support.run_cli(
                "har", "answer", "HAR-0001", "--project", str(project), "--answer", "a"
            )
            code, out = support.run_cli(
                "har", "answer", "HAR-0001", "--project", str(project), "--answer", "b"
            )
            self.assertEqual(code, 1, out)
            self.assertIn("not OPEN", out)

    def test_cancel_moves_open_to_cancelled(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            init_project(project)
            har_create(project, "--requested-action", "decide")
            code, out = support.run_cli("har", "cancel", "HAR-0001", "--project", str(project))
            self.assertEqual(code, 0, out)
            self.assertIn("cancelled HAR-0001", out)

    def test_expire_moves_open_to_expired(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            init_project(project)
            har_create(project, "--requested-action", "decide")
            code, out = support.run_cli("har", "expire", "HAR-0001", "--project", str(project))
            self.assertEqual(code, 0, out)
            self.assertIn("expired HAR-0001", out)

    def test_past_expiry_surfaces_stale_and_blocks_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            init_project(project)
            har_create(
                project, "--requested-action", "stale",
                "--expires-at", "2020-01-01T00:00:00+00:00",
            )
            code, out = support.run_cli("har", "list", "--project", str(project))
            self.assertEqual(code, 0, out)
            self.assertIn("STALE", out)
            code, out = support.run_cli(
                "har", "answer", "HAR-0001", "--project", str(project), "--answer", "x"
            )
            self.assertEqual(code, 1, out)
            self.assertIn("not OPEN", out)

    def test_list_filters_by_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            init_project(project)
            har_create(project, "--requested-action", "keep open")
            har_create(project, "--requested-action", "to answer")
            support.run_cli(
                "har", "answer", "HAR-0002", "--project", str(project), "--answer", "ok"
            )
            code, out = support.run_cli(
                "har", "list", "--project", str(project), "--state", "OPEN"
            )
            self.assertEqual(code, 0, out)
            self.assertIn("HAR-0001", out)
            self.assertNotIn("HAR-0002", out)


class HarResumeTests(unittest.TestCase):
    def test_resume_requires_answered(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            init_project(project)
            har_create(project, "--requested-action", "decide")
            code, out = support.run_cli(
                "resume", "HAR-0001", "--project", str(project), "--by", "alice"
            )
            self.assertEqual(code, 1, out)
            self.assertIn("not ANSWERED", out)

    def test_resume_reports_frozen_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            init_project(project)
            har_create(project, "--requested-action", "decide")
            support.run_cli(
                "har", "answer", "HAR-0001", "--project", str(project),
                "--answer", "approved", "--by", "alice",
            )
            code, out = support.run_cli(
                "resume", "HAR-0001", "--project", str(project), "--by", "bob"
            )
            self.assertEqual(code, 0, out)
            self.assertIn("Resuming HAR-0001", out)
            self.assertIn("adapter: opencode", out)
            self.assertIn("approved", out)

    def test_resume_records_recovery_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            init_project(project)
            har_create(project, "--requested-action", "decide")
            support.run_cli(
                "har", "answer", "HAR-0001", "--project", str(project), "--answer", "ok"
            )
            support.run_cli(
                "resume", "HAR-0001", "--project", str(project), "--by", "bob"
            )
            code, out = support.run_cli("har", "show", "HAR-0001", "--project", str(project))
            har = json.loads(out[out.index("{"):])
            self.assertEqual(har["recovery"]["last_resumed_by"], "bob")
            self.assertTrue(har["recovery"]["last_resumed_at"])

    def test_resume_unknown_har_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            init_project(project)
            code, out = support.run_cli("resume", "HAR-9999", "--project", str(project))
            self.assertEqual(code, 1, out)
            self.assertIn("not found", out)


if __name__ == "__main__":
    unittest.main()
