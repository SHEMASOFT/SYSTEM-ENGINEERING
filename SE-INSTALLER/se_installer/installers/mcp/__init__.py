"""MCP Server Installers."""

from __future__ import annotations

from typing import Optional
from pathlib import Path
import shutil

from ..base import BaseInstaller, InstallResult, run_tool
from ...models import InstallableComponent, InstallStatus, OSType


class Context7Installer(BaseInstaller):
    """Context7 - Up-to-date library documentation MCP."""
    
    def check_installed(self) -> tuple[bool, Optional[str]]:
        # Context7 is npx-based (fetched on demand): ready when npx is present.
        return self._npx_ready()
    
    def install(self) -> InstallResult:
        self.component.status = InstallStatus.INSTALLING
        
        ready, version = self._npx_ready()
        if not ready:
            return InstallResult(
                success=False,
                error="npx not found. Please install Node.js first."
            )
        
        self.component.status = InstallStatus.SUCCESS
        return InstallResult(success=True, version=version or "npx", message="Context7 MCP ready (npx-based)")


class FilesystemInstaller(BaseInstaller):
    """Filesystem MCP - Read/write files under a root."""
    
    def check_installed(self) -> tuple[bool, Optional[str]]:
        # npx-based server; its CLI does not support --version/--help.
        return self._npx_ready()
    
    def install(self) -> InstallResult:
        self.component.status = InstallStatus.INSTALLING
        
        ready, version = self._npx_ready()
        if not ready:
            return InstallResult(
                success=False,
                error="npx not found. Please install Node.js first."
            )
        
        self.component.status = InstallStatus.SUCCESS
        return InstallResult(success=True, version=version or "npx", message="Filesystem MCP ready (npx-based)")


class PlaywrightInstaller(BaseInstaller):
    """Playwright MCP - Browser automation."""
    
    def check_installed(self) -> tuple[bool, Optional[str]]:
        return self._npx_ready()
    
    def install(self) -> InstallResult:
        self.component.status = InstallStatus.INSTALLING
        
        ready, version = self._npx_ready()
        if not ready:
            return InstallResult(success=False, error="npx not found. Install Node.js first.")
        
        # Also install Playwright browsers
        self.component.status = InstallStatus.CONFIGURING
        browser_result = run_tool("npx", ["playwright", "install", "chromium"], timeout=300)
        
        if not browser_result or browser_result.returncode != 0:
            err = browser_result.stderr if browser_result else "npx not found on PATH"
            return InstallResult(success=False, error=f"Failed to install browsers: {err}")
        
        self.component.status = InstallStatus.SUCCESS
        return InstallResult(success=True, version=version or "npx", message="Playwright MCP + Chromium installed")


class FirecrawlInstaller(BaseInstaller):
    """Firecrawl - Web scraping and search MCP."""
    
    def check_installed(self) -> tuple[bool, Optional[str]]:
        return self._npx_ready()
    
    def install(self) -> InstallResult:
        self.component.status = InstallStatus.INSTALLING
        
        ready, version = self._npx_ready()
        if not ready:
            return InstallResult(success=False, error="npx not found. Install Node.js first.")
        
        self.component.status = InstallStatus.SUCCESS
        return InstallResult(success=True, version=version or "npx", message="Firecrawl MCP ready (npx-based). Set FIRECRAWL_API_KEY env var.")


class EngramInstaller(BaseInstaller):
    """Engram - Persistent memory MCP."""
    
    def check_installed(self) -> tuple[bool, Optional[str]]:
        result = run_tool("engram", ["--version"], timeout=10)
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
    
    def _install_windows(self) -> InstallResult:
        # Try winget first
        result = run_tool(
            "winget",
            ["install", "--id", "GentlemanProgramming.Engram", "--silent",
             "--accept-source-agreements", "--accept-package-agreements"],
            timeout=300,
        )
        if result and result.returncode == 0:
            return self._post_install()
        
        # Fallback: download binary
        import urllib.request
        url = "https://github.com/Gentleman-Programming/engram/releases/latest/download/engram-windows-amd64.exe"
        dest = Path.home() / ".local" / "bin" / "engram.exe"
        dest.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            import urllib.request
            urllib.request.urlretrieve(url, dest)
            # Add to PATH
            import os
            os.environ["PATH"] = str(dest.parent) + os.pathsep + os.environ.get("PATH", "")
        except Exception as e:
            return InstallResult(success=False, error=f"Download failed: {e}")
        
        return self._post_install()
    
    def _install_macos(self) -> InstallResult:
        # Try Homebrew
        if shutil.which("brew"):
            result = run_tool("brew", ["install", "gentleman-programming/tap/engram"], timeout=300)
            if result and result.returncode == 0:
                return self._post_install()
        
        # Fallback: go install
        if shutil.which("go"):
            result = run_tool(
                "go",
                ["install", "github.com/Gentleman-Programming/engram/v3/cmd/engram@latest"],
                timeout=300,
            )
            if result and result.returncode == 0:
                return self._post_install()
        
        return InstallResult(success=False, error="No installation method available. Install Homebrew or Go.")
    
    def _install_linux(self) -> InstallResult:
        # Try Homebrew on Linux
        if shutil.which("brew"):
            result = run_tool("brew", ["install", "gentleman-programming/tap/engram"], timeout=300)
            if result and result.returncode == 0:
                return self._post_install()
        
        # Fallback: go install
        if shutil.which("go"):
            result = run_tool(
                "go",
                ["install", "github.com/Gentleman-Programming/engram/v3/cmd/engram@latest"],
                timeout=300,
            )
            if result and result.returncode == 0:
                return self._post_install()
        
        return InstallResult(success=False, error="No installation method available. Install Homebrew or Go.")
    
    def _post_install(self) -> InstallResult:
        # Setup Engram for OpenCode
        result = run_tool("engram", ["setup", "opencode"], timeout=60)
        
        if result and result.returncode == 0:
            self.component.status = InstallStatus.SUCCESS
            return InstallResult(success=True, version="latest", message="Engram installed and configured for OpenCode")
        else:
            err = result.stderr if result else "engram not found on PATH"
            return InstallResult(success=False, error=f"Engram setup failed: {err}")


class CodeGraphInstaller(BaseInstaller):
    """CodeGraph - Code intelligence MCP (optional)."""
    
    def check_installed(self) -> tuple[bool, Optional[str]]:
        result = run_tool("codegraph", ["--version"], timeout=10)
        if result and result.returncode == 0:
            return True, result.stdout.strip()
        result = run_tool("codegraph-mcp", ["--version"], timeout=10)
        if result and result.returncode == 0:
            return True, result.stdout.strip()
        return False, None
    
    def install(self) -> InstallResult:
        self.component.status = InstallStatus.INSTALLING
        
        # CodeGraph is installed via Cargo
        if not shutil.which("cargo"):
            return InstallResult(success=False, error="Rust/Cargo not installed. Install from https://rustup.rs/")
        
        result = run_tool("cargo", ["install", "codegraph"], timeout=600)
        
        if result and result.returncode == 0:
            self.component.status = InstallStatus.SUCCESS
            return InstallResult(success=True, version="latest", message="CodeGraph installed via Cargo")
        else:
            err = result.stderr if result else "cargo not found on PATH"
            return InstallResult(success=False, error=f"Cargo install failed: {err}")


class NodeInstaller(BaseInstaller):
    """Node.js / npx - Runtime for npm-based MCPs."""
    
    def check_installed(self) -> tuple[bool, Optional[str]]:
        try:
            result = run_tool("node", ["--version"], timeout=10)
            if not result or result.returncode != 0:
                return False, None
            node_version = result.stdout.strip()
            result = run_tool("npx", ["--version"], timeout=10)
            if result and result.returncode == 0:
                npx_version = result.stdout.strip()
                return True, f"node {node_version}, npx {npx_version}"
        except Exception:
            pass
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
    
    def _install_windows(self) -> InstallResult:
        # Try winget first
        if shutil.which("winget"):
            result = run_tool(
                "winget",
                ["install", "--id", "OpenJS.NodeJS.LTS", "--silent",
                 "--accept-source-agreements", "--accept-package-agreements"],
                timeout=300,
            )
            if result and result.returncode == 0:
                return self._post_install()
        
        # Try Scoop
        if shutil.which("scoop"):
            result = run_tool("scoop", ["install", "nodejs-lts"], timeout=300)
            if result and result.returncode == 0:
                return self._post_install()
        
        # Try Chocolatey
        if shutil.which("choco"):
            result = run_tool("choco", ["install", "nodejs-lts", "-y", "--no-progress"], timeout=300)
            if result and result.returncode == 0:
                return self._post_install()
        
        return InstallResult(success=False, error="No Windows package manager found (winget/scoop/choco)")
    
    def _install_macos(self) -> InstallResult:
        # Homebrew
        if shutil.which("brew"):
            result = run_tool("brew", ["install", "node@20"], timeout=300)
            if result and result.returncode == 0:
                return self._post_install()
        
        return InstallResult(success=False, error="Homebrew not found. Install from https://brew.sh/")
    
    def _install_linux(self) -> InstallResult:
        # Try fnm first (recommended)
        if shutil.which("fnm"):
            result = run_tool("fnm", ["install", "--lts"], timeout=300)
            if result and result.returncode == 0:
                return self._post_install()
        
        # Try package manager
        pm = self._detect_package_manager()
        if pm:
            pkg = "nodejs" if pm in ("apt", "dnf", "pacman") else "nodejs-lts"
            import subprocess
            result = subprocess.run(
                ["sudo", pm, "install", "-y", pkg],
                capture_output=True, text=True, timeout=300
            )
            if result.returncode == 0:
                return self._post_install()
        
        return InstallResult(success=False, error="No installation method available. Install Node.js manually from https://nodejs.org/")
    
    def _detect_package_manager(self) -> str:
        for pm in ["apt", "dnf", "pacman", "zypper", "apk"]:
            if shutil.which(pm):
                return pm
        return "unknown"
    
    def _post_install(self) -> InstallResult:
        result = run_tool("node", ["--version"], timeout=10)
        if result and result.returncode == 0:
            npx_result = run_tool("npx", ["--version"], timeout=10)
            if npx_result and npx_result.returncode == 0:
                self.component.status = InstallStatus.SUCCESS
                return InstallResult(success=True, version=f"node {result.stdout.strip()}, npx {npx_result.stdout.strip()}", message="Node.js installed")
        return InstallResult(success=False, error="Node.js install verification failed")


# Registry of all MCP installers
MCP_INSTALLERS = {
    "node": NodeInstaller,
    "context7": Context7Installer,
    "filesystem": FilesystemInstaller,
    "playwright": PlaywrightInstaller,
    "firecrawl": FirecrawlInstaller,
    "engram": EngramInstaller,
    "codegraph": CodeGraphInstaller,
}


def get_mcp_installer(component_id: str, component: 'InstallableComponent', dry_run: bool = False):
    """Get installer instance for an MCP component."""
    installer_class = MCP_INSTALLERS.get(component_id)
    if not installer_class:
        raise ValueError(f"No installer for MCP: {component_id}")
    return installer_class(component, dry_run)
