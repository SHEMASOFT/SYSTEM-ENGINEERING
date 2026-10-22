"""Regression tests for the installer defects fixed in `fix/se-installer-defects`.

These lock in behaviour that previously broke silently:

* ``cli.py`` must not regress into duplicated top-level definitions (it once
  contained three copies of every command);
* ``cli.py`` output must stay Latin-1 safe so ``doctor`` does not crash with a
  ``charmap`` ``UnicodeEncodeError`` on Windows consoles;
* every ``InstallStatus`` must render a known icon (no ``[?]``);
* the MCP/runtime installer modules must import ``shutil`` where they use it
  (previously a ``NameError`` killed real installs);
* tools are launched through ``run_tool`` so Windows ``.cmd`` shims resolve;
* a tool that is on PATH but unusable must be reported as a failed probe, never
  raised out of ``check_installed`` (windows CI: ``cargo --version`` timed out);
* Firecrawl must point at the published npm package;
* every selectable component must have a registered installer
  (``sequential-thinking`` and ``rust`` had none, so ``install --all``
  reported them as FAILED).
"""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from se_installer.cli import print_components
from se_installer.installers import base as base_module
from se_installer.installers.base import run_tool
from se_installer.installers.mcp import (
    Context7Installer,
    FilesystemInstaller,
    FirecrawlInstaller,
    PlaywrightInstaller,
    RustInstaller,
    SequentialThinkingInstaller,
)
from se_installer.installers.runtime import OpenCodeInstaller
from se_installer.models import (
    ComponentType,
    InstallationPlan,
    InstallableComponent,
    InstallStatus,
)
from se_installer.orchestrator import InstallerOrchestrator

CLI_PATH = Path(__file__).resolve().parents[1] / "se_installer" / "cli.py"


def _make_component(component_id: str = "x") -> InstallableComponent:
    return InstallableComponent(
        id=component_id,
        name=component_id,
        description="d",
        component_type=ComponentType.MCP,
        category="Cat",
    )


def _make_runtime_component(component_id: str = "opencode") -> InstallableComponent:
    return InstallableComponent(
        id=component_id,
        name=component_id,
        description="d",
        component_type=ComponentType.RUNTIME,
        category="Runtime",
    )


def test_opencode_windows_installs_with_npm(monkeypatch):
    """Windows OpenCode v2 comes from @opencode/cli, not a package manager."""
    from se_installer.installers import runtime as runtime_module

    calls: list[tuple[str, tuple[str, ...]]] = []

    def fake_which(name: str):
        return "/usr/bin/npm" if name == "npm" else None

    def fake_run_tool(name: str, args=None, timeout=30, **kwargs):
        calls.append((name, tuple(args or ())))
        if name == "npm":
            return subprocess.CompletedProcess([name], 0, "", "")
        if name == "opencode":
            return subprocess.CompletedProcess([name], 0, "opencode 2.1.1\n", "")
        raise AssertionError(f"unexpected tool: {name}")

    monkeypatch.setattr(runtime_module.shutil, "which", fake_which)
    monkeypatch.setattr(runtime_module, "run_tool", fake_run_tool)

    result = OpenCodeInstaller(_make_runtime_component())._install_windows()

    assert result.success is True
    assert result.version == "opencode 2.1.1"
    assert [name for name, _ in calls] == ["npm", "opencode"]
    assert ("npm", ("install", "-g", "@opencode/cli")) in calls


def test_opencode_windows_falls_back_to_binary_when_npm_fails(monkeypatch, tmp_path):
    from se_installer.installers import runtime as runtime_module

    calls: list[str] = []
    added_paths: list[str] = []

    def fake_which(name: str):
        return "/usr/bin/npm" if name == "npm" else None

    def fake_run_tool(name: str, args=None, timeout=30, **kwargs):
        calls.append(name)
        if name == "npm":
            return subprocess.CompletedProcess([name], 1, "", "EACCES")
        if name == "opencode":
            return subprocess.CompletedProcess([name], 0, "opencode 2.1.1\n", "")
        raise AssertionError(f"unexpected tool: {name}")

    def fake_extract(archive, dest):
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "opencode.exe").write_text("", encoding="utf-8")
        return True

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(runtime_module.shutil, "which", fake_which)
    monkeypatch.setattr(runtime_module, "run_tool", fake_run_tool)
    monkeypatch.setattr(runtime_module.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(
        runtime_module.WindowsInstallerMixin,
        "add_to_user_path",
        lambda path: added_paths.append(path) or True,
    )

    installer = OpenCodeInstaller(_make_runtime_component())
    installer._download_windows_binary = lambda url, dest: True
    installer.extract_archive = fake_extract
    installer.ensure_in_path = lambda path: added_paths.append(str(path)) or True

    result = installer._install_windows()

    assert result.success is True
    assert calls == ["npm", "opencode"]
    assert str(tmp_path / "Programs" / "opencode") in added_paths


def test_opencode_windows_reports_binary_failure(monkeypatch):
    from se_installer.installers import runtime as runtime_module

    def unexpected(*args, **kwargs):
        raise AssertionError("no installation tool should run")

    monkeypatch.setattr(runtime_module.shutil, "which", lambda name: None)
    monkeypatch.setattr(runtime_module, "run_tool", unexpected)

    installer = OpenCodeInstaller(_make_runtime_component())
    installer._download_windows_binary = lambda *args, **kwargs: (_ for _ in ()).throw(
        RuntimeError("offline")
    )

    result = installer._install_windows()

    assert result.success is False
    assert "standalone binary install failed" in (result.error or "")
    assert "npm" in (result.error or "")


def test_opencode_windows_binary_download_sets_user_agent(monkeypatch, tmp_path):
    from se_installer.installers import runtime as runtime_module

    captured: dict[str, str] = {}

    class _Response:
        def __init__(self):
            self._sent = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size=-1):
            if self._sent:
                return b""
            self._sent = True
            return b"zip-bytes"

    def fake_urlopen(request, timeout=300):
        captured["user_agent"] = request.get_header("User-agent") or ""
        return _Response()

    monkeypatch.setattr(runtime_module.urllib.request, "urlopen", fake_urlopen)

    dest = tmp_path / "opencode.zip"
    OpenCodeInstaller(_make_runtime_component())._download_windows_binary(
        "https://example.invalid/opencode.zip", dest
    )

    assert dest.read_bytes() == b"zip-bytes"
    assert "SE-Installer" in captured["user_agent"]


def test_opencode_macos_uses_v2_brew_formula(monkeypatch):
    from se_installer.installers import runtime as runtime_module

    calls: list[tuple[str, tuple[str, ...]]] = []

    def fake_run_tool(name: str, args=None, timeout=30, **kwargs):
        calls.append((name, tuple(args or ())))
        if name == "brew":
            return subprocess.CompletedProcess([name], 0, "", "")
        if name == "opencode":
            return subprocess.CompletedProcess([name], 0, "opencode 2.1.1\n", "")
        raise AssertionError(f"unexpected tool: {name}")

    monkeypatch.setattr(runtime_module.shutil, "which", lambda name: "/usr/bin/brew")
    monkeypatch.setattr(runtime_module, "run_tool", fake_run_tool)

    result = OpenCodeInstaller(_make_runtime_component())._install_macos()

    assert result.success is True
    assert ("brew", ("install", "anomalyco/tap/opencode-v2")) in calls


def test_opencode_linux_script_adds_install_dir_to_path(monkeypatch):
    from se_installer.installers import runtime as runtime_module

    paths: list[Path] = []

    class _OkScript:
        returncode = 0

    def fake_run_tool(name: str, args=None, timeout=30, **kwargs):
        if name == "opencode":
            return subprocess.CompletedProcess([name], 0, "opencode 2.1.1\n", "")
        raise AssertionError(f"unexpected tool: {name}")

    monkeypatch.setattr(runtime_module, "run_tool", fake_run_tool)
    monkeypatch.setattr(runtime_module.subprocess, "run", lambda *a, **k: _OkScript())

    installer = OpenCodeInstaller(_make_runtime_component())
    installer.ensure_in_path = lambda path: paths.append(path) or True

    result = installer._install_linux()

    assert result.success is True
    assert Path.home() / ".opencode" / "bin" in paths


def test_opencode_linux_falls_back_to_npm_after_script_failure(monkeypatch):
    from se_installer.installers import runtime as runtime_module

    script_calls: list[list[str]] = []
    calls: list[tuple[str, tuple[str, ...]]] = []

    class _FailedScript:
        returncode = 1

    def fake_which(name: str):
        return "/usr/bin/npm" if name == "npm" else None

    def fake_run_tool(name: str, args=None, timeout=30, **kwargs):
        calls.append((name, tuple(args or ())))
        if name == "npm":
            return subprocess.CompletedProcess([name], 0, "", "")
        if name == "opencode":
            return subprocess.CompletedProcess([name], 0, "opencode 2.1.1\n", "")
        raise AssertionError(f"unexpected tool: {name}")

    def fake_subprocess_run(args, **kwargs):
        script_calls.append(args)
        return _FailedScript()

    monkeypatch.setattr(runtime_module.shutil, "which", fake_which)
    monkeypatch.setattr(runtime_module, "run_tool", fake_run_tool)
    monkeypatch.setattr(runtime_module.subprocess, "run", fake_subprocess_run)

    result = OpenCodeInstaller(_make_runtime_component())._install_linux()

    assert result.success is True
    assert result.version == "opencode 2.1.1"
    assert "https://opencode.ai/v2/install" in script_calls[0][-1]
    assert ("npm", ("install", "-g", "@opencode/cli")) in calls


def test_cli_has_no_duplicate_top_level_definitions():
    tree = ast.parse(CLI_PATH.read_text(encoding="utf-8"))
    names = [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    assert duplicates == [], f"duplicate top-level definitions in cli.py: {duplicates}"


def test_cli_source_is_latin1_safe():
    """No character above U+00FF, so the cp1252 console cannot break output."""
    src = CLI_PATH.read_text(encoding="utf-8")
    offenders = sorted({ch for ch in src if ord(ch) > 0xFF})
    assert offenders == [], (
        "cli.py contains characters that crash a cp1252 console: "
        + ", ".join(hex(ord(c)) for c in offenders)
    )


def test_print_components_renders_every_status_icon(capsys):
    component = _make_component()
    for status in InstallStatus:
        component.status = status
        component.installed_version = None
        print_components([component], show_status=True)
        out = capsys.readouterr().out
        assert "[?]" not in out, f"status '{status.value}' rendered as [?]"


def test_installer_modules_import_shutil():
    from se_installer.installers import mcp as mcp_module
    from se_installer.installers import runtime as runtime_module

    assert hasattr(mcp_module, "shutil"), "installers/mcp/__init__.py uses shutil without importing it"
    assert hasattr(runtime_module, "shutil")


def test_run_tool_returns_none_for_missing_tool():
    assert run_tool("definitely-not-a-real-tool-xyz", ["--version"]) is None


@pytest.mark.skipif(shutil.which("npx") is None, reason="npx not available")
def test_run_tool_resolves_path_tool_with_extension():
    result = run_tool("npx", ["--version"], timeout=30)
    assert result is not None
    assert result.returncode == 0


def _hang(*args, **kwargs):
    """Stand in for ``subprocess.run`` on a tool that never answers."""
    raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout", 10))


def test_run_tool_reports_a_timeout_instead_of_raising(monkeypatch):
    """Windows CI has rustup installed, so ``cargo`` resolves to a shim and
    ``cargo --version`` can outlive the 10s probe budget. The run then raised
    ``subprocess.TimeoutExpired`` out of ``RustInstaller.check_installed()``,
    whose contract (asserted below) is that it never raises."""
    exe = r"C:\Users\runneradmin\.cargo\bin\cargo.EXE"
    monkeypatch.setattr(base_module.shutil, "which", lambda name: exe)
    monkeypatch.setattr(base_module.subprocess, "run", _hang)

    result = run_tool("cargo", ["--version"], timeout=10)

    assert result is not None
    assert result.returncode != 0
    assert "timed out" in result.stderr.lower()


def test_run_tool_reports_an_unlaunchable_tool_instead_of_raising(monkeypatch):
    """``shutil.which`` resolves a path that the OS then refuses to launch
    (``WinError 193`` on a broken shim, ``WinError 2`` on a dangling one)."""

    def refuse(*args, **kwargs):
        raise OSError(193, "%1 is not a valid Win32 application")

    monkeypatch.setattr(base_module.shutil, "which", lambda name: r"C:\fake\tool.EXE")
    monkeypatch.setattr(base_module.subprocess, "run", refuse)

    result = run_tool("tool", ["--version"], timeout=10)

    assert result is not None
    assert result.returncode != 0
    assert result.stderr


def test_rust_check_installed_is_false_when_cargo_hangs(monkeypatch):
    """The exact windows-latest failure: cargo present but timing out."""
    monkeypatch.setattr(
        base_module.shutil, "which", lambda name: r"C:\Users\runneradmin\.cargo\bin\cargo.EXE"
    )
    monkeypatch.setattr(base_module.subprocess, "run", _hang)

    installed, version = RustInstaller(_make_component("rust")).check_installed()

    assert installed is False
    assert version is None


@pytest.mark.parametrize(
    "installer_cls",
    [
        Context7Installer,
        FilesystemInstaller,
        PlaywrightInstaller,
        FirecrawlInstaller,
        SequentialThinkingInstaller,
    ],
)
def test_npx_based_check_installed_never_raises(installer_cls):
    installed, version = installer_cls(_make_component()).check_installed()
    assert isinstance(installed, bool)
    assert version is None or isinstance(version, str)


@pytest.mark.parametrize(
    "installer_cls",
    [Context7Installer, FilesystemInstaller, FirecrawlInstaller, SequentialThinkingInstaller],
)
def test_npx_based_install_never_raises(installer_cls):
    """Real installs used to raise ``NameError: name 'shutil' is not defined``."""
    result = installer_cls(_make_component()).install()
    if shutil.which("npx"):
        assert result.success is True
    else:
        assert result.success is False


def test_firecrawl_uses_published_npm_package():
    from se_installer.components import get_all_components

    firecrawl = next(c for c in get_all_components() if c.id == "firecrawl")
    assert "firecrawl-mcp" in firecrawl.verification_command
    assert "@firecrawl/" not in firecrawl.verification_command


def test_firecrawl_registry_entry_uses_published_package():
    from se_installer.mcp_registry import get_mcp_registry

    server = get_mcp_registry().get_mcp("firecrawl")
    assert server is not None
    assert "firecrawl-mcp" in server.args
    assert all("@firecrawl/" not in arg for arg in server.args)
    assert "@firecrawl/" not in server.verification_command


def test_rust_installer_check_installed_never_raises():
    installed, version = RustInstaller(_make_component("rust")).check_installed()
    assert isinstance(installed, bool)
    assert version is None or isinstance(version, str)


def test_rust_installer_dry_run_never_shells_out(capsys):
    """A dry-run must plan without invoking rustup/winget/curl."""
    installer = RustInstaller(_make_component("rust"), dry_run=True)
    result = installer.install()
    assert result.success is True
    assert "[RUN]" not in capsys.readouterr().out


def test_orchestrator_fails_cleanly_when_no_installer_is_registered():
    """A selectable component with no installer must FAIL with a readable
    message, not raise an unhandled ``ValueError``."""
    orphan = InstallableComponent(
        id="orphan", name="Orphan", description="d",
        component_type=ComponentType.MCP, install_method="auto",
    )
    plan = InstallationPlan(components=[orphan])
    orchestrator = InstallerOrchestrator(plan, dry_run=False)
    orchestrator.prepare_plan(["orphan"])

    result = orchestrator.run_installation()

    assert result is False
    assert orphan.status == InstallStatus.FAILED
    assert (orphan.error_message or "").startswith(
        "No installer registered for component 'orphan'"
    )


INSTALLER_ROOT = Path(__file__).resolve().parents[1]


def test_merge_path_entries_deduplicates_in_order():
    from se_installer.installers.base import _merge_path_entries

    sep = os.pathsep
    merged = _merge_path_entries([sep.join(["alpha", "beta"]), sep.join(["beta", "gamma"])])
    assert merged.split(sep) == ["alpha", "beta", "gamma"]


def test_opencode_post_install_refreshes_path(monkeypatch):
    """A package manager updates PATH, but the running process does not.

    ``_post_install`` must refresh before probing, otherwise a successful
    winget/choco/scoop install is reported as failed.
    """
    from se_installer.installers import runtime as runtime_module

    calls: list[bool] = []

    class _Result:
        returncode = 0
        stdout = "1.2.3"

    monkeypatch.setattr(runtime_module, "refresh_process_path", lambda: calls.append(True))
    monkeypatch.setattr(runtime_module, "run_tool", lambda *args, **kwargs: _Result())

    component = InstallableComponent(
        id="opencode",
        name="OpenCode",
        description="d",
        component_type=ComponentType.RUNTIME,
        category="Runtime",
    )
    result = runtime_module.OpenCodeInstaller(component)._post_install()

    assert result.success is True
    assert calls == [True]


def test_bootstrap_ps1_forwards_positional_arguments():
    """`[CmdletBinding()]` rejects unbound positional arguments, so the Windows
    bootstrap must declare a remaining-args catch-all and splat it. Without the
    catch-all the documented command
    (`bootstrap.ps1 install --recommended --dry-run`) fails with
    "A positional parameter cannot be found that accepts argument 'install'".
    """
    src = (INSTALLER_ROOT / "bootstrap.ps1").read_text(encoding="utf-8")
    assert "ValueFromRemainingArguments" in src, (
        "bootstrap.ps1 must declare a catch-all for the forwarded arguments"
    )
    assert "@RunArgs" in src, (
        "bootstrap.ps1 must splat the filtered catch-all parameter "
        "(plus the TUI-only opt-out)"
    )
    assert "@args" not in src, (
        "bootstrap.ps1 must not splat the automatic $args (unbound under "
        "[CmdletBinding()])"
    )


def test_bootstrap_ps1_registers_mcp_servers_after_install():
    """The one-command install must not leave OpenCode MCPs unregistered."""
    src = (INSTALLER_ROOT / "bootstrap.ps1").read_text(encoding="utf-8")
    assert "SCRIPTS\\se.py" in src
    assert "install --project" in src
    assert "--skip-mcp-registration" in src
    assert "--dry-run" in src


def test_bootstrap_ps1_installs_python_and_refreshes_path():
    """A clean Windows box may not have Python, Node or OpenCode yet."""
    src = (INSTALLER_ROOT / "bootstrap.ps1").read_text(encoding="utf-8")
    assert "Python.Python.3.12" in src, "bootstrap must be able to install Python"
    assert "Update-ProcessPath" in src, "bootstrap must refresh PATH after installs"
    assert "opencode auth login" in src, "bootstrap must point at provider auth"


def test_bootstrap_sh_forwards_positional_arguments():
    """The POSIX entry point must forward every argument to the CLI."""
    src = (INSTALLER_ROOT / "install.sh").read_text(encoding="utf-8")
    assert '"${ARGS[@]}"' in src, "install.sh must splat the filtered arguments"
    assert "--skip-mcp-registration" in src
    assert "sys.version_info" in src, "install.sh must enforce Python 3.10+"
    assert "opencode auth login" in src, "install.sh must point at provider auth"


def test_tui_bootstrap_forwards_the_registration_opt_out():
    """The TUI does its own registration, so both bootstraps must pass the opt-out."""
    ps1 = (INSTALLER_ROOT / "bootstrap.ps1").read_text(encoding="utf-8")
    sh = (INSTALLER_ROOT / "install.sh").read_text(encoding="utf-8")

    assert "RunArgs" in ps1
    assert "TUI finished" in ps1
    assert "after a TUI install" not in ps1
    assert "RUN_ARGS" in sh
    assert "TUI finished" in sh
    assert "after a TUI install" not in sh
