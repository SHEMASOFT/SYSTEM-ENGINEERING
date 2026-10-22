"""MCP Server Installers."""

from __future__ import annotations

from typing import Optional
from pathlib import Path
import json
import os
import platform
import shutil
import tempfile
import urllib.request

from ..base import (
    BaseInstaller,
    InstallResult,
    WindowsInstallerMixin,
    refresh_process_path,
    run_tool,
)
from ...models import InstallableComponent, InstallStatus, OSType

#: Official Node.js distribution index. The first entry with a truthy ``lts``
#: field is the current LTS line; files are listed under ``win-x64``/``win-arm64``.
NODE_DIST_INDEX_URL = "https://nodejs.org/dist/index.json"
NODE_DIST_BASE = "https://nodejs.org/dist"


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


class SequentialThinkingInstaller(BaseInstaller):
    """Sequential Thinking MCP - structured, revisable multi-step reasoning.

    Like Context7/Filesystem/Firecrawl this is an npx-based reference server:
    it is fetched on demand and has no local install artifact, so readiness is
    exactly "is npx available".
    """

    def check_installed(self) -> tuple[bool, Optional[str]]:
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
        return InstallResult(
            success=True,
            version=version or "npx",
            message="Sequential Thinking MCP ready (npx-based)",
        )


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
        
        # No package manager (or all of them failed): use the official signed
        # distribution instead. This is what makes the bootstrap work on a
        # clean Windows image that only has PowerShell and Python.
        print("[INFO] No Windows package manager installed Node.js; using the official ZIP ...")
        return self._install_windows_zip()

    def _http_text(self, url: str) -> str:
        request = urllib.request.Request(url, headers={"User-Agent": "se-installer/1.0"})
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8")

    def _node_lts_asset(self) -> tuple[str, str]:
        """Return ``(version, asset_name)`` for the current LTS Windows build."""
        releases = json.loads(self._http_text(NODE_DIST_INDEX_URL))
        machine = platform.machine().lower()
        architectures = ("arm64", "x64") if machine in ("arm64", "aarch64") else ("x64",)
        for release in releases:
            if not release.get("lts"):
                continue
            version = release.get("version")
            if not version:
                continue
            files = set(release.get("files") or [])
            for arch in architectures:
                if f"win-{arch}-zip" in files:
                    return version, f"node-{version}-win-{arch}.zip"
        raise RuntimeError("no Node.js LTS Windows build found in the distribution index")

    @staticmethod
    def _sha256_for(checksums: str, asset: str) -> str:
        for line in checksums.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1].lstrip("*") == asset:
                return parts[0]
        raise RuntimeError(f"no SHA256 entry for {asset}")

    def _install_windows_zip(self) -> InstallResult:
        """Install Node.js from nodejs.org without winget/scoop/choco."""
        if self.dry_run:
            return InstallResult(
                success=True,
                message="[dry-run] would install Node.js from the official ZIP",
            )
        try:
            version, asset = self._node_lts_asset()
            checksums = self._http_text(f"{NODE_DIST_BASE}/{version}/SHASUMS256.txt")
            digest = self._sha256_for(checksums, asset)
            with tempfile.TemporaryDirectory(prefix="se-node-") as tmp:
                archive = Path(tmp) / asset
                self.download_file(
                    f"{NODE_DIST_BASE}/{version}/{asset}",
                    archive,
                    expected_sha256=digest,
                )
                extracted = Path(tmp) / "extract"
                self.extract_archive(archive, extracted)
                node_exe = next(extracted.rglob("node.exe"), None)
                if node_exe is None:
                    raise RuntimeError("archive did not contain node.exe")
                local_appdata = os.environ.get("LOCALAPPDATA")
                base = Path(local_appdata) if local_appdata else Path.home() / "AppData" / "Local"
                install_dir = base / "Programs" / "node"
                shutil.copytree(node_exe.parent, install_dir, dirs_exist_ok=True)
        except Exception as exc:  # noqa: BLE001 - reported through InstallResult
            return InstallResult(
                success=False,
                error=f"standalone Node.js install failed: {exc}",
            )

        self.ensure_in_path(install_dir)
        WindowsInstallerMixin.add_to_user_path(str(install_dir))
        return self._post_install()
    
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
        refresh_process_path()
        result = run_tool("node", ["--version"], timeout=10)
        if result and result.returncode == 0:
            npx_result = run_tool("npx", ["--version"], timeout=10)
            if npx_result and npx_result.returncode == 0:
                self.component.status = InstallStatus.SUCCESS
                return InstallResult(success=True, version=f"node {result.stdout.strip()}, npx {npx_result.stdout.strip()}", message="Node.js installed")
        return InstallResult(success=False, error="Node.js install verification failed")


class RustInstaller(BaseInstaller):
    """Rust / Cargo toolchain - required by CodeGraph (installed via rustup).

    Rust is a toolchain dependency, not an MCP server, but it lives in this
    registry for the same reason ``node`` does: the orchestrator dispatches
    MCP-typed components here. Without this installer, selecting ``rust`` (or
    ``install --all``) failed with "No installer for MCP: rust".
    """

    def check_installed(self) -> tuple[bool, Optional[str]]:
        result = run_tool("cargo", ["--version"], timeout=10)
        if result and result.returncode == 0:
            return True, result.stdout.strip()
        return False, None

    def install(self) -> InstallResult:
        self.component.status = InstallStatus.INSTALLING

        installed, version = self.check_installed()
        if installed:
            self.component.status = InstallStatus.SUCCESS
            return InstallResult(
                success=True, version=version, message="Rust toolchain already present"
            )

        if self.dry_run:
            return InstallResult(success=True, message="[dry-run] would install Rust via rustup")

        if self._detect_os() == OSType.WINDOWS:
            return self._install_windows()
        return self._install_unix()

    def _install_windows(self) -> InstallResult:
        if shutil.which("winget"):
            result = run_tool(
                "winget",
                ["install", "--id", "Rustlang.Rustup", "--silent",
                 "--accept-source-agreements", "--accept-package-agreements"],
                timeout=600,
            )
            if result and result.returncode == 0:
                return self._post_install()

        if shutil.which("scoop"):
            result = run_tool("scoop", ["install", "rustup"], timeout=600)
            if result and result.returncode == 0:
                return self._post_install()

        return InstallResult(
            success=False,
            error="No Windows package manager found (winget/scoop). Install Rust from https://rustup.rs/",
        )

    def _install_unix(self) -> InstallResult:
        if shutil.which("rustup"):
            result = run_tool(
                "rustup", ["toolchain", "install", "stable", "--profile", "minimal"], timeout=600
            )
            if result and result.returncode == 0:
                return self._post_install()

        if shutil.which("bash"):
            result = run_tool(
                "bash",
                ["-c",
                 "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs "
                 "| sh -s -- -y --profile minimal"],
                timeout=600,
            )
            if result and result.returncode == 0:
                return self._post_install()

        return InstallResult(
            success=False, error="rustup install failed. Install Rust from https://rustup.rs/"
        )

    def _post_install(self) -> InstallResult:
        # rustup installs into ~/.cargo/bin, which is not on this process's PATH yet.
        self.ensure_in_path(Path.home() / ".cargo" / "bin")
        installed, version = self.check_installed()
        if installed:
            self.component.status = InstallStatus.SUCCESS
            return InstallResult(
                success=True, version=version, message="Rust toolchain installed via rustup"
            )
        return InstallResult(
            success=False,
            error=(
                "Rust installed but `cargo --version` failed; open a new shell so "
                "~/.cargo/bin is on PATH"
            ),
        )


# Registry of all MCP installers
MCP_INSTALLERS = {
    "node": NodeInstaller,
    "context7": Context7Installer,
    "filesystem": FilesystemInstaller,
    "playwright": PlaywrightInstaller,
    "firecrawl": FirecrawlInstaller,
    "sequential-thinking": SequentialThinkingInstaller,
    "codegraph": CodeGraphInstaller,
    "rust": RustInstaller,
}


def get_mcp_installer(component_id: str, component: 'InstallableComponent', dry_run: bool = False):
    """Get installer instance for an MCP component."""
    installer_class = MCP_INSTALLERS.get(component_id)
    if not installer_class:
        raise ValueError(f"No installer for MCP: {component_id}")
    return installer_class(component, dry_run)
