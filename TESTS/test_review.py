"""`se review` tests: references, bidirectional consistency, coverage."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = support.make_project(Path(self._tmp.name) / "proj")

    def tearDown(self):
        self._tmp.cleanup()

    def test_valid_references(self):
        support.write_json(self.project / "requirements" / "REQ-0001.json", support.requirement())
        support.write_json(self.project / "objectives" / "OBJ-0001.json", support.objective())
        code, out = support.run_cli("review", "--project", str(self.project))
        self.assertEqual(code, 0, out)
        self.assertIn("REVIEW: no findings", out)

    def test_broken_reference(self):
        support.write_json(
            self.project / "tasks" / "TASK-0001.json",
            support.task(related_requirements=["REQ-9999"]),
        )
        code, out = support.run_cli("review", "--project", str(self.project))
        self.assertEqual(code, 1, out)
        self.assertIn("unresolved reference REQ-9999", out)

    def test_wrong_project_id(self):
        support.write_json(
            self.project / "objectives" / "OBJ-0001.json",
            support.objective(project_id="PRJ-OTHER-001"),
        )
        code, out = support.run_cli("review", "--project", str(self.project))
        self.assertEqual(code, 1, out)
        self.assertIn("does not match manifest", out)

    def test_duplicate_id(self):
        support.write_json(self.project / "requirements" / "REQ-0001.json", support.requirement())
        support.write_json(
            self.project / "requirements" / "REQ-0001-copy.json", support.requirement()
        )
        code, out = support.run_cli("review", "--project", str(self.project))
        self.assertEqual(code, 1, out)
        self.assertIn("duplicate id REQ-0001", out)

    def test_orphan_coverage_gap_is_informational(self):
        support.write_json(self.project / "requirements" / "REQ-0001.json", support.requirement())
        code, out = support.run_cli("review", "--project", str(self.project))
        self.assertEqual(code, 0, out)
        self.assertIn("gap: requirements not linked to an objective", out)

    def test_bidirectional_mismatch_reported_as_note(self):
        # related_* lists are non-exhaustive associations, so a missing reverse entry is
        # reported as an informational note, not as a failure (no redundancy is required).
        support.write_json(
            self.project / "requirements" / "REQ-0001.json",
            support.requirement(related_tasks=["TASK-0001"]),
        )
        support.write_json(
            self.project / "requirements" / "REQ-0002.json",
            support.requirement(id="REQ-0002"),
        )
        support.write_json(
            self.project / "tasks" / "TASK-0001.json",
            support.task(related_requirements=["REQ-0002"]),
        )
        code, out = support.run_cli("review", "--project", str(self.project))
        self.assertEqual(code, 0, out)
        self.assertIn("LINK NOTES", out)
        self.assertIn("omits REQ-0001", out)

    def test_full_coverage_has_no_gaps(self):
        project = support.make_full_project(Path(self._tmp.name) / "full")
        code, out = support.run_cli("review", "--project", str(project))
        self.assertEqual(code, 0, out)
        self.assertIn("no coverage gaps", out)

    def test_incomplete_coverage_reports_gap(self):
        support.write_json(self.project / "requirements" / "REQ-0001.json", support.requirement())
        support.write_json(self.project / "tasks" / "TASK-0001.json", support.task())
        code, out = support.run_cli("review", "--project", str(self.project))
        self.assertEqual(code, 0, out)
        self.assertIn("gap:", out)


if __name__ == "__main__":
    unittest.main()
