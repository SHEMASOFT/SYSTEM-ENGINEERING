"""Core models for SE Installer."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
from pathlib import Path


class OSType(str, Enum):
    WINDOWS = "windows"
    MACOS = "macos"
    LINUX = "linux"


class InstallStatus(str, Enum):
    PENDING = "pending"
    CHECKING = "checking"
    DOWNLOADING = "downloading"
    INSTALLING = "installing"
    CONFIGURING = "configuring"
    VERIFYING = "verifying"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class ComponentType(str, Enum):
    MCP = "mcp"
    RUNTIME = "runtime"
    SE_CORE = "se_core"
    SE_CONSOLE = "se_console"


@dataclass
class InstallableComponent:
    """Base class for anything installable."""
    id: str
    name: str
    description: str
    component_type: ComponentType
    # Dependencies
    requires: list[str] = field(default_factory=list)  # other component IDs
    conflicts_with: list[str] = field(default_factory=list)
    # Platform support
    supported_os: list[OSType] = field(default_factory=lambda: [OSType.WINDOWS, OSType.MACOS, OSType.LINUX])
    # Installation
    install_method: str = "auto"  # "auto", "winget", "scoop", "brew", "npm", "binary", "pip", "script"
    install_args: dict = field(default_factory=dict)
    # Post-install
    post_install_commands: list[str] = field(default_factory=list)
    verification_command: Optional[str] = None
    # Metadata
    homepage: str = ""
    docs_url: str = ""
    license: str = ""
    version: str = "latest"
    # State
    status: InstallStatus = InstallStatus.PENDING
    installed_version: Optional[str] = None
    error_message: Optional[str] = None
    # UI
    recommended: bool = True
    category: str = ""
    long_description: str = ""

    def is_supported_on(self, os_type: OSType) -> bool:
        return os_type in self.supported_os


@dataclass
class InstallationPlan:
    """Complete installation plan."""
    components: list[InstallableComponent] = field(default_factory=list)
    os_type: OSType = OSType.WINDOWS
    target_dir: Path = Path.home() / ".se-installer"
    # Runtime targets
    target_runtimes: list[str] = field(default_factory=lambda: ["opencode"])
    # Options
    dry_run: bool = False
    force_reinstall: bool = False
    skip_verification: bool = False
    # Install-time desktop shortcut for the SE Console (DESIGN-5C phase 4).
    # Opt-in, and only ever one: it writes to the operator's Desktop, so it is
    # not something an install should do behind their back.
    create_shortcuts: bool = False
    # State
    created_at: str = ""
    completed_at: Optional[str] = None
    
    def get_selected(self) -> list[InstallableComponent]:
        return [c for c in self.components if c.status != InstallStatus.SKIPPED]
    
    def get_by_id(self, component_id: str) -> Optional[InstallableComponent]:
        for c in self.components:
            if c.id == component_id:
                return c
        return None
    
    def get_dependencies(self, component_id: str) -> list[InstallableComponent]:
        comp = self.get_by_id(component_id)
        if not comp:
            return []
        deps = []
        for dep_id in comp.requires:
            dep = self.get_by_id(dep_id)
            if dep:
                deps.append(dep)
        return deps
    
    def topological_sort(self) -> list[InstallableComponent]:
        """Sort components by dependencies (Kahn's algorithm)."""
        selected = self.get_selected()
        if not selected:
            return []
        
        # Build graph
        graph = {c.id: [] for c in selected}
        in_degree = {c.id: 0 for c in selected}
        id_to_comp = {c.id: c for c in selected}
        
        for comp in selected:
            for dep_id in comp.requires:
                if dep_id in id_to_comp:
                    graph[dep_id].append(comp.id)
                    in_degree[comp.id] += 1
        
        # Kahn's algorithm
        from collections import deque
        queue = deque([cid for cid, deg in in_degree.items() if deg == 0])
        result = []
        
        while queue:
            # Deterministic ordering
            queue = deque(sorted(queue))
            cid = queue.popleft()
            result.append(id_to_comp[cid])
            for neighbor in graph[cid]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        
        if len(result) != len(selected):
            # Cycle detected - return original order as fallback
            return selected
        
        return result