"""End-to-end traceability tests: direct and reverse traversal."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.artifacts import ID_FIELD, collection  # noqa: E402


def load(project, kind):
    items, _ = collection(project, kind)
    return {data[ID_FIELD[kind]]: data for _, data in items}


class TraceabilityTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = support.make_full_project(Path(self._tmp.name) / "proj")
        self.objectives = load(self.project, "objective")
        self.requirements = load(self.project, "requirement")
        self.tasks = load(self.project, "task")
        self.artifacts = load(self.project, "artifact")
        self.evidence = load(self.project, "evidence")
        self.acceptances = load(self.project, "acceptance")
        self.releases = load(self.project, "release")

    def tearDown(self):
        self._tmp.cleanup()

    def test_review_has_no_findings(self):
        code, out = support.run_cli("review", "--project", str(self.project))
        self.assertEqual(code, 0, out)

    def test_direct_chain_links_resolve(self):
        objective = self.objectives["OBJ-0001"]
        req_id = objective["related_requirements"][0]
        self.assertIn(req_id, self.requirements)

        task_id = "TASK-0001"
        self.assertIn(req_id, self.tasks[task_id]["related_requirements"])

        artifact = self.artifacts["ART-0001"]
        self.assertIn(task_id, artifact["produced_by"])

        evidence = self.evidence["EVD-0001"]
        self.assertIn(task_id, evidence["related_tasks"])
        self.assertIn("ART-0001", evidence["related_artifacts"])

        acceptance = self.acceptances["ACC-0001"]
        self.assertIn("EVD-0001", acceptance["evidence"])
        self.assertEqual(acceptance["result"], "ACCEPTED")

        release = self.releases["REL-0001"]
        self.assertIn("ACC-0001", release["acceptances"])

    def test_reverse_chain_is_walkable(self):
        release = self.releases["REL-0001"]
        acceptance = self.acceptances[release["acceptances"][0]]
        evidence = self.evidence[acceptance["evidence"][0]]
        task = self.tasks[evidence["related_tasks"][0]]
        artifact = self.artifacts[evidence["related_artifacts"][0]]
        requirement = self.requirements[task["related_requirements"][0]]
        objective_ids = [
            oid for oid, obj in self.objectives.items()
            if requirement["id"] in obj.get("related_requirements", [])
        ]
        self.assertEqual(artifact["produced_by"], [task["id"]])
        self.assertTrue(objective_ids, "requirement should trace back to an objective")


if __name__ == "__main__":
    unittest.main()
