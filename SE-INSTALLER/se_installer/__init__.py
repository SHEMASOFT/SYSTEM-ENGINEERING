"""SE Installer - Unified installer for System Engineering Master System."""

from __future__ import annotations

__version__ = "0.1.0"
__author__ = "SHEMASOFT"

from .models import (
    InstallableComponent,
    InstallationPlan,
    InstallStatus,
    OSType,
    ComponentType,
)

from .components import get_all_components, get_recommended_components, get_components_by_category
from .orchestrator import InstallerOrchestrator
from .state import InstallationState
from .model_registry import (
    ModelRegistry, Model, ModelProvider, ModelCapability, 
    get_model_registry, MODEL_REGISTRY
)
from .mcp_registry import (
    MCPRegistry, MCPServer, MCPFunction, MCPCapability, MCPTransport,
    get_mcp_registry, MCP_REGISTRY
)
from .agent_mcp_binding import (
    AgentMCPRegistry, AgentMCPBinding, AgentType,
    get_agent_mcp_registry, DEFAULT_AGENT_BINDINGS
)
from .skill_mcp_bridge import (
    SkillMCPBridge, MCPToolCall, MCPToolResult,
    get_skill_mcp_bridge, requires_mcp_capabilities
)
from .runtime_config_generator import (
    RuntimeConfigGenerator, RuntimeConfig,
    get_runtime_config_generator
)

__all__ = [
    # Core models
    "InstallableComponent",
    "InstallationPlan",
    "InstallStatus",
    "OSType",
    "ComponentType",
    # Components
    "get_all_components",
    "get_recommended_components",
    "get_components_by_category",
    # Orchestrator
    "InstallerOrchestrator",
    "InstallationState",
    # Model Registry
    "ModelRegistry", "Model", "ModelProvider", "ModelCapability",
    "get_model_registry", "MODEL_REGISTRY",
    # MCP Registry
    "MCPRegistry", "MCPServer", "MCPFunction", "MCPCapability", "MCPTransport",
    "get_mcp_registry", "MCP_REGISTRY",
    # Agent-MCP Binding
    "AgentMCPRegistry", "AgentMCPBinding", "AgentType",
    "get_agent_mcp_registry", "DEFAULT_AGENT_BINDINGS",
    # Skill-MCP Bridge
    "SkillMCPBridge", "MCPToolCall", "MCPToolResult",
    "get_skill_mcp_bridge", "requires_mcp_capabilities",
    # Runtime Config Generator
    "RuntimeConfigGenerator", "RuntimeConfig",
    "get_runtime_config_generator",
]