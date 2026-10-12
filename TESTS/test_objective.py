"""OBJECTIVE entity tests."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.schemas import validate  # noqa: E402


class ObjectiveSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schemas = support.schemas()

    def test_valid(self):
        self.assertEqual(validate(support.objective(), self.schemas["objective"]), [])

    def test_unknown_requires_rationale(self):
        self.assertNotEqual(
            validate(support.objective(epistemic_status="UNKNOWN"), self.schemas["objective"]), []
        )
        self.assertEqual(
            validate(
                support.objective(epistemic_status="UNKNOWN", rationale="Objective not yet defined."),
                self.schemas["objective"],
            ),
            [],
        )

    def test_assumption_requires_rationale(self):
        self.assertNotEqual(
            validate(support.objective(epistemic_status="ASSUMPTION"), self.schemas["objective"]), []
        )

    def test_fact_requires_evidence(self):
        self.assertNotEqual(
            validate(support.objective(epistemic_status="FACT"), self.schemas["objective"]), []
        )
        self.assertEqual(
            validate(
                support.objective(epistemic_status="FACT", evidence=["EVD-0001"]),
                self.schemas["objective"],
            ),
            [],
        )

    def test_missing_epistemic_status_rejected(self):
        data = support.objective()
        del data["epistemic_status"]
        self.assertNotEqual(validate(data, self.schemas["objective"]), [])

    def test_invalid_id_and_status_rejected(self):
        self.assertNotEqual(validate(support.objective(objective_id="OBJ-1"), self.schemas["objective"]), [])
        self.assertNotEqual(validate(support.objective(status="DONE"), self.schemas["objective"]), [])


class ObjectiveReferenceTests(unittest.TestCase):
    def test_project_reference_is_checked_by_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_project(Path(tmp) / "proj")
            support.write_json(
                project / "objectives" / "OBJ-0001.json",
                support.objective(project_id="PRJ-NOPE-001"),
            )
            code, out = support.run_cli("review", "--project", str(project))
            self.assertEqual(code, 1, out)
            self.assertIn("does not match manifest", out)


if __name__ == "__main__":
    unittest.main()
