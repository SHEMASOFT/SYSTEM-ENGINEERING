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
* Firecrawl must point at the published npm package;
* every selectable component must have a registered installer
  (``sequential-thinking`` and ``rust`` had none, so ``install --all``
  reported them as FAILED).
"""

from __future__ import annotations

import ast
import shutil
from pathlib import Path

import pytest

from se_installer.cli import print_components
from se_installer.installers.base import run_tool
from se_installer.installers.mcp import (
    Context7Installer,
    FilesystemInstaller,
    FirecrawlInstaller,
    PlaywrightInstaller,
    RustInstaller,
    SequentialThinkingInstaller,
)
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
