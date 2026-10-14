"""`se new` tests: assisted record creation from templates."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.paths import load_json  # noqa: E402
from se_core.schemas import validate  # noqa: E402

PREFIX = {
    "objective": "OBJ-",
    "requirement": "REQ-",
    "task": "TASK-",
    "artifact": "ART-",
    "evidence": "EVD-",
    "acceptance": "ACC-",
}
DIR = {
    "objective": "objectives",
    "requirement": "requirements",
    "task": "tasks",
    "artifact": "artifacts",
    "evidence": "evidence",
    "acceptance": "acceptances",
}
ID_FIELD = {
    "objective": "objective_id",
    "requirement": "id",
    "task": "id",
    "artifact": "artifact_id",
    "evidence": "id",
    "acceptance": "acceptance_id",
}


class NewRecordTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = support.make_project(Path(self._tmp.name) / "proj")
        self.schemas = support.schemas()

    def tearDown(self):
        self._tmp.cleanup()

    def create(self, kind, *extra):
        return support.run_cli("new", kind, "--project", str(self.project), *extra)

    def assert_created(self, kind, out):
        self.assertIn(f"PASS: created {PREFIX[kind]}", out)

    def test_objective_valid(self):
        code, out = self.create("objective", "--title", "Obj", "--epistemic-status", "OBJECTIVE")
        self.assertEqual(code, 0, out)
        self.assert_created("objective", out)
        data = load_json(self.project / DIR["objective"] / "OBJ-0001.json")
        self.assertEqual(validate(data, self.schemas["objective"]), [])
        self.assertEqual(data["objective_id"], "OBJ-0001")
        self.assertEqual(data["project_id"], "PRJ-TEST-001")

    def test_requirement_valid(self):
        code, out = self.create("requirement", "--title", "Req", "--acceptance-criteria", "C1,C2")
        self.assertEqual(code, 0, out)
        data = load_json(self.project / DIR["requirement"] / "REQ-0001.json")
        self.assertEqual(validate(data, self.schemas["requirement"]), [])
        self.assertEqual(data["id"], "REQ-0001")
        self.assertEqual(data["acceptance_criteria"], ["C1", "C2"])
        self.assertEqual(data["project_id"], "PRJ-TEST-001")

    def test_task_valid(self):
        code, out = self.create("task", "--title", "Task", "--objective", "Do it")
        self.assertEqual(code, 0, out)
        data = load_json(self.project / DIR["task"] / "TASK-0001.json")
        self.assertEqual(validate(data, self.schemas["task"]), [])
        self.assertEqual(data["id"], "TASK-0001")

    def test_artifact_valid(self):
        code, out = self.create("artifact", "--title", "Art", "--produced-by", "TASK-0001")
        self.assertEqual(code, 0, out)
        data = load_json(self.project / DIR["artifact"] / "ART-0001.json")
        self.assertEqual(validate(data, self.schemas["artifact"]), [])
        self.assertEqual(data["artifact_id"], "ART-0001")
        self.assertEqual(data["produced_by"], ["TASK-0001"])

    def test_evidence_valid(self):
        code, out = self.create("evidence", "--title", "Evd", "--type", "test", "--result", "PASS")
        self.assertEqual(code, 0, out)
        data = load_json(self.project / DIR["evidence"] / "EVD-0001.json")
        self.assertEqual(validate(data, self.schemas["evidence"]), [])
        self.assertEqual(data["id"], "EVD-0001")

    def test_acceptance_valid(self):
        code, out = self.create(
            "acceptance", "--scope", "Accept it", "--decided-by", "owner", "--evidence", "EVD-0001"
        )
        self.assertEqual(code, 0, out)
        data = load_json(self.project / DIR["acceptance"] / "ACC-0001.json")
        self.assertEqual(validate(data, self.schemas["acceptance"]), [])
        self.assertEqual(data["acceptance_id"], "ACC-0001")
        self.assertEqual(data["result"], "DEFERRED")

    def test_requirement_without_criteria_rejected(self):
        code, out = self.create("requirement", "--title", "Req")
        self.assertEqual(code, 1, out)
        self.assertIn("acceptance-criteria is required", out)
        self.assertFalse((self.project / DIR["requirement"] / "REQ-0001.json").exists())

    def test_artifact_without_producer_rejected(self):
        code, out = self.create("artifact", "--title", "Art")
        self.assertEqual(code, 1, out)
        self.assertIn("produced-by", out)

    def test_acceptance_without_required_fields_rejected(self):
        code, out = self.create("acceptance", "--decided-by", "owner", "--evidence", "EVD-0001")
        self.assertEqual(code, 1, out)
        self.assertIn("--scope is required", out)

        code, out = self.create("acceptance", "--scope", "s", "--evidence", "EVD-0001")
        self.assertEqual(code, 1, out)
        self.assertIn("--decided-by", out)

        code, out = self.create("acceptance", "--scope", "s", "--decided-by", "owner")
        self.assertEqual(code, 1, out)
        self.assertIn("--evidence", out)

    def test_objective_assumption_requires_rationale(self):
        code, out = self.create("objective", "--title", "Obj", "--epistemic-status", "ASSUMPTION")
        self.assertEqual(code, 1, out)
        self.assertIn("--rationale is required", out)

    def test_no_overwrite_and_distinct_ids(self):
        self.create("requirement", "--title", "First", "--acceptance-criteria", "C")
        first = load_json(self.project / DIR["requirement"] / "REQ-0001.json")
        code, out = self.create("requirement", "--title", "Second", "--acceptance-criteria", "C")
        self.assertEqual(code, 0, out)
        self.assertTrue((self.project / DIR["requirement"] / "REQ-0001.json").exists())
        self.assertTrue((self.project / DIR["requirement"] / "REQ-0002.json").exists())
        still_first = load_json(self.project / DIR["requirement"] / "REQ-0001.json")
        self.assertEqual(still_first["title"], "First")
        self.assertEqual(first["id"], "REQ-0001")


    def test_decision_valid(self):
        code, out = self.create(
            "decision", "--context", "ctx", "--problem", "p", "--decision", "d",
            "--reason", "r", "--consequences", "c", "--affected-components", "svc",
            "--options", "A,B",
        )
        self.assertEqual(code, 0, out)
        self.assertIn("PASS: created ADR-", out)
        data = load_json(self.project / "decisions" / "ADR-0001.json")
        self.assertEqual(validate(data, self.schemas["decision"]), [])
        self.assertEqual(data["decision_id"], "ADR-0001")
        self.assertEqual(data["project_id"], "PRJ-TEST-001")
        self.assertEqual(data["options_considered"], [{"option": "A"}, {"option": "B"}])

    def test_decision_missing_required_fields(self):
        code, out = self.create("decision", "--context", "ctx")
        self.assertEqual(code, 1, out)
        self.assertIn("required", out)
        self.assertFalse((self.project / "decisions" / "ADR-0001.json").exists())

    def test_requirement_dependencies(self):
        code, out = self.create(
            "requirement", "--title", "R", "--acceptance-criteria", "C",
            "--dependencies", "REQ-0002,REQ-0003",
        )
        self.assertEqual(code, 0, out)
        data = load_json(self.project / "requirements" / "REQ-0001.json")
        self.assertEqual(data["dependencies"], ["REQ-0002", "REQ-0003"])

    def test_requirement_related_decisions(self):
        code, out = self.create(
            "requirement", "--title", "R", "--acceptance-criteria", "C",
            "--related-decisions", "ADR-0001",
        )
        self.assertEqual(code, 0, out)
        data = load_json(self.project / "requirements" / "REQ-0001.json")
        self.assertEqual(data["related_decisions"], ["ADR-0001"])


    def test_evidence_description_is_recorded(self):
        """`--description` is declared for `se new` and the evidence schema has
        the field, yet the value was dropped silently (`description: ""`)."""
        text = "Ran the harness twice; identical payload (20480 chars) both times."
        code, out = self.create(
            "evidence", "--title", "Evd", "--type", "test", "--result", "PASS",
            "--location", "SE-CONSOLE/tests/validate_poc.py",
            "--command", "python SE-CONSOLE/tests/validate_poc.py",
            "--description", text,
        )
        self.assertEqual(code, 0, out)
        data = load_json(self.project / DIR["evidence"] / "EVD-0001.json")
        self.assertEqual(validate(data, self.schemas["evidence"]), [])
        self.assertEqual(data["description"], text)

    def test_evidence_without_description_is_empty(self):
        code, out = self.create("evidence", "--title", "Evd", "--type", "test", "--result", "PASS")
        self.assertEqual(code, 0, out)
        data = load_json(self.project / DIR["evidence"] / "EVD-0001.json")
        self.assertEqual(validate(data, self.schemas["evidence"]), [])
        self.assertEqual(data["description"], "")

    def test_evidence_keeps_location_and_command(self):
        """Guard: the fix must not disturb the flags that already worked."""
        code, out = self.create(
            "evidence", "--title", "Evd", "--type", "test", "--result", "PASS",
            "--location", "TESTS/test_new.py", "--command", "python -m unittest",
            "--description", "txt",
        )
        self.assertEqual(code, 0, out)
        data = load_json(self.project / DIR["evidence"] / "EVD-0001.json")
        self.assertEqual(data["location"], "TESTS/test_new.py")
        self.assertEqual(data["command"], "python -m unittest")
        self.assertEqual(data["description"], "txt")

    def test_artifact_description_is_recorded(self):
        """Same class as the evidence fix: `--description` is declared for every
        `se new` kind and the artifact template has the field, yet the value was
        dropped — the record kept the template placeholder instead."""
        text = "Executable adopted by ART-0001: SCRIPTS/se_core/commands.py"
        code, out = self.create(
            "artifact", "--title", "Art", "--produced-by", "TASK-0001",
            "--kind", "code", "--location", "SCRIPTS/se_core/commands.py",
            "--description", text,
        )
        self.assertEqual(code, 0, out)
        self.assert_created("artifact", out)
        data = load_json(self.project / DIR["artifact"] / "ART-0001.json")
        self.assertEqual(validate(data, self.schemas["artifact"]), [])
        self.assertEqual(data["description"], text)
        self.assertEqual(data["location"], "SCRIPTS/se_core/commands.py")

    def test_artifact_without_description_keeps_template_default(self):
        """Guard: with no flag the record must keep the template text (the fix
        must not blank the field)."""
        code, out = self.create("artifact", "--title", "Art", "--produced-by", "TASK-0001")
        self.assertEqual(code, 0, out)
        data = load_json(self.project / DIR["artifact"] / "ART-0001.json")
        self.assertEqual(validate(data, self.schemas["artifact"]), [])
        self.assertEqual(data["description"], "What this deliverable is.")


if __name__ == "__main__":
    unittest.main()
