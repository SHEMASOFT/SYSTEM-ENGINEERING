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

    def test_agentrunner_output_normalized_to_outputs_in_context(self):
        """C4 regression: AgentRunner returns 'output', OrchestrationEngine receives 'outputs'."""
        self._write_workflow(
            WORKFLOW_ID,
            [
                _node("n1", "step1", outputs={}),
                _node("n2", "step2", inputs={"from_n1": "context:step1_val"}),
            ],
            edges=[{"from": "n1", "to": "n2"}],
        )

        # Mock returns the format that fixed AgentRunner produces (both 'output' and 'outputs')
        script = {
            "step1": [{"status": "COMPLETED", "output": {"step1_val": "hello"}, "outputs": {"step1_val": "hello"}}],
            "step2": [{"status": "COMPLETED", "output": {}}],
        }
        calls = []
        result = self._execute_with(script, calls)

        self.assertEqual(result["status"], "COMPLETED")
        # The downstream node should receive the upstream output via context
        n2_inputs = [c["inputs"] for c in calls if c["action"] == "step2"]
        self.assertEqual(len(n2_inputs), 1)
        self.assertEqual(n2_inputs[0].get("from_n1"), "hello")


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

    def test_resume_from_reaches_engine_via_cli(self):
        """The --resume-from flag value reaches engine.execute(resume_from_checkpoint=...)."""
        # Write a simple workflow
        support.write_json(
            self.project / "workflows" / f"{WORKFLOW_ID}.json",
            {
                "schema_version": "1",
                "workflow_id": WORKFLOW_ID,
                "project_id": PROJECT_ID,
                "name": "Resume test",
                "version": "1.0.0",
                "status": "DRAFT",
                "nodes": [
                    {"node_id": "n1", "agent": "analyst", "action": "step1", "inputs": {}, "outputs": {}}
                ],
                "edges": [],
                "gates": [],
            },
        )

        # Create a checkpoint to resume from
        from se_core.orchestration.checkpoint import CheckpointManager
        manager = CheckpointManager(self.project)
        cp_id = manager.save(WORKFLOW_ID, "WEX-0001", [], {}, {}, {})

        # Capture what engine.execute receives
        captured = {}

        def fake_execute(self, workflow_id, project_id, execution_id=None, dry_run=False, start_node=None, resume_from_checkpoint=None):
            captured["resume_from_checkpoint"] = resume_from_checkpoint
            # Return minimal successful result
            return {
                "execution_id": execution_id or "WEX-0002",
                "workflow_id": workflow_id,
                "status": "COMPLETED",
                "completed_at": "2026-01-01T00:00:00Z",
                "node_states": {},
                "gate_results": {},
                "context": {},
            }

        from se_core.orchestration.engine import OrchestrationEngine
        with mock.patch.object(OrchestrationEngine, "execute", fake_execute):
            code, out = support.run_cli(
                "orchestrate", "execute",
                "--workflow", WORKFLOW_ID,
                "--project", str(self.project),
                "--resume-from", cp_id,
                "--json",
            )

        self.assertEqual(code, 0, out)
        self.assertEqual(captured.get("resume_from_checkpoint"), cp_id)


class SimulatedNodeRegressionTests(unittest.TestCase):
    """Regression tests for SIMULATED node handling in checkpoints and resume."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.project = support.make_project(self.root / "proj")
        self.project_id = "PRJ-TEST-001"

    def tearDown(self):
        self._tmp.cleanup()

    def _write_workflow(self, workflow_id, nodes, edges=None, gates=None):
        data = {
            "schema_version": "1",
            "workflow_id": workflow_id,
            "project_id": self.project_id,
            "name": "Test workflow",
            "version": "1.0.0",
            "status": "DRAFT",
            "nodes": nodes,
            "edges": edges or [],
            "gates": gates or [],
        }
        support.write_json(self.project / "workflows" / f"{workflow_id}.json", data)

    def _node(self, node_id, action, agent="analyst", inputs=None, outputs=None):
        return {
            "node_id": node_id,
            "agent": agent,
            "action": action,
            "inputs": inputs or {},
            "outputs": outputs or {},
        }

    def test_checkpoint_contains_simulated_node_status(self):
        """Checkpoint must preserve SIMULATED node status correctly."""
        from se_core.orchestration.engine import OrchestrationEngine
        from se_core.orchestration.checkpoint import CheckpointManager

        self._write_workflow("WF-0001", [self._node("n1", "analyze")])

        engine = OrchestrationEngine(root=self.root)
        engine._find_project_dir = mock.MagicMock(return_value=self.project)

        with mock.patch.object(engine.memory_engine, "get", return_value=None):
            with mock.patch.object(engine, "_auto_save_memory"):
                result = engine.execute("WF-0001", self.project_id)

        self.assertEqual(result["status"], "SIMULATED")
        self.assertEqual(result["node_states"]["n1"]["status"], "SIMULATED")

        # Load checkpoint and verify SIMULATED status is preserved
        cp_manager = CheckpointManager(self.project)
        checkpoints = cp_manager.list_checkpoints("WF-0001")
        self.assertGreater(len(checkpoints), 0)
        latest_cp = cp_manager.load(checkpoints[0]["checkpoint_id"])

        self.assertEqual(latest_cp["status"], "SIMULATED")
        self.assertEqual(latest_cp["node_results"]["n1"]["status"], "SIMULATED")
        self.assertNotIn("n1", latest_cp["completed_nodes"])

    def test_resume_does_not_skip_simulated_node(self):
        """Resume must re-execute SIMULATED nodes, not skip them."""
        from se_core.orchestration.engine import OrchestrationEngine
        from se_core.agents.runner import AgentRunner

        # Two nodes: n1 (simulated on first run) -> n2 (real)
        # On resume, n1 should be re-executed with real provider
        self._write_workflow("WF-0002", [
            self._node("n1", "analyze"),
            self._node("n2", "plan", inputs={"prev": "context:n1_out"}),
        ], edges=[{"from": "n1", "to": "n2"}])

        engine = OrchestrationEngine(root=self.root)
        engine._find_project_dir = mock.MagicMock(return_value=self.project)

        # Track which nodes are executed and how many times
        execution_count = {"n1": 0, "n2": 0}

        def make_mock_run(should_simulate):
            """Create a mock run that returns SIMULATED or COMPLETED based on flag."""
            def mock_run(instance, action, inputs, context, max_tokens=None):
                node_id = "n1" if action == "analyze" else "n2"
                execution_count[node_id] += 1
                if node_id == "n1" and should_simulate:
                    return {"status": "SIMULATED", "output": {}, "outputs": {"n1_out": "simulated"}}
                # Real execution returns COMPLETED with real outputs
                return {"status": "COMPLETED", "output": {}, "outputs": {"n1_out": "real"} if node_id == "n1" else {}}
            return mock_run

        # First execution: n1 is SIMULATED (no llm_config)
        with mock.patch.object(AgentRunner, "run", make_mock_run(should_simulate=True)):
            with mock.patch.object(engine.memory_engine, "get", return_value=None):
                with mock.patch.object(engine, "_auto_save_memory"):
                    result1 = engine.execute("WF-0002", self.project_id)

        self.assertEqual(result1["status"], "SIMULATED")
        self.assertEqual(execution_count["n1"], 1)
        self.assertEqual(execution_count["n2"], 0)  # n2 never executed because n1 was SIMULATED

        # Load checkpoint and resume
        from se_core.orchestration.checkpoint import CheckpointManager
        cp_manager = CheckpointManager(self.project)
        checkpoints = cp_manager.list_checkpoints("WF-0002")
        self.assertGreater(len(checkpoints), 0)
        resume_cp = checkpoints[0]["checkpoint_id"]

        # Reset counter
        execution_count = {"n1": 0, "n2": 0}

        # Resume: n1 should be re-executed with REAL provider (should_simulate=False)
        # n2 should execute after n1 completes with real outputs
        with mock.patch.object(AgentRunner, "run", make_mock_run(should_simulate=False)):
            with mock.patch.object(engine.memory_engine, "get", return_value=None):
                with mock.patch.object(engine, "_auto_save_memory"):
                    result2 = engine.execute("WF-0002", self.project_id, resume_from_checkpoint=resume_cp)

        # n1 should be re-executed (not skipped), n2 should execute after
        self.assertEqual(execution_count["n1"], 1, "SIMULATED node must be re-executed on resume")
        self.assertEqual(execution_count["n2"], 1, "Downstream node must execute after SIMULATED node is re-run")
        self.assertEqual(result2["status"], "COMPLETED", "Full execution with real provider should complete")


if __name__ == "__main__":
    unittest.main()
