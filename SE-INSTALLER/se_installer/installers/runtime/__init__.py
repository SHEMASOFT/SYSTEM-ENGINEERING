"""Runtime Adapters Installers."""

from __future__ import annotations

from typing import Optional
from pathlib import Path
import json
import os
import platform
import subprocess
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
        # OpenCode v2 does not ship through Windows package managers. Use the
        # supported npm package first, then the standalone binary, which needs
        # no Node.js installation.
        errors: list[str] = []

        npm_result = self._install_with_npm()
        if npm_result is not None:
            if npm_result.success:
                return npm_result
            errors.append(npm_result.error or "npm install failed")

        binary_result = self._install_windows_binary()
        if binary_result.success:
            return binary_result
        errors.append(binary_result.error or "standalone binary install failed")

        return InstallResult(
            success=False,
            error=(
                "OpenCode v2 could not be installed. "
                + " ".join(errors)
                + " Install Node.js/npm or download the Windows binary from "
                "https://opencode.ai/v2/docs."
            ),
        )

    def _install_windows_binary(self) -> 'InstallResult':
        if self.dry_run:
            return InstallResult(
                success=True,
                message="[dry-run] would install the OpenCode v2 Windows binary",
            )

        machine = (platform.machine() or "").lower()
        if machine in {"arm64", "aarch64"}:
            asset = "opencode-windows-arm64.zip"
        else:
            asset = "opencode-windows-x64.zip"
        url = f"https://opencode.ai/update/api/latest/cli/opencode/{asset}"
        install_dir = self._windows_opencode_dir()
        archive = Path(tempfile.gettempdir()) / asset

        try:
            self._download_windows_binary(url, archive)
            self.extract_archive(archive, install_dir)
        except (RuntimeError, OSError) as exc:
            return InstallResult(
                success=False,
                error=f"standalone binary install failed: {exc}",
            )
        finally:
            try:
                archive.unlink(missing_ok=True)
            except OSError:
                pass

        exe = install_dir / "opencode.exe"
        if not exe.exists():
            matches = list(install_dir.rglob("opencode.exe"))
            if not matches:
                return InstallResult(
                    success=False,
                    error="standalone binary archive did not contain opencode.exe",
                )
            exe = matches[0]

        bin_dir = exe.parent
        self.ensure_in_path(bin_dir)
        WindowsInstallerMixin.add_to_user_path(str(bin_dir))
        return self._post_install()

    @staticmethod
    def _windows_opencode_dir() -> Path:
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "Programs" / "opencode"
        return Path.home() / ".opencode" / "bin"

    @staticmethod
    def _download_windows_binary(url: str, dest: Path) -> None:
        """Download the standalone ZIP with a user agent.

        The update endpoint rejects Python's default ``Python-urllib`` agent
        with HTTP 403, so use an explicit UA.
        """
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"[DOWNLOAD] {url}", flush=True)
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "SE-Installer/1.0 "
                    "(+https://github.com/SHEMASOFT/SYSTEM-ENGINEERING)"
                )
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                with dest.open("wb") as handle:
                    shutil.copyfileobj(response, handle)
        except Exception as exc:
            try:
                dest.unlink(missing_ok=True)
            except OSError:
                pass
            raise RuntimeError(f"Download failed: {exc}") from exc

    def _install_macos(self) -> 'InstallResult':
        # OpenCode v2 uses the anomalyco tap, not the old sst tap.
        brew_result: Optional['InstallResult'] = None
        if shutil.which("brew"):
            result = run_tool("brew", ["install", "anomalyco/tap/opencode-v2"], timeout=300)
            if result and result.returncode == 0:
                brew_result = self._post_install()
                if brew_result.success:
                    return brew_result

        npm_result = self._install_with_npm()
        if npm_result is not None:
            return npm_result
        if brew_result is not None:
            return brew_result

        return InstallResult(
            success=False,
            error=(
                "OpenCode v2 could not be installed with Homebrew, and npm is not "
                "available. Install Homebrew (https://brew.sh/) or Node.js."
            ),
        )

    def _install_linux(self) -> 'InstallResult':
        # OpenCode v2 has its own install script; /install still points at v1.
        script_result: Optional['InstallResult'] = None
        try:
            result = subprocess.run(
                ["bash", "-c", "curl -fsSL https://opencode.ai/v2/install | bash"],
                capture_output=True, text=True, timeout=300
            )
            if result.returncode == 0:
                # The script updates shell profiles, not the current process PATH.
                self.ensure_in_path(Path.home() / ".opencode" / "bin")
                script_result = self._post_install()
                if script_result.success:
                    return script_result
        except (OSError, subprocess.TimeoutExpired):
            # Missing bash/curl or a hung download: npm may still work.
            pass

        npm_result = self._install_with_npm()
        if npm_result is not None:
            return npm_result
        if script_result is not None:
            return script_result

        return InstallResult(
            success=False,
            error=(
                "OpenCode v2 install script failed and npm is not available. "
                "Install Node.js (which provides npm) or install OpenCode manually "
                "from https://opencode.ai/v2/docs."
            ),
        )

    def _install_with_npm(self) -> Optional['InstallResult']:
        """Install OpenCode v2 from its published npm package.

        ``@opencode/cli`` is the v2 package; the older ``opencode-ai`` package
        installs v1. Returns ``None`` when npm itself is not on PATH, so callers
        can distinguish "not attempted" from "attempted and failed".
        """
        if not shutil.which("npm"):
            return None

        result = run_tool("npm", ["install", "-g", "@opencode/cli"], timeout=300)
        if result and result.returncode == 0:
            return self._post_install()

        detail = ""
        if result:
            output = (result.stderr or result.stdout or "").strip()
            if output:
                detail = output.splitlines()[-1]
        suffix = f": {detail}" if detail else ""
        return InstallResult(
            success=False,
            error=f"npm install -g @opencode/cli failed{suffix}",
        )
    
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
