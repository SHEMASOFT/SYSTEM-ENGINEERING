"""Runtime Adapters Installers."""

from __future__ import annotations

from typing import Optional
from pathlib import Path
import json
import subprocess
import shutil

from ..base import BaseInstaller, InstallResult, refresh_process_path, run_tool
from ...models import InstallableComponent, InstallStatus, OSType


class OpenCodeInstaller(BaseInstaller):
    """OpenCode - Primary runtime for SE."""
    
    def check_installed(self) -> tuple[bool, Optional[str]]:
        result = run_tool("opencode", ["--version"], timeout=10)
        if result and result.returncode == 0:
            return True, result.stdout.strip()
        return False, None
    
    def install(self) -> InstallResult:
        self.component.status = InstallStatus.INSTALLING
        os_type = self._detect_os()
        
        if os_type == OSType.WINDOWS:
            return self._install_windows()
        elif os_type == OSType.MACOS:
            return self._install_macos()
        else:
            return self._install_linux()
    
    def _install_windows(self) -> 'InstallResult':
        # Try winget first
        result = run_tool(
            "winget",
            ["install", "--id", "OpenCode.OpenCode", "--silent",
             "--accept-source-agreements", "--accept-package-agreements"],
            timeout=300,
        )
        if result and result.returncode == 0:
            return self._post_install()
        
        # Try Scoop
        if shutil.which("scoop"):
            result = run_tool("scoop", ["install", "opencode"], timeout=300)
            if result and result.returncode == 0:
                return self._post_install()
        
        # Try Chocolatey
        if shutil.which("choco"):
            result = run_tool("choco", ["install", "opencode", "-y", "--no-progress"], timeout=300)
            if result and result.returncode == 0:
                return self._post_install()
        
        return InstallResult(success=False, error="No Windows package manager found (winget/scoop/choco)")
    
    def _install_macos(self) -> 'InstallResult':
        # Homebrew
        if shutil.which("brew"):
            result = run_tool("brew", ["install", "sst/tap/opencode"], timeout=300)
            if result and result.returncode == 0:
                return self._post_install()
        
        return InstallResult(success=False, error="Homebrew not found. Install from https://brew.sh/")
    
    def _install_linux(self) -> 'InstallResult':
        # Try the official install script
        result = subprocess.run(
            ["bash", "-c", "curl -fsSL https://opencode.ai/install | bash"],
            capture_output=True, text=True, timeout=300
        )
        if result.returncode == 0:
            return self._post_install()
        
        return InstallResult(success=False, error="OpenCode install script failed")
    
    def _post_install(self) -> 'InstallResult':
        refresh_process_path()
        result = run_tool("opencode", ["--version"], timeout=10)
        if result and result.returncode == 0:
            self.component.status = InstallStatus.SUCCESS
            return InstallResult(success=True, version=result.stdout.strip(), message="OpenCode installed")
        return InstallResult(success=False, error="OpenCode installed but version check failed")


class CodexInstaller(BaseInstaller):
    """Codex - OpenAI Codex CLI."""
    
    def check_installed(self) -> tuple[bool, Optional[str]]:
        result = run_tool("codex", ["--version"], timeout=10)
        if result and result.returncode == 0:
            return True, result.stdout.strip()
        return False, None
    
    def install(self) -> 'InstallResult':
        self.component.status = InstallStatus.INSTALLING
        
        # Codex is installed via npm
        if not shutil.which("npm"):
            return InstallResult(success=False, error="npm not found. Install Node.js first.")
        
        result = run_tool("npm", ["install", "-g", "@openai/codex"], timeout=300)
        
        if result and result.returncode == 0:
            self.component.status = InstallStatus.SUCCESS
            return InstallResult(success=True, version="latest", message="Codex CLI installed via npm")
        else:
            err = result.stderr if result else "npm not found on PATH"
            return InstallResult(success=False, error=f"npm install failed: {err}")


class ClaudeCodeInstaller(BaseInstaller):
    """Claude Code - Anthropic's CLI."""
    
    def check_installed(self) -> tuple[bool, Optional[str]]:
        result = run_tool("claude", ["--version"], timeout=10)
        if result and result.returncode == 0:
            return True, result.stdout.strip()
        return False, None
    
    def install(self) -> 'InstallResult':
        self.component.status = InstallStatus.INSTALLING
        
        # Claude Code is distributed via npm
        if not shutil.which("npm"):
            return InstallResult(success=False, error="npm not found. Install Node.js first.")
        
        result = run_tool("npm", ["install", "-g", "@anthropic-ai/claude-code"], timeout=300)
        
        if result and result.returncode == 0:
            self.component.status = InstallStatus.SUCCESS
            return InstallResult(success=True, version="latest", message="Claude Code installed via npm")
        else:
            err = result.stderr if result else "npm not found on PATH"
            return InstallResult(success=False, error=f"npm install failed: {err}")


# Registry
RUNTIME_INSTALLERS = {
    "opencode": OpenCodeInstaller,
    "codex": CodexInstaller,
    "claude_code": ClaudeCodeInstaller,
}


def get_runtime_installer(component_id: str, component: 'InstallableComponent', dry_run: bool = False):
    installer_class = RUNTIME_INSTALLERS.get(component_id)
    if not installer_class:
        raise ValueError(f"No installer for runtime: {component_id}")
    return installer_class(component, dry_run)
