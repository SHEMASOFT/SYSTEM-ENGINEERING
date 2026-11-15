"""A managed workspace outside ``PROJECTS/`` must be reachable.

``se orchestrate`` and ``se memory`` resolved the project by id, sweeping
``PROJECTS/`` inside the Master System checkout. A workspace managed outside
that directory (the common case: a product repository that keeps its own
``PROJECT.json``) was therefore invisible: ``orchestrate create`` failed with
``Project PRJ-... not found`` and ``memory add`` wrote nothing.

The contract asserted here:

* the directory the caller passes *is* the project (no sweep, no fallback);
* the workflow is created in that directory and can be executed from it;
* the canonical memory store is written next to that project and is searchable;
* a project whose manifest declares another id is an explicit error, never a
  silent fallback to a different workspace.

Hermetic: temporary directories only, no network.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

PROJECT_ID = "PRJ-TEST-001"
OTHER_PROJECT_ID = "PRJ-OTHER-001"

NODES = [
    {
        "node_id": "n1",
        "agent": "analyst",
        "action": "analyze",
        "inputs": {},
        "outputs": {},
    }
]


class ExternalProjectOrchestrationTests(unittest.TestCase):
    """``se orchestrate`` must work on a workspace that is not under ``PROJECTS/``."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.project = support.make_project(self.root / "external-workspace")

    def _nodes_file(self) -> Path:
        path = self.root / "nodes.json"
        support.write_json(path, NODES)
        return path

    def _create_workflow(self):
        code, out = support.run_cli(
            "orchestrate",
            "create",
            "--project",
            str(self.project),
            "--name",
            "External flow",
            "--nodes",
            str(self._nodes_file()),
        )
        self.assertEqual(code, 0, out)
        return code, out

    def test_orchestrate_create_writes_the_workflow_into_the_external_project(self):
        self._create_workflow()

        self.assertTrue(
            (self.project / "workflows" / "WF-0001.json").is_file(),
            f"the workflow must be written next to the project: {list(self.project.rglob('*'))}",
        )

    def test_orchestrate_execute_dry_run_reads_the_external_project(self):
        self._create_workflow()

        code, out = support.run_cli(
            "orchestrate",
            "execute",
            "--workflow",
            "WF-0001",
            "--project",
            str(self.project),
            "--dry-run",
        )

        self.assertEqual(code, 0, out)
        self.assertIn("DRY_RUN", out)

    def test_orchestrate_execute_rejects_a_workflow_of_another_project(self):
        """A workflow that declares another project is an explicit error."""
        support.write_json(
            self.project / "workflows" / "WF-0001.json",
            {
                "schema_version": "1",
                "workflow_id": "WF-0001",
                "project_id": OTHER_PROJECT_ID,
                "name": "Foreign flow",
                "version": "0.1.0",
                "status": "DRAFT",
                "nodes": NODES,
                "edges": [],
                "gates": [],
            },
        )

        code, out = support.run_cli(
            "orchestrate",
            "execute",
            "--workflow",
            "WF-0001",
            "--project",
            str(self.project),
            "--dry-run",
        )

        self.assertEqual(code, 1, out)
        self.assertIn("project_id mismatch", out)
        self.assertIn(OTHER_PROJECT_ID, out)


class ExternalProjectMemoryTests(unittest.TestCase):
    """``se memory`` must read and write the store of an external workspace."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.project = support.make_project(self.root / "external-workspace")

    def _add_memory(self):
        code, out = support.run_cli(
            "memory",
            "add",
            "--project",
            str(self.project),
            "--type",
            "decision",
            "--content",
            '{"decision": "keep the workspace outside PROJECTS"}',
        )
        self.assertEqual(code, 0, out)
        return code, out

    def test_memory_add_writes_the_record_next_to_the_external_project(self):
        self._add_memory()

        stored = list((self.project / "memories").glob("MEM-*.json"))
        self.assertEqual(len(stored), 1, f"one record must be stored: {stored}")

    def test_memory_search_finds_the_record_of_the_external_project(self):
        self._add_memory()

        code, out = support.run_cli(
            "memory",
            "search",
            "--project",
            str(self.project),
            "--query",
            "workspace",
        )

        self.assertEqual(code, 0, out)
        self.assertIn("MEM-", out)

    def test_memory_query_lists_the_records_of_the_external_project(self):
        self._add_memory()

        code, out = support.run_cli(
            "memory",
            "query",
            "--project",
            str(self.project),
        )

        self.assertEqual(code, 0, out)
        self.assertIn("MEM-", out)

    def test_memory_engine_rejects_a_project_id_mismatch(self):
        """The directory is the authority, but it must be the expected project."""
        from se_core.memory.engine import MemoryEngine

        engine = MemoryEngine(root=self.root)

        with self.assertRaises(ValueError) as raised:
            engine.add(
                project_id=OTHER_PROJECT_ID,
                type="decision",
                content={"decision": "wrong project"},
                author="tester",
                scope="project",
                project_dir=self.project,
            )

        self.assertIn("project_id mismatch", str(raised.exception))
        self.assertIn(PROJECT_ID, str(raised.exception))
        self.assertIn(OTHER_PROJECT_ID, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
