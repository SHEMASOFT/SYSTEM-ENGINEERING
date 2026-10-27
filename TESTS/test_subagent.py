"""F1-A1: `se subagent` must not report false success.

These tests use deterministic stubs only: no network, no credentials and no
real LLM provider. They cover the provider/result/CLI contract fixed in F1-A1:

* absent ``llm_config`` is not silently presented as a real execution;
* explicit simulation is labelled ``SIMULATED`` and uses a distinct exit code;
* provider errors, empty/malformed responses and tool failures are ``FAILED``;
* a valid provider response is still ``COMPLETED`` with exit code 0.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.agents.runner import AgentRunner  # noqa: E402
from se_core.llm.providers import DummyProvider, LLMResponse  # noqa: E402


class StubProvider:
    """Minimal provider stub (not a DummyProvider) for deterministic tests."""

    def __init__(self, response):
        self.response = response
        self.calls = []

    def chat(self, messages, tools=None, temperature=0.3, max_tokens=4096, **kwargs):
        self.calls.append(
            {
                "messages": messages,
                "tools": tools,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        return self.response


class _ProjectTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = support.make_project(Path(self._tmp.name) / "proj")

    def tearDown(self):
        self._tmp.cleanup()


class AgentRunnerResultTests(_ProjectTestCase):
    def _run_with(self, response):
        stub = StubProvider(response)
        with mock.patch.object(AgentRunner, "_load_agent_config", return_value={}):
            with mock.patch.object(
                AgentRunner, "_create_llm_provider", return_value=stub
            ):
                runner = AgentRunner(agent_name="analyst", project_dir=self.project)
        return runner.run(action="analyze", inputs={}, context={})

    def test_provider_error_finish_reason_is_failed(self):
        result = self._run_with(
            LLMResponse(
                content="",
                finish_reason="error",
                raw_response={"error": "401 unauthorized"},
            )
        )
        self.assertEqual(result["status"], "FAILED")
        self.assertIn("401 unauthorized", result["error"])

    def test_empty_response_is_failed(self):
        result = self._run_with(LLMResponse(content="   ", finish_reason="stop"))
        self.assertEqual(result["status"], "FAILED")
        self.assertIn("empty", result["error"].lower())

    def test_malformed_json_is_failed(self):
        result = self._run_with(
            LLMResponse(content="this is not json", finish_reason="stop")
        )
        self.assertEqual(result["status"], "FAILED")
        self.assertIn("non-JSON", result["error"])

    def test_json_array_is_failed(self):
        result = self._run_with(LLMResponse(content='["x"]', finish_reason="stop"))
        self.assertEqual(result["status"], "FAILED")

    def test_missing_status_is_failed(self):
        result = self._run_with(
            LLMResponse(content='{"output": {}}', finish_reason="stop")
        )
        self.assertEqual(result["status"], "FAILED")

    def test_provider_reported_failed_is_failed(self):
        result = self._run_with(
            LLMResponse(
                content='{"status": "FAILED", "error": "boom"}',
                finish_reason="stop",
            )
        )
        self.assertEqual(result["status"], "FAILED")
        self.assertIn("boom", result["error"])

    def test_tool_call_failure_is_not_completed(self):
        tool_calls = [
            {
                "id": "call-1",
                "function": {"name": "read", "arguments": "{}"},
            }
        ]
        result = self._run_with(
            LLMResponse(
                content="",
                tool_calls=tool_calls,
                finish_reason="tool_calls",
            )
        )
        self.assertEqual(result["status"], "FAILED")
        self.assertIn("Tool execution failed", result["error"])
        self.assertNotIn("COMPLETED", result["status"])

    def test_valid_response_completes(self):
        result = self._run_with(
            LLMResponse(
                content='{"status": "COMPLETED", "output": {"ok": true}}',
                finish_reason="stop",
            )
        )
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["output"]["status"], "COMPLETED")
        self.assertEqual(result["output"]["output"], {"ok": True})

    def test_dummy_without_llm_config_is_simulated(self):
        with mock.patch.object(AgentRunner, "_load_agent_config", return_value={}):
            runner = AgentRunner(agent_name="analyst", project_dir=self.project)
        self.assertTrue(runner.simulated)
        result = runner.run(action="analyze", inputs={}, context={})
        self.assertEqual(result["status"], "SIMULATED")
        # The nested provider payload must not keep claiming a real completion.
        self.assertEqual(result["output"]["status"], "SIMULATED")
        self.assertNotEqual(result["output"]["status"], "COMPLETED")
        self.assertIn("echo", result["output"]["output"])


class OrchestrationConsumerRegressionTests(_ProjectTestCase):
    """I-1 regression tests: the engine must propagate SIMULATED correctly.

    These tests verify that a real AgentRunner + DummyProvider returning
    SIMULATED is correctly handled by OrchestrationEngine:
    - The engine receives SIMULATED from the runner
    - The engine returns SIMULATED (not COMPLETED) as execution status
    - The node state is SIMULATED (not COMPLETED)
    - No decision memory is saved for simulated nodes
    - Outputs are not propagated to context
    """

    PROJECT_ID = "PRJ-TEST-001"

    def _write_workflow(self):
        support.write_json(
            self.project / "workflows" / "WF-0001.json",
            {
                "schema_version": "1",
                "workflow_id": "WF-0001",
                "project_id": self.PROJECT_ID,
                "name": "Simulated consumer regression",
                "version": "1.0.0",
                "status": "DRAFT",
                "nodes": [
                    {
                        "node_id": "n1",
                        "agent": "analyst",
                        "action": "analyze",
                        "inputs": {},
                        "outputs": {},
                    }
                ],
                "edges": [],
                "gates": [],
            },
        )

    def test_engine_propagates_simulated_status(self):
        """Engine must return SIMULATED when a node returns SIMULATED."""
        from se_core.orchestration.engine import OrchestrationEngine

        self._write_workflow()

        # 1. Real runner path: agent has no llm_config, so AgentRunner
        #    selects DummyProvider and returns SIMULATED.
        runner = AgentRunner(agent_name="analyst", project_dir=self.project)
        self.assertTrue(runner.simulated)
        simulated = runner.run(action="analyze", inputs={}, context={})
        self.assertEqual(simulated["status"], "SIMULATED")

        # 2. Feed real SIMULATED result into the engine.
        engine = OrchestrationEngine(root=self.project.parent)
        engine._find_project_dir = mock.MagicMock(return_value=self.project)
        real_run = AgentRunner.run
        received = {}

        def recording_run(instance, *args, **kwargs):
            result = real_run(instance, *args, **kwargs)
            received["status"] = result.get("status")
            return result

        with mock.patch.object(AgentRunner, "run", recording_run):
            with mock.patch.object(engine.memory_engine, "get", return_value=None):
                with mock.patch.object(engine, "_auto_save_memory"):
                    result = engine.execute("WF-0001", self.PROJECT_ID)

        # 3. Engine must receive SIMULATED from runner.
        self.assertEqual(received.get("status"), "SIMULATED")

        # 4. Engine must return SIMULATED (not COMPLETED) as execution status.
        self.assertEqual(result["status"], "SIMULATED")

        # 5. Node state must be SIMULATED (not COMPLETED).
        self.assertEqual(result["node_states"]["n1"]["status"], "SIMULATED")

    def test_engine_does_not_propagate_simulated_outputs_to_context(self):
        """Outputs from SIMULATED node must not pollute execution context."""
        from se_core.orchestration.engine import OrchestrationEngine

        self._write_workflow()

        engine = OrchestrationEngine(root=self.project.parent)
        engine._find_project_dir = mock.MagicMock(return_value=self.project)

        with mock.patch.object(engine.memory_engine, "get", return_value=None):
            with mock.patch.object(engine, "_auto_save_memory"):
                result = engine.execute("WF-0001", self.PROJECT_ID)

        # Context should be empty since SIMULATED node outputs are not propagated
        self.assertEqual(result["context"], {})

    def test_engine_does_not_save_decision_memory_for_simulated(self):
        """No decision memory should be saved for SIMULATED nodes."""
        from se_core.orchestration.engine import OrchestrationEngine

        self._write_workflow()

        engine = OrchestrationEngine(root=self.project.parent)
        engine._find_project_dir = mock.MagicMock(return_value=self.project)
        memory_calls = []

        def mock_save_memory(**kwargs):
            memory_calls.append(kwargs)

        with mock.patch.object(engine.memory_engine, "get", return_value=None):
            with mock.patch.object(engine, "_auto_save_memory", side_effect=mock_save_memory):
                result = engine.execute("WF-0001", self.PROJECT_ID)

        # Check that no decision memory was saved for the simulated node
        decision_calls = [c for c in memory_calls if c.get("memory_type") == "decision"]
        self.assertEqual(len(decision_calls), 0, "No decision memory should be saved for SIMULATED nodes")

    def test_checkpoint_contains_simulated_node(self):
        """Checkpoint must include SIMULATED node with correct status."""
        from se_core.orchestration.engine import OrchestrationEngine
        from se_core.orchestration.checkpoint import CheckpointManager

        self._write_workflow()

        engine = OrchestrationEngine(root=self.project.parent)
        engine._find_project_dir = mock.MagicMock(return_value=self.project)

        with mock.patch.object(engine.memory_engine, "get", return_value=None):
            with mock.patch.object(engine, "_auto_save_memory"):
                result = engine.execute("WF-0001", self.PROJECT_ID)

        # Load the latest checkpoint
        cp_manager = CheckpointManager(self.project)
        checkpoints = cp_manager.list_checkpoints("WF-0001")
        self.assertGreater(len(checkpoints), 0)
        latest = checkpoints[0]
        cp = cp_manager.load(latest["checkpoint_id"])

        # Checkpoint status should be SIMULATED
        self.assertEqual(cp["status"], "SIMULATED")
        # Node result should be SIMULATED
        self.assertEqual(cp["node_results"]["n1"]["status"], "SIMULATED")
        # Completed nodes should NOT include the simulated node
        self.assertNotIn("n1", cp["completed_nodes"])


class SubagentCliTests(_ProjectTestCase):
    def _run(self, *extra):
        return support.run_cli(
            "subagent",
            "--project",
            str(self.project),
            "--agent",
            "analyst",
            "--action",
            "analyze",
            *extra,
        )

    def test_no_llm_config_without_simulate_fails(self):
        with mock.patch.object(AgentRunner, "_load_agent_config", return_value={}):
            code, out = self._run()
        self.assertEqual(code, 1, out)
        self.assertIn("no LLM configuration", out)
        self.assertIn("--simulate", out)
        self.assertNotIn("Status: COMPLETED", out)

    def test_explicit_dummy_config_names_the_configured_cause(self):
        config = {"llm_config": {"provider": "dummy", "model": "dummy"}}
        with mock.patch.object(AgentRunner, "_load_agent_config", return_value=config):
            code, out = self._run()
        self.assertEqual(code, 1, out)
        self.assertIn("configured with the simulated DummyProvider", out)
        self.assertIn("llm_config.provider='dummy'", out)
        self.assertNotIn("has no LLM configuration", out)

    def test_other_simulation_resolution_names_the_dummy_provider(self):
        config = {"llm_config": {"provider": "local", "model": "local-model"}}
        with mock.patch.object(AgentRunner, "_load_agent_config", return_value=config):
            with mock.patch.object(
                AgentRunner, "_create_llm_provider", return_value=DummyProvider()
            ):
                code, out = self._run()
        self.assertEqual(code, 1, out)
        self.assertIn("resolved to the simulated DummyProvider", out)
        self.assertNotIn("has no LLM configuration", out)
        self.assertNotIn("llm_config.provider='dummy'", out)

    def test_explicit_simulation_is_labelled(self):
        code, out = self._run("--simulate")
        self.assertEqual(code, 3, out)
        self.assertIn("Status: SIMULATED", out)
        self.assertIn("DummyProvider", out)
        self.assertNotIn("Status: COMPLETED", out)
        self.assertNotIn('"status": "COMPLETED"', out)

    def test_explicit_simulation_json_is_simulated(self):
        code, out = self._run("--simulate", "--json")
        self.assertEqual(code, 3, out)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "SIMULATED")
        self.assertEqual(payload["output"]["status"], "SIMULATED")
        self.assertNotEqual(payload["output"]["status"], "COMPLETED")
        self.assertIn("echo", payload["output"]["output"])

    def test_help_documents_command_specific_exit_codes(self):
        code, out = support.run_cli("subagent", "--help")
        self.assertEqual(code, 0, out)
        normalized = " ".join(out.split())
        for fragment in (
            "0=COMPLETED",
            "1=failure/refusal/error",
            "2=argparse usage error",
            "3=SIMULATED",
            "not a global CLI convention",
        ):
            self.assertIn(fragment, normalized)

    def test_provider_init_failure_exits_1(self):
        with mock.patch.object(
            AgentRunner,
            "_create_llm_provider",
            side_effect=ImportError("openai package required"),
        ):
            code, out = self._run("--simulate")
        self.assertEqual(code, 1, out)
        self.assertIn("failed to create agent runner", out)
        self.assertNotIn("Status: COMPLETED", out)

    def test_real_provider_completion_exits_0(self):
        stub = StubProvider(
            LLMResponse(
                content='{"status": "COMPLETED", "output": {"ok": true}}',
                finish_reason="stop",
            )
        )
        with mock.patch.object(
            AgentRunner, "_create_llm_provider", return_value=stub
        ):
            code, out = self._run()
        self.assertEqual(code, 0, out)
        self.assertIn("Status: COMPLETED", out)

    def test_real_provider_error_exits_1(self):
        stub = StubProvider(
            LLMResponse(
                content="",
                finish_reason="error",
                raw_response={"error": "provider boom"},
            )
        )
        with mock.patch.object(
            AgentRunner, "_create_llm_provider", return_value=stub
        ):
            code, out = self._run()
        self.assertEqual(code, 1, out)
        self.assertIn("Status: FAILED", out)
        self.assertIn("provider boom", out)


if __name__ == "__main__":
    unittest.main()
