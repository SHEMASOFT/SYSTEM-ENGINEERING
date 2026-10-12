"""ARTIFACT entity tests."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.schemas import validate  # noqa: E402


class ArtifactSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schemas = support.schemas()

    def test_valid(self):
        self.assertEqual(validate(support.artifact(), self.schemas["artifact"]), [])

    def test_missing_produced_by_rejected(self):
        data = support.artifact()
        del data["produced_by"]
        self.assertNotEqual(validate(data, self.schemas["artifact"]), [])

    def test_empty_produced_by_rejected(self):
        self.assertNotEqual(
            validate(support.artifact(produced_by=[]), self.schemas["artifact"]), []
        )

    def test_invalid_kind_rejected(self):
        self.assertNotEqual(
            validate(support.artifact(kind="poem"), self.schemas["artifact"]), []
        )

    def test_invalid_id_rejected(self):
        self.assertNotEqual(
            validate(support.artifact(artifact_id="ART-1"), self.schemas["artifact"]), []
        )


class ArtifactReferenceTests(unittest.TestCase):
    def test_orphan_produced_by_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_project(Path(tmp) / "proj")
            support.write_json(
                project / "artifacts" / "ART-0001.json",
                support.artifact(produced_by=["TASK-9999"]),
            )
            code, out = support.run_cli("review", "--project", str(project))
            self.assertEqual(code, 1, out)
            self.assertIn("unresolved reference TASK-9999", out)


if __name__ == "__main__":
    unittest.main()
