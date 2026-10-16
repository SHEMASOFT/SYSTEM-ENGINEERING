"""`se orchestrate checkpoint` and workflow recovery tests.

The contract asserted here:

1. A deterministic run persists a checkpoint after every node, so an interrupted
   run leaves durable progress behind (not just an in-memory state).
2. A failed node leaves a resumable checkpoint (`status: FAILED`) whose
   `completed_nodes` reflects exactly the work that provably finished.
3. `--resume-from` continues from that checkpoint: completed nodes are *not*
   re-executed and the accumulated context of upstream nodes is restored, so a
   downstream node still receives its declared `context:` inputs.
4. The checkpoint store rejects malformed records instead of persisting garbage.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

PROJECT_ID = "PRJ-TEST-001"
WORKFLOW_ID = "WF-0001"


def _node(node_id, action, agent="analyst", inputs=None, outputs=None):
    return {
        "node_id": node_id,
        "agent": agent,
        "action": action,
        "inputs": inputs or {},
        "outputs": outputs or {},
    }


def _workflow(nodes, edges=None):
    return {
        "schema_version": "1",
        "workflow_id": WORKFLOW_ID,
        "project_id": PROJECT_ID,
        "name": "Recovery flow",
        "version": "1.0.0",
        "status": "DRAFT",
        "nodes": nodes,
        "edges": edges or [],
        "gates": [],
    }


def _completed(outputs=None):
    return {"status": "COMPLETED", "output": outputs or {}, "outputs": outputs or {}}


def _failed(error="boom"):
    return {"status": "FAILED", "error": error}


class CheckpointManagerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.project = support.make_project(self.root / "proj")
        from se_core.orchestration.checkpoint import CheckpointManager

        self.manager = CheckpointManager(self.project)

    def tearDown(self):
        self._tmp.cleanup()

    def _node_result(self, status="COMPLETED"):
        return {
            "status": status,
            "outputs": {"out": "v"},
            "error": None,
            "started_at": "2026-01-01T00:00:00Z",
            "completed_at": "2026-01-01T00:00:01Z",
        }

    def test_save_assigns_sequential_ids_and_persists_atomically(self):
        first = self.manager.save(
            WORKFLOW_ID, "WEX-0001", ["n1"], {"n1": self._node_result()}, {}, {"k": "v"}
        )
        second = self.manager.save(WORKFLOW_ID, "WEX-0001", ["n1", "n2"], {}, {}, {})

        self.assertEqual(first, "CP-0001")
        self.assertEqual(second, "CP-0002")
        self.assertTrue(
            (self.project / ".workflows" / "checkpoints" / "CP-0001.json").exists()
        )
        # atomic write leaves no staging files behind
        leftovers = list(
            (self.project / ".workflows" / "checkpoints").glob("*.tmp")
        )
        self.assertEqual(leftovers, [])

    def test_load_round_trips_state(self):
        cp_id = self.manager.save(
            WORKFLOW_ID, "WEX-0001", ["n1"], {"n1": self._node_result()}, {}, {"step": "v"}
        )

        loaded = self.manager.load(cp_id)

        self.assertEqual(loaded["checkpoint_id"], cp_id)
        self.assertEqual(loaded["workflow_id"], WORKFLOW_ID)
        self.assertEqual(loaded["completed_nodes"], ["n1"])
        self.assertEqual(loaded["context"], {"step": "v"})
        self.assertEqual(loaded["status"], "IN_PROGRESS")

    def test_load_unknown_checkpoint_returns_none(self):
        self.assertIsNone(self.manager.load("CP-9999"))

    def test_save_rejects_a_malformed_checkpoint(self):
        """A bad record must fail loudly, never persist (garbage in the store)."""
        with self.assertRaises(ValueError):
            self.manager.save("NOT-A-WORKFLOW-ID", "WEX-0001", [], {}, {}, {})

    def test_list_filters_by_workflow_and_orders_newest_first(self):
        self.manager.save(WORKFLOW_ID, "WEX-0001", [], {}, {}, {})
        self.manager.save(WORKFLOW_ID, "WEX-0001", [], {}, {}, {})
        self.manager.save("WF-0002", "WEX-0002", [], {}, {}, {})

        self.assertEqual(len(self.manager.list_checkpoints()), 3)
        only = self.manager.list_checkpoints(workflow_id=WORKFLOW_ID)
        self.assertEqual([cp["workflow_id"] for cp in only], [WORKFLOW_ID, WORKFLOW_ID])
        # newest first even though every created_at shares a second
        self.assertEqual([cp["checkpoint_id"] for cp in only], ["CP-0002", "CP-0001"])

    def test_delete_removes_file_and_reports_absence(self):
        cp_id = self.manager.save(WORKFLOW_ID, "WEX-0001", [], {}, {}, {})

        self.assertTrue(self.manager.delete(cp_id))
        self.assertIsNone(self.manager.load(cp_id))
        self.assertFalse(self.manager.delete(cp_id))

    def test_cleanup_old_keeps_the_newest(self):
        for _ in range(4):
            self.manager.save(WORKFLOW_ID, "WEX-0001", [], {}, {}, {})

        removed = self.manager.cleanup_old(keep=2)

        self.assertEqual(removed, 2)
        remaining = self.manager.list_checkpoints(WORKFLOW_ID)
        self.assertEqual(
            [cp["checkpoint_id"] for cp in remaining], ["CP-0004", "CP-0003"]
        )

    def test_cleanup_old_is_a_noop_below_the_limit(self):
        self.manager.save(WORKFLOW_ID, "WEX-0001", [], {}, {}, {})
        self.assertEqual(self.manager.cleanup_old(keep=5), 0)
        self.assertEqual(len(self.manager.list_checkpoints()), 1)


class WorkflowRecoveryIntegrationTests(unittest.TestCase):
    """End-to-end `execute()` behaviour: checkpoint per node and resume."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.project = support.make_project(self.root / "proj")

        from se_core.orchestration.engine import OrchestrationEngine

        self.engine = OrchestrationEngine(root=self.root)
        # `_find_project_dir` hard-codes repo_root()/PROJECTS; point it at the tmp one.
        self.engine._find_project_dir = mock.MagicMock(return_value=self.project)

    def tearDown(self):
        self._tmp.cleanup()

    def _write_workflow(self, workflow_id, nodes, edges=None):
        data = _workflow(nodes, edges)
        data["workflow_id"] = workflow_id
        support.write_json(self.project / "workflows" / f"{workflow_id}.json", data)

    def _checkpoints(self, workflow_id=WORKFLOW_ID):
        from se_core.orchestration.checkpoint import CheckpointManager

        return CheckpointManager(self.project).list_checkpoints(workflow_id)

    def _execute_with(self, script, calls, *args, **kwargs):
        """Run execute() with AgentRunner.run replaced by a scripted stub.

        `script` maps action -> list of results consumed in order (the last entry
        repeats). `calls` records every invocation for assertions.
        """
        from se_core.agents.runner import AgentRunner

        def fake_run(runner_self, action, inputs, context, max_tokens=None):
            calls.append({"action": action, "inputs": inputs, "context": context})
            queue = script[action]
            return queue.pop(0) if len(queue) > 1 else queue[0]

        with mock.patch.object(AgentRunner, "run", fake_run):
            return self.engine.execute(WORKFLOW_ID, PROJECT_ID, *args, **kwargs)

    def test_execute_persists_a_checkpoint_for_every_node(self):
        self._write_workflow(
            WORKFLOW_ID,
            [_node("n1", "step1"), _node("n2", "step2")],
            edges=[{"from": "n1", "to": "n2"}],
        )

        script = {"step1": [_completed({"a": 1})], "step2": [_completed({"b": 2})]}
        result = self._execute_with(script, [])

        self.assertEqual(result["status"], "COMPLETED")
        checkpoints = self._checkpoints()
        # one per node (IN_PROGRESS) plus the terminal COMPLETED checkpoint
        self.assertEqual(len(checkpoints), 3)
        self.assertEqual(checkpoints[0]["status"], "COMPLETED")
        self.assertEqual(checkpoints[0]["completed_nodes"], ["n1", "n2"])

    def test_dry_run_writes_no_checkpoints(self):
        self._write_workflow(WORKFLOW_ID, [_node("n1", "step1")])

        result = self._execute_with({"step1": [_completed()]}, [], dry_run=True)

        self.assertEqual(result["status"], "DRY_RUN")
        self.assertEqual(self._checkpoints(), [])

    def test_failed_node_leaves_a_resumable_checkpoint(self):
        self._write_workflow(
            WORKFLOW_ID,
            [_node("n1", "step1"), _node("n2", "step2")],
            edges=[{"from": "n1", "to": "n2"}],
        )

        script = {"step1": [_completed({"a": 1})], "step2": [_failed("nope")]}
        result = self._execute_with(script, [])

        self.assertEqual(result["status"], "FAILED")
        failed = [cp for cp in self._checkpoints() if cp["status"] == "FAILED"]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["completed_nodes"], ["n1"])

    def test_resume_skips_completed_nodes_and_finishes(self):
        self._write_workflow(
            WORKFLOW_ID,
            [_node("n1", "step1"), _node("n2", "step2")],
            edges=[{"from": "n1", "to": "n2"}],
        )

        # first attempt: n2 fails; the retry (second entry) succeeds
        script = {"step1": [_completed({"a": 1})], "step2": [_failed(), _completed({"b": 2})]}
        calls = []
        first = self._execute_with(script, calls)
        self.assertEqual(first["status"], "FAILED")

        resume_id = [cp for cp in self._checkpoints() if cp["status"] == "FAILED"][0][
            "checkpoint_id"
        ]
        second = self._execute_with(script, calls, resume_from_checkpoint=resume_id)

        self.assertEqual(second["status"], "COMPLETED")
        executed = [call["action"] for call in calls]
        # n1 ran exactly once across both attempts: the resume skipped it
        self.assertEqual(executed.count("step1"), 1)
        self.assertEqual(executed.count("step2"), 2)

    def test_resume_restores_context_for_downstream_nodes(self):
        self._write_workflow(
            WORKFLOW_ID,
            [
                _node("n1", "step1", outputs={"step1_out": "memory:unused"}),
                _node("n2", "step2", inputs={"prev": "context:step1_out"}),
            ],
            edges=[{"from": "n1", "to": "n2"}],
        )

        script = {
            "step1": [_completed({"step1_out": "v1"})],
            "step2": [_failed(), _completed()],
        }
        calls = []
        self._execute_with(script, calls)
        resume_id = [cp for cp in self._checkpoints() if cp["status"] == "FAILED"][0][
            "checkpoint_id"
        ]

        self._execute_with(script, calls, resume_from_checkpoint=resume_id)

        step2_inputs = [c["inputs"] for c in calls if c["action"] == "step2"]
        self.assertEqual(step2_inputs[0].get("prev"), "v1")

    def test_resume_from_unknown_checkpoint_fails_loudly(self):
        self._write_workflow(WORKFLOW_ID, [_node("n1", "step1")])

        with self.assertRaises(ValueError):
            self._execute_with({"step1": [_completed()]}, [], resume_from_checkpoint="CP-9999")

    def test_resume_rejects_a_checkpoint_from_another_workflow(self):
        from se_core.orchestration.checkpoint import CheckpointManager

        self._write_workflow(WORKFLOW_ID, [_node("n1", "step1")])
        other = CheckpointManager(self.project).save(
            "WF-0002", "WEX-0002", [], {}, {}, {}
        )

        with self.assertRaises(ValueError):
            self._execute_with({"step1": [_completed()]}, [], resume_from_checkpoint=other)


class OrchestrateCheckpointCliTests(unittest.TestCase):
    """The `se orchestrate checkpoint` surface and the `--resume-from` flag."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.project = support.make_project(self.root / "proj")

    def tearDown(self):
        self._tmp.cleanup()

    def _manager(self):
        from se_core.orchestration.checkpoint import CheckpointManager

        return CheckpointManager(self.project)

    def test_list_on_an_empty_store_reports_none(self):
        code, out = support.run_cli(
            "orchestrate", "checkpoint", "list", "--project", str(self.project)
        )

        self.assertEqual(code, 0, out)
        self.assertIn("No checkpoints found", out)

    def test_list_shows_a_created_checkpoint(self):
        cp_id = self._manager().save(WORKFLOW_ID, "WEX-0001", ["n1"], {}, {}, {})

        code, out = support.run_cli(
            "orchestrate", "checkpoint", "list",
            "--project", str(self.project), "--workflow", WORKFLOW_ID,
        )

        self.assertEqual(code, 0, out)
        self.assertIn(cp_id, out)
        self.assertIn("IN_PROGRESS", out)

    def test_delete_removes_the_checkpoint(self):
        cp_id = self._manager().save(WORKFLOW_ID, "WEX-0001", [], {}, {}, {})

        code, out = support.run_cli(
            "orchestrate", "checkpoint", "delete",
            "--project", str(self.project), "--checkpoint", cp_id,
        )

        self.assertEqual(code, 0, out)
        self.assertIsNone(self._manager().load(cp_id))

    def test_clean_keeps_the_requested_number(self):
        for _ in range(3):
            self._manager().save(WORKFLOW_ID, "WEX-0001", [], {}, {}, {})

        code, out = support.run_cli(
            "orchestrate", "checkpoint", "clean",
            "--project", str(self.project), "--keep", "1",
        )

        self.assertEqual(code, 0, out)
        self.assertEqual(len(self._manager().list_checkpoints(WORKFLOW_ID)), 1)

    def test_checkpoint_requires_a_managed_project(self):
        empty = self.root / "not-a-project"
        empty.mkdir(parents=True)

        code, out = support.run_cli(
            "orchestrate", "checkpoint", "list", "--project", str(empty)
        )

        self.assertEqual(code, 1, out)
        self.assertIn("no PROJECT.json", out)

    def test_execute_declares_the_resume_from_flag(self):
        code, out = support.run_cli("orchestrate", "execute", "--help")

        self.assertEqual(code, 0, out)
        self.assertIn("--resume-from", out)


if __name__ == "__main__":
    unittest.main()
