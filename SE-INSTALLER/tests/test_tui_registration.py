"""Tests for the TUI's post-install MCP registration."""

from __future__ import annotations

from types import SimpleNamespace

import se_installer.tui as tui_module
from se_installer.cli import cmd_tui, create_parser
from se_installer.tui import register_mcps


class _Completed:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _repo(tmp_path, keys=("context7", "filesystem")):
    (tmp_path / "SCRIPTS").mkdir()
    (tmp_path / "SCRIPTS" / "se.py").write_text("", encoding="utf-8")
    templates = tmp_path / "TEMPLATES" / "mcp"
    templates.mkdir(parents=True)
    for key in keys:
        (templates / f"{key}.json.tmpl").write_text("{}", encoding="utf-8")
    return tmp_path


def test_tui_parser_accepts_skip_mcp_registration():
    args = create_parser().parse_args(["tui", "--skip-mcp-registration"])

    assert args.command == "tui"
    assert args.skip_mcp_registration is True


def test_register_mcps_uses_only_selected_templates(tmp_path):
    repo = _repo(tmp_path)
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return _Completed(stdout="registered\n")

    result = register_mcps(
        ["context7", "filesystem", "playwright"],
        repo_root=repo,
        project=repo,
        runner=runner,
    )

    assert result == 0
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command[2] == "install"
    assert command[3:5] == ["--project", str(repo)]
    assert command[5:7] == ["--with", "context7,filesystem"]
    assert kwargs["cwd"] == str(repo)
    assert kwargs["timeout"] == 300


def test_register_mcps_skips_when_no_selected_mcp_has_a_template(tmp_path, capsys):
    repo = _repo(tmp_path)
    calls = []

    result = register_mcps(
        ["playwright", "firecrawl"],
        repo_root=repo,
        project=repo,
        runner=lambda *args, **kwargs: calls.append(args) or _Completed(),
    )

    assert result == 0
    assert calls == []
    assert "no selected MCP has a registration template" in capsys.readouterr().out


def test_register_mcps_skips_when_repository_cli_is_missing(tmp_path):
    calls = []

    result = register_mcps(
        ["context7"],
        repo_root=tmp_path,
        project=tmp_path,
        runner=lambda *args, **kwargs: calls.append(args) or _Completed(),
    )

    assert result == 0
    assert calls == []


def test_register_mcps_returns_failure_for_nonzero_exit(tmp_path):
    repo = _repo(tmp_path)

    result = register_mcps(
        ["context7"],
        repo_root=repo,
        project=repo,
        runner=lambda *args, **kwargs: _Completed(returncode=2, stderr="boom\n"),
    )

    assert result == 1


def test_register_mcps_converts_oserror_to_failure(tmp_path):
    repo = _repo(tmp_path)

    def runner(*args, **kwargs):
        raise OSError("no python")

    assert (
        register_mcps(
            ["context7"],
            repo_root=repo,
            project=repo,
            runner=runner,
        )
        == 1
    )


def test_cmd_tui_registers_installed_mcps_after_success(monkeypatch):
    fake_app = SimpleNamespace(
        installation_attempted=True,
        install_succeeded=True,
        installed_mcp_ids=["context7", "filesystem"],
        run=lambda: None,
    )
    registered = []

    monkeypatch.setattr(tui_module, "InstallerApp", lambda: fake_app)
    monkeypatch.setattr(
        tui_module,
        "register_mcps",
        lambda ids: registered.append(ids) or 0,
    )

    assert cmd_tui(SimpleNamespace(skip_mcp_registration=False)) == 0
    assert registered == [["context7", "filesystem"]]


def test_cmd_tui_skips_registration_after_a_dry_run(monkeypatch):
    fake_app = SimpleNamespace(
        installation_attempted=True,
        install_succeeded=True,
        install_was_dry_run=True,
        installed_mcp_ids=["context7"],
        run=lambda: None,
    )
    registered = []

    monkeypatch.setattr(tui_module, "InstallerApp", lambda: fake_app)
    monkeypatch.setattr(
        tui_module,
        "register_mcps",
        lambda ids: registered.append(ids) or 0,
    )

    assert cmd_tui(SimpleNamespace(skip_mcp_registration=False)) == 0
    assert registered == []


def test_cmd_tui_skips_registration_when_requested(monkeypatch):
    fake_app = SimpleNamespace(
        installation_attempted=True,
        install_succeeded=True,
        installed_mcp_ids=["context7"],
        run=lambda: None,
    )
    registered = []

    monkeypatch.setattr(tui_module, "InstallerApp", lambda: fake_app)
    monkeypatch.setattr(
        tui_module,
        "register_mcps",
        lambda ids: registered.append(ids) or 0,
    )

    assert cmd_tui(SimpleNamespace(skip_mcp_registration=True)) == 0
    assert registered == []


def test_cmd_tui_returns_failure_and_does_not_register_after_failed_install(
    monkeypatch,
):
    fake_app = SimpleNamespace(
        installation_attempted=True,
        install_succeeded=False,
        installed_mcp_ids=[],
        run=lambda: None,
    )
    registered = []

    monkeypatch.setattr(tui_module, "InstallerApp", lambda: fake_app)
    monkeypatch.setattr(
        tui_module,
        "register_mcps",
        lambda ids: registered.append(ids) or 0,
    )

    assert cmd_tui(SimpleNamespace(skip_mcp_registration=False)) == 1
    assert registered == []


def test_cmd_tui_returns_zero_when_install_was_not_attempted(monkeypatch):
    fake_app = SimpleNamespace(
        installation_attempted=False,
        install_succeeded=False,
        installed_mcp_ids=[],
        run=lambda: None,
    )
    registered = []

    monkeypatch.setattr(tui_module, "InstallerApp", lambda: fake_app)
    monkeypatch.setattr(
        tui_module,
        "register_mcps",
        lambda ids: registered.append(ids) or 0,
    )

    assert cmd_tui(SimpleNamespace(skip_mcp_registration=False)) == 0
    assert registered == []


def test_cmd_tui_propagates_registration_failure(monkeypatch):
    fake_app = SimpleNamespace(
        installation_attempted=True,
        install_succeeded=True,
        installed_mcp_ids=["context7"],
        run=lambda: None,
    )

    monkeypatch.setattr(tui_module, "InstallerApp", lambda: fake_app)
    monkeypatch.setattr(tui_module, "register_mcps", lambda ids: 1)

    assert cmd_tui(SimpleNamespace(skip_mcp_registration=False)) == 1
