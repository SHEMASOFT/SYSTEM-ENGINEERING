"""`se review` tests: references, bidirectional consistency, coverage."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402


def rdd(**over):
    """A valid receipt whose `evidence` entries are objects, not ids."""
    data = {
        "schema_version": "1",
        "rdd_id": "RDD-0001",
        "project_id": "PRJ-TEST-001",
        "title": "Review receipt",
        "version": "1.0.0",
        "status": "APPROVED",
        "candidate": {
            "kind": "worktree",
            "ref": "HEAD",
            "hash": "34a906c6694b405f948dc5f1010cd2e29ba0bddf",
        },
        "verdict": "PARTIAL",
        "evidence": [
            {
                "id": "EVD-0001",
                "claim": "Battery ran",
                "result": "PASS",
                "path": "artifacts/battery.log",
            }
        ],
        "reviewer": "tester",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
    }
    data.update(over)
    return data


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

    def test_rdd_object_evidence_is_resolved_not_skipped(self):
        # Regression: an RDD's `evidence` entries are objects, not ids. They used to be
        # fed to the id index, which raised `unhashable type: 'dict'`. Skipping them
        # was not the fix either: the `id` inside each entry is a reference and a
        # dangling one must be reported (it used to produce "no findings").
        support.write_json(self.project / "rdds" / "RDD-0001.json", rdd())
        code, out = support.run_cli("review", "--project", str(self.project))
        self.assertEqual(code, 1, out)
        self.assertIn("unresolved reference EVD-0001", out)

    def test_rdd_object_evidence_resolves_when_the_evd_exists(self):
        support.write_json(self.project / "evidence" / "EVD-0001.json", support.evidence())
        support.write_json(self.project / "rdds" / "RDD-0001.json", rdd())
        code, out = support.run_cli("review", "--project", str(self.project))
        self.assertEqual(code, 0, out)
        self.assertIn("REVIEW: no findings", out)

    def test_string_references_are_still_checked(self):
        # The object-entry guard must not blind the string path.
        support.write_json(
            self.project / "tasks" / "TASK-0001.json",
            support.task(evidence=["EVD-9999"]),
        )
        code, out = support.run_cli("review", "--project", str(self.project))
        self.assertEqual(code, 1, out)
        self.assertIn("unresolved reference EVD-9999", out)


if __name__ == "__main__":
    unittest.main()
