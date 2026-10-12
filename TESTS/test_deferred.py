"""ADR-0012 tests: DEFERRED/REJECTED requirement semantics."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.gates import evaluate_gate  # noqa: E402
from se_core.schemas import validate  # noqa: E402


class DeferredSemanticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schemas = support.schemas()

    def test_deferred_requires_rationale(self):
        self.assertNotEqual(
            validate(support.requirement(status="DEFERRED"), self.schemas["requirement"]), []
        )
        self.assertEqual(
            validate(
                support.requirement(status="DEFERRED", rationale="Postponed."),
                self.schemas["requirement"],
            ),
            [],
        )

    def test_rejected_requires_rationale(self):
        self.assertNotEqual(
            validate(support.requirement(status="REJECTED"), self.schemas["requirement"]), []
        )

    def _deferred_project(self, root):
        project = support.make_project(root, state="PLANNING")
        support.write_json(project / "objectives" / "OBJ-0001.json", support.objective())
        support.write_json(project / "requirements" / "REQ-0001.json", support.requirement())
        support.write_json(
            project / "requirements" / "REQ-0002.json",
            support.requirement(id="REQ-0002", status="DEFERRED", rationale="Postponed."),
        )
        support.write_json(
            project / "requirements" / "REQ-0003.json",
            support.requirement(id="REQ-0003", type="RISK", status="PROPOSED",
                                acceptance_criteria=[], priority="medium"),
        )
        return project

    def test_g2_ignores_deferred_requirement(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = self._deferred_project(Path(tmp) / "proj")
            report = evaluate_gate(project, "G2")
            self.assertEqual(report["status"], "PASS", report)

    def test_g5_ignores_deferred_requirement(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = self._deferred_project(Path(tmp) / "proj")
            support.write_json(
                project / "evidence" / "EVD-0001.json",
                support.evidence(related_requirements=["REQ-0001"]),
            )
            report = evaluate_gate(project, "G5")
            self.assertEqual(report["status"], "MANUAL", report)

    def test_coverage_ignores_deferred_requirement(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_project(Path(tmp) / "proj")
            support.write_json(
                project / "requirements" / "REQ-0002.json",
                support.requirement(id="REQ-0002", status="DEFERRED", rationale="Postponed."),
            )
            code, out = support.run_cli("review", "--project", str(project))
            self.assertEqual(code, 0, out)
            self.assertNotIn("requirements not linked to an objective: REQ-0002", out)

    def test_update_can_defer_with_rationale(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_project(Path(tmp) / "proj")
            support.write_json(project / "requirements" / "REQ-0001.json", support.requirement())
            code, out = support.run_cli(
                "update", "requirement", "REQ-0001", "--project", str(project),
                "--set", "status=DEFERRED", "--set", "rationale=Postponed.", "--by", "owner",
            )
            self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
