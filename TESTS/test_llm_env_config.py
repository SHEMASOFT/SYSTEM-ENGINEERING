"""Environment-driven default LLM configuration.

This pins the fix for the "always SIMULATED" gap: a real provider must be
reachable without declaring ``llm_config`` in every ``AGENTS/*/agent.json``.
``llm_config_from_env`` reads the process-level default and ``AgentRunner``
applies a documented precedence:

    override_llm_config > agent_config["llm_config"] > env > DummyProvider

The test suite is hermetic: it registers local stub providers, patches
``os.environ`` for the duration of each test only, and never touches the
network or optional LLM dependencies.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.agents.runner import AgentRunner  # noqa: E402
from se_core.llm import factory  # noqa: E402
from se_core.llm.factory import llm_config_from_env, register_provider  # noqa: E402
from se_core.llm.providers import DummyProvider, LLMProvider, LLMResponse  # noqa: E402


SE_LLM_VARS = (
    "SE_LLM_PROVIDER",
    "SE_LLM_MODEL",
    "SE_LLM_TEMPERATURE",
    "SE_LLM_MAX_TOKENS",
    "SE_LLM_API_KEY_ENV",
    "SE_LLM_BASE_URL",
)

BUILTIN_PROVIDERS = ("openai", "anthropic", "local", "ollama", "vllm", "dummy")


class _StubProvider(LLMProvider):
    """Minimal provider that satisfies the ABC without any network access."""

    def __init__(self, model: str = "stub-model", **kwargs):
        super().__init__(model=model, **kwargs)

    def chat(self, messages, tools=None, temperature=0.3, max_tokens=4096, **kwargs):
        return LLMResponse(
            content='{"status": "COMPLETED", "output": {"stub": true}}',
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            finish_reason="stop",
        )

    def stream_chat(self, messages, tools=None, temperature=0.3, max_tokens=4096, **kwargs):
        yield self.chat(
            messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )


class _OtherStubProvider(_StubProvider):
    """A second, distinguishable stub used to prove the agent config wins."""


class LlmConfigFromEnvTests(unittest.TestCase):
    """Pure function contract for ``llm_config_from_env``."""

    def test_empty_env_returns_none(self):
        self.assertIsNone(llm_config_from_env({}))

    def test_provider_without_model_raises_naming_the_missing_variable(self):
        with self.assertRaises(ValueError) as ctx:
            llm_config_from_env({"SE_LLM_PROVIDER": "openai"})
        self.assertIn("SE_LLM_MODEL", str(ctx.exception))

    def test_model_without_provider_raises_naming_the_missing_variable(self):
        with self.assertRaises(ValueError) as ctx:
            llm_config_from_env({"SE_LLM_MODEL": "m"})
        self.assertIn("SE_LLM_PROVIDER", str(ctx.exception))

    def test_full_env_maps_to_provider_config(self):
        config = llm_config_from_env(
            {
                "SE_LLM_PROVIDER": "openai",
                "SE_LLM_MODEL": "gpt-4o-mini",
                "SE_LLM_TEMPERATURE": "0.2",
                "SE_LLM_MAX_TOKENS": "1024",
                "SE_LLM_API_KEY_ENV": "MY_KEY_ENV",
                "SE_LLM_BASE_URL": "https://example.invalid/v1",
            }
        )
        self.assertEqual(
            config,
            {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "temperature": 0.2,
                "max_tokens": 1024,
                "provider_options": {
                    "api_key_env": "MY_KEY_ENV",
                    "base_url": "https://example.invalid/v1",
                },
            },
        )

    def test_minimal_env_omits_unset_optionals(self):
        self.assertEqual(
            llm_config_from_env(
                {"SE_LLM_PROVIDER": "openai", "SE_LLM_MODEL": "gpt-4o-mini"}
            ),
            {"provider": "openai", "model": "gpt-4o-mini"},
        )

    def test_invalid_temperature_names_variable_and_value(self):
        with self.assertRaises(ValueError) as ctx:
            llm_config_from_env(
                {
                    "SE_LLM_PROVIDER": "openai",
                    "SE_LLM_MODEL": "m",
                    "SE_LLM_TEMPERATURE": "hot",
                }
            )
        message = str(ctx.exception)
        self.assertIn("SE_LLM_TEMPERATURE", message)
        self.assertIn("hot", message)

    def test_invalid_max_tokens_names_variable_and_value(self):
        with self.assertRaises(ValueError) as ctx:
            llm_config_from_env(
                {
                    "SE_LLM_PROVIDER": "openai",
                    "SE_LLM_MODEL": "m",
                    "SE_LLM_MAX_TOKENS": "lots",
                }
            )
        message = str(ctx.exception)
        self.assertIn("SE_LLM_MAX_TOKENS", message)
        self.assertIn("lots", message)


class AgentRunnerEnvPrecedenceTests(unittest.TestCase):
    """AgentRunner precedence: override > agent config > env > dummy.

    The stub providers are registered under unique names, inside this class,
    and the registry is restored in ``tearDownClass`` so nothing leaks into
    other test modules.
    """

    ENV_PROVIDER = "se_test_env_stub"
    CONFIG_PROVIDER = "se_test_config_stub"

    @classmethod
    def setUpClass(cls):
        cls._registry_snapshot = dict(factory._get_provider_classes())
        register_provider(cls.ENV_PROVIDER, _StubProvider)
        register_provider(cls.CONFIG_PROVIDER, _OtherStubProvider)

    @classmethod
    def tearDownClass(cls):
        registry = factory._get_provider_classes()
        registry.clear()
        registry.update(cls._registry_snapshot)

    def setUp(self):
        # Guard against pre-existing SE_LLM_* variables in the outer process:
        # snapshot the environment, remove the variables for this test, and
        # restore the whole mapping on cleanup.
        self._env_guard = mock.patch.dict(os.environ, {}, clear=False)
        self._env_guard.start()
        self.addCleanup(self._env_guard.stop)
        for name in SE_LLM_VARS:
            os.environ.pop(name, None)

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = Path(self._tmp.name)

    def _make_runner(self, agent_config=None, override=None):
        with mock.patch.object(
            AgentRunner, "_load_agent_config", return_value=agent_config or {}
        ):
            return AgentRunner(
                agent_name="analyst",
                project_dir=self.project,
                override_llm_config=override,
            )

    def _env(self, provider, model):
        return {"SE_LLM_PROVIDER": provider, "SE_LLM_MODEL": model}

    def test_env_only_uses_the_env_provider(self):
        with mock.patch.dict(
            os.environ, self._env(self.ENV_PROVIDER, "env-model"), clear=False
        ):
            runner = self._make_runner()
        self.assertIs(runner.llm_provider.__class__, _StubProvider)
        self.assertEqual(runner.llm_provider.model, "env-model")
        self.assertFalse(runner.simulated)
        # patch.dict restores the environment even on success.
        self.assertNotIn("SE_LLM_PROVIDER", os.environ)

    def test_agent_config_wins_over_env(self):
        agent_config = {
            "llm_config": {"provider": self.CONFIG_PROVIDER, "model": "config-model"}
        }
        with mock.patch.dict(
            os.environ, self._env(self.ENV_PROVIDER, "env-model"), clear=False
        ):
            runner = self._make_runner(agent_config=agent_config)
        self.assertIs(runner.llm_provider.__class__, _OtherStubProvider)
        self.assertEqual(runner.llm_provider.model, "config-model")
        self.assertFalse(runner.simulated)

    def test_override_wins_over_agent_config_and_env(self):
        agent_config = {
            "llm_config": {"provider": self.CONFIG_PROVIDER, "model": "config-model"}
        }
        with mock.patch.dict(
            os.environ, self._env(self.ENV_PROVIDER, "env-model"), clear=False
        ):
            runner = self._make_runner(
                agent_config=agent_config,
                override={"provider": "dummy", "model": "dummy"},
            )
        self.assertIs(runner.llm_provider.__class__, DummyProvider)
        self.assertTrue(runner.simulated)

    def test_no_env_no_config_falls_back_to_simulated(self):
        runner = self._make_runner()
        self.assertIs(runner.llm_provider.__class__, DummyProvider)
        self.assertTrue(runner.simulated)

    def test_stub_registration_is_scoped_to_this_class(self):
        registry = factory._get_provider_classes()
        self.assertIs(registry[self.ENV_PROVIDER], _StubProvider)
        self.assertIs(registry[self.CONFIG_PROVIDER], _OtherStubProvider)
        # The unique names cannot shadow a built-in provider.
        self.assertNotIn(self.ENV_PROVIDER, BUILTIN_PROVIDERS)
        self.assertNotIn(self.CONFIG_PROVIDER, BUILTIN_PROVIDERS)
        for builtin in BUILTIN_PROVIDERS:
            self.assertIsNot(registry[builtin], _StubProvider)
            self.assertIsNot(registry[builtin], _OtherStubProvider)


class RegistryRestorationTests(unittest.TestCase):
    """Registering a stub must be visible only while it is registered."""

    PROVIDER = "se_test_leak_probe"

    def test_registered_stub_does_not_leak_out_of_its_scope(self):
        snapshot = dict(factory._get_provider_classes())
        try:
            register_provider(self.PROVIDER, _StubProvider)
            self.assertIn(self.PROVIDER, factory._get_provider_classes())
        finally:
            registry = factory._get_provider_classes()
            registry.clear()
            registry.update(snapshot)
        self.assertNotIn(self.PROVIDER, factory._get_provider_classes())


def tearDownModule():
    """Fail if the class-scoped stub providers survived into the next module."""
    registry = factory._get_provider_classes()
    leaked = [
        name
        for name in (
            AgentRunnerEnvPrecedenceTests.ENV_PROVIDER,
            AgentRunnerEnvPrecedenceTests.CONFIG_PROVIDER,
        )
        if name in registry
    ]
    if leaked:
        raise AssertionError(
            f"stub providers leaked into the global registry: {leaked}"
        )


if __name__ == "__main__":
    unittest.main()
