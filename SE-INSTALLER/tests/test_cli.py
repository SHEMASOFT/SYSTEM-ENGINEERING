"""Hermetic tests for SE Installer CLI - parser and basic commands."""

from __future__ import annotations

import pytest
import json
from unittest.mock import Mock, patch

from se_installer.cli import (
    cmd_list,
    cmd_status,
    cmd_doctor,
    cmd_install,
    create_parser,
)
from se_installer.models import InstallStatus


class TestCLI:
    """Tests for CLI commands."""

    def test_parser_creation(self):
        parser = create_parser()
        assert parser.prog == "se-installer"

    def test_install_parser_args(self):
        parser = create_parser()
        args = parser.parse_args(["install", "--dry-run", "--recommended", "--json"])
        assert args.command == "install"
        assert args.dry_run is True
        assert args.recommended is True
        assert args.json is True

    def test_install_bootstrap_args_not_in_se_installer(self):
        """--bootstrap is in `se` CLI, not `se-installer` CLI."""
        parser = create_parser()
        # se-installer doesn't have --bootstrap flag
        with pytest.raises(SystemExit):
            parser.parse_args(["install", "--bootstrap", "--dry-run"])

    def test_list_parser_args(self):
        parser = create_parser()
        args = parser.parse_args(["list", "--category", "Core", "--json"])
        assert args.command == "list"
        assert args.category == "Core"
        assert args.json is True

    def test_status_parser_args(self):
        parser = create_parser()
        args = parser.parse_args(["status", "--json"])
        assert args.command == "status"
        assert args.json is True

    def test_doctor_parser_args(self):
        parser = create_parser()
        args = parser.parse_args(["doctor", "--json"])
        assert args.command == "doctor"
        assert args.json is True


class TestCmdList:
    """Tests for cmd_list."""

    def test_list_all_components(self, capsys):
        exit_code = cmd_list(Mock(category=None, installed=False, json=False))
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "SE Core" in captured.out
        assert "Engram" in captured.out

    def test_list_json_output(self, capsys):
        args = Mock(category=None, installed=False, json=True)
        exit_code = cmd_list(args)
        captured = capsys.readouterr()
        assert exit_code == 0
        data = json.loads(captured.out)
        assert isinstance(data, list)
        assert len(data) >= 13

    def test_list_filter_by_category(self, capsys):
        args = Mock(category="Core", installed=False, json=False)
        exit_code = cmd_list(args)
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "Core" in captured.out

    def test_list_installed_only(self, capsys):
        args = Mock(category=None, installed=True, json=False)
        exit_code = cmd_list(args)
        captured = capsys.readouterr()
        assert exit_code == 0