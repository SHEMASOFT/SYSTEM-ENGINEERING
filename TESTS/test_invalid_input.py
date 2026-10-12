"""Invalid input rejection tests across the system."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.schemas import validate  # noqa: E402


class InvalidInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schemas = support.schemas()

    def test_non_object_rejected(self):
        for name in ["project", "requirement", "task", "decision", "evidence", "release"]:
            errors = validate([], self.schemas[name])
            self.assertNotEqual(errors, [], name)

    def test_extra_property_rejected(self):
        data = support.task()
        data["unexpected"] = "value"
        self.assertNotEqual(validate(data, self.schemas["task"]), [])

    def test_bad_id_patterns_rejected(self):
        cases = [
            ("requirement", support.requirement(id="REQ-1")),
            ("task", support.task(id="TASK-1")),
            ("evidence", support.evidence(id="EV-1")),
            ("release", support.release(id="REL-1")),
            ("decision", support.decision(decision_id="DEC-1")),
        ]
        for name, data in cases:
            self.assertNotEqual(validate(data, self.schemas[name]), [], name)

    def test_invalid_timestamp_rejected(self):
        self.assertNotEqual(
            validate(support.evidence(collected_at="not-a-date"), self.schemas["evidence"]),
            [],
        )

    def test_wrong_permission_rejected(self):
        self.assertNotEqual(
            validate(support.task(authorized_actions=["FLY"]), self.schemas["task"]),
            [],
        )

    def test_release_invalid_status_rejected(self):
        self.assertNotEqual(
            validate(support.release(status="SHIPPED"), self.schemas["release"]),
            [],
        )


if __name__ == "__main__":
    unittest.main()
