"""ACCEPTANCE entity tests."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.schemas import validate  # noqa: E402


class AcceptanceSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schemas = support.schemas()

    def test_valid(self):
        self.assertEqual(validate(support.acceptance(), self.schemas["acceptance"]), [])

    def test_missing_authority_rejected(self):
        data = support.acceptance()
        del data["authority"]
        self.assertNotEqual(validate(data, self.schemas["acceptance"]), [])

    def test_empty_authority_rejected(self):
        self.assertNotEqual(
            validate(support.acceptance(authority=""), self.schemas["acceptance"]), []
        )

    def test_missing_evidence_rejected(self):
        data = support.acceptance()
        del data["evidence"]
        self.assertNotEqual(validate(data, self.schemas["acceptance"]), [])
        self.assertNotEqual(
            validate(support.acceptance(evidence=[]), self.schemas["acceptance"]), []
        )

    def test_invalid_result_rejected(self):
        self.assertNotEqual(
            validate(support.acceptance(result="APPROVED"), self.schemas["acceptance"]), []
        )

    def test_invalid_id_rejected(self):
        self.assertNotEqual(
            validate(support.acceptance(acceptance_id="ACC-1"), self.schemas["acceptance"]), []
        )


class AcceptanceReferenceTests(unittest.TestCase):
    def test_missing_evidence_detected_by_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_project(Path(tmp) / "proj")
            support.write_json(
                project / "acceptances" / "ACC-0001.json",
                support.acceptance(evidence=["EVD-9999"]),
            )
            code, out = support.run_cli("review", "--project", str(project))
            self.assertEqual(code, 1, out)
            self.assertIn("unresolved reference EVD-9999", out)


if __name__ == "__main__":
    unittest.main()
