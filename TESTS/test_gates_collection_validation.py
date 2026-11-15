"""A gate must not pass on records the workspace cannot prove.

The gate checks counted whatever files they found in a collection directory.
A workspace that keeps its tasks in a single wrapper file (a list) therefore
counted one "record" that is not a task at all, and a workspace with no
records counted zero and still passed: G3/G4 reported success without ever
evaluating a single task.

The contract asserted here:

* a record that does not validate against its schema is not a record: it is
  excluded from the collection and reported exactly once per record;
* a collection that holds an invalid record fails the gate, naming the count;
* a collection that holds nothing fails the gate instead of passing empty;
* a valid collection is still counted exactly as before.

Hermetic: temporary directories only, no network.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.artifacts import collection  # noqa: E402
from se_core.gates import ProjectContext, c_tasks_present, evaluate_gate  # noqa: E402
from se_core.schemas import HAVE_JSONSCHEMA  # noqa: E402

TASK_COUNT = 14


def _tasks(count: int):
    return [
        support.task(
            id=f"TASK-{index:04d}",
            title=f"Task {index}",
            objective=f"Objective {index}",
        )
        for index in range(1, count + 1)
    ]


class CollectionValidationTests(unittest.TestCase):
    """The collection is the set of records the schema accepts."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.project = support.make_project(self.root / "proj")

    def _write_tasks(self, records):
        for record in records:
            support.write_json(
                self.project / "tasks" / f"{record['id']}.json", record
            )

    def test_valid_records_are_counted(self):
        self._write_tasks(_tasks(TASK_COUNT))

        items, errors = collection(self.project, "task")

        self.assertEqual(len(items), TASK_COUNT)
        self.assertEqual(errors, [])

    @unittest.skipUnless(HAVE_JSONSCHEMA, "jsonschema is required to validate records")
    def test_wrapper_file_is_not_a_record(self):
        """A file holding a list of tasks is one invalid record, not 14 tasks."""
        support.write_json(self.project / "tasks" / "tasks.json", _tasks(TASK_COUNT))

        items, errors = collection(self.project, "task")

        self.assertEqual(items, [])
        self.assertEqual(len(errors), 1, "one error per record, not per task")
        path, message = errors[0]
        self.assertEqual(path.name, "tasks.json")
        self.assertIn("schema validation failed", message)

    @unittest.skipUnless(HAVE_JSONSCHEMA, "jsonschema is required to validate records")
    def test_every_invalid_record_is_reported_once(self):
        support.write_json(self.project / "tasks" / "tasks.json", _tasks(2))
        support.write_json(self.project / "tasks" / "broken.json", {"id": "TASK-0001"})

        items, errors = collection(self.project, "task")

        self.assertEqual(items, [])
        self.assertEqual(len(errors), 2)
        self.assertEqual(
            sorted(path.name for path, _ in errors), ["broken.json", "tasks.json"]
        )


class GateFailsClosedOnUnprovableRecordsTests(unittest.TestCase):
    """A gate answers FAIL when it cannot evaluate what the workspace holds."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.project = support.make_project(self.root / "proj")

    def _detail(self, check=c_tasks_present):
        context = ProjectContext(self.project)
        return check(context)

    def test_empty_collection_is_not_evaluable(self):
        status, detail = self._detail()

        self.assertEqual(status, "FAIL")
        self.assertEqual(detail, "no TASK records found (0 valid, 0 invalid)")

    @unittest.skipUnless(HAVE_JSONSCHEMA, "jsonschema is required to validate records")
    def test_invalid_record_fails_the_check_with_its_count(self):
        support.write_json(self.project / "tasks" / "tasks.json", _tasks(TASK_COUNT))

        status, detail = self._detail()

        self.assertEqual(status, "FAIL")
        self.assertIn("1 invalid TASK record(s)", detail)
        self.assertIn("tasks.json", detail)

    def test_valid_collection_still_passes_with_its_count(self):
        for record in _tasks(TASK_COUNT):
            support.write_json(self.project / "tasks" / f"{record['id']}.json", record)

        status, detail = self._detail()

        self.assertEqual(status, "PASS")
        self.assertEqual(detail, f"{TASK_COUNT} TASK artifact(s)")

    @unittest.skipUnless(HAVE_JSONSCHEMA, "jsonschema is required to validate records")
    def test_the_gate_fails_and_names_the_invalid_records(self):
        support.write_json(self.project / "tasks" / "tasks.json", _tasks(TASK_COUNT))

        report = evaluate_gate(self.project, "G3")

        self.assertEqual(report["status"], "FAIL")
        conditions = {item["id"]: item for item in report["conditions"]}
        self.assertEqual(conditions["G3.1"]["status"], "FAIL")
        self.assertIn("invalid TASK record", conditions["G3.1"]["detail"])

    def test_a_record_without_an_id_never_breaks_the_check(self):
        """The check must answer, not raise (a missing id is not a joinable id)."""
        support.write_json(
            self.project / "tasks" / "TASK-0001.json",
            {"title": "no id, no authorized_actions"},
        )

        status, detail = self._detail()

        self.assertEqual(status, "FAIL")
        self.assertNotIn("check error", detail)


if __name__ == "__main__":
    unittest.main()
