"""Agent-MCP Binding - Conecta agentes con MCPs y skills."""

from __future__ import annotations

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable
from pathlib import Path
import json
from typing import Any, Callable

from .models import InstallableComponent, ComponentType
from .mcp_registry import MCPRegistry, MCPCapability, MCPServer, MCPFunction
from .model_registry import ModelRegistry, Model, ModelCapability


class AgentType(str, Enum):
    ANALYST = "analyst"
    ARCHITECT = "architect"
    IMPLEMENTER = "implementer"
    TESTER = "tester"
    REVIEWER = "reviewer"
    PLANNER = "planner"
    COORDINATOR = "coordinator"
    EXPLORER = "explorer"
    SECURITY = "security"
    DOCUMENTATION = "documentation"
    DEVOPS = "devops"
    VISUAL = "visual"


@dataclass
class AgentMCPBinding:
    """Binding entre un agente y los MCPs que puede usar."""
    agent_id: str
    agent_type: AgentType
    # MCPs permitidos para este agente
    allowed_mcp_ids: list[str] = field(default_factory=list)
    # MCPs requeridos (siempre disponibles)
    required_mcp_ids: list[str] = field(default_factory=list)
    # MCPs prohibidos
    forbidden_mcp_ids: list[str] = field(default_factory=list)
    # Capacidades requeridas del agente
    required_capabilities: list[str] = field(default_factory=list)
    # Configuración de modelo para este agente
    preferred_model_id: str = ""
    fallback_model_ids: list[str] = field(default_factory=list)
    # Configuración de comportamiento
    auto_approve_mcp_calls: bool = False
    max_mcp_calls_per_task: int = 10
    timeout_seconds: int = 300


# Bindings predefinidos por tipo de agente
DEFAULT_AGENT_BINDINGS = {
    AgentType.ANALYST: AgentMCPBinding(
        agent_id="analyst",
        agent_type=AgentType.ANALYST,
        required_mcp_ids=["context7", "filesystem"],
        allowed_mcp_ids=["context7", "filesystem", "codegraph"],
        required_capabilities=["analysis", "research", "requirements"],
        preferred_model_id="deepseek-r1-free",
        fallback_model_ids=["gpt-4o-mini", "claude-3.5-haiku"],
    ),
    AgentType.ARCHITECT: AgentMCPBinding(
        agent_id="architect",
        agent_type=AgentType.ARCHITECT,
        required_mcp_ids=["context7", "filesystem", "codegraph"],
        allowed_mcp_ids=["context7", "filesystem", "codegraph", "firecrawl"],
        required_capabilities=["architecture", "design", "technical-specs"],
        preferred_model_id="claude-3.5-sonnet",
        fallback_model_ids=["gpt-4o", "deepseek-r1-free"],
    ),
    AgentType.IMPLEMENTER: AgentMCPBinding(
        agent_id="implementer",
        agent_type=AgentType.IMPLEMENTER,
        required_mcp_ids=["filesystem"],
        allowed_mcp_ids=["filesystem", "codegraph", "playwright", "firecrawl"],
        required_capabilities=["implementation", "coding", "testing"],
        preferred_model_id="claude-3.5-sonnet",
        fallback_model_ids=["gpt-4o", "qwen-2.5-coder-free"],
    ),
    AgentType.TESTER: AgentMCPBinding(
        agent_id="tester",
        agent_type=AgentType.TESTER,
        required_mcp_ids=["filesystem", "playwright"],
        allowed_mcp_ids=["filesystem", "playwright", "codegraph", "firecrawl"],
        required_capabilities=["testing", "verification", "automation"],
        preferred_model_id="gpt-4o-mini",
        fallback_model_ids=["claude-3.5-haiku", "deepseek-r1-free"],
    ),
    AgentType.REVIEWER: AgentMCPBinding(
        agent_id="reviewer",
        agent_type=AgentType.REVIEWER,
        required_mcp_ids=["filesystem", "codegraph"],
        allowed_mcp_ids=["filesystem", "codegraph", "context7"],
        required_capabilities=["review", "security", "quality"],
        preferred_model_id="claude-3.5-sonnet",
        fallback_model_ids=["gpt-4o", "deepseek-r1-free"],
    ),
    AgentType.PLANNER: AgentMCPBinding(
        agent_id="planner",
        agent_type=AgentType.PLANNER,
        required_mcp_ids=["context7", "filesystem"],
        allowed_mcp_ids=["context7", "filesystem", "codegraph", "firecrawl"],
        required_capabilities=["planning", "estimation", "dependencies"],
        preferred_model_id="claude-3.5-sonnet",
        fallback_model_ids=["gpt-4o", "deepseek-r1-free"],
    ),
    AgentType.COORDINATOR: AgentMCPBinding(
        agent_id="coordinator",
        agent_type=AgentType.COORDINATOR,
        required_mcp_ids=["filesystem"],
        allowed_mcp_ids=["filesystem", "context7", "codegraph", "firecrawl", "playwright"],
        required_capabilities=["coordination", "orchestration", "gates"],
        preferred_model_id="claude-3.5-sonnet",
        fallback_model_ids=["gpt-4o", "deepseek-r1-free"],
    ),
    AgentType.EXPLORER: AgentMCPBinding(
        agent_id="explorer",
        agent_type=AgentType.EXPLORER,
        required_mcp_ids=["filesystem", "context7"],
        allowed_mcp_ids=["filesystem", "context7", "codegraph", "firecrawl", "playwright"],
        required_capabilities=["exploration", "discovery", "research"],
        preferred_model_id="deepseek-r1-free",
        fallback_model_ids=["claude-3.5-sonnet", "gpt-4o-mini"],
    ),
    AgentType.SECURITY: AgentMCPBinding(
        agent_id="security",
        agent_type=AgentType.SECURITY,
        required_mcp_ids=["filesystem", "codegraph"],
        allowed_mcp_ids=["filesystem", "codegraph", "firecrawl", "playwright"],
        required_capabilities=["security", "audit", "vulnerability"],
        preferred_model_id="claude-3.5-sonnet",
        fallback_model_ids=["gpt-4o", "deepseek-r1-free"],
    ),
    AgentType.DOCUMENTATION: AgentMCPBinding(
        agent_id="documentation",
        agent_type=AgentType.DOCUMENTATION,
        required_mcp_ids=["context7", "filesystem"],
        allowed_mcp_ids=["context7", "filesystem", "firecrawl"],
        required_capabilities=["documentation", "writing", "research"],
        preferred_model_id="gpt-4o-mini",
        fallback_model_ids=["claude-3.5-haiku", "gemini-flash-free"],
    ),
    AgentType.DEVOPS: AgentMCPBinding(
        agent_id="devops",
        agent_type=AgentType.DEVOPS,
        required_mcp_ids=["filesystem"],
        allowed_mcp_ids=["filesystem", "playwright", "firecrawl", "codegraph"],
        required_capabilities=["deployment", "infrastructure", "ci-cd"],
        preferred_model_id="gpt-4o-mini",
        fallback_model_ids=["claude-3.5-haiku", "deepseek-r1-free"],
    ),
    AgentType.VISUAL: AgentMCPBinding(
        agent_id="visual",
        agent_type=AgentType.VISUAL,
        required_mcp_ids=["playwright", "filesystem"],
        allowed_mcp_ids=["playwright", "filesystem", "firecrawl"],
        required_capabilities=["visual", "design", "screenshots"],
        preferred_model_id="gpt-4o-mini",
        fallback_model_ids=["gemini-flash-free", "claude-3.5-haiku"],
    ),
}


class AgentMCPRegistry:
    """Registro de bindings agente-MCP con resolución dinámica."""
    
    def __init__(self, mcp_registry: 'MCPRegistry', model_registry: 'ModelRegistry'):
        self.mcp_registry = mcp_registry
        self.model_registry = model_registry
        self.bindings: dict[str, AgentMCPBinding] = {}
        self._load_default_bindings()
    
    def _load_default_bindings(self) -> None:
        """Carga los bindings por defecto."""
        for agent_type, binding in DEFAULT_AGENT_BINDINGS.items():
            self.bindings[binding.agent_id] = binding
    
    def get_binding(self, agent_id: str) -> Optional['AgentMCPBinding']:
        return self.bindings.get(agent_id)
    
    def get_binding_by_type(self, agent_type: 'AgentType') -> Optional['AgentMCPBinding']:
        return self.bindings.get(agent_type.value)
    
    def get_available_mcps(self, agent_id: str) -> list['MCPServer']:
        """Obtiene MCPs disponibles para un agente."""
        binding = self.get_binding(agent_id)
        if not binding:
            return []
        
        mcps = []
        for mcp_id in binding.allowed_mcp_ids:
            mcp = self.mcp_registry.get_mcp(mcp_id)
            if mcp and mcp.enabled:
                mcps.append(mcp)
        return mcps
    
    def get_required_mcps(self, agent_id: str) -> list['MCPServer']:
        """Obtiene MCPs requeridos para un agente."""
        binding = self.get_binding(agent_id)
        if not binding:
            return []
        
        mcps = []
        for mcp_id in binding.required_mcp_ids:
            mcp = self.mcp_registry.get_mcp(mcp_id)
            if mcp and mcp.enabled:
                mcps.append(mcp)
        return mcps
    
    def get_available_functions(self, agent_id: str) -> list[dict]:
        """Obtiene todas las funciones disponibles en formato OpenAI."""
        mcps = self.get_available_mcps(agent_id)
        functions = []
        for mcp in mcps:
            for func in mcp.functions:
                functions.append(func.to_openai_function())
        return functions
    
    def get_selected_model(self, agent_id: str) -> Optional['Model']:
        """Obtiene el modelo seleccionado para un agente."""
        binding = self.get_binding(agent_id)
        if not binding:
            return None
        
        model_registry = self.model_registry
        
        # Primero intentar modelo preferido
        if binding.preferred_model_id:
            model = self.model_registry.get_model(binding.preferred_model_id)
            if model:
                return model
        
        # Fallbacks
        for fallback_id in binding.fallback_model_ids:
            model = self.model_registry.get_model(fallback_id)
            if model:
                return model
        
        # Fallback: primer modelo gratuito con capabilities básicas
        free_models = [m for m in self.model_registry.models.values() if m.is_free]
        return free_models[0] if free_models else None
    
    def get_available_mcps_for_agent(self, agent_id: str) -> list:
        """Obtiene MCPs disponibles para un agente como diccionarios para config."""
        binding = self.get_binding(agent_id)
        if not binding:
            return []
        
        mcps = []
        for mcp_id in binding.allowed_mcp_ids:
            mcp = self.mcp_registry.get_mcp(mcp_id)
            if mcp and mcp.enabled:
                mcps.append(mcp)
        return mcps
    
    def generate_agent_config(self, agent_id: str, project_root: str = "") -> dict:
        """Genera configuración completa para un agente."""
        binding = self.get_binding(agent_id)
        if not binding:
            return {}
        
        # Obtener modelo
        model = self.model_registry.get_selected_model(agent_id) or self.model_registry.get_model("deepseek-r1-free")
        
        # Obtener MCPs disponibles
        mcps = self.get_available_mcps(agent_id)
        
        # Generar config de MCPs para OpenCode
        mcp_configs = {}
        for mcp in mcps:
            config = mcp.to_opencode_config(project_root)
            if "mcp" in config and "servers" in config["mcp"]:
                mcp_configs.update(config["mcp"]["servers"])
        
        # Generar tools en formato OpenAI
        functions = []
        for mcp in mcps:
            for func in mcp.functions:
                func_dict = func.to_openai_function()
                func_dict["mcp_server"] = mcp.id
                func_dict["mcp_name"] = mcp.name
                func_dict["_mcp_capabilities"] = [c.value for c in mcp.capabilities]
                func_dict["_mcp_id"] = mcp.id
                functions.append(func_dict)
        
        return {
            "agent_id": agent_id,
            "model": model.to_opencode_config() if model else {},
            "mcp_servers": mcp_configs,
            "functions": functions,
            "capabilities": self.get_binding(agent_id).required_capabilities if self.get_binding(agent_id) else [],
            "max_mcp_calls": self.get_binding(agent_id).max_mcp_calls_per_task if self.get_binding(agent_id) else 10,
        }
    
    def register_custom_binding(self, binding: 'AgentMCPBinding') -> None:
        """Registra un binding personalizado."""
        self.bindings[binding.agent_id] = binding
    
    def update_binding(self, agent_id: str, **kwargs) -> bool:
        """Actualiza un binding existente."""
        binding = self.get_binding(agent_id)
        if not binding:
            return False
        
        for key, value in kwargs.items():
            if hasattr(binding, key):
                setattr(binding, key, value)
        return True


# Instancia global
AGENT_MCP_REGISTRY = None


def get_agent_mcp_registry(mcp_registry=None, model_registry=None) -> 'AgentMCPRegistry':
    global AGENT_MCP_REGISTRY
    if AGENT_MCP_REGISTRY is None:
        from .mcp_registry import get_mcp_registry
        from .model_registry import get_model_registry
        AGENT_MCP_REGISTRY = AgentMCPRegistry(
            mcp_registry or get_mcp_registry(),
            model_registry or get_model_registry()
        )
    return AGENT_MCP_REGISTRY