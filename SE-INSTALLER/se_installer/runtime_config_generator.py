"""Runtime Config Generator - Genera configuraciones de runtime con modelos + MCPs seleccionados."""

from __future__ import annotations

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Any
from pathlib import Path
import json

from .mcp_registry import MCPRegistry, MCPServer
from .model_registry import ModelRegistry, Model
from .agent_mcp_binding import AgentMCPRegistry, AgentType, get_agent_mcp_registry


@dataclass
class RuntimeConfig:
    """Configuración completa para un runtime."""
    runtime_id: str
    runtime_name: str
    # Modelo seleccionado
    model: Optional[dict] = None
    # MCPs configurados
    mcp_servers: dict = field(default_factory=dict)
    # Variables de entorno requeridas
    env_vars: dict[str, str] = field(default_factory=dict)
    # Variables de entorno requeridas pero no configuradas
    missing_env_vars: list[str] = field(default_factory=list)
    # Configuración adicional
    extra_config: dict = field(default_factory=dict)


class RuntimeConfigGenerator:
    """
    Genera configuraciones de runtime (OpenCode, Codex, Claude Code, etc.)
    con los modelos y MCPs seleccionados por el usuario.
    """
    
    SUPPORTED_RUNTIMES = {
        "opencode": "OpenCode",
        "codex": "Codex CLI",
        "claude_code": "Claude Code",
    }
    
    def __init__(
        self,
        mcp_registry: MCPRegistry,
        model_registry: ModelRegistry,
        agent_mcp_registry: Optional[AgentMCPRegistry] = None,
        project_root: str = ""
    ):
        self.mcp_registry = mcp_registry
        self.model_registry = model_registry
        self.agent_mcp_registry = agent_mcp_registry or get_agent_mcp_registry(mcp_registry, model_registry)
        self.project_root = project_root
        self._user_model_selections: dict[str, str] = {}  # agent_id -> model_id
        self._user_mcp_selections: dict[str, list[str]] = {}  # runtime -> mcp_ids
    
    def set_model_for_agent(self, agent_id: str, model_id: str) -> bool:
        """Usuario selecciona modelo para un agente."""
        return self.model_registry.select_model_for_agent(agent_id, model_id)
    
    def set_mcps_for_runtime(self, runtime: str, mcp_ids: list[str]) -> None:
        """Usuario selecciona MCPs para un runtime."""
        self._user_mcp_selections[runtime] = mcp_ids
    
    def get_available_models_for_agent(self, agent_id: str) -> list[Model]:
        """Obtiene modelos recomendados para un agente."""
        binding = self.agent_mcp_registry.get_binding(agent_id)
        if not binding:
            return self.model_registry.get_free_models()
        
        required_caps = []
        # Mapear capabilities del agente a ModelCapability
        cap_mapping = {
            "coding": ["code"],
            "reasoning": ["reasoning"],
            "analysis": ["reasoning", "chat"],
            "vision": ["vision"],
            "long_context": ["long_context"],
        }
        for cap in binding.required_capabilities:
            required_caps.extend(cap_mapping.get(cap, ["chat", "code", "tools"]))
        
        # Deduplicar y convertir a ModelCapability
        from .model_registry import ModelCapability
        model_caps = list(set(
            ModelCapability(c) for c in required_caps if c in [e.value for e in ModelCapability]
        ))
        
        return self.model_registry.get_recommended_for_agent(agent_id, model_caps)
    
    def get_available_mcps_for_runtime(self, runtime: str) -> list[MCPServer]:
        """Obtiene MCPs compatibles con un runtime."""
        # Para OpenCode, todos los MCPs stdio son compatibles
        # Filtrar por los que el usuario seleccionó o todos si no hay selección
        if runtime in self._user_mcp_selections:
            return [self.mcp_registry.get_mcp(mid) for mid in self._user_mcp_selections[runtime] if self.mcp_registry.get_mcp(mid)]
        return self.mcp_registry.get_enabled_mcps()
    
    def generate_opencode_config(
        self, 
        agent_id: str = "default",
        include_all_mcps: bool = False
    ) -> RuntimeConfig:
        """Genera configuración para OpenCode."""
        binding = self.agent_mcp_registry.get_binding(agent_id)
        if not binding:
            # Crear binding por defecto
            binding = self.agent_mcp_registry.bindings.get("implementer")
        
        # Modelo
        model = self.model_registry.get_selected_model(agent_id)
        
        # MCPs
        if include_all_mcps:
            mcps = self.mcp_registry.get_enabled_mcps()
        else:
            mcps = self.agent_mcp_registry.get_available_mcps(agent_id)
        
        mcp_configs = {}
        env_vars = {}
        missing_env = []
        
        for mcp in mcps:
            config = mcp.to_opencode_config(self.project_root)
            if "mcp" in config and "servers" in config["mcp"]:
                mcp_configs.update(config["mcp"]["servers"])
            
            # Recopilar env vars requeridas
            for env_var in mcp.get_required_env_vars():
                if env_var.startswith("${") and env_var.endswith("}"):
                    var_name = env_var[2:-1]
                    missing_env.append(var_name)
                elif "=" in env_var:
                    key, val = env_var.split("=", 1)
                    env_vars[key] = val
        
        return RuntimeConfig(
            runtime_id="opencode",
            runtime_name="OpenCode",
            model=model.to_opencode_config() if model else {},
            mcp_servers=mcp_configs,
            env_vars=env_vars,
            missing_env_vars=missing_env,
            extra_config={
                "version": "2",
                "theme": "default",
            }
        )
    
    def generate_codex_config(self, agent_id: str = "default") -> RuntimeConfig:
        """Genera configuración para Codex CLI."""
        # Codex usa config similar a OpenCode pero con diferencias
        model = self.model_registry.get_selected_model(agent_id)
        mcps = self.agent_mcp_registry.get_available_mcps(agent_id)
        
        mcp_configs = {}
        for mcp in mcps:
            if mcp.transport.value == "stdio":
                mcp_configs[mcp.name] = {
                    "command": mcp.command,
                    "args": mcp.args,
                    "env": mcp.env,
                }
        
        return RuntimeConfig(
            runtime_id="codex",
            runtime_name="Codex CLI",
            model=model.to_opencode_config() if model else {},
            mcp_servers=mcp_configs,
            extra_config={
                "model_provider": model.provider.value if model else "openai",
            }
        )
    
    def generate_claude_code_config(self, agent_id: str = "default") -> RuntimeConfig:
        """Genera configuración para Claude Code."""
        model = self.model_registry.get_selected_model(agent_id)
        mcps = self.agent_mcp_registry.get_available_mcps(agent_id)
        
        mcp_configs = {}
        for mcp in mcps:
            if mcp.transport.value == "stdio":
                mcp_configs[mcp.name] = {
                    "command": mcp.command,
                    "args": mcp.args,
                    "env": mcp.env,
                }
        
        return RuntimeConfig(
            runtime_id="claude_code",
            runtime_name="Claude Code",
            model=model.to_opencode_config() if model else {},
            mcp_servers=mcp_configs,
        )
    
    def generate_all_runtime_configs(self, agent_id: str = "default") -> dict[str, RuntimeConfig]:
        """Genera configs para todos los runtimes soportados."""
        return {
            "opencode": self.generate_opencode_config(agent_id),
            "codex": self.generate_codex_config(agent_id),
            "claude_code": self.generate_claude_code_config(agent_id),
        }
    
    def write_opencode_config(self, config: RuntimeConfig, output_path: Path) -> None:
        """Escribe configuración OpenCode a archivo."""
        opencode_config = {
            "version": "2",
            "theme": config.extra_config.get("theme", "default"),
        }
        
        if config.model:
            opencode_config["model"] = config.model
        
        if config.mcp_servers:
            opencode_config["mcp"] = {"servers": config.mcp_servers}
        
        if config.env_vars:
            opencode_config["environment"] = config.env_vars
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(opencode_config, indent=2, ensure_ascii=False), encoding="utf-8")
    
    def write_codex_config(self, config: RuntimeConfig, output_path: Path) -> None:
        """Escribe configuración Codex a archivo."""
        codex_config = {
            "model": config.model.get("model") if config.model else "gpt-4o",
            "mcp_servers": config.mcp_servers,
        }
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(codex_config, indent=2, ensure_ascii=False), encoding="utf-8")
    
    def write_claude_code_config(self, config: RuntimeConfig, output_path: Path) -> None:
        """Escribe configuración Claude Code a archivo."""
        claude_config = {
            "mcp_servers": config.mcp_servers,
        }
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(claude_config, indent=2, ensure_ascii=False), encoding="utf-8")
    
    def get_model_selection_menu(self, agent_id: str) -> list[dict]:
        """Obtiene menú de selección de modelos para UI."""
        models = self.get_available_models_for_agent(agent_id)
        return [
            {
                "id": m.id,
                "name": m.name,
                "provider": m.provider.value,
                "is_free": m.is_free,
                "description": m.description,
                "capabilities": [c.value for c in m.capabilities],
                "cost": f"${m.cost_per_1k_input:.4f}/${m.cost_per_1k_output:.4f} per 1k" if not m.is_free else "GRATIS",
                "context_window": m.context_window,
                "tags": m.tags,
            }
            for m in models
        ]
    
    def get_mcp_selection_menu(self, runtime: str) -> list[dict]:
        """Obtiene menú de selección de MCPs para UI."""
        mcps = self.mcp_registry.get_enabled_mcps()
        selected = set(self._user_mcp_selections.get(runtime, []))
        
        return [
            {
                "id": mcp.id,
                "name": mcp.name,
                "description": mcp.description,
                "category": mcp.category,
                "capabilities": [c.value for c in mcp.capabilities],
                "requires_env": mcp.get_required_env_vars(),
                "install_method": mcp.install_method,
                "selected": mcp.id in selected,
                "tags": mcp.tags,
            }
            for mcp in mcps
        ]


# Instancia global
RUNTIME_CONFIG_GENERATOR = None


def get_runtime_config_generator(
    mcp_registry: Optional[MCPRegistry] = None,
    model_registry: Optional[ModelRegistry] = None,
    agent_mcp_registry: Optional[AgentMCPRegistry] = None,
    project_root: str = ""
) -> RuntimeConfigGenerator:
    global RUNTIME_CONFIG_GENERATOR
    if RUNTIME_CONFIG_GENERATOR is None:
        from .mcp_registry import get_mcp_registry
        from .model_registry import get_model_registry
        RUNTIME_CONFIG_GENERATOR = RuntimeConfigGenerator(
            mcp_registry or get_mcp_registry(),
            model_registry or get_model_registry(),
            agent_mcp_registry,
            project_root
        )
    return RUNTIME_CONFIG_GENERATOR