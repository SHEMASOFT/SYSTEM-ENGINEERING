"""Base installer classes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional
from pathlib import Path
import subprocess
import shutil
import os
import sys

from ..models import InstallableComponent, InstallStatus, OSType


@dataclass
class InstallResult:
    success: bool
    version: Optional[str] = None
    message: str = ""
    error: Optional[str] = None


#: Directories that Windows package managers populate after the current process
#: started. The registry PATH is the primary source; these cover installers that
#: only create a per-user shim/link.
_WINDOWS_PATH_HINTS = (
    r"%ProgramFiles%\nodejs",
    r"%APPDATA%\npm",
    r"%LOCALAPPDATA%\Programs\node",
    r"%LOCALAPPDATA%\Microsoft\WinGet\Links",
    r"C:\ProgramData\chocolatey\bin",
    r"%USERPROFILE%\scoop\shims",
)


def _merge_path_entries(entries: list[str], *, case_insensitive: bool = False) -> str:
    """Join PATH fragments, dropping empty and duplicate entries in order."""
    merged: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        for part in str(entry).split(os.pathsep):
            part = part.strip()
            if not part:
                continue
            key = part.lower() if case_insensitive else part
            if key in seen:
                continue
            seen.add(key)
            merged.append(part)
    return os.pathsep.join(merged)


def _windows_registry_path_entries() -> list[str]:
    """Read the machine and user PATH values Windows installers update."""
    try:
        import winreg
    except ImportError:  # pragma: no cover - only reachable on non-Windows
        return []
    entries: list[str] = []
    locations = (
        (
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
        ),
        (winreg.HKEY_CURRENT_USER, "Environment"),
    )
    for root, subkey in locations:
        try:
            with winreg.OpenKey(root, subkey) as key:
                value, _ = winreg.QueryValueEx(key, "Path")
        except OSError:
            continue
        if value:
            entries.append(str(value))
    return entries


def refresh_process_path() -> None:
    """Refresh ``PATH`` after a package manager installs a tool.

    ``winget``/``choco``/``scoop`` update the machine or user PATH, but the
    running Python process keeps the environment it started with. Without this
    refresh, ``_post_install`` cannot find the tool it just installed and the
    component is reported as failed. On POSIX the process normally already has
    the right PATH; the function still deduplicates and preserves it.
    """
    is_windows = sys.platform.startswith("win")
    entries = [os.environ.get("PATH", "")]
    if is_windows:
        entries.extend(_windows_registry_path_entries())
        for hint in _WINDOWS_PATH_HINTS:
            expanded = os.path.expandvars(hint)
            if os.path.isdir(expanded):
                entries.append(expanded)
        entries = [os.path.expandvars(entry) for entry in entries]
    merged = _merge_path_entries(entries, case_insensitive=is_windows)
    if merged:
        os.environ["PATH"] = merged


def run_tool(
    name: str,
    args: Optional[list[str]] = None,
    timeout: int = 30,
    **kwargs: Any,
) -> Optional[subprocess.CompletedProcess]:
    """Run a PATH tool, resolving Windows ``.cmd``/``.bat`` shims.

    Console tools on Windows (``opencode``, ``npx``, ``npm``, ``scoop`` ...) are
    ``.cmd``/``.bat`` shims. ``subprocess`` uses ``CreateProcess``, which only
    appends ``.exe``, so launching them by bare name fails with ``WinError 2``.
    ``shutil.which`` honours ``PATHEXT``, so we resolve the executable first and
    hand the absolute path to ``subprocess``.

    Returns the ``CompletedProcess``, or ``None`` when the tool is not on PATH
    (callers must handle ``None`` instead of assuming a result).

    Never raises. A tool that is on PATH but unusable is reported as a failed
    run -- a non-zero ``returncode`` and the reason in ``stderr`` -- because
    every caller branches on the result and ``check_installed`` is documented to
    never raise. Two ways that happens in practice: the tool outlives
    ``timeout`` (on Windows the rustup shims ``cargo``/``rustup`` run their own
    update on first use, and CI saw ``cargo --version`` exceed 10s), or the
    resolved path cannot be launched at all (``OSError`` / ``WinError 193`` on a
    broken shim). ``124`` is the conventional exit code for a timeout.
    """
    exe = shutil.which(name)
    if not exe:
        return None
    argv = [exe, *(args or [])]
    try:
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            **kwargs,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(argv, 124, "", f"timed out after {timeout}s")
    except OSError as exc:
        return subprocess.CompletedProcess(argv, 1, "", f"could not run {exe}: {exc}")


class BaseInstaller(ABC):
    """Abstract base class for component installers."""
    
    def __init__(self, component: 'InstallableComponent', dry_run: bool = False):
        self.component = component
        self.dry_run = dry_run
        self.os_type = self._detect_os()
    
    @staticmethod
    def _detect_os() -> OSType:
        import sys
        if sys.platform.startswith("win"):
            return OSType.WINDOWS
        elif sys.platform == "darwin":
            return OSType.MACOS
        else:
            return OSType.LINUX
    
    @abstractmethod
    def check_installed(self) -> tuple[bool, Optional[str]]:
        """Check if component is already installed. Returns (is_installed, version)."""
        pass
    
    @abstractmethod
    def install(self) -> 'InstallResult':
        """Install the component."""
        pass
    
    def _npx_ready(self) -> tuple[bool, Optional[str]]:
        """Readiness probe for npx-based MCP servers.

        These servers are fetched on demand by ``npx``; they have no local
        install artifact, and their CLI probes are inconsistent (some servers
        return non-zero for ``--version``/``--help``, e.g. the filesystem
        server). The meaningful check is therefore that ``npx`` is available.
        """
        result = run_tool("npx", ["--version"], timeout=10)
        if result and result.returncode == 0:
            return True, f"npx {result.stdout.strip()}"
        return False, None
    
    def verify(self) -> tuple[bool, Optional[str]]:
        """Verify installation. Returns (success, version)."""
        if self.component.verification_command:
            try:
                result = subprocess.run(
                    self.component.verification_command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if result.returncode == 0:
                    return True, result.stdout.strip()
            except Exception:
                pass
        return self.check_installed()
    
    def run_command(
        self, 
        command: str | list[str], 
        cwd: Optional[Path] = None,
        env: Optional[dict] = None,
        timeout: int = 300,
        shell: bool = True
    ) -> subprocess.CompletedProcess:
        """Run a command with proper error handling."""
        if self.dry_run:
            print(f"[DRY RUN] Would run: {command}")
            return subprocess.CompletedProcess(command, 0, "", "")
        
        if isinstance(command, list):
            cmd_str = " ".join(command)
        else:
            cmd_str = command
        
        print(f"[RUN] {cmd_str}")
        
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)
        
        try:
            result = subprocess.run(
                command,
                shell=shell,
                cwd=cwd,
                env=merged_env,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            if result.returncode != 0:
                print(f"[ERROR] Command failed ({result.returncode}): {result.stderr}")
            return result
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Command timed out after {timeout}s: {command}")
        except Exception as e:
            raise RuntimeError(f"Failed to run command: {e}")
    
    def download_file(
        self, 
        url: str, 
        dest: Path, 
        expected_sha256: Optional[str] = None,
        progress: bool = True
    ) -> bool:
        """Download a file with optional SHA256 verification."""
        if self.dry_run:
            print(f"[DRY RUN] Would download {url} -> {dest}")
            return True
        
        import hashlib
        import urllib.request
        
        dest.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            if progress:
                print(f"[DOWNLOAD] {url}")
            
            def progress_hook(block_num, block_size, total_size):
                if total_size > 0 and progress:
                    percent = min(100, (block_num * block_size * 100) // total_size)
                    print(f"\r  Progress: {percent}%", end="", flush=True)
            
            urllib.request.urlretrieve(url, dest, reporthook=progress_hook if progress else None)
            if progress:
                print()  # newline
            
            if expected_sha256:
                sha256 = hashlib.sha256()
                with open(dest, "rb") as f:
                    for chunk in iter(lambda: f.read(8192), b""):
                        sha256.update(chunk)
                actual = sha256.hexdigest()
                if actual.lower() != expected_sha256.lower():
                    dest.unlink(missing_ok=True)
                    raise ValueError(f"SHA256 mismatch: expected {expected_sha256}, got {actual}")
            
            return True
        except Exception as e:
            dest.unlink(missing_ok=True)
            raise RuntimeError(f"Download failed: {e}")
    
    def extract_archive(self, archive: Path, dest: Path) -> bool:
        """Extract archive (zip, tar.gz, tar)."""
        if self.dry_run:
            print(f"[DRY RUN] Would extract {archive} -> {dest}")
            return True
        
        import tarfile
        import zipfile
        
        dest.mkdir(parents=True, exist_ok=True)
        
        try:
            if archive.suffix == ".zip":
                with zipfile.ZipFile(archive, 'r') as zf:
                    zf.extractall(dest)
            elif archive.suffix in (".tar", ".gz", ".tgz") or ".tar." in archive.name:
                with tarfile.open(archive, 'r:*') as tf:
                    tf.extractall(dest)
            else:
                raise ValueError(f"Unsupported archive format: {archive.suffix}")
            return True
        except Exception as e:
            raise RuntimeError(f"Extraction failed: {e}")
    
    def ensure_in_path(self, path: Path) -> bool:
        """Add directory to PATH for current session."""
        path_str = str(path.resolve())
        current_path = os.environ.get("PATH", "")
        if path_str not in current_path:
            os.environ["PATH"] = path_str + os.pathsep + current_path
            return True
        return False


class WindowsInstallerMixin:
    """Windows-specific installation helpers."""
    
    @staticmethod
    def run_powershell(script: str, args: str = "") -> subprocess.CompletedProcess:
        """Run PowerShell script."""
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script]
        if args:
            cmd.append(args)
        return subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    
    @staticmethod
    def winget_install(package_id: str, version: Optional[str] = None) -> subprocess.CompletedProcess:
        """Install via winget."""
        cmd = ["winget", "install", "--id", package_id, "--silent", "--accept-source-agreements", "--accept-package-agreements"]
        if version:
            cmd.extend(["--version", version])
        return subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    
    @staticmethod
    def scoop_install(package: str, bucket: Optional[str] = None) -> subprocess.CompletedProcess:
        """Install via Scoop."""
        cmd = ["scoop", "install"]
        if bucket:
            cmd.extend(["--bucket", bucket])
        cmd.append(package)
        return subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    
    @staticmethod
    def choco_install(package: str, version: Optional[str] = None) -> subprocess.CompletedProcess:
        """Install via Chocolatey."""
        cmd = ["choco", "install", package, "-y", "--no-progress"]
        if version:
            cmd.extend(["--version", version])
        return subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    
    @staticmethod
    def add_to_user_path(path: str) -> bool:
        """Add directory to user PATH via registry."""
        import winreg
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ | winreg.KEY_WRITE)
            try:
                current_path, _ = winreg.QueryValueEx(key, "PATH")
            except FileNotFoundError:
                current_path = ""
            
            if path not in current_path.split(";"):
                new_path = current_path + ";" + path if current_path else path
                winreg.SetValueEx(key, "PATH", 0, winreg.REG_EXPAND_SZ, new_path)
                return True
        except Exception:
            pass
        return False


class MacOSInstallerMixin:
    """macOS-specific installation helpers."""
    
    @staticmethod
    def brew_install(formula: str, cask: bool = False) -> subprocess.CompletedProcess:
        cmd = ["brew", "install"]
        if cask:
            cmd.append("--cask")
        cmd.append(formula)
        return subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    
    @staticmethod
    def brew_tap(tap: str) -> subprocess.CompletedProcess:
        return subprocess.run(["brew", "tap", tap], capture_output=True, text=True, timeout=120)


class LinuxInstallerMixin:
    """Linux-specific installation helpers."""
    
    @staticmethod
    def detect_package_manager() -> str:
        """Detect available package manager."""
        for pm in ["apt", "dnf", "pacman", "zypper", "apk"]:
            if shutil.which(pm):
                return pm
        return "unknown"
    
    @staticmethod
    def install_package(package: str) -> subprocess.CompletedProcess:
        pm = LinuxInstallerMixin.detect_package_manager()
        if pm == "apt":
            cmd = ["sudo", "apt", "update", "&&", "sudo", "apt", "install", "-y"]
        elif pm == "dnf":
            cmd = ["sudo", "dnf", "install", "-y"]
        elif pm == "pacman":
            cmd = ["sudo", "pacman", "-S", "--noconfirm"]
        elif pm == "zypper":
            cmd = ["sudo", "zypper", "install", "-y"]
        elif pm == "apk":
            cmd = ["sudo", "apk", "add"]
        else:
            raise RuntimeError("No supported package manager found")
        cmd.append(package)
        return subprocess.run(" ".join(cmd), shell=True, capture_output=True, text=True, timeout=600)