"""Skill-MCP Bridge - Permite que skills invoquen MCPs como herramientas."""

from __future__ import annotations

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Any, Callable
from pathlib import Path
import json
import asyncio
from typing import Awaitable

from .mcp_registry import MCPRegistry, MCPServer, MCPFunction, MCPCapability
from .model_registry import ModelRegistry


@dataclass
class MCPToolCall:
    """Representa una llamada a una herramienta MCP."""
    mcp_id: str
    function_name: str
    arguments: dict
    request_id: str = ""


@dataclass
class MCPToolResult:
    """Resultado de una llamada a herramienta MCP."""
    request_id: str
    success: bool
    result: Any = None
    error: Optional[str] = None
    mcp_id: str = ""
    function_name: str = ""


class SkillMCPBridge:
    """
    Puente entre skills y MCPs.
    
    Los skills pueden declarar qué capacidades MCP necesitan y el bridge
    resuelve dinámicamente qué MCPs están disponibles y expone sus funciones.
    """
    
    def __init__(
        self, 
        mcp_registry: MCPRegistry,
        model_registry: Optional[ModelRegistry] = None,
        project_root: str = ""
    ):
        self.mcp_registry = mcp_registry
        self.model_registry = model_registry
        self.project_root = project_root
        self._mcp_clients: dict[str, Any] = {}  # Clientes MCP activos por ID
        self._skill_mcp_requirements: dict[str, list[MCPCapability]] = {}
        self._skill_mcp_bindings: dict[str, list[str]] = {}  # skill_id -> mcp_ids
    
    def register_skill_requirements(self, skill_id: str, required_capabilities: list[MCPCapability]) -> None:
        """Registra qué capacidades MCP necesita un skill."""
        self._skill_mcp_requirements[skill_id] = required_capabilities
        # Auto-resolver MCPs que proveen esas capacidades
        mcps = []
        for cap in required_capabilities:
            providers = self.mcp_registry.get_mcps_by_capability(cap)
            for mcp in providers:
                if mcp.enabled and mcp.id not in mcps:
                    mcps.append(mcp.id)
        self._skill_mcp_bindings[skill_id] = mcps
    
    def get_available_mcps_for_skill(self, skill_id: str) -> list[MCPServer]:
        """Obtiene MCPs disponibles para un skill."""
        mcp_ids = self._skill_mcp_bindings.get(skill_id, [])
        return [self.mcp_registry.get_mcp(mid) for mid in mcp_ids if self.mcp_registry.get_mcp(mid)]
    
    def get_all_functions_for_skill(self, skill_id: str) -> list[dict]:
        """Obtiene todas las funciones MCP disponibles para un skill en formato OpenAI."""
        mcps = self.get_available_mcps_for_skill(skill_id)
        functions = []
        for mcp in mcps:
            for func in mcp.functions:
                func_dict = func.to_openai_function()
                func_dict["_mcp_server"] = mcp.id
                func_dict["_mcp_name"] = mcp.name
                func_dict["_mcp_capabilities"] = [c.value for c in mcp.capabilities]
                functions.append(func_dict)
        return functions
    
    def get_function_schema_for_skill(self, skill_id: str) -> dict:
        """Genera schema completo de funciones para un skill."""
        functions = self.get_all_functions_for_skill(skill_id)
        return {
            "skill_id": skill_id,
            "functions": functions,
            "mcp_servers": {mcp.id: mcp.to_opencode_config(self.project_root) for mcp in self.get_available_mcps_for_skill(skill_id)},
        }
    
    async def call_mcp_function(
        self, 
        mcp_id: str, 
        function_name: str, 
        arguments: dict,
        request_id: str = ""
    ) -> MCPToolResult:
        """
        Invoca una función de un MCP.
        
        Nota: Esta es la interfaz abstracta. La implementación real depende
        del transporte (stdio, SSE, HTTP) y del cliente MCP usado.
        """
        mcp = self.mcp_registry.get_mcp(mcp_id)
        if not mcp:
            return MCPToolResult(
                request_id=request_id,
                success=False,
                error=f"MCP {mcp_id} no encontrado",
                mcp_id=mcp_id,
                function_name=function_name
            )
        
        func = mcp.get_function(function_name)
        if not func:
            return MCPToolResult(
                request_id=request_id,
                success=False,
                error=f"Función {function_name} no encontrada en MCP {mcp_id}",
                mcp_id=mcp_id,
                function_name=function_name
            )
        
        # Validar parámetros requeridos
        for req_param in func.required_params:
            if req_param not in arguments:
                return MCPToolResult(
                    request_id=request_id,
                    success=False,
                    error=f"Parámetro requerido faltante: {req_param}",
                    mcp_id=mcp_id,
                    function_name=function_name
                )
        
        # Aquí iría la invocación real al MCP via transporte apropiado
        # Por ahora retornamos un placeholder para la interfaz
        return MCPToolResult(
            request_id=request_id,
            success=True,
            result={"status": "placeholder", "message": f"Invocaría {function_name} en {mcp_id} con {arguments}"},
            mcp_id=mcp_id,
            function_name=function_name
        )
    
    def get_mcp_status(self, skill_id: str) -> dict:
        """Obtiene estado de MCPs para un skill."""
        mcps = self.get_available_mcps_for_skill(skill_id)
        return {
            "skill_id": skill_id,
            "mcps": [
                {
                    "id": mcp.id,
                    "name": mcp.name,
                    "description": mcp.description,
                    "enabled": mcp.enabled,
                    "capabilities": [c.value for c in mcp.capabilities],
                    "functions": [f.name for f in mcp.functions],
                    "requires_env": mcp.get_required_env_vars(),
                }
                for mcp in mcps
            ],
            "total_functions": sum(len(mcp.functions) for mcp in mcps),
        }
    
    def list_all_skill_bindings(self) -> dict:
        """Lista todos los bindings skill-MCP registrados."""
        return {
            skill_id: {
                "required_capabilities": [c.value for c in caps],
                "bound_mcps": self._skill_mcp_bindings.get(skill_id, []),
            }
            for skill_id, caps in self._skill_mcp_requirements.items()
        }


# Decorador para facilitar declaración de requirements en skills
def requires_mcp_capabilities(*capabilities: MCPCapability):
    """
    Decorador para declarar capacidades MCP requeridas por un skill.
    
    Uso:
        @requires_mcp_capabilities(MCPCapability.FILE_READ, MCPCapability.WEB_SEARCH)
        class MySkill:
            ...
    """
    def decorator(skill_class):
        skill_class._mcp_required_capabilities = list(capabilities)
        return skill_class
    return decorator


# Instancia global
SKILL_MCP_BRIDGE = None


def get_skill_mcp_bridge(
    mcp_registry: Optional[MCPRegistry] = None,
    model_registry: Optional[ModelRegistry] = None,
    project_root: str = ""
) -> SkillMCPBridge:
    global SKILL_MCP_BRIDGE
    if SKILL_MCP_BRIDGE is None:
        from .mcp_registry import get_mcp_registry
        from .model_registry import get_model_registry
        SKILL_MCP_BRIDGE = SkillMCPBridge(
            mcp_registry or get_mcp_registry(),
            model_registry or get_model_registry(),
            project_root
        )
    return SKILL_MCP_BRIDGE