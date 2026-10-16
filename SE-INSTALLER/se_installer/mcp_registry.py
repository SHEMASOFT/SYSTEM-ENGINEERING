"""MCP Registry - Registro de MCPs disponibles con sus capacidades y funciones."""

from __future__ import annotations

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from pathlib import Path
import json
import subprocess
import shutil


class MCPTransport(str, Enum):
    STDIO = "stdio"
    SSE = "sse"
    HTTP = "http"


class MCPCapability(str, Enum):
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    FILE_LIST = "file_list"
    FILE_SEARCH = "file_search"
    WEB_SEARCH = "web_search"
    WEB_SCRAPE = "web_scrape"
    WEB_CRAWL = "web_crawl"
    DOC_LOOKUP = "doc_lookup"
    CODE_SEARCH = "code_search"
    CODE_ANALYSIS = "code_analysis"
    BROWSER_AUTOMATION = "browser_automation"
    BROWSER_SCREENSHOT = "browser_screenshot"
    BROWSER_CLICK = "browser_click"
    BROWSER_FORM = "browser_form"
    CODE_INTELLIGENCE = "code_intelligence"
    BLAST_RADIUS = "blast_radius"
    GO_TO_DEFINITION = "go_to_definition"
    FILE_OPERATIONS = "file_operations"
    WEB_SCRAPING = "web_scraping"
    BROWSER_CONTROL = "browser_control"


@dataclass
class MCPFunction:
    """Definición de una función/herramienta expuesta por un MCP."""
    name: str
    description: str
    parameters: dict  # JSON Schema
    required_params: list[str] = field(default_factory=list)
    
    def to_openai_function(self) -> dict:
        """Convierte a formato OpenAI function calling."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": self.parameters,
                "required": self.required_params
            }
        }


@dataclass
class MCPServer:
    """Definición completa de un servidor MCP."""
    id: str
    name: str
    description: str
    transport: MCPTransport = MCPTransport.STDIO
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    env_required: list[str] = field(default_factory=list)
    capabilities: list[MCPCapability] = field(default_factory=list)
    functions: list[MCPFunction] = field(default_factory=list)
    # Instalación
    install_method: str = "auto"  # "npm", "binary", "cargo", "pip", "auto"
    install_command: str = ""
    install_args: list[str] = field(default_factory=list)
    post_install_commands: list[str] = field(default_factory=list)
    verification_command: str = ""
    # Metadatos
    homepage: str = ""
    docs_url: str = ""
    license: str = ""
    category: str = ""
    tags: list[str] = field(default_factory=list)
    # Requisitos
    requires: list[str] = field(default_factory=list)  # IDs de otros MCPs/runtime
    conflicts_with: list[str] = field(default_factory=list)
    # Estado
    enabled: bool = True
    priority: int = 0  # Para orden de carga
    
    def get_function_names(self) -> list[str]:
        return [f.name for f in self.functions]
    
    def get_function(self, name: str) -> Optional[MCPFunction]:
        for f in self.functions:
            if f.name == name:
                return f
        return None
    
    def has_capability(self, cap: MCPCapability) -> bool:
        return cap in self.capabilities
    
    def to_opencode_config(self, project_root: str = "") -> dict:
        """Genera configuración para OpenCode."""
        cmd = [self.command] + self.args
        # Resolver placeholders
        resolved_args = []
        for arg in self.args:
            arg = arg.replace("${SE_PROJECT_ROOT}", project_root)
            arg = arg.replace("${SE_ROOT}", "")  # Se resuelve en runtime
            resolved_args.append(arg)
        
        config = {
            "name": self.name,
            "type": "local",
            "command": self.command,
            "args": resolved_args,
        }
        if self.env:
            config["environment"] = self.env
        if self.transport != MCPTransport.STDIO:
            config["transport"] = self.transport.value
        return {"mcp": {"servers": {self.name: config}}}
    
    def get_required_env_vars(self) -> list[str]:
        return self.env_required.copy()


class MCPRegistry:
    """Registro de MCPs disponibles con descubrimiento de capacidades."""
    
    def __init__(self, custom_mcps_path: Optional[Path] = None):
        self.mcps: dict[str, MCPServer] = {}
        self.custom_mcps_path = custom_mcps_path
        self._load_builtin_mcps()
        self._load_custom_mcps()
    
    def _load_builtin_mcps(self) -> None:
        # Context7 - Documentación de librerías
        self.mcps["context7"] = MCPServer(
            id="context7",
            name="Context7",
            description="Documentación actualizada de librerías/frameworks via Context7 API",
            transport=MCPTransport.STDIO,
            command="npx",
            args=["-y", "@upstash/context7-mcp"],
            env={"CONTEXT7_API_KEY": "${CONTEXT7_API_KEY}"},
            env_required=["CONTEXT7_API_KEY"],
            capabilities=[
                MCPCapability.DOC_LOOKUP,
                MCPCapability.WEB_SEARCH,
            ],
            functions=[
                MCPFunction(
                    name="resolve-library-id",
                    description="Resolve library name to Context7-compatible ID",
                    parameters={"libraryName": {"type": "string"}},
                    required_params=["libraryName"]
                ),
                MCPFunction(
                    name="query-docs",
                    description="Query library documentation",
                    parameters={
                        "libraryId": {"type": "string"},
                        "query": {"type": "string"},
                        "language": {"type": "string"}
                    },
                    required_params=["libraryId", "query"]
                ),
            ],
            install_method="npx",
            verification_command="npx -y @upstash/context7-mcp --help",
            homepage="https://context7.com",
            category="Documentation",
            tags=["documentation", "libraries", "api"],
            requires=["node"],
        )
        
        # Filesystem - Operaciones de archivos
        self.mcps["filesystem"] = MCPServer(
            id="filesystem",
            name="Filesystem MCP",
            description="Operaciones de archivos: read, write, list, search bajo un root",
            transport=MCPTransport.STDIO,
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", "${SE_PROJECT_ROOT}"],
            capabilities=[
                MCPCapability.FILE_READ,
                MCPCapability.FILE_WRITE,
                MCPCapability.FILE_LIST,
                MCPCapability.FILE_SEARCH,
                MCPCapability.FILE_OPERATIONS,
            ],
            functions=[
                MCPFunction(
                    name="read_file",
                    description="Read file contents",
                    parameters={"path": {"type": "string"}},
                    required_params=["path"]
                ),
                MCPFunction(
                    name="write_file",
                    description="Write file contents",
                    parameters={"path": {"type": "string"}, "content": {"type": "string"}},
                    required_params=["path", "content"]
                ),
                MCPFunction(
                    name="list_directory",
                    description="List directory contents",
                    parameters={"path": {"type": "string"}},
                    required_params=["path"]
                ),
                MCPFunction(
                    name="search_files",
                    description="Search files by pattern",
                    parameters={"pattern": {"type": "string"}, "path": {"type": "string"}},
                    required_params=["pattern"]
                ),
            ],
            install_method="npx",
            verification_command="npx -y @modelcontextprotocol/server-filesystem --help",
            homepage="https://github.com/modelcontextprotocol/servers",
            category="File Operations",
            tags=["filesystem", "files", "read", "write"],
            requires=["node"],
        )
        
        # Playwright - Browser automation
        self.mcps["playwright"] = MCPServer(
            id="playwright",
            name="Playwright MCP",
            description="Automatización de navegadores: navegar, click, screenshots, forms",
            transport=MCPTransport.STDIO,
            command="npx",
            args=["-y", "@playwright/mcp"],
            capabilities=[
                MCPCapability.BROWSER_AUTOMATION,
                MCPCapability.BROWSER_SCREENSHOT,
                MCPCapability.BROWSER_CLICK,
                MCPCapability.BROWSER_FORM,
                MCPCapability.WEB_SEARCH,
                MCPCapability.WEB_SCRAPE,
            ],
            functions=[
                MCPFunction(
                    name="navigate",
                    description="Navigate to URL",
                    parameters={"url": {"type": "string"}},
                    required_params=["url"]
                ),
                MCPFunction(
                    name="click",
                    description="Click element",
                    parameters={"selector": {"type": "string"}},
                    required_params=["selector"]
                ),
                MCPFunction(
                    name="screenshot",
                    description="Take screenshot",
                    parameters={"path": {"type": "string"}, "full_page": {"type": "boolean"}},
                    required_params=["path"]
                ),
                MCPFunction(
                    name="fill_form",
                    description="Fill form fields",
                    parameters={"selector": {"type": "string"}, "value": {"type": "string"}},
                    required_params=["selector", "value"]
                ),
                MCPFunction(
                    name="evaluate",
                    description="Execute JavaScript in page",
                    parameters={"script": {"type": "string"}},
                    required_params=["script"]
                ),
            ],
            install_method="npx",
            post_install_commands=["npx playwright install chromium"],
            verification_command="npx -y @playwright/mcp --help",
            homepage="https://playwright.dev",
            category="Browser Automation",
            tags=["browser", "automation", "testing", "screenshots"],
            requires=["node"],
        )
        
        # Firecrawl - Web scraping
        self.mcps["firecrawl"] = MCPServer(
            id="firecrawl",
            name="Firecrawl",
            description="Web scraping, crawling y búsqueda web. Requiere FIRECRAWL_API_KEY",
            transport=MCPTransport.STDIO,
            command="npx",
            args=["-y", "firecrawl-mcp"],
            env={"FIRECRAWL_API_KEY": "${FIRECRAWL_API_KEY}"},
            env_required=["FIRECRAWL_API_KEY"],
            capabilities=[
                MCPCapability.WEB_SCRAPE,
                MCPCapability.WEB_CRAWL,
                MCPCapability.WEB_SEARCH,
            ],
            functions=[
                MCPFunction(
                    name="scrape",
                    description="Scrape single URL",
                    parameters={"url": {"type": "string"}, "formats": {"type": "array", "items": {"type": "string"}}},
                    required_params=["url"]
                ),
                MCPFunction(
                    name="crawl",
                    description="Crawl website",
                    parameters={"url": {"type": "string"}, "max_pages": {"type": "integer"}},
                    required_params=["url"]
                ),
                MCPFunction(
                    name="search",
                    description="Web search",
                    parameters={"query": {"type": "string"}, "limit": {"type": "integer"}},
                    required_params=["query"]
                ),
            ],
            install_method="npx",
            verification_command="npx -y firecrawl-mcp --help",
            homepage="https://firecrawl.dev",
            category="Web Scraping",
            tags=["scraping", "crawling", "search"],
            requires=["node"],
        )
        
        # CodeGraph - Code intelligence
        self.mcps["codegraph"] = MCPServer(
            id="codegraph",
            name="CodeGraph",
            description="Code intelligence: blast radius, go-to-definition, impact analysis",
            transport=MCPTransport.STDIO,
            command="codegraph-mcp",
            args=[],
            capabilities=[
                MCPCapability.CODE_INTELLIGENCE,
                MCPCapability.BLAST_RADIUS,
                MCPCapability.GO_TO_DEFINITION,
                MCPCapability.CODE_SEARCH,
                MCPCapability.CODE_ANALYSIS,
                MCPCapability.CODE_INTELLIGENCE,
            ],
            functions=[
                MCPFunction(
                    name="blast_radius",
                    description="Analyze blast radius of changes",
                    parameters={"files": {"type": "array", "items": {"type": "string"}}},
                    required_params=["files"]
                ),
                MCPFunction(
                    name="go_to_definition",
                    description="Go to definition of symbol",
                    parameters={"file": {"type": "string"}, "line": {"type": "integer"}, "column": {"type": "integer"}},
                    required_params=["file", "line", "column"]
                ),
                MCPFunction(
                    name="find_references",
                    description="Find all references to symbol",
                    parameters={"symbol": {"type": "string"}},
                    required_params=["symbol"]
                ),
                MCPFunction(
                    name="impact_analysis",
                    description="Analyze impact of changes",
                    parameters={"changes": {"type": "array", "items": {"type": "string"}}},
                    required_params=["changes"]
                ),
            ],
            install_method="cargo",
            verification_command="codegraph --version",
            homepage="https://codegraph.dev",
            category="Code Intelligence",
            tags=["code-intelligence", "blast-radius", "go-to-definition"],
            requires=["rust"],
        )
    
    def _load_custom_mcps(self) -> None:
        # Cargar MCPs personalizados desde archivo
        pass
    
    def get_mcp(self, mcp_id: str) -> Optional[MCPServer]:
        return self.mcps.get(mcp_id)
    
    def get_mcps_by_capability(self, cap: MCPCapability) -> list[MCPServer]:
        return [m for m in self.mcps.values() if cap in m.capabilities]
    
    def get_mcps_by_category(self) -> dict[str, list[MCPServer]]:
        from collections import defaultdict
        by_cat = defaultdict(list)
        for m in self.mcps.values():
            by_cat[m.category].append(m)
        return dict(by_cat)
    
    def get_enabled_mcps(self) -> list[MCPServer]:
        return [m for m in self.mcps.values() if m.enabled]
    
    def get_mcps_for_agent(self, agent_capabilities: list[MCPCapability]) -> list[MCPServer]:
        """Obtiene MCPs relevantes para un agente basado en sus capacidades."""
        return [m for m in self.mcps.values() if any(c in m.capabilities for c in agent_capabilities)]
    
    def get_all_functions(self, mcp_ids: list[str]) -> list[MCPFunction]:
        """Obtiene todas las funciones de una lista de MCPs."""
        functions = []
        for mcp_id in mcp_ids:
            mcp = self.get_mcp(mcp_id)
            if mcp:
                functions.extend(mcp.functions)
        return functions
    
    def generate_openai_functions(self, mcp_ids: list[str]) -> list[dict]:
        """Genera funciones en formato OpenAI para MCPs seleccionados."""
        functions = []
        for mcp_id in mcp_ids:
            mcp = self.get_mcp(mcp_id)
            if mcp:
                for f in mcp.functions:
                    functions.append(f.to_openai_function())
        return functions


# Instancia global
MCP_REGISTRY = MCPRegistry()


def get_mcp_registry() -> MCPRegistry:
    return MCP_REGISTRY