"""Model precedence for the internal ``AgentRunner`` route.

The harness selection (the ``opencode.jsonc`` that ``se shema-ai model``
writes) must reach ``se subagent``/orchestration. The documented chain is:

    override > agent.json llm_config > SE_LLM_* env >
    harness selection > SCRIPTS/se_core/llm/se-llm-config.json > dummy

Every case here is hermetic: temporary directories, locally registered stub
providers and the deterministic DummyProvider. No network, no credentials and
no optional LLM dependency is touched.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402,F401

from se_core.agents.runner import AgentRunner  # noqa: E402
from se_core.llm import factory  # noqa: E402
from se_core.llm.factory import register_provider  # noqa: E402
from se_core.llm.providers import DummyProvider, LLMProvider, LLMResponse  # noqa: E402


SE_LLM_VARS = (
    "SE_LLM_PROVIDER",
    "SE_LLM_MODEL",
    "SE_LLM_TEMPERATURE",
    "SE_LLM_MAX_TOKENS",
    "SE_LLM_API_KEY_ENV",
    "SE_LLM_BASE_URL",
)

HARNESS_PROVIDER = "se_test_harness_stub"
OTHER_PROVIDER = "se_test_other_stub"
ENV_PROVIDER = "se_test_env_stub"


class _StubProvider(LLMProvider):
    """Offline provider that satisfies the ABC."""

    def __init__(self, model: str = "stub-model", **kwargs):
        super().__init__(model=model, **kwargs)

    def chat(self, messages, tools=None, temperature=0.3, max_tokens=4096, **kwargs):
        return LLMResponse(
            content='{"status": "COMPLETED", "output": {"stub": true}}',
            finish_reason="stop",
        )

    def stream_chat(self, messages, tools=None, temperature=0.3, max_tokens=4096, **kwargs):
        yield self.chat(
            messages, tools=tools, temperature=temperature, max_tokens=max_tokens
        )


class _OtherStubProvider(_StubProvider):
    """A second, distinguishable offline provider."""


def write_jsonc(path: Path, model: str | None, agents: dict | None = None) -> None:
    """Write an opencode.jsonc containing a model selection and optional overrides."""
    data: dict = {}
    if model is not None:
        data["model"] = model
    if agents:
        data["agents"] = agents
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


class RunnerModelPrecedenceTests(unittest.TestCase):
    """One runner, one temp root, one controlled configuration per assertion."""

    @classmethod
    def setUpClass(cls):
        cls._registry_snapshot = dict(factory._get_provider_classes())
        register_provider(HARNESS_PROVIDER, _StubProvider)
        register_provider(OTHER_PROVIDER, _OtherStubProvider)
        register_provider(ENV_PROVIDER, _OtherStubProvider)

    @classmethod
    def tearDownClass(cls):
        registry = factory._get_provider_classes()
        registry.clear()
        registry.update(cls._registry_snapshot)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "root"
        self.project = self.root / "proj"
        self.project.mkdir(parents=True)
        (self.root / "AGENTS" / "analyst").mkdir(parents=True)

        # These tests control the environment explicitly.
        env_guard = mock.patch.dict(os.environ, {}, clear=False)
        env_guard.start()
        self.addCleanup(env_guard.stop)
        for name in SE_LLM_VARS:
            os.environ.pop(name, None)

    def _runner(self, agent_config: dict | None = None) -> AgentRunner:
        with mock.patch.object(
            AgentRunner, "_load_agent_config", return_value=agent_config or {}
        ):
            return AgentRunner(
                agent_name="analyst",
                project_dir=self.project,
                root=self.root,
            )

    def _repo_llm_config(self, provider: str, model: str) -> None:
        path = self.root / "SCRIPTS" / "se_core" / "llm" / "se-llm-config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"provider": provider, "model": model}), encoding="utf-8"
        )

    # 1. The selection alone must be enough to leave simulation behind.
    def test_harness_selection_reaches_the_runner(self):
        write_jsonc(self.root / "opencode.jsonc", f"{HARNESS_PROVIDER}/harness-model")

        runner = self._runner()

        self.assertIs(runner.llm_provider.__class__, _StubProvider)
        self.assertEqual(runner.llm_provider.model, "harness-model")
        self.assertFalse(runner.simulated)

    def test_harness_per_agent_override_wins_over_the_global(self):
        write_jsonc(
            self.root / "opencode.jsonc",
            "dummy/dummy",
            {"analyst": {"model": {"providerID": HARNESS_PROVIDER, "model": "per-agent"}}},
        )

        runner = self._runner()

        self.assertIs(runner.llm_provider.__class__, _StubProvider)
        self.assertEqual(runner.llm_provider.model, "per-agent")

    # 2. The new source sits below env and above the repo JSON file.
    def test_environment_wins_over_the_harness_selection(self):
        write_jsonc(self.root / "opencode.jsonc", f"{HARNESS_PROVIDER}/harness-model")
        with mock.patch.dict(
            os.environ,
            {"SE_LLM_PROVIDER": ENV_PROVIDER, "SE_LLM_MODEL": "env-model"},
            clear=False,
        ):
            runner = self._runner()

        self.assertIs(runner.llm_provider.__class__, _OtherStubProvider)
        self.assertEqual(runner.llm_provider.model, "env-model")

    def test_harness_selection_wins_over_the_repo_json_file(self):
        write_jsonc(self.root / "opencode.jsonc", f"{HARNESS_PROVIDER}/harness-model")
        self._repo_llm_config("dummy", "dummy")

        runner = self._runner()

        self.assertIs(runner.llm_provider.__class__, _StubProvider)
        self.assertEqual(runner.llm_provider.model, "harness-model")

    def test_agent_contract_wins_over_the_harness_selection(self):
        write_jsonc(self.root / "opencode.jsonc", f"{HARNESS_PROVIDER}/harness-model")
        agent_config = {
            "llm_config": {"provider": OTHER_PROVIDER, "model": "contract-model"}
        }

        runner = self._runner(agent_config=agent_config)

        self.assertIs(runner.llm_provider.__class__, _OtherStubProvider)
        self.assertEqual(runner.llm_provider.model, "contract-model")

    def test_override_wins_over_the_harness_selection(self):
        write_jsonc(self.root / "opencode.jsonc", f"{HARNESS_PROVIDER}/harness-model")
        with mock.patch.object(
            AgentRunner, "_load_agent_config", return_value={}
        ):
            runner = AgentRunner(
                agent_name="analyst",
                project_dir=self.project,
                root=self.root,
                override_llm_config={"provider": "dummy", "model": "dummy"},
            )

        self.assertIs(runner.llm_provider.__class__, DummyProvider)
        self.assertTrue(runner.simulated)

    # 3. No invented model: unset keeps falling through to the dummy provider.
    def test_unset_harness_falls_through_to_the_repo_json_then_dummy(self):
        self._repo_llm_config("dummy", "dummy")

        runner = self._runner()

        self.assertIs(runner.llm_provider.__class__, DummyProvider)
        self.assertTrue(runner.simulated)

    def test_nothing_configured_stays_simulated(self):
        runner = self._runner()

        self.assertIs(runner.llm_provider.__class__, DummyProvider)
        self.assertTrue(runner.simulated)

    def test_an_explicit_dummy_selection_is_simulated(self):
        write_jsonc(self.root / "opencode.jsonc", "dummy/dummy")

        runner = self._runner()

        self.assertIs(runner.llm_provider.__class__, DummyProvider)
        self.assertTrue(runner.simulated)

    # 4. Fail-soft: a broken harness file cannot crash a run.
    def test_malformed_harness_file_is_fail_soft(self):
        (self.root / "opencode.jsonc").write_text(
            '{\n  "model": "' + HARNESS_PROVIDER + '/harness-model",\n', encoding="utf-8"
        )

        runner = self._runner()

        self.assertIs(runner.llm_provider.__class__, DummyProvider)
        self.assertTrue(runner.simulated)

    def test_model_without_a_provider_is_ignored(self):
        write_jsonc(self.root / "opencode.jsonc", "bare-alias")

        runner = self._runner()

        self.assertIs(runner.llm_provider.__class__, DummyProvider)
        self.assertTrue(runner.simulated)


if __name__ == "__main__":
    unittest.main()
