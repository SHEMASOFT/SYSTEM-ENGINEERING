"""Hermetic tests for SE Installer CLI - status, doctor, install commands."""

from __future__ import annotations

import pytest
import json
from unittest.mock import Mock, patch

from se_installer.cli import (
    cmd_status,
    cmd_doctor,
    cmd_install,
)
from se_installer.models import InstallStatus


class TestCmdStatus:
    """Tests for cmd_status."""

    def test_status_json(self, capsys):
        args = Mock(json=True)
        with patch('se_installer.cli.InstallerOrchestrator'):
            with patch('se_installer.cli.get_all_components') as mock_comps:
                comp = Mock()
                comp.id = "test"
                comp.name = "Test"
                comp.component_type = Mock(value="mcp")
                comp.category = "Test"
                comp.status = InstallStatus.PENDING
                comp.installed_version = None
                comp.recommended = True
                comp.requires = []
                comp.install_method = "auto"
                mock_comps.return_value = [comp]

                with patch('se_installer.installers.mcp.get_mcp_installer') as mock_installer:
                    mock_inst = Mock()
                    mock_inst.check_installed.return_value = (False, None)
                    mock_installer.return_value = mock_inst

                    exit_code = cmd_status(args)
        captured = capsys.readouterr()
        assert exit_code == 0
        data = json.loads(captured.out)
        assert isinstance(data, list)

    def test_status_marks_vendored_components_installed(self, capsys):
        args = Mock(json=True)

        def component(cid, name, component_type):
            comp = Mock()
            comp.id = cid
            comp.name = name
            comp.component_type = Mock(value=component_type)
            comp.category = "Core"
            comp.status = InstallStatus.PENDING
            comp.installed_version = None
            return comp

        core = component("se_core", "SE Core", "se_core")
        console = component("se_console", "SE Console", "se_console")

        with patch('se_installer.cli.InstallerOrchestrator'):
            with patch('se_installer.cli.get_all_components', return_value=[core, console]):
                exit_code = cmd_status(args)

        assert exit_code == 0
        data = json.loads(capsys.readouterr().out)
        assert [(item["id"], item["status"], item["version"]) for item in data] == [
            ("se_core", "success", "vendored"),
            ("se_console", "success", "vendored"),
        ]


class TestCmdDoctor:
    """Tests for cmd_doctor."""

    def test_doctor_json(self, capsys):
        args = Mock(json=True)
        with patch('se_installer.cli.InstallerOrchestrator'):
            with patch('se_installer.cli.get_all_components') as mock_comps:
                comp = Mock()
                comp.id = "test"
                comp.name = "Test"
                comp.component_type = Mock(value="mcp")
                comp.recommended = True
                mock_comps.return_value = [comp]

                with patch('se_installer.installers.mcp.get_mcp_installer') as mock_installer:
                    mock_inst = Mock()
                    mock_inst.check_installed.return_value = (False, None)
                    mock_installer.return_value = mock_inst

                    exit_code = cmd_doctor(args)
        captured = capsys.readouterr()
        assert exit_code in (0, 1)
        data = json.loads(captured.out)
        assert "issues" in data
        assert "warnings" in data
        assert "ok" in data

    def test_doctor_reports_vendored_components(self, capsys):
        args = Mock(json=False)

        def component(cid, name, component_type):
            comp = Mock()
            comp.id = cid
            comp.name = name
            comp.component_type = Mock(value=component_type)
            comp.recommended = True
            return comp

        core = component("se_core", "SE Core", "se_core")
        console = component("se_console", "SE Console", "se_console")

        with patch('se_installer.cli.InstallerOrchestrator'):
            with patch('se_installer.cli.get_all_components', return_value=[core, console]):
                exit_code = cmd_doctor(args)

        out = capsys.readouterr().out
        assert exit_code == 0
        assert "[OK] SE Core vvendored" in out
        assert "[OK] SE Console vvendored" in out


class TestCmdInstall:
    """Tests for cmd_install."""

    def test_install_dry_run(self, capsys):
        args = Mock(
            all=False, components=None, recommended=True,
            dry_run=True, runtimes=["opencode"], force=False,
            skip_verification=False, json=False,
            bootstrap=False, bootstrap_components=None, bootstrap_runtimes=None
        )
        with patch('se_installer.cli.InstallerOrchestrator') as mock_orch_class:
            mock_orch = Mock()
            mock_orch.get_summary.return_value = {
                "total": 2, "success": 2, "failed": 0, "skipped": 5,
                "components": [
                    {"id": "a", "name": "A", "status": "success", "version": "dry-run", "error": None},
                    {"id": "b", "name": "B", "status": "success", "version": "dry-run", "error": None},
                ]
            }
            mock_orch.run_installation.return_value = True
            mock_orch_class.return_value = mock_orch

            exit_code = cmd_install(args)
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "DONE" in captured.out or "Instalación completada" in captured.out

    def test_install_json_output(self, capsys):
        args = Mock(
            all=False, components=None, recommended=True,
            dry_run=True, runtimes=["opencode"], force=False,
            skip_verification=False, json=True,
            bootstrap=False, bootstrap_components=None, bootstrap_runtimes=None
        )
        # cmd_install imports InstallerOrchestrator from .orchestrator at call
        # time, so the patch target is the source module, not se_installer.cli.
        with patch('se_installer.orchestrator.InstallerOrchestrator') as mock_orch_class:
            mock_orch = Mock()
            # The real get_summary uses actual component data, mock the whole method
            mock_orch.get_summary.return_value = {
                "total": 7, "success": 7, "failed": 0, "skipped": 6,
                "components": [
                    {"id": "se_core", "name": "SE Core", "status": "success", "version": "dry-run", "error": None},
                    {"id": "playwright", "name": "Playwright MCP", "status": "success", "version": "dry-run", "error": None},
                    {"id": "context7", "name": "Context7", "status": "success", "version": "dry-run", "error": None},
                    {"id": "filesystem", "name": "Filesystem MCP", "status": "success", "version": "dry-run", "error": None},
                    {"id": "node", "name": "Node.js / npx", "status": "success", "version": "dry-run", "error": None},
                    {"id": "opencode", "name": "OpenCode", "status": "success", "version": "dry-run", "error": None},
                    {"id": "se_console", "name": "SE Console", "status": "success", "version": "dry-run", "error": None},
                ]
            }
            mock_orch.run_installation.return_value = True
            mock_orch_class.return_value = mock_orch

            exit_code = cmd_install(args)
        captured = capsys.readouterr()
        assert exit_code == 0
        data = json.loads(captured.out)
        assert data["success"] == 7

    def test_install_bootstrap_flag_not_in_se_installer(self):
        """--bootstrap flag is in `se` CLI, not `se-installer` CLI."""
        from se_installer.cli import create_parser
        parser = create_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["install", "--bootstrap", "--dry-run"])