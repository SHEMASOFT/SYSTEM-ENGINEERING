"""DISCOVERY report schema tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.schemas import validate  # noqa: E402


def discovery(**over):
    data = {
        "schema_version": "1",
        "summary": "Discovery summary.",
        "findings": [{"area": "files", "detail": "3 files", "confidence": "HIGH"}],
        "unknowns": [{"id": "UNK-0001", "question": "What is the objective?", "impact": "Blocks requirements."}],
        "assumptions": [{"id": "ASM-0001", "statement": "Owner is X.", "basis": "Provided."}],
        "constraints": [{"id": "CON-0001", "statement": "No production access.", "basis": "Pilot rules."}],
        "risks": [{"id": "RSK-0001", "statement": "Scope creep.", "basis": "Objective unknown."}],
        "reviewed_by": "",
        "reviewed_at": None,
    }
    data.update(over)
    return data


class DiscoverySchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schemas = support.schemas()

    def test_valid(self):
        self.assertEqual(validate(discovery(), self.schemas["discovery"]), [])

    def test_missing_unknowns_rejected(self):
        data = discovery()
        del data["unknowns"]
        self.assertNotEqual(validate(data, self.schemas["discovery"]), [])

    def test_unknown_is_represented_explicitly(self):
        self.assertEqual(
            validate(
                discovery(unknowns=[{"id": "UNK-0002", "question": "Who are the users?", "impact": "Blocks UX."}]),
                self.schemas["discovery"],
            ),
            [],
        )

    def test_invalid_unknown_id_rejected(self):
        self.assertNotEqual(
            validate(discovery(unknowns=[{"id": "UNK-1", "question": "x"}]), self.schemas["discovery"]),
            [],
        )

    def test_invalid_confidence_rejected(self):
        self.assertNotEqual(
            validate(discovery(findings=[{"area": "a", "detail": "b", "confidence": "SURE"}]),
                     self.schemas["discovery"]),
            [],
        )

    def test_unknown_extra_property_rejected(self):
        self.assertNotEqual(
            validate(discovery(unknowns=[{"id": "UNK-0001", "question": "x", "certainty": "high"}]),
                     self.schemas["discovery"]),
            [],
        )


if __name__ == "__main__":
    unittest.main()
