"""`se orchestrate` tests (SE-04).

Two defects observed in the field:

1. `se orchestrate list --project <p>` aborted with
   `FAIL: unexpected error: name 'Dict' is not defined`: the module
   `se_core/orchestration/schemas.py` annotates its helpers with `Dict[str, Any]`
   but never imports `typing`. Annotations are evaluated at import time, so the
   whole orchestration surface (create/execute/list) was dead.
2. `list` globbed every `*.json` under `workflows/`, so the workflow *components*
   (`nodes.json`, `edges.json`, `gates.json`) were reported as workflows
   ("(invalid)") — accounting noise that hides the real inventory.

The contract asserted here: the schema helpers are importable, only files that
declare a `workflow_id` are workflows, a broken workflow is still surfaced (never
silently dropped), and component files are named in one informational line.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402


class OrchestrationSchemasImportTests(unittest.TestCase):
    """The orchestration modules must be importable at runtime."""

    def test_orchestration_schemas_importable_and_load_schemas(self):
        from se_core.orchestration import schemas as orq_schemas

        self.assertIsInstance(orq_schemas.load_workflow_schema(), dict)
        self.assertIsInstance(orq_schemas.load_execution_schema(), dict)

    def test_engine_is_importable(self):
        from se_core.orchestration.engine import OrchestrationEngine

        self.assertTrue(callable(getattr(OrchestrationEngine, "execute")))

    def test_orchestrate_list_does_not_crash(self):
        """The command itself must not turn into `unexpected error`."""
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_project(Path(tmp) / "proj")
            code, out = support.run_cli("orchestrate", "list", "--project", str(project))
            self.assertEqual(code, 0, out)
            self.assertNotIn("unexpected error", out)


class OrchestrateListTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.project = support.make_project(self.root / "proj")

    def tearDown(self):
        self._tmp.cleanup()

    def _write_workflow(self, workflow_id, **over):
        data = {
            "schema_version": "1",
            "workflow_id": workflow_id,
            "name": "Release flow",
            "version": "1",
            "status": "DRAFT",
            "nodes": [],
            "edges": [],
        }
        data.update(over)
        support.write_json(self.project / "workflows" / f"{workflow_id}.json", data)

    def _write_component(self, name, payload):
        support.write_json(self.project / "workflows" / name, payload)

    def _lines_reporting_workflows(self, out):
        """Output lines that claim a file is a workflow (`<id>: <name> ...`)."""
        found = []
        for line in out.splitlines():
            stripped = line.strip()
            if ":" in stripped and not stripped.startswith(("(", "No ", "Workflows in")):
                found.append(stripped)
        return found

    def test_component_json_is_not_reported_as_workflow(self):
        self._write_workflow("WF-0001")
        self._write_component("nodes.json", [{"node_id": "N1", "type": "task"}])
        self._write_component("edges.json", [{"from": "N1", "to": "N2"}])
        self._write_component("gates.json", [{"gate": "G1"}])

        code, out = support.run_cli("orchestrate", "list", "--project", str(self.project))

        self.assertEqual(code, 0, out)
        reported = self._lines_reporting_workflows(out)
        self.assertTrue(
            any(line.startswith("WF-0001:") for line in reported),
            f"the real workflow must be listed: {out!r}",
        )
        self.assertEqual(len(reported), 1, f"only the real workflow: {out!r}")
        # the component files are disclosed, not silently swallowed
        self.assertIn("nodes.json", out)
        self.assertIn("edges.json", out)
        self.assertIn("gates.json", out)

    def test_broken_workflow_still_surfaces(self):
        self._write_workflow("WF-0001")
        support.write_json(
            self.project / "workflows" / "WF-0002.json",
            {"workflow_id": "WF-0002", "nodes": []},  # no name/version/status
        )

        code, out = support.run_cli("orchestrate", "list", "--project", str(self.project))

        self.assertEqual(code, 0, out)
        self.assertIn("WF-0001", out)
        self.assertIn("WF-0002", out)
        self.assertIn("(invalid)", out)

    def test_only_components_reports_no_workflows(self):
        self._write_component("nodes.json", [])
        self._write_component("edges.json", [])

        code, out = support.run_cli("orchestrate", "list", "--project", str(self.project))

        self.assertEqual(code, 0, out)
        self.assertIn("No workflows found", out)
        self.assertEqual(self._lines_reporting_workflows(out), [], out)

    def test_missing_workflows_dir_is_not_an_error(self):
        code, out = support.run_cli("orchestrate", "list", "--project", str(self.project))

        self.assertEqual(code, 0, out)
        self.assertIn("No workflows found", out)

    def test_missing_project_json_fails_loudly(self):
        empty = self.root / "not-a-project"
        empty.mkdir(parents=True, exist_ok=True)

        code, out = support.run_cli("orchestrate", "list", "--project", str(empty))

        self.assertEqual(code, 1, out)
        self.assertIn("no PROJECT.json", out)


class OrchestrateExecuteExitCodeTests(unittest.TestCase):
    """`execute` must exit 0 when the run succeeded and 1 when it failed.

    A dry-run is an intentional, successful plan: it printed `Status: DRY_RUN`
    and the execution order, yet the command exited 1. And `--json` always
    exited 0, even for a failed execution, which is the same defect mirrored.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.project = support.make_project(self.root / "proj")

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, status, *extra):
        result = {
            "execution_id": "WEX-0001",
            "workflow_id": "WF-0001",
            "status": status,
            "execution_order": ["intake", "release"],
        }
        fake = mock.MagicMock()
        fake.execute.return_value = result
        with mock.patch("se_core.orchestration.engine.OrchestrationEngine", return_value=fake):
            return support.run_cli(
                "orchestrate", "execute", "--workflow", "WF-0001",
                "--project", str(self.project), *extra,
            )

    def test_dry_run_exits_zero(self):
        code, out = self._run("DRY_RUN", "--dry-run")
        self.assertEqual(code, 0, out)
        self.assertIn("DRY_RUN", out)

    def test_dry_run_with_json_exits_zero(self):
        code, out = self._run("DRY_RUN", "--dry-run", "--json")
        self.assertEqual(code, 0, out)

    def test_completed_exits_zero(self):
        code, out = self._run("COMPLETED")
        self.assertEqual(code, 0, out)

    def test_failed_exits_one(self):
        code, out = self._run("FAILED")
        self.assertEqual(code, 1, out)

    def test_failed_with_json_exits_one(self):
        code, out = self._run("FAILED", "--json")
        self.assertEqual(code, 1, out)


if __name__ == "__main__":
    unittest.main()
