"""`se health` tests: a review that cannot complete is an error, not a finding.

`se review` exits 1 when it *finds* something, so a non-zero exit code says
nothing about whether the review actually ran. Only a review that could not
complete (an internal error) may fail health.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

DOCTOR_OK = {
    "ok": True,
    "summary": {"PASS": 1, "WARN": 0, "FAIL": 0},
    "results": [
        {"id": "structure", "status": "PASS", "description": "Repository layout", "detail": "ok"},
    ],
}


class HealthReviewTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = support.make_full_project(Path(self._tmp.name) / "proj")

    def tearDown(self):
        self._tmp.cleanup()

    def health(self, *argv):
        """Run `se health` against a deterministic, fast doctor report."""
        from se_core import commands

        with mock.patch.object(commands, "run_doctor", return_value=dict(DOCTOR_OK)):
            return support.run_cli("health", "--project", str(self.project), *argv)

    def break_review(self):
        """Force the review internals to raise (an operation that cannot complete)."""
        from se_core import commands

        return mock.patch.object(commands, "_collect_refs", side_effect=RuntimeError("boom"))

    def add_broken_reference(self):
        support.write_json(
            self.project / "tasks" / "TASK-0002.json",
            support.task(id="TASK-0002", related_requirements=["REQ-9999"]),
        )

    # --- the defect: an operation that did not complete is not a finding ----

    def test_review_that_cannot_run_fails_health(self):
        with self.break_review():
            code, out = self.health()
        self.assertNotEqual(code, 0, out)
        self.assertIn("Overall: FAIL", out)
        self.assertIn("could not complete", out)
        self.assertIn("RuntimeError", out)
        self.assertNotIn("finding(s)", out)

    def test_review_error_is_reported_in_the_json_envelope(self):
        with self.break_review():
            code, out = self.health("--json")
        self.assertNotEqual(code, 0, out)
        envelope = json.loads(out)
        self.assertEqual(envelope["status"], "FAIL", envelope)
        review = envelope["details"]["review"]
        self.assertIn("RuntimeError", review["error"])
        self.assertEqual(review["findings"], [])
        self.assertTrue(
            any("review" in conflict for conflict in envelope["conflicts"]),
            envelope["conflicts"],
        )

    # --- the guards: normal findings must stay normal -----------------------

    def test_findings_are_not_reported_as_an_internal_error(self):
        self.add_broken_reference()
        code, out = self.health()
        self.assertEqual(code, 0, out)
        self.assertIn("finding(s)", out)
        self.assertNotIn("could not complete", out)

    def test_clean_review_keeps_health_green(self):
        code, out = self.health()
        self.assertEqual(code, 0, out)
        self.assertIn("PASS: no findings", out)
        self.assertNotIn("could not complete", out)

    def test_findings_survive_in_the_json_envelope(self):
        self.add_broken_reference()
        code, out = self.health("--json")
        self.assertEqual(code, 0, out)
        review = json.loads(out)["details"]["review"]
        self.assertIsNone(review["error"])
        self.assertTrue(review["findings"], review)


if __name__ == "__main__":
    unittest.main()
