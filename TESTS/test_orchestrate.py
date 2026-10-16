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


class OrchestrationContextFilteringTests(unittest.TestCase):
    """Tests for context filtering in _execute_node (token economy)."""

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

    def _make_mock_result(self, status="COMPLETED", output=None, outputs=None):
        """Create a mock AgentRunner.run result."""
        return {
            "status": status,
            "output": output or {},
            "outputs": outputs or {},
        }

    def _make_engine_with_mocked_project(self):
        """Create engine with mocked _find_project_dir to return test project."""
        from se_core.orchestration.engine import OrchestrationEngine
        engine = OrchestrationEngine(root=self.root)
        # Mock _find_project_dir to return our test project
        engine._find_project_dir = mock.MagicMock(return_value=self.project)
        return engine

    def test_context_filtered_to_only_declared_keys(self):
        """Node receives only context keys it declares via inputs.context:*."""
        from se_core.agents.runner import AgentRunner
        engine = self._make_engine_with_mocked_project()
        
        # Workflow with two nodes: first produces output, second consumes specific key
        self._write_workflow("WF-0001", nodes=[
            {
                "node_id": "producer",
                "agent": "analyst",
                "action": "produce_data",
                "inputs": {},
                "outputs": {"result": "memory:producer_result"},
            },
            {
                "node_id": "consumer",
                "agent": "planner",
                "action": "plan",
                "inputs": {"data": "context:producer_result"},
                "outputs": {},
            },
        ], edges=[{"from": "producer", "to": "consumer"}])

        workflow = engine.load_workflow("WF-0001", self.project_id)

        # Test _execute_node directly with mocked AgentRunner
        mock_result = self._make_mock_result(outputs={"produced": "value"})
        captured = {}
        def mock_run(self, action, inputs, context, max_tokens=None):
            captured["context"] = context
            captured["action"] = action
            captured["max_tokens"] = max_tokens
            return mock_result

        with mock.patch.object(AgentRunner, "run", mock_run):
            with mock.patch.object(engine.memory_engine, "get", return_value=None):
                node1 = workflow["nodes"][0]
                project_dir = self.project
                context = {"workflow_id": "WF-0001", "project_id": self.project_id, "extra": "should_not_be_sent"}
                engine._execute_node(node1, project_dir, context, workflow)

        # Verify first node got empty context (no context: refs in inputs)
        self.assertEqual(captured.get("context"), {}, 
            "Node with no context: refs should receive empty context")
        self.assertIsNone(captured.get("max_tokens"))

    def test_context_includes_only_referenced_keys(self):
        """Node with context: refs receives only those keys."""
        from se_core.agents.runner import AgentRunner
        engine = self._make_engine_with_mocked_project()
        
        self._write_workflow("WF-0002", nodes=[
            {
                "node_id": "consumer",
                "agent": "planner",
                "action": "plan",
                "inputs": {
                    "needed": "context:workflow_id",
                    "also_needed": "context:project_id",
                },
                "outputs": {},
            },
        ])

        workflow = engine.load_workflow("WF-0002", self.project_id)
        node = workflow["nodes"][0]
        project_dir = self.project
        
        # Full context with extra keys that should NOT be passed
        full_context = {
            "workflow_id": "WF-0002",
            "project_id": self.project_id,
            "project_name": "Test",
            "project_data": workflow,
            "previous_node_output": "large_data_that_should_not_be_sent",
            "another_key": "more_data",
        }

        mock_result = self._make_mock_result()
        captured = {}
        def mock_run(self, action, inputs, context, max_tokens=None):
            captured["context"] = context
            captured["inputs"] = inputs
            captured["max_tokens"] = max_tokens
            return mock_result

        with mock.patch.object(AgentRunner, "run", mock_run):
            with mock.patch.object(engine.memory_engine, "get", return_value=None):
                engine._execute_node(node, project_dir, full_context, workflow)

        # Verify only declared keys are in context
        received_context = captured.get("context", {})
        self.assertIn("workflow_id", received_context)
        self.assertIn("project_id", received_context)
        self.assertNotIn("project_name", received_context)
        self.assertNotIn("project_data", received_context)
        self.assertNotIn("previous_node_output", received_context)
        self.assertNotIn("another_key", received_context)
        self.assertEqual(len(received_context), 2)
        self.assertIsNone(captured.get("max_tokens"))

    def test_context_empty_when_no_context_refs(self):
        """Node with no context: refs receives empty context."""
        from se_core.agents.runner import AgentRunner
        engine = self._make_engine_with_mocked_project()
        
        self._write_workflow("WF-0003", nodes=[
            {
                "node_id": "no-context",
                "agent": "analyst",
                "action": "analyze",
                "inputs": {"param": "literal:fixed_value"},
                "outputs": {},
            },
        ])

        workflow = engine.load_workflow("WF-0003", self.project_id)
        node = workflow["nodes"][0]
        project_dir = self.project
        
        full_context = {"key1": "value1", "key2": "value2"}

        mock_result = self._make_mock_result()
        captured = {}
        def mock_run(self, action, inputs, context, max_tokens=None):
            captured["context"] = context
            captured["max_tokens"] = max_tokens
            return mock_result

        with mock.patch.object(AgentRunner, "run", mock_run):
            with mock.patch.object(engine.memory_engine, "get", return_value=None):
                engine._execute_node(node, project_dir, full_context, workflow)

        self.assertEqual(captured.get("context"), {})
        self.assertIsNone(captured.get("max_tokens"))

    def test_memory_and_literal_inputs_still_work(self):
        """Non-context inputs (memory:, literal:) still resolve correctly."""
        from se_core.agents.runner import AgentRunner
        engine = self._make_engine_with_mocked_project()
        
        self._write_workflow("WF-0004", nodes=[
            {
                "node_id": "mixed",
                "agent": "analyst",
                "action": "analyze",
                "inputs": {
                    "from_memory": "memory:some_mem",
                    "from_literal": "literal:fixed",
                    "from_context": "context:workflow_id",
                },
                "outputs": {},
            },
        ])

        workflow = engine.load_workflow("WF-0004", self.project_id)
        node = workflow["nodes"][0]
        project_dir = self.project
        
        full_context = {"workflow_id": "WF-0004", "extra": "should_not_pass"}

        mock_result = self._make_mock_result()
        captured = {}
        def mock_run(self, action, inputs, context, max_tokens=None):
            captured["inputs"] = inputs
            captured["context"] = context
            captured["max_tokens"] = max_tokens
            return mock_result

        with mock.patch.object(AgentRunner, "run", mock_run):
            # Mock memory_engine.get to return a value for the memory source
            with mock.patch.object(engine.memory_engine, "get", 
                                 return_value={"content": {"mem_key": "mem_value"}}):
                engine._execute_node(node, project_dir, full_context, workflow)

        inputs = captured.get("inputs", {})
        self.assertEqual(inputs.get("from_literal"), "fixed")
        self.assertEqual(inputs.get("from_context"), "WF-0004")
        self.assertEqual(inputs.get("from_memory"), {"mem_key": "mem_value"})
        # Context should only have workflow_id
        self.assertEqual(captured.get("context"), {"workflow_id": "WF-0004"})
        self.assertIsNone(captured.get("max_tokens"))

    def test_context_accumulation_still_works_for_dependent_nodes(self):
        """Context accumulates outputs for subsequent nodes that declare them."""
        from se_core.agents.runner import AgentRunner
        engine = self._make_engine_with_mocked_project()
        
        # Two nodes: producer -> consumer
        # Producer outputs to context key "step1_result"
        # Consumer declares it needs "context:step1_result"
        self._write_workflow("WF-0005", nodes=[
            {
                "node_id": "producer",
                "agent": "analyst",
                "action": "produce",
                "inputs": {},
                "outputs": {"step1_result": "memory:producer_mem"},  # output mapping
            },
            {
                "node_id": "consumer",
                "agent": "planner",
                "action": "consume",
                "inputs": {"prev": "context:step1_result"},
                "outputs": {},
            },
        ], edges=[{"from": "producer", "to": "consumer"}])

        workflow = engine.load_workflow("WF-0005", self.project_id)
        project_dir = self.project

        # Simulate execution order
        node_map = {n["node_id"]: n for n in workflow["nodes"]}
        
        # Track what each node receives
        received_contexts = {}
        
        producer_result = self._make_mock_result(outputs={"step1_result": "produced_value"})
        consumer_result = self._make_mock_result(outputs={})
        
        def make_mock_run(node_id, result):
            def mock_run(self, action, inputs, context, max_tokens=None):
                received_contexts[node_id] = context
                return result
            return mock_run

        with mock.patch.object(AgentRunner, "run", make_mock_run("producer", producer_result)):
            with mock.patch.object(engine.memory_engine, "get", return_value=None):
                engine._execute_node(node_map["producer"], project_dir, {}, workflow)

        # After producer, context should have step1_result from its outputs
        # The execute() method does: context.update(result.get("outputs", {}))
        # So for the consumer, context should have step1_result
        context_after_producer = {"step1_result": "produced_value"}

        with mock.patch.object(AgentRunner, "run", make_mock_run("consumer", consumer_result)):
            with mock.patch.object(engine.memory_engine, "get", return_value=None):
                engine._execute_node(node_map["consumer"], project_dir, context_after_producer, workflow)

        # Consumer should receive step1_result in context
        consumer_context = received_contexts.get("consumer", {})
        self.assertIn("step1_result", consumer_context)
        self.assertEqual(consumer_context["step1_result"], "produced_value")


class OrchestrationGateEnforcementTests(unittest.TestCase):
    """Top-level `gates` array must be enforced by the engine, without duplication.

    The engine previously only read a per-node ``gate`` field, so a workflow
    that declared its gates in the top-level ``gates`` array (the documented
    shape) ran with no gate enforcement at all. These tests pin the unified
    node -> gate resolution, the FAIL/WARN-only blocking (mirroring `se
    transition`), and that each gate is evaluated exactly once.
    """

    PROJECT_ID = "PRJ-TEST-001"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.project = support.make_project(self.root / "proj")

    def tearDown(self):
        self._tmp.cleanup()

    def _write_workflow(self, workflow_id, nodes, edges=None, gates=None):
        data = {
            "schema_version": "1",
            "workflow_id": workflow_id,
            "project_id": self.PROJECT_ID,
            "name": "Gate workflow",
            "version": "1.0.0",
            "status": "DRAFT",
            "nodes": nodes,
            "edges": edges or [],
            "gates": gates or [],
        }
        support.write_json(self.project / "workflows" / f"{workflow_id}.json", data)

    def _make_engine(self):
        from se_core.orchestration.engine import OrchestrationEngine
        engine = OrchestrationEngine(root=self.root)
        engine._find_project_dir = mock.MagicMock(return_value=self.project)
        return engine

    # --- _resolve_node_gates -------------------------------------------------

    def test_resolver_maps_top_level_array(self):
        """Nodes listed in the top-level gates array resolve to that gate."""
        from se_core.orchestration.engine import OrchestrationEngine
        wf = {
            "nodes": [{"node_id": "a"}, {"node_id": "b"}],
            "gates": [{"gate_id": "G1", "nodes": ["b"]}],
        }
        self.assertEqual(
            OrchestrationEngine._resolve_node_gates(wf),
            {"b": "G1"},
        )

    def test_resolver_per_node_gate_overrides_array(self):
        """A per-node `gate` wins over the array (no duplicate/conflicting map)."""
        from se_core.orchestration.engine import OrchestrationEngine
        wf = {
            "nodes": [{"node_id": "a"}, {"node_id": "b", "gate": "G2"}],
            "gates": [{"gate_id": "G1", "nodes": ["b"]}],
        }
        # b keeps its explicit G2; array's G1 for b is superseded, not duplicated.
        self.assertEqual(
            OrchestrationEngine._resolve_node_gates(wf),
            {"b": "G2"},
        )

    def test_resolver_rejects_node_in_two_gates(self):
        """A node listed under two different gates is a definition error."""
        from se_core.orchestration.engine import OrchestrationEngine
        wf = {
            "nodes": [{"node_id": "a"}],
            "gates": [
                {"gate_id": "G1", "nodes": ["a"]},
                {"gate_id": "G2", "nodes": ["a"]},
            ],
        }
        with self.assertRaises(ValueError):
            OrchestrationEngine._resolve_node_gates(wf)

    # --- execute() enforcement ---------------------------------------------

    def _run_execute(self, gate_status_by_id, nodes, edges, gates):
        """Run execute() with AgentRunner and evaluate_gate mocked.

        Returns (result, call_log) where call_log lists evaluated gate_ids.
        """
        from se_core.agents.runner import AgentRunner
        engine = self._make_engine()
        self._write_workflow("WF-0001", nodes=nodes, edges=edges, gates=gates)

        call_log = []

        def fake_evaluate_gate(project_dir, gate_id, root=None):
            call_log.append(gate_id)
            status = gate_status_by_id.get(gate_id, "PASS")
            return {"gate": gate_id, "conditions": [], "status": status}

        def fake_run(self, action, inputs, context, max_tokens=None):
            return {"status": "COMPLETED", "output": {}, "outputs": {}}

        with mock.patch("se_core.orchestration.engine.evaluate_gate", fake_evaluate_gate):
            with mock.patch.object(AgentRunner, "run", fake_run):
                with mock.patch.object(engine.memory_engine, "get", return_value=None):
                    result = engine.execute("WF-0001", self.PROJECT_ID)
        return result, call_log

    def test_fail_gate_from_array_blocks_node(self):
        """A FAIL gate declared in the top-level array blocks its node."""
        nodes = [
            {"node_id": "n1", "agent": "analyst", "action": "a", "inputs": {}, "outputs": {}},
            {"node_id": "n2", "agent": "planner", "action": "p", "inputs": {}, "outputs": {}},
        ]
        edges = [{"from": "n1", "to": "n2"}]
        gates = [{"gate_id": "G1", "nodes": ["n2"]}]

        result, call_log = self._run_execute({"G1": "FAIL"}, nodes, edges, gates)

        self.assertEqual(result["status"], "FAILED")
        self.assertIn("G1", call_log)
        self.assertIn("G1", result.get("error", ""))

    def test_manual_gate_does_not_block(self):
        """MANUAL gates are attested at the lifecycle boundary, not blocked here."""
        nodes = [
            {"node_id": "n1", "agent": "analyst", "action": "a", "inputs": {}, "outputs": {}},
            {"node_id": "n2", "agent": "planner", "action": "p", "inputs": {}, "outputs": {}},
        ]
        edges = [{"from": "n1", "to": "n2"}]
        gates = [{"gate_id": "G1", "nodes": ["n2"]}]

        result, call_log = self._run_execute({"G1": "MANUAL"}, nodes, edges, gates)

        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["gate_results"]["G1"]["status"], "MANUAL")
        self.assertEqual(result["node_states"]["n2"]["status"], "COMPLETED")

    def test_shared_gate_evaluated_once(self):
        """Two nodes sharing one gate -> evaluate_gate called exactly once."""
        nodes = [
            {"node_id": "n1", "agent": "analyst", "action": "a", "inputs": {}, "outputs": {}},
            {"node_id": "n2", "agent": "planner", "action": "p", "inputs": {}, "outputs": {}},
            {"node_id": "n3", "agent": "analyst", "action": "a", "inputs": {}, "outputs": {}},
        ]
        edges = [{"from": "n1", "to": "n2"}, {"from": "n2", "to": "n3"}]
        gates = [{"gate_id": "G1", "nodes": ["n2", "n3"]}]

        result, call_log = self._run_execute({"G1": "PASS"}, nodes, edges, gates)

        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(call_log.count("G1"), 1, "gate must be evaluated once, not duplicated")

    def test_node_level_gate_still_enforced(self):
        """The pre-existing per-node `gate` field continues to work."""
        nodes = [
            {"node_id": "n1", "agent": "analyst", "action": "a", "inputs": {}, "outputs": {}},
            {"node_id": "n2", "agent": "planner", "action": "p", "inputs": {}, "outputs": {}, "gate": "G2"},
        ]
        edges = [{"from": "n1", "to": "n2"}]

        result, call_log = self._run_execute({"G2": "WARN"}, nodes, edges, gates=[])

        self.assertEqual(result["status"], "FAILED")
        self.assertIn("G2", call_log)


if __name__ == "__main__":
    unittest.main()
