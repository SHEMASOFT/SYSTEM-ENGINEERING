"""Schema tests: valid instances pass, invalid instances are rejected."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.schemas import validate  # noqa: E402


class SchemaValidityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schemas = support.schemas()

    def assert_valid(self, instance, schema_name):
        errors = validate(instance, self.schemas[schema_name])
        self.assertEqual(errors, [], f"expected valid, got {errors}")

    def assert_invalid(self, instance, schema_name):
        errors = validate(instance, self.schemas[schema_name])
        self.assertNotEqual(errors, [], "expected validation errors but got none")

    def test_project_valid(self):
        self.assert_valid(support.manifest(), "project")

    def test_project_invalid_lifecycle(self):
        self.assert_invalid(support.manifest(lifecycle_state="NOPE"), "project")

    def test_project_blocked_requires_reason(self):
        self.assert_invalid(support.manifest(blocked=True), "project")
        self.assert_valid(support.manifest(blocked=True, blocked_reason="waiting"), "project")

    def test_requirement_valid(self):
        self.assert_valid(support.requirement(), "requirement")

    def test_requirement_requires_acceptance_criteria(self):
        self.assert_invalid(support.requirement(acceptance_criteria=[]), "requirement")

    def test_requirement_invalid_type(self):
        self.assert_invalid(support.requirement(type="WISH"), "requirement")

    def test_task_valid(self):
        self.assert_valid(support.task(), "task")

    def test_task_blocked_requires_reason_and_resolution(self):
        self.assert_invalid(support.task(status="BLOCKED"), "task")
        self.assert_valid(
            support.task(status="BLOCKED", blocked_reason="dep", resolution_path="unblock dep"),
            "task",
        )

    def test_task_invalid_status(self):
        self.assert_invalid(support.task(status="FINISHED"), "task")

    def test_decision_valid(self):
        self.assert_valid(support.decision(), "decision")

    def test_decision_missing_required(self):
        data = support.decision()
        del data["decision"]
        self.assert_invalid(data, "decision")

    def test_evidence_valid(self):
        self.assert_valid(support.evidence(), "evidence")

    def test_evidence_invalid_type(self):
        self.assert_invalid(support.evidence(type="rumor"), "evidence")

    def test_release_valid(self):
        self.assert_valid(support.release(), "release")

    def test_coordinator_agent_contract_valid(self):
        import json
        from pathlib import Path
        instance = json.loads(
            (Path(support.REPO_ROOT) / "AGENTS" / "shema-ai-coordinador" / "agent.json").read_text(encoding="utf-8")
        )
        self.assert_valid(instance, "agent_contract")
        self.assertIn("delegation_instructions", instance)
        self.assertGreaterEqual(len(instance["delegation_instructions"]), 1)

    def test_agent_contract_rejects_unknown_field(self):
        import json
        from pathlib import Path
        instance = json.loads(
            (Path(support.REPO_ROOT) / "AGENTS" / "shema-ai-coordinador" / "agent.json").read_text(encoding="utf-8")
        )
        instance["__unknown_field__"] = "nope"
        self.assert_invalid(instance, "agent_contract")


if __name__ == "__main__":
    unittest.main()
