"""MCP Server Installers."""

from __future__ import annotations

from typing import Optional
from pathlib import Path

from ..base import BaseInstaller, InstallResult
from ...models import InstallableComponent, InstallStatus, OSType


class Context7Installer(BaseInstaller):
    """Context7 - Up-to-date library documentation MCP."""
    
    def check_installed(self) -> tuple[bool, Optional[str]]:
        # Context7 is an npx-based server, check if package is available
        try:
            import subprocess
            result = subprocess.run(
                ["npx", "-y", "@context7/mcp-server", "--version"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                return True, result.stdout.strip()
        except Exception:
            pass
        return False, None
    
    def install(self) -> InstallResult:
        self.component.status = InstallStatus.INSTALLING
        
        # Context7 is npx-based, no local installation needed
        # Just verify npx is available
        if not shutil.which("npx"):
            return InstallResult(
                success=False,
                error="npx not found. Please install Node.js first."
            )
        
        # Test that the package can be fetched
        import subprocess
        result = subprocess.run(
            ["npx", "-y", "@context7/mcp-server", "--help"],
            capture_output=True, text=True, timeout=60
        )
        
        if result.returncode == 0:
            self.component.status = InstallStatus.SUCCESS
            return InstallResult(success=True, version="latest", message="Context7 MCP ready (npx-based)")
        else:
            return InstallResult(success=False, error=f"Failed to fetch Context7: {result.stderr}")


class FilesystemInstaller(BaseInstaller):
    """Filesystem MCP - Read/write files under a root."""
    
    def check_installed(self) -> tuple[bool, Optional[str]]:
        try:
            import subprocess
            result = subprocess.run(
                ["npx", "-y", "@modelcontextprotocol/server-filesystem", "--version"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                return True, result.stdout.strip()
        except Exception:
            pass
        return False, None
    
    def install(self) -> InstallResult:
        self.component.status = InstallStatus.INSTALLING
        
        if not shutil.which("npx"):
            return InstallResult(
                success=False,
                error="npx not found. Please install Node.js first."
            )
        
        import subprocess
        result = subprocess.run(
            ["npx", "-y", "@modelcontextprotocol/server-filesystem", "--help"],
            capture_output=True, text=True, timeout=60
        )
        
        if result.returncode == 0:
            self.component.status = InstallStatus.SUCCESS
            return InstallResult(success=True, version="latest", message="Filesystem MCP ready (npx-based)")
        else:
            return InstallResult(success=False, error=f"Failed to fetch Filesystem MCP: {result.stderr}")


class PlaywrightInstaller(BaseInstaller):
    """Playwright MCP - Browser automation."""
    
    def check_installed(self) -> tuple[bool, Optional[str]]:
        try:
            import subprocess
            result = subprocess.run(
                ["npx", "-y", "@playwright/mcp", "--version"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                return True, result.stdout.strip()
        except Exception:
            pass
        return False, None
    
    def install(self) -> InstallResult:
        self.component.status = InstallStatus.INSTALLING
        
        if not shutil.which("npx"):
            return InstallResult(success=False, error="npx not found. Install Node.js first.")
        
        # Install Playwright MCP package
        import subprocess
        result = subprocess.run(
            ["npx", "-y", "@playwright/mcp", "--help"],
            capture_output=True, text=True, timeout=60
        )
        
        if result.returncode != 0:
            return InstallResult(success=False, error=f"Failed to fetch Playwright MCP: {result.stderr}")
        
        # Also install Playwright browsers
        self.component.status = InstallStatus.CONFIGURING
        browser_result = subprocess.run(
            ["npx", "playwright", "install", "chromium"],
            capture_output=True, text=True, timeout=300
        )
        
        if browser_result.returncode != 0:
            return InstallResult(success=False, error=f"Failed to install browsers: {browser_result.stderr}")
        
        self.component.status = InstallStatus.SUCCESS
        return InstallResult(success=True, version="latest", message="Playwright MCP + Chromium installed")


class FirecrawlInstaller(BaseInstaller):
    """Firecrawl - Web scraping and search MCP."""
    
    def check_installed(self) -> tuple[bool, Optional[str]]:
        try:
            import subprocess
            result = subprocess.run(
                ["npx", "-y", "@firecrawl/mcp", "--version"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                return True, result.stdout.strip()
        except Exception:
            pass
        return False, None
    
    def install(self) -> InstallResult:
        self.component.status = InstallStatus.INSTALLING
        
        if not shutil.which("npx"):
            return InstallResult(success=False, error="npx not found. Install Node.js first.")
        
        import subprocess
        result = subprocess.run(
            ["npx", "-y", "@firecrawl/mcp", "--help"],
            capture_output=True, text=True, timeout=60
        )
        
        if result.returncode == 0:
            self.component.status = InstallStatus.SUCCESS
            return InstallResult(success=True, version="latest", message="Firecrawl MCP ready (npx-based). Set FIRECRAWL_API_KEY env var.")
        else:
            return InstallResult(success=False, error=f"Failed to fetch Firecrawl: {result.stderr}")


class EngramInstaller(BaseInstaller):
    """Engram - Persistent memory MCP."""
    
    def check_installed(self) -> tuple[bool, Optional[str]]:
        import subprocess
        result = subprocess.run(["engram", "--version"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
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
        import subprocess
        
        # Try winget first
        if shutil.which("winget"):
            result = subprocess.run(
                ["winget", "install", "--id", "GentlemanProgramming.Engram", "--silent", 
                 "--accept-source-agreements", "--accept-package-agreements"],
                capture_output=True, text=True, timeout=300
            )
            if result.returncode == 0:
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
            os.environ["PATH"] = str(dest.parent) + os.pathsep + os.environ.get("PATH", "")
        except Exception as e:
            return InstallResult(success=False, error=f"Download failed: {e}")
        
        return self._post_install()
    
    def _install_macos(self) -> InstallResult:
        import subprocess
        # Try Homebrew
        if shutil.which("brew"):
            result = subprocess.run(
                ["brew", "install", "gentleman-programming/tap/engram"],
                capture_output=True, text=True, timeout=300
            )
            if result.returncode == 0:
                return self._post_install()
        
        # Fallback: go install
        if shutil.which("go"):
            result = subprocess.run(
                ["go", "install", "github.com/Gentleman-Programming/engram/v3/cmd/engram@latest"],
                capture_output=True, text=True, timeout=300
            )
            if result.returncode == 0:
                return self._post_install()
        
        return InstallResult(success=False, error="No installation method available. Install Homebrew or Go.")
    
    def _install_linux(self) -> InstallResult:
        import subprocess
        
        # Try Homebrew on Linux
        if shutil.which("brew"):
            result = subprocess.run(
                ["brew", "install", "gentleman-programming/tap/engram"],
                capture_output=True, text=True, timeout=300
            )
            if result.returncode == 0:
                return self._post_install()
        
        # Fallback: go install
        if shutil.which("go"):
            result = subprocess.run(
                ["go", "install", "github.com/Gentleman-Programming/engram/v3/cmd/engram@latest"],
                capture_output=True, text=True, timeout=300
            )
            if result.returncode == 0:
                return self._post_install()
        
        return InstallResult(success=False, error="No installation method available. Install Homebrew or Go.")
    
    def _post_install(self) -> InstallResult:
        # Setup Engram for OpenCode
        import subprocess
        result = subprocess.run(
            ["engram", "setup", "opencode"],
            capture_output=True, text=True, timeout=60
        )
        
        if result.returncode == 0:
            self.component.status = InstallStatus.SUCCESS
            return InstallResult(success=True, version="latest", message="Engram installed and configured for OpenCode")
        else:
            return InstallResult(success=False, error=f"Engram setup failed: {result.stderr}")


class CodeGraphInstaller(BaseInstaller):
    """CodeGraph - Code intelligence MCP (optional)."""
    
    def check_installed(self) -> tuple[bool, Optional[str]]:
        import subprocess
        result = subprocess.run(["codegraph", "--version"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return True, result.stdout.strip()
        result = subprocess.run(["codegraph-mcp", "--version"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, None
    
    def install(self) -> InstallResult:
        self.component.status = InstallStatus.INSTALLING
        
        # CodeGraph is installed via Cargo
        import subprocess
        if not shutil.which("cargo"):
            return InstallResult(success=False, error="Rust/Cargo not installed. Install from https://rustup.rs/")
        
        result = subprocess.run(
            ["cargo", "install", "codegraph"],
            capture_output=True, text=True, timeout=600
        )
        
        if result.returncode == 0:
            self.component.status = InstallStatus.SUCCESS
            return InstallResult(success=True, version="latest", message="CodeGraph installed via Cargo")
        else:
            return InstallResult(success=False, error=f"Cargo install failed: {result.stderr}")


class NodeInstaller(BaseInstaller):
    """Node.js / npx - Runtime for npm-based MCPs."""
    
    def check_installed(self) -> tuple[bool, Optional[str]]:
        import subprocess
        try:
            result = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                node_version = result.stdout.strip()
            else:
                return False, None
            result = subprocess.run(["npx", "--version"], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
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
        import subprocess
        
        # Try winget first
        if shutil.which("winget"):
            result = subprocess.run(
                ["winget", "install", "--id", "OpenJS.NodeJS.LTS", "--silent",
                 "--accept-source-agreements", "--accept-package-agreements"],
                capture_output=True, text=True, timeout=300
            )
            if result.returncode == 0:
                return self._post_install()
        
        # Try Scoop
        if shutil.which("scoop"):
            result = subprocess.run(
                ["scoop", "install", "nodejs-lts"],
                capture_output=True, text=True, timeout=300
            )
            if result.returncode == 0:
                return self._post_install()
        
        # Try Chocolatey
        if shutil.which("choco"):
            result = subprocess.run(
                ["choco", "install", "nodejs-lts", "-y", "--no-progress"],
                capture_output=True, text=True, timeout=300
            )
            if result.returncode == 0:
                return self._post_install()
        
        return InstallResult(success=False, error="No Windows package manager found (winget/scoop/choco)")
    
    def _install_macos(self) -> InstallResult:
        import subprocess
        
        # Homebrew
        if shutil.which("brew"):
            result = subprocess.run(
                ["brew", "install", "node@20"],
                capture_output=True, text=True, timeout=300
            )
            if result.returncode == 0:
                return self._post_install()
        
        return InstallResult(success=False, error="Homebrew not found. Install from https://brew.sh/")
    
    def _install_linux(self) -> InstallResult:
        import subprocess
        
        # Try fnm first (recommended)
        if shutil.which("fnm"):
            result = subprocess.run(
                ["fnm", "install", "--lts"],
                capture_output=True, text=True, timeout=300
            )
            if result.returncode == 0:
                return self._post_install()
        
        # Try package manager
        pm = self._detect_package_manager()
        if pm:
            pkg = "nodejs" if pm in ("apt", "dnf", "pacman") else "nodejs-lts"
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
        import subprocess
        result = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            npx_result = subprocess.run(["npx", "--version"], capture_output=True, text=True, timeout=10)
            if npx_result.returncode == 0:
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