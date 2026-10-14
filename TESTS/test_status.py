"""`se status` tests: the overall verdict must not ignore failing gates.

`se status` lists every gate it evaluated, so reporting `Overall: PASS` while
gates are failing tells the reader the opposite of what the same output shows
right below. The verdict (and the exit code derived from it) has to aggregate
everything the command reports.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402


class StatusVerdictTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def draft_project(self):
        return support.make_project(self.root / "draft")

    def status(self, project, *argv):
        return support.run_cli("status", "--project", str(project), *argv)

    # --- the defect: failing gates must fail the overall verdict ------------

    def test_failing_gates_are_not_reported_as_an_overall_pass(self):
        code, out = self.status(self.draft_project())
        self.assertNotEqual(code, 0, out)
        self.assertIn("Overall: FAIL", out)
        self.assertRegex(out, r"\[FAIL\s*\] G\d")

    def test_json_verdict_agrees_with_the_human_verdict(self):
        code, out = self.status(self.draft_project(), "--json")
        self.assertNotEqual(code, 0, out)
        envelope = json.loads(out)
        self.assertEqual(envelope["status"], "FAIL", envelope["status"])
        self.assertTrue(
            any(gate["status"] in {"FAIL", "ERROR"} for gate in envelope["details"]["gates"]),
            envelope["details"]["gates"],
        )

    # --- the guard: a project whose gates pass is not failed by them --------

    def test_a_complete_project_is_not_failed_by_its_gates(self):
        project = support.make_full_project(self.root / "full")
        code, out = self.status(project)
        self.assertEqual(code, 0, out)
        self.assertNotIn("Overall: FAIL", out)
        self.assertNotIn("[FAIL", out)


if __name__ == "__main__":
    unittest.main()
