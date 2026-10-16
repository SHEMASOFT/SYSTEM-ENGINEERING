"""Hermetic tests for SE Installer registries."""

from __future__ import annotations

import pytest
from se_installer import (
    ModelRegistry, Model, ModelProvider, ModelCapability,
    MCPRegistry, MCPServer, MCPFunction, MCPCapability, MCPTransport,
    AgentMCPRegistry, AgentMCPBinding, AgentType,
    SkillMCPBridge, MCPToolCall, MCPToolResult,
    RuntimeConfigGenerator, RuntimeConfig,
)


class TestModelRegistry:
    """Tests for ModelRegistry."""

    def test_builtin_models_loaded(self):
        registry = ModelRegistry()
        assert len(registry.models) >= 14

    def test_nemotron_models_present(self):
        registry = ModelRegistry()
        assert "nemotron-3-ultra-free" in registry.models
        assert "nemotron-4-340b-free" in registry.models

    def test_deepseek_models_present(self):
        registry = ModelRegistry()
        assert "deepseek-r1-free" in registry.models
        assert "deepseek-r1-local" in registry.models

    def test_get_model_by_provider(self):
        registry = ModelRegistry()
        free_models = registry.get_models_by_provider(ModelProvider.FREE)
        assert len(free_models) >= 6  # DeepSeek, Llama, Qwen, Gemini, Nemotron 3, Nemotron 4

    def test_get_model_by_capability(self):
        registry = ModelRegistry()
        code_models = registry.get_models_by_capability(ModelCapability.CODE)
        assert len(code_models) >= 10

    def test_free_models(self):
        registry = ModelRegistry()
        free = registry.get_free_models()
        assert all(m.is_free for m in free)
        assert len(free) >= 6

    def test_user_selection(self):
        registry = ModelRegistry()
        assert registry.select_model_for_agent("implementer", "deepseek-r1-free") is True
        assert registry.get_selected_model("implementer").id == "deepseek-r1-free"

    def test_invalid_selection_rejected(self):
        registry = ModelRegistry()
        assert registry.select_model_for_agent("implementer", "non-existent") is False

    def test_fallback_to_free(self):
        registry = ModelRegistry()
        # No selection made, should get a free model
        model = registry.get_selected_model("unknown-agent")
        assert model is not None
        assert model.is_free is True

    def test_recommendations_sorted_by_cost(self):
        registry = ModelRegistry()
        models = registry.get_recommended_for_agent("test", [ModelCapability.CODE, ModelCapability.TOOLS])
        # Free models should come first
        assert models[0].is_free is True
        # Cost should be non-decreasing
        costs = [m.cost_per_1k_input + m.cost_per_1k_output for m in models if not m.is_free]
        assert costs == sorted(costs)


class TestMCPRegistry:
    """Tests for MCPRegistry."""

    def test_builtin_mcps_loaded(self):
        registry = MCPRegistry()
        assert len(registry.mcps) == 5

    def test_mcp_ids(self):
        registry = MCPRegistry()
        ids = set(registry.mcps.keys())
        assert ids == {"context7", "filesystem", "playwright", "firecrawl", "codegraph"}

    def test_mcp_capabilities(self):
        registry = MCPRegistry()
        ctx7 = registry.get_mcp("context7")
        assert MCPCapability.DOC_LOOKUP in ctx7.capabilities
        assert MCPCapability.WEB_SEARCH in ctx7.capabilities

        fs = registry.get_mcp("filesystem")
        assert MCPCapability.FILE_READ in fs.capabilities
        assert MCPCapability.FILE_WRITE in fs.capabilities

    def test_mcp_functions_openai_format(self):
        registry = MCPRegistry()
        ctx7 = registry.get_mcp("context7")
        func = ctx7.get_function("query-docs")
        assert func is not None
        openai_func = func.to_openai_function()
        assert openai_func["name"] == "query-docs"
        assert "parameters" in openai_func
        assert "libraryId" in openai_func["parameters"]["properties"]

    def test_get_mcps_by_capability(self):
        registry = MCPRegistry()
        file_mcps = registry.get_mcps_by_capability(MCPCapability.FILE_READ)
        assert len(file_mcps) == 1
        assert file_mcps[0].id == "filesystem"

    def test_opencode_config_generation(self):
        registry = MCPRegistry()
        ctx7 = registry.get_mcp("context7")
        config = ctx7.to_opencode_config("/project/root")
        assert "mcp" in config
        assert "servers" in config["mcp"]
        assert "Context7" in config["mcp"]["servers"]
        server = config["mcp"]["servers"]["Context7"]
        assert server["command"] == "npx"
        assert "-y" in server["args"]
        assert "@upstash/context7-mcp" in server["args"]

    def test_env_vars_collected(self):
        registry = MCPRegistry()
        ctx7 = registry.get_mcp("context7")
        env_vars = ctx7.get_required_env_vars()
        assert "CONTEXT7_API_KEY" in env_vars


class TestAgentMCPBinding:
    """Tests for AgentMCPBinding."""

    def test_all_agent_types_bound(self):
        mcp_reg = MCPRegistry()
        model_reg = ModelRegistry()
        binding = AgentMCPRegistry(mcp_reg, model_reg)
        assert len(binding.bindings) == 12

    def test_implementer_binding(self):
        mcp_reg = MCPRegistry()
        model_reg = ModelRegistry()
        binding = AgentMCPRegistry(mcp_reg, model_reg)
        impl_binding = binding.get_binding("implementer")
        assert impl_binding is not None
        assert "filesystem" in impl_binding.required_mcp_ids
        assert "engram" not in impl_binding.required_mcp_ids
        assert impl_binding.preferred_model_id == "claude-3.5-sonnet"

    def test_analyst_binding(self):
        mcp_reg = MCPRegistry()
        model_reg = ModelRegistry()
        binding = AgentMCPRegistry(mcp_reg, model_reg)
        analyst = binding.get_binding("analyst")
        assert "context7" in analyst.required_mcp_ids
        assert "filesystem" in analyst.required_mcp_ids
        assert "engram" not in analyst.required_mcp_ids
        assert analyst.preferred_model_id == "deepseek-r1-free"

    def test_get_available_mcps(self):
        mcp_reg = MCPRegistry()
        model_reg = ModelRegistry()
        binding = AgentMCPRegistry(mcp_reg, model_reg)
        mcps = binding.get_available_mcps("implementer")
        ids = {m.id for m in mcps}
        assert "filesystem" in ids
        assert "engram" not in ids
        assert "codegraph" in ids

    def test_get_required_mcps(self):
        mcp_reg = MCPRegistry()
        model_reg = ModelRegistry()
        binding = AgentMCPRegistry(mcp_reg, model_reg)
        mcps = binding.get_required_mcps("implementer")
        ids = {m.id for m in mcps}
        assert ids == {"filesystem"}

    def test_generate_agent_config(self):
        mcp_reg = MCPRegistry()
        model_reg = ModelRegistry()
        binding = AgentMCPRegistry(mcp_reg, model_reg)
        config = binding.generate_agent_config("implementer", "/project")
        assert "model" in config
        assert "mcp_servers" in config
        assert "functions" in config
        assert len(config["functions"]) > 0


class TestSkillMCPBridge:
    """Tests for SkillMCPBridge."""

    def test_skill_registration(self):
        mcp_reg = MCPRegistry()
        model_reg = ModelRegistry()
        bridge = SkillMCPBridge(mcp_reg, model_reg)

        bridge.register_skill_requirements("my_skill", [MCPCapability.FILE_READ, MCPCapability.WEB_SEARCH])

        bound = bridge._skill_mcp_bindings.get("my_skill", [])
        assert "filesystem" in bound
        assert "context7" in bound

    def test_get_functions_for_skill(self):
        mcp_reg = MCPRegistry()
        model_reg = ModelRegistry()
        bridge = SkillMCPBridge(mcp_reg, model_reg)

        bridge.register_skill_requirements("research_skill", [MCPCapability.DOC_LOOKUP])
        functions = bridge.get_all_functions_for_skill("research_skill")

        assert len(functions) >= 2  # resolve-library-id + query-docs
        names = {f["name"] for f in functions}
        assert "resolve-library-id" in names
        assert "query-docs" in names

    def test_decorator(self):
        from se_installer.skill_mcp_bridge import requires_mcp_capabilities

        @requires_mcp_capabilities(MCPCapability.FILE_READ, MCPCapability.FILE_WRITE)
        class TestSkill:
            pass

        assert hasattr(TestSkill, "_mcp_required_capabilities")
        caps = TestSkill._mcp_required_capabilities
        assert MCPCapability.FILE_READ in caps
        assert MCPCapability.FILE_WRITE in caps


class TestRuntimeConfigGenerator:
    """Tests for RuntimeConfigGenerator."""

    def test_opencode_config_generation(self):
        mcp_reg = MCPRegistry()
        model_reg = ModelRegistry()
        agent_reg = AgentMCPRegistry(mcp_reg, model_reg)
        generator = RuntimeConfigGenerator(mcp_reg, model_reg, agent_reg)

        config = generator.generate_opencode_config("implementer")

        assert config.runtime_id == "opencode"
        assert config.model is not None
        assert "provider" in config.model
        assert len(config.mcp_servers) >= 2  # filesystem + codegraph at minimum

    def test_codex_config_generation(self):
        mcp_reg = MCPRegistry()
        model_reg = ModelRegistry()
        agent_reg = AgentMCPRegistry(mcp_reg, model_reg)
        generator = RuntimeConfigGenerator(mcp_reg, model_reg, agent_reg)

        config = generator.generate_codex_config("implementer")
        assert config.runtime_id == "codex"

    def test_claude_code_config_generation(self):
        mcp_reg = MCPRegistry()
        model_reg = ModelRegistry()
        agent_reg = AgentMCPRegistry(mcp_reg, model_reg)
        generator = RuntimeConfigGenerator(mcp_reg, model_reg, agent_reg)

        config = generator.generate_claude_code_config("implementer")
        assert config.runtime_id == "claude_code"

    def test_all_runtime_configs(self):
        mcp_reg = MCPRegistry()
        model_reg = ModelRegistry()
        agent_reg = AgentMCPRegistry(mcp_reg, model_reg)
        generator = RuntimeConfigGenerator(mcp_reg, model_reg, agent_reg)

        configs = generator.generate_all_runtime_configs("implementer")
        assert "opencode" in configs
        assert "codex" in configs
        assert "claude_code" in configs

    def test_model_selection_menu(self):
        mcp_reg = MCPRegistry()
        model_reg = ModelRegistry()
        agent_reg = AgentMCPRegistry(mcp_reg, model_reg)
        generator = RuntimeConfigGenerator(mcp_reg, model_reg, agent_reg)

        menu = generator.get_model_selection_menu("implementer")
        assert len(menu) >= 5
        for item in menu:
            assert "id" in item
            assert "name" in item
            assert "provider" in item
            assert "is_free" in item
            assert "cost" in item

    def test_mcp_selection_menu(self):
        mcp_reg = MCPRegistry()
        model_reg = ModelRegistry()
        agent_reg = AgentMCPRegistry(mcp_reg, model_reg)
        generator = RuntimeConfigGenerator(mcp_reg, model_reg, agent_reg)

        menu = generator.get_mcp_selection_menu("opencode")
        assert len(menu) == 5
        for item in menu:
            assert "id" in item
            assert "name" in item
            assert "category" in item
            assert "selected" in item