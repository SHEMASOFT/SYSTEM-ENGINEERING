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


class OrchestrateNativePromptTests(unittest.TestCase):
    """`orchestrate execute --native` must only reference tools that exist.

    OpenCode V2 exposes `subagent` (agent, description, prompt, model,
    sessionID, background). The generated prompt used to ask for an `invoke`
    tool that does not exist, so the native route could never be followed.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.project = support.make_project(self.root / "proj")
        self.project_id = "PRJ-TEST-001"

    def tearDown(self):
        self._tmp.cleanup()

    def _engine(self):
        from se_core.orchestration.engine import OrchestrationEngine
        engine = OrchestrationEngine(root=self.root)
        engine._find_project_dir = mock.MagicMock(return_value=self.project)
        return engine

    def _write_workflow(self, workflow_id="WF-NAT-0001"):
        support.write_json(self.project / "workflows" / f"{workflow_id}.json", {
            "schema_version": "1",
            "workflow_id": workflow_id,
            "project_id": self.project_id,
            "name": "Native prompt workflow",
            "version": "1.0.0",
            "status": "DRAFT",
            "nodes": [
                {"node_id": "n1", "agent": "analyst", "action": "analyze",
                 "inputs": {}, "outputs": {}},
                {"node_id": "n2", "agent": "planner", "action": "plan",
                 "inputs": {"prior": "context:n1_out"}, "outputs": {}},
            ],
            "edges": [{"from": "n1", "to": "n2"}],
            "gates": [],
        })
        return workflow_id

    def _prompt(self):
        workflow_id = self._write_workflow("WF-7001")
        return self._engine().generate_native_execution_prompt(workflow_id, self.project_id)

    def test_prompt_uses_the_native_subagent_tool(self):
        prompt = self._prompt()
        self.assertIn("`subagent`", prompt)
        self.assertNotIn("invoke", prompt.lower())

    def test_prompt_arguments_match_the_available_tool_schema(self):
        prompt = self._prompt()
        for name in ("agent", "description", "prompt", "background"):
            self.assertIn(f'"{name}"', prompt, name)
        # The `subagent` tool takes no structured payload and no tool wrapper.
        for stale in ('"tool"', '"arguments"', '"input"'):
            self.assertNotIn(stale, prompt, stale)

    def test_prompt_documents_background_only_for_independent_nodes(self):
        prompt = self._prompt()
        self.assertIn("background: true", prompt)
        self.assertIn("Never poll", prompt)
        # Internal SE orchestration must not be turned async by this route.
        self.assertIn("stay synchronous", prompt)

    def test_prompt_names_the_delegated_agents_from_the_workflow(self):
        prompt = self._prompt()
        self.assertIn("- **Agent**: analyst", prompt)
        self.assertIn("- **Agent**: planner", prompt)
        self.assertIn('"agent": "planner"', prompt)

    def test_build_native_subagent_input_still_filters_context(self):
        node = {"node_id": "n2", "agent": "planner", "action": "plan",
                "inputs": {"prior": "context:n1_out"}, "outputs": {}}
        result = self._engine().build_native_subagent_input(
            node, {"n1_out": "kept", "unrelated": "dropped"}, {"prior": "kept"}
        )
        self.assertEqual(result, {
            "action": "plan",
            "inputs": {"prior": "kept"},
            "context": {"n1_out": "kept"},
        })


class AgentRunnerMemoryToolTests(unittest.TestCase):
    """Tests for the memory tool in AgentRunner (P3-B.1)."""

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

    def _make_mock_result(self, status="COMPLETED", output=None, outputs=None, error=None):
        result = {
            "status": status,
            "output": output or {},
            "outputs": outputs or {},
        }
        if error:
            result["error"] = error
        return result

    def _make_engine_with_mocked_project(self):
        from se_core.orchestration.engine import OrchestrationEngine
        engine = OrchestrationEngine(root=self.root)
        engine._find_project_dir = mock.MagicMock(return_value=self.project)
        engine.memory_engine._find_project_dir = mock.MagicMock(return_value=self.project)
        return engine

    def test_memory_tool_get_existing(self):
        """memory.get retrieves content of existing memory."""
        from se_core.agents.runner import AgentRunner

        engine = self._make_engine_with_mocked_project()

        # Pre-create a memory directly in the engine's memory engine
        mem_result = engine.memory_engine.add(
            project_id=self.project_id,
            type="decision",
            content={"data": "test_content_for_retrieval"},
            author="test",
            scope="project",
            topic_key="test_memory_key",
        )
        mem_id = mem_result["memory_id"]

        # Create agent runner with the shared memory engine
        runner = AgentRunner(agent_name="analyst", project_dir=self.project, memory_engine=engine.memory_engine)

        # Test memory.get
        result = runner._invoke_memory_tool({"action": "get", "memory_id": mem_id})

        self.assertEqual(result["status"], "OK")
        self.assertIn("content", result)
        self.assertEqual(result["content"], {"data": "test_content_for_retrieval"})

    def test_memory_tool_get_missing(self):
        """memory.get with non-existent ID returns explicit error."""
        from se_core.agents.runner import AgentRunner

        engine = self._make_engine_with_mocked_project()
        runner = AgentRunner(agent_name="analyst", project_dir=self.project, memory_engine=engine.memory_engine)

        result = runner._invoke_memory_tool({"action": "get", "memory_id": "NONEXISTENT_ID"})

        self.assertEqual(result["status"], "ERROR")
        self.assertIn("Memory not found", result["error"])
        self.assertIn("NONEXISTENT_ID", result["error"])

    def test_memory_tool_get_wrong_project(self):
        """memory.get with memory from different project returns error."""
        from se_core.agents.runner import AgentRunner
        from se_core.memory.engine import MemoryEngine

        # Create a separate project
        project2 = support.make_project(self.root / "proj2")
        project2_id = "PRJ-TEST-002"

        # Create memory in project2 using a separate memory engine with mocked _find_project_dir
        mem_engine = MemoryEngine(root=self.root)
        mem_engine._find_project_dir = mock.MagicMock(return_value=self.root / "proj2")
        mem_result = mem_engine.add(
            project_id=project2_id,
            type="decision",
            content={"data": "project2_secret"},
            author="test",
            scope="project",
        )
        mem_id = mem_result["memory_id"]

        # Try to access from project1's runner
        engine = self._make_engine_with_mocked_project()
        runner = AgentRunner(agent_name="analyst", project_dir=self.project, memory_engine=engine.memory_engine)

        result = runner._invoke_memory_tool({"action": "get", "memory_id": mem_id})

        self.assertEqual(result["status"], "ERROR")
        self.assertIn("Memory not found", result["error"])

    def test_memory_tool_search(self):
        """memory.search returns hits with snippet."""
        from se_core.agents.runner import AgentRunner

        engine = self._make_engine_with_mocked_project()

        # Add some memories using the engine's memory engine
        for i in range(3):
            engine.memory_engine.add(
                project_id=self.project_id,
                type="decision",
                content={"data": f"searchable_content_{i}"},
                author="test",
                scope="project",
                topic_key=f"search_test_{i}",
            )

        runner = AgentRunner(agent_name="analyst", project_dir=self.project, memory_engine=engine.memory_engine)

        # Search for the content
        result = runner._invoke_memory_tool({"action": "search", "query": "searchable", "limit": 5})

        self.assertEqual(result["status"], "OK")
        self.assertIn("hits", result)
        self.assertGreaterEqual(len(result["hits"]), 3)
        for hit in result["hits"]:
            self.assertIn("memory_id", hit)
            self.assertIn("type", hit)
            self.assertIn("summary", hit)
            self.assertIn("score", hit)

    def test_memory_tool_invalid_action(self):
        """Invalid action returns explicit error."""
        from se_core.agents.runner import AgentRunner

        runner = AgentRunner(agent_name="analyst", project_dir=self.project)

        result = runner._invoke_memory_tool({"action": "invalid_action"})

        self.assertEqual(result["status"], "ERROR")
        self.assertIn("Invalid action", result["error"])
        self.assertIn("get, search", result["error"])

    def test_memory_tool_missing_memory_id(self):
        """get action without memory_id returns explicit error."""
        from se_core.agents.runner import AgentRunner

        runner = AgentRunner(agent_name="analyst", project_dir=self.project)

        result = runner._invoke_memory_tool({"action": "get"})

        self.assertEqual(result["status"], "ERROR")
        self.assertIn("memory_id required", result["error"])

    def test_memory_tool_search_missing_query(self):
        """search action without query returns explicit error."""
        from se_core.agents.runner import AgentRunner

        runner = AgentRunner(agent_name="analyst", project_dir=self.project)

        result = runner._invoke_memory_tool({"action": "search"})

        self.assertEqual(result["status"], "ERROR")
        self.assertIn("query required", result["error"])


class AgentRunnerInternalRouteIntegrationTests(unittest.TestCase):
    """End-to-end tests for internal route reference resolution (P3-B.1)."""

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

    def _make_mock_result(self, status="COMPLETED", output=None, outputs=None, error=None):
        result = {
            "status": status,
            "output": output or {},
            "outputs": outputs or {},
        }
        if error:
            result["error"] = error
        return result

    def _make_engine_with_mocked_project(self):
        from se_core.orchestration.engine import OrchestrationEngine
        engine = OrchestrationEngine(root=self.root)
        engine._find_project_dir = mock.MagicMock(return_value=self.project)
        engine.memory_engine._find_project_dir = mock.MagicMock(return_value=self.project)
        return engine

    def test_internal_route_resolves_reference(self):
        """Internal route: producer creates memory:new:, consumer uses memory.get and retrieves content."""
        from se_core.agents.runner import AgentRunner
        engine = self._make_engine_with_mocked_project()

        # Producer creates memory reference
        # Consumer consumes it via context:
        self._write_workflow("WF-0001", nodes=[
            {
                "node_id": "producer",
                "agent": "analyst",
                "action": "produce",
                "inputs": {},
                "outputs": {"result": "memory:new:shared_data"},
            },
            {
                "node_id": "consumer",
                "agent": "planner",
                "action": "consume",
                "inputs": {"data": "context:result"},
                "outputs": {},
            },
        ], edges=[{"from": "producer", "to": "consumer"}])

        workflow = engine.load_workflow("WF-0001", self.project_id)

        producer_result = self._make_mock_result(
            output={"result": "shared_content_value"},
            outputs={"result": "memory:new:shared_data"},
        )
        consumer_result = {"status": "COMPLETED", "output": {}, "outputs": {}}

        # Track if consumer received the reference
        consumer_inputs_captured = {}

        def mock_run(agent_self, action, inputs, context, max_tokens=None):
            if action == "produce":
                return producer_result
            elif action == "consume":
                # Consumer receives reference in inputs
                consumer_inputs_captured["inputs"] = inputs
                return consumer_result

        # Mock memory tool directly on the runner
        mock_mem_result = {"memory_id": "MEM-SHARED-123", "status": "created"}

        with mock.patch.object(AgentRunner, "run", mock_run):
            with mock.patch.object(engine.memory_engine, "get", return_value=None):
                with mock.patch.object(engine.memory_engine, "add", return_value={"memory_id": "MEM-SHARED-123", "status": "created"}):
                    result = engine.execute("WF-0001", self.project_id)

        self.assertEqual(result["status"], "COMPLETED")
        # Verify the reference was passed to consumer
        self.assertIn("data", consumer_inputs_captured.get("inputs", {}))
        ref = consumer_inputs_captured["inputs"]["data"]
        self.assertIsInstance(ref, dict)
        self.assertIn("memory_id", ref)

    def test_reference_resolution_on_demand(self):
        """LLM decides when to call memory.get (not automatic)."""
        from se_core.agents.runner import AgentRunner
        engine = self._make_engine_with_mocked_project()

        self._write_workflow("WF-0002", nodes=[
            {
                "node_id": "producer",
                "agent": "analyst",
                "action": "produce",
                "inputs": {},
                "outputs": {"result": "memory:new:optional_data"},
            },
            {
                "node_id": "consumer",
                "agent": "planner",
                "action": "consume",
                "inputs": {"data": "context:result"},
                "outputs": {},
            },
        ], edges=[{"from": "producer", "to": "consumer"}])

        workflow = engine.load_workflow("WF-0002", self.project_id)

        producer_result = self._make_mock_result(
            output={"result": "large_content_here"},
            outputs={"result": "memory:new:optional_data"},
        )
        consumer_result = self._make_mock_result(outputs={})

        def mock_run(agent_self, action, inputs, context, max_tokens=None):
            if action == "produce":
                return producer_result
            elif action == "consume":
                # Consumer receives reference but doesn't need to resolve it
                # for this task - it just passes it along
                self.assertIn("data", inputs)
                self.assertIsInstance(inputs["data"], dict)
                self.assertIn("memory_id", inputs["data"])
                return consumer_result

        with mock.patch.object(AgentRunner, "run", mock_run):
            with mock.patch.object(engine.memory_engine, "get", return_value=None):
                with mock.patch.object(engine.memory_engine, "add", return_value={"memory_id": "MEM-OPT-123", "status": "created"}):
                    result = engine.execute("WF-0002", self.project_id)

        self.assertEqual(result["status"], "COMPLETED")
        # Reference was passed but not resolved (consumer didn't need it)


class ReferenceDispatcherTests(unittest.TestCase):
    """Tests for P3-A ReferenceDispatcher auto-resolution."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.project = support.make_project(self.root / "proj")
        self.project_id = "PRJ-TEST-001"

    def tearDown(self):
        self._tmp.cleanup()

    def _make_engine_with_mocked_project(self):
        from se_core.orchestration.engine import OrchestrationEngine
        engine = OrchestrationEngine(root=self.root)
        engine._find_project_dir = mock.MagicMock(return_value=self.project)
        engine.memory_engine._find_project_dir = mock.MagicMock(return_value=self.project)
        return engine

    def test_dispatcher_resolves_memory_id_ref_in_inputs(self):
        """Dispatcher resolves {"memory_id": "..."} in inputs to actual content."""
        from se_core.orchestration.dispatcher import ReferenceDispatcher

        engine = self._make_engine_with_mocked_project()

        # Pre-create a memory
        mem_result = engine.memory_engine.add(
            project_id=self.project_id,
            type="decision",
            content={"key": "resolved_value"},
            author="test",
            scope="project",
        )
        mem_id = mem_result["memory_id"]

        # Create dispatcher and resolve
        dispatcher = ReferenceDispatcher(engine.memory_engine, self.project_id)
        inputs = {"data": {"memory_id": mem_id, "param": "result"}}
        resolved = dispatcher.resolve_inputs(inputs)

        self.assertEqual(resolved["data"], {"key": "resolved_value"})

    def test_dispatcher_resolves_memory_id_ref_in_context(self):
        """Dispatcher resolves {"memory_id": "..."} in context to actual content."""
        from se_core.orchestration.dispatcher import ReferenceDispatcher

        engine = self._make_engine_with_mocked_project()

        mem_result = engine.memory_engine.add(
            project_id=self.project_id,
            type="decision",
            content={"ctx_key": "ctx_value"},
            author="test",
            scope="project",
        )
        mem_id = mem_result["memory_id"]

        dispatcher = ReferenceDispatcher(engine.memory_engine, self.project_id)
        context = {"shared": {"memory_id": mem_id}}
        resolved = dispatcher.resolve_context(context)

        self.assertEqual(resolved["shared"], {"ctx_key": "ctx_value"})

    def test_dispatcher_preserves_non_reference_dicts(self):
        """Dispatcher doesn't modify dicts that aren't memory references."""
        from se_core.orchestration.dispatcher import ReferenceDispatcher

        engine = self._make_engine_with_mocked_project()
        dispatcher = ReferenceDispatcher(engine.memory_engine, self.project_id)

        # Regular content dict (has multiple content-like keys)
        inputs = {"data": {"output": "value", "status": "ok"}}
        resolved = dispatcher.resolve_inputs(inputs)

        self.assertEqual(resolved["data"], {"output": "value", "status": "ok"})

    def test_dispatcher_handles_missing_memory_gracefully(self):
        """Dispatcher returns unresolved marker for missing memory."""
        from se_core.orchestration.dispatcher import ReferenceDispatcher

        engine = self._make_engine_with_mocked_project()
        dispatcher = ReferenceDispatcher(engine.memory_engine, self.project_id)

        inputs = {"data": {"memory_id": "NONEXISTENT"}}
        resolved = dispatcher.resolve_inputs(inputs)

        self.assertIn("_unresolved", resolved["data"])
        self.assertEqual(resolved["data"]["error"], "not_found")

    def test_dispatcher_respects_auto_resolve_false(self):
        """Dispatcher with auto_resolve=False returns refs as-is."""
        from se_core.orchestration.dispatcher import ReferenceDispatcher

        engine = self._make_engine_with_mocked_project()

        mem_result = engine.memory_engine.add(
            project_id=self.project_id,
            type="decision",
            content={"key": "value"},
            author="test",
            scope="project",
        )
        mem_id = mem_result["memory_id"]

        dispatcher = ReferenceDispatcher(engine.memory_engine, self.project_id, auto_resolve=False)
        inputs = {"data": {"memory_id": mem_id}}
        resolved = dispatcher.resolve_inputs(inputs)

        # Should return ref as-is
        self.assertEqual(resolved["data"], {"memory_id": mem_id})

    def test_dispatcher_handles_nested_references(self):
        """Dispatcher resolves references nested in lists/dicts."""
        from se_core.orchestration.dispatcher import ReferenceDispatcher

        engine = self._make_engine_with_mocked_project()

        mem_result = engine.memory_engine.add(
            project_id=self.project_id,
            type="decision",
            content={"nested": "data"},
            author="test",
            scope="project",
        )
        mem_id = mem_result["memory_id"]

        dispatcher = ReferenceDispatcher(engine.memory_engine, self.project_id)
        inputs = {
            "list_refs": [{"memory_id": mem_id}, {"memory_id": mem_id}],
            "dict_refs": {"a": {"memory_id": mem_id}, "b": "literal"}
        }
        resolved = dispatcher.resolve_inputs(inputs)

        self.assertEqual(resolved["list_refs"][0], {"nested": "data"})
        self.assertEqual(resolved["list_refs"][1], {"nested": "data"})
        self.assertEqual(resolved["dict_refs"]["a"], {"nested": "data"})
        self.assertEqual(resolved["dict_refs"]["b"], "literal")


class DispatcherIntegrationTests(unittest.TestCase):
    """End-to-end tests for dispatcher auto-resolution in workflow execution."""

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

    def _make_mock_result(self, status="COMPLETED", output=None, outputs=None, error=None):
        result = {
            "status": status,
            "output": output or {},
            "outputs": outputs or {},
        }
        if error:
            result["error"] = error
        return result

    def _make_engine_with_mocked_project(self):
        from se_core.orchestration.engine import OrchestrationEngine
        engine = OrchestrationEngine(root=self.root)
        engine._find_project_dir = mock.MagicMock(return_value=self.project)
        engine.memory_engine._find_project_dir = mock.MagicMock(return_value=self.project)
        return engine

    def test_dispatcher_auto_resolves_in_workflow(self):
        """Dispatcher auto-resolves memory refs when node has auto_resolve_refs=true (default)."""
        from se_core.agents.runner import AgentRunner
        engine = self._make_engine_with_mocked_project()

        # Producer creates memory reference
        # Consumer receives it via context - should be auto-resolved by dispatcher
        self._write_workflow("WF-0100", nodes=[
            {
                "node_id": "producer",
                "agent": "analyst",
                "action": "produce",
                "inputs": {},
                "outputs": {"result": "memory:new:shared_data"},
            },
            {
                "node_id": "consumer",
                "agent": "planner",
                "action": "consume",
                "inputs": {"data": "context:result"},
                "outputs": {},
            },
        ], edges=[{"from": "producer", "to": "consumer"}])

        workflow = engine.load_workflow("WF-0100", self.project_id)

        producer_result = self._make_mock_result(
            output={"result": "shared_content_value"},
            outputs={"result": "memory:new:shared_data"},
        )
        consumer_inputs_captured = {}

        def mock_run(agent_self, action, inputs, context, max_tokens=None):
            if action == "produce":
                return producer_result
            elif action == "consume":
                consumer_inputs_captured["inputs"] = inputs
                return {"status": "COMPLETED", "output": {}, "outputs": {}}

        # Mock memory engine to return the created memory
        created_mem_id = "MEM-DISP-123"
        created_content = {"result": "shared_content_value"}

        with mock.patch.object(AgentRunner, "run", mock_run):
            with mock.patch.object(engine.memory_engine, "get", return_value=None):
                with mock.patch.object(engine.memory_engine, "add", return_value={"memory_id": created_mem_id, "status": "created"}):
                    # The dispatcher will call memory_engine.get again to resolve the reference
                    def mock_get(mem_id, proj_id):
                        if mem_id == created_mem_id:
                            return {"content": created_content, "memory_id": mem_id}
                        return None
                    engine.memory_engine.get = mock_get
                    result = engine.execute("WF-0100", self.project_id)

        self.assertEqual(result["status"], "COMPLETED")
        # Consumer should receive RESOLVED content, not reference
        self.assertIn("data", consumer_inputs_captured.get("inputs", {}))
        data = consumer_inputs_captured["inputs"]["data"]
        self.assertEqual(data, {"result": "shared_content_value"})
        self.assertNotIn("memory_id", data)

    def test_dispatcher_can_be_disabled_per_node(self):
        """Node with auto_resolve_refs=false receives reference, not resolved content."""
        from se_core.agents.runner import AgentRunner
        engine = self._make_engine_with_mocked_project()

        self._write_workflow("WF-0101", nodes=[
            {
                "node_id": "producer",
                "agent": "analyst",
                "action": "produce",
                "inputs": {},
                "outputs": {"result": "memory:new:shared_data"},
            },
            {
                "node_id": "consumer",
                "agent": "planner",
                "action": "consume",
                "inputs": {"data": "context:result"},
                "outputs": {},
                "auto_resolve_refs": False,  # Disable auto-resolution
            },
        ], edges=[{"from": "producer", "to": "consumer"}])

        workflow = engine.load_workflow("WF-0101", self.project_id)

        producer_result = self._make_mock_result(
            output={"result": "shared_content_value"},
            outputs={"result": "memory:new:shared_data"},
        )
        consumer_inputs_captured = {}

        def mock_run(agent_self, action, inputs, context, max_tokens=None):
            if action == "produce":
                return producer_result
            elif action == "consume":
                consumer_inputs_captured["inputs"] = inputs
                return {"status": "COMPLETED", "output": {}, "outputs": {}}

        created_mem_id = "MEM-DISP-456"

        with mock.patch.object(AgentRunner, "run", mock_run):
            with mock.patch.object(engine.memory_engine, "get", return_value=None):
                with mock.patch.object(engine.memory_engine, "add", return_value={"memory_id": created_mem_id, "status": "created"}):
                    result = engine.execute("WF-0101", self.project_id)

        self.assertEqual(result["status"], "COMPLETED")
        # Consumer should receive REFERENCE (not resolved) because auto_resolve_refs=false
        self.assertIn("data", consumer_inputs_captured.get("inputs", {}))
        data = consumer_inputs_captured["inputs"]["data"]
        self.assertIsInstance(data, dict)
        self.assertIn("memory_id", data)
        self.assertNotIn("result", data)  # Content not resolved


class NativeExecutionModeTests(unittest.TestCase):
    """Tests for P3-C native execution mode (OpenCode subagent tool)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.project = support.make_project(self.root / "proj")
        self.project_id = "PRJ-TEST-001"

    def tearDown(self):
        self._tmp.cleanup()

    def _write_workflow(self, workflow_id, nodes, edges=None, gates=None, execution_mode="internal"):
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
            "execution_mode": execution_mode,
        }
        support.write_json(self.project / "workflows" / f"{workflow_id}.json", data)

    def _make_engine_with_mocked_project(self):
        from se_core.orchestration.engine import OrchestrationEngine
        engine = OrchestrationEngine(root=self.root)
        engine._find_project_dir = mock.MagicMock(return_value=self.project)
        engine.memory_engine._find_project_dir = mock.MagicMock(return_value=self.project)
        return engine

    def test_native_execution_mode_returns_prompt(self):
        """Workflow with execution_mode=native returns NATIVE status and prompt."""
        from se_core.orchestration.engine import OrchestrationEngine
        engine = self._make_engine_with_mocked_project()

        self._write_workflow("WF-0200", nodes=[
            {"node_id": "n1", "agent": "analyst", "action": "analyze", "inputs": {}, "outputs": {}},
        ], execution_mode="native")

        result = engine.execute("WF-0200", self.project_id)

        self.assertEqual(result["status"], "NATIVE")
        self.assertIn("native_prompt", result)
        self.assertIn("WF-0200", result["native_prompt"])
        self.assertIn("subagent", result["native_prompt"])

    def test_internal_execution_mode_still_works(self):
        """Workflow with execution_mode=internal (default) runs normally."""
        from se_core.orchestration.engine import OrchestrationEngine
        engine = self._make_engine_with_mocked_project()

        self._write_workflow("WF-0201", nodes=[
            {"node_id": "n1", "agent": "analyst", "action": "analyze", "inputs": {}, "outputs": {}},
        ], execution_mode="internal")

        # Mock the runner to avoid actual LLM calls
        def mock_run(agent_self, action, inputs, context, max_tokens=None):
            return {"status": "COMPLETED", "output": {}, "outputs": {}}

        with mock.patch("se_core.agents.runner.AgentRunner.run", mock_run):
            result = engine.execute("WF-0201", self.project_id)

        self.assertEqual(result["status"], "COMPLETED")

    def test_native_execution_via_cli_flag(self):
        """CLI --native flag generates prompt regardless of workflow config."""
        from se_core.orchestration.engine import OrchestrationEngine
        engine = self._make_engine_with_mocked_project()

        # Workflow with default internal mode
        self._write_workflow("WF-0202", nodes=[
            {"node_id": "n1", "agent": "analyst", "action": "analyze", "inputs": {}, "outputs": {}},
        ])  # No execution_mode specified -> defaults to internal

        # The CLI --native flag is handled in commands.py, not engine
        # But we can test that generate_native_execution_prompt works for any workflow
        prompt = engine.generate_native_execution_prompt("WF-0202", self.project_id)
        self.assertIn("subagent", prompt)
        self.assertIn("WF-0202", prompt)


if __name__ == "__main__":
    unittest.main()
