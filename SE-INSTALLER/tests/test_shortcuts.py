"""Hermetic tests for the SE Console desktop shortcut (DESIGN-5C phase 4).

These run on Linux and on Windows (the CI matrix) without a Desktop: every test
either plans only, or creates inside ``tmp_path``.

The entry points the shortcut points at are checked against the real repository,
so a rename in SE-CONSOLE cannot silently leave the installer pointing at
nothing.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from se_installer import shortcuts
from se_installer.cli import cmd_install, create_parser
from se_installer.models import (
    ComponentType,
    InstallableComponent,
    InstallationPlan,
    OSType,
)
from se_installer.orchestrator import InstallerOrchestrator
from se_installer.shortcuts import (
    KIND_LINUX_DESKTOP,
    KIND_MACOS_COMMAND,
    KIND_WINDOWS_LNK,
    ShortcutError,
    create_shortcut,
    plan_shortcut,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FAKE_DESKTOP = Path("/somewhere/Desktop")
POSIX_ONLY = pytest.mark.skipif(os.name != "posix", reason="file modes are POSIX-only")


class TestPlanShortcut:
    """The decision: what, where, and pointing at what."""

    def test_defaults_to_no_shortcut_at_all(self):
        assert InstallationPlan().create_shortcuts is False

    def test_windows_is_a_shortcut_to_the_console_script_next_to_it(self):
        shortcut = plan_shortcut(OSType.WINDOWS, root=REPO_ROOT, desktop=FAKE_DESKTOP)
        assert shortcut.kind == KIND_WINDOWS_LNK
        assert shortcut.path == FAKE_DESKTOP / "SE Console.lnk"
        assert shortcut.target == REPO_ROOT / "SE-CONSOLE" / "scripts" / "Start SE Console.cmd"
        assert shortcut.target.exists(), "the shortcut must point at a file the console ships"

    def test_macos_hands_over_to_the_console_script_by_absolute_path(self):
        shortcut = plan_shortcut(OSType.MACOS, root=REPO_ROOT, desktop=FAKE_DESKTOP)
        assert shortcut.kind == KIND_MACOS_COMMAND
        assert shortcut.path == FAKE_DESKTOP / "SE Console.command"
        assert shortcut.target.name == "Start SE Console.command"
        assert shortcut.target.exists()
        assert shortcut.contents.startswith("#!/bin/sh")
        assert f'exec "{shortcut.target}"' in shortcut.contents
        assert shortcut.mode == 0o755

    def test_macos_is_a_wrapper_and_not_a_symlink(self):
        """A symlink on the Desktop would break the console's own launcher.

        That launcher starts with ``cd "$(dirname "$0")"``, so through a symlink
        it would cd to the Desktop and then fail to find dev_console.py.
        """
        shortcut = plan_shortcut(OSType.MACOS, root=REPO_ROOT, desktop=FAKE_DESKTOP)
        assert shortcut.contents is not None
        assert "$0" not in shortcut.contents
        assert str(shortcut.target) in shortcut.contents

    def test_linux_is_a_desktop_file_that_starts_the_console_and_opens_the_browser(self):
        shortcut = plan_shortcut(OSType.LINUX, root=REPO_ROOT, desktop=FAKE_DESKTOP)
        assert shortcut.kind == KIND_LINUX_DESKTOP
        assert shortcut.path == FAKE_DESKTOP / "SE Console.desktop"
        assert shortcut.target == REPO_ROOT / "SE-CONSOLE" / "scripts" / "dev_console.py"
        assert shortcut.target.exists()
        body = shortcut.contents
        assert body.startswith("[Desktop Entry]")
        assert f"'{shortcut.target}' start" in body      # starts the console
        assert "xdg-open" in body and shortcuts.CONSOLE_URL in body  # opens the browser
        assert "Terminal=true" in body
        assert "read -r _" in body, "a failed start must stay readable, as in the .cmd"
        assert shortcut.mode == 0o755

    def test_the_linux_exec_line_needs_no_escaping(self):
        """The Exec is one double-quoted argument, so it must not contain a quote
        or a stray backslash inside: the entry parser would consume them and the
        shell would never see the recipe.

        A path is the one thing that may legitimately carry backslashes -- on
        Windows, where this is never the platform the shortcut is planned for.
        """
        shortcut = plan_shortcut(OSType.LINUX, root=REPO_ROOT, desktop=FAKE_DESKTOP)
        line = next(l for l in shortcut.contents.splitlines() if l.startswith("Exec="))
        body = line[len("Exec="):]
        assert body.startswith('sh -c "') and body.endswith('"')
        inner = body[len('sh -c "'):-1]
        assert '"' not in inner
        assert "\\" not in inner.replace(str(shortcut.target), "")

    def test_there_is_exactly_one_shortcut_and_never_a_stop_one(self):
        """D3: one shortcut, start only. The console stops itself."""
        for os_type in OSType:
            shortcut = plan_shortcut(os_type, root=REPO_ROOT, desktop=FAKE_DESKTOP)
            assert shortcut.path.parent == FAKE_DESKTOP
            assert "stop" not in shortcut.path.name.lower()
            assert "dev_console.py stop" not in (shortcut.contents or "")

    def test_planning_touches_nothing(self, tmp_path):
        for os_type in OSType:
            plan_shortcut(os_type, root=REPO_ROOT, desktop=tmp_path)
        assert list(tmp_path.iterdir()) == []
        assert not (tmp_path / "Desktop").exists()


class TestCreateShortcut:
    """The side effect."""

    def test_a_missing_entry_point_is_refused_before_anything_is_written(self, tmp_path):
        shortcut = plan_shortcut(
            OSType.LINUX, root=tmp_path / "not-the-repo", desktop=tmp_path / "Desktop"
        )
        with pytest.raises(ShortcutError):
            create_shortcut(shortcut)
        assert not (tmp_path / "Desktop").exists()

    @POSIX_ONLY
    def test_the_linux_shortcut_is_created_and_executable(self, tmp_path):
        shortcut = plan_shortcut(OSType.LINUX, root=REPO_ROOT, desktop=tmp_path)
        result = create_shortcut(shortcut)
        assert result.created is True
        assert shortcut.path.exists()
        assert os.access(shortcut.path, os.X_OK), "a shortcut that cannot launch is not one"
        assert shortcut.path.read_text(encoding="utf-8") == shortcut.contents

    @POSIX_ONLY
    def test_the_macos_shortcut_is_created_and_executable(self, tmp_path):
        shortcut = plan_shortcut(OSType.MACOS, root=REPO_ROOT, desktop=tmp_path)
        create_shortcut(shortcut)
        assert os.access(shortcut.path, os.X_OK)
        assert shortcut.path.read_bytes().startswith(b"#!/bin/sh")

    @POSIX_ONLY
    def test_generated_launchers_are_lf_only(self, tmp_path):
        """The repository is LF-only; a generated shell file must be too."""
        for os_type in (OSType.LINUX, OSType.MACOS):
            shortcut = plan_shortcut(os_type, root=REPO_ROOT, desktop=tmp_path)
            create_shortcut(shortcut)
            assert b"\r\n" not in shortcut.path.read_bytes()

    def test_creating_twice_overwrites_instead_of_failing(self, tmp_path):
        first = create_shortcut(plan_shortcut(OSType.LINUX, root=REPO_ROOT, desktop=tmp_path))
        second = create_shortcut(plan_shortcut(OSType.LINUX, root=REPO_ROOT, desktop=tmp_path))
        assert first.created and second.created

    @pytest.mark.skipif(os.name != "nt", reason="a .lnk is created through the Windows shell")
    def test_the_windows_shortcut_is_created(self, tmp_path):
        shortcut = plan_shortcut(OSType.WINDOWS, root=REPO_ROOT, desktop=tmp_path)
        result = create_shortcut(shortcut)
        assert result.created is True
        assert shortcut.path.exists()
        assert shortcut.path.suffix == ".lnk"


def _console_plan() -> InstallationPlan:
    return InstallationPlan(components=[
        InstallableComponent(
            id="se_core", name="SE Core", description="", component_type=ComponentType.SE_CORE
        ),
        InstallableComponent(
            id="se_console", name="SE Console", description="",
            component_type=ComponentType.SE_CONSOLE, requires=["se_core"],
        ),
    ])


class TestOrchestratorShortcut:
    """The plan field drives it; nothing else does."""

    def _orchestrator(self, tmp_path, monkeypatch, *, dry_run, created_via):
        """An orchestrator whose plan includes the console, with state saves off."""
        plan = _console_plan()
        plan.os_type = OSType.LINUX      # set before __init__, which detects only when WINDOWS
        plan.create_shortcuts = True
        plan.dry_run = dry_run
        orchestrator = InstallerOrchestrator(plan, dry_run=dry_run)
        monkeypatch.setattr(orchestrator.state, "save_plan", lambda _plan: None)
        # Redirect the Desktop only, keeping the real planning logic under test.
        real_plan_shortcut = shortcuts.plan_shortcut
        monkeypatch.setattr(
            shortcuts, "plan_shortcut",
            lambda **kw: real_plan_shortcut(
                os_type=kw["os_type"], root=REPO_ROOT, desktop=tmp_path
            ),
        )
        monkeypatch.setattr(shortcuts, "install_console_shortcut", created_via)
        return orchestrator, plan

    def test_a_dry_run_reports_the_shortcut_and_creates_nothing(self, tmp_path, monkeypatch):
        def must_not_run(**_kw):
            raise AssertionError("a dry run must not create a shortcut")

        orchestrator, _ = self._orchestrator(
            tmp_path, monkeypatch, dry_run=True, created_via=must_not_run
        )
        orchestrator.prepare_plan(["se_console"])

        assert orchestrator.run_installation() is True
        assert orchestrator.shortcut["dry_run"] is True
        assert orchestrator.shortcut["created"] is False
        assert orchestrator.shortcut["path"] == str(tmp_path / "SE Console.desktop")
        assert list(tmp_path.iterdir()) == []

    def test_the_shortcut_is_created_after_a_successful_install(self, tmp_path, monkeypatch):
        def really_create(**kw):
            return create_shortcut(
                shortcuts.plan_shortcut(os_type=kw["os_type"], root=REPO_ROOT, desktop=tmp_path)
            )

        orchestrator, _ = self._orchestrator(
            tmp_path, monkeypatch, dry_run=False, created_via=really_create
        )
        orchestrator.prepare_plan(["se_console"])

        assert orchestrator.run_installation() is True
        assert orchestrator.shortcut["created"] is True
        assert (tmp_path / "SE Console.desktop").exists()
        assert orchestrator.get_summary()["shortcut"] == orchestrator.shortcut

    def test_no_shortcut_when_the_console_is_not_part_of_the_install(self, tmp_path, monkeypatch):
        def must_not_run(**_kw):
            raise AssertionError("no console, no console shortcut")

        orchestrator, _ = self._orchestrator(
            tmp_path, monkeypatch, dry_run=False, created_via=must_not_run
        )
        orchestrator.prepare_plan(["se_core"])   # console stays SKIPPED

        orchestrator.run_installation()
        assert orchestrator.shortcut["skipped"] is True
        assert "SE Console is not part" in orchestrator.shortcut["reason"]
        assert list(tmp_path.iterdir()) == []

    def test_a_failed_install_creates_no_shortcut(self, tmp_path, monkeypatch):
        def must_not_run(**_kw):
            raise AssertionError("a failed install must not leave a shortcut behind")

        orchestrator, _ = self._orchestrator(
            tmp_path, monkeypatch, dry_run=False, created_via=must_not_run
        )
        orchestrator.prepare_plan(["se_console"])

        orchestrator.install_console_shortcut(succeeded=False)
        assert orchestrator.shortcut["skipped"] is True
        assert list(tmp_path.iterdir()) == []

    def test_a_shortcut_failure_is_reported_and_not_raised(self, tmp_path, monkeypatch):
        def broken(**_kw):
            raise ShortcutError("no desktop here")

        orchestrator, _ = self._orchestrator(
            tmp_path, monkeypatch, dry_run=False, created_via=broken
        )
        orchestrator.prepare_plan(["se_console"])

        assert orchestrator.run_installation() is True     # the install itself still succeeded
        assert orchestrator.shortcut == {"created": False, "error": "no desktop here"}

    def test_without_the_flag_nothing_is_reported(self):
        orchestrator = InstallerOrchestrator(_console_plan(), dry_run=False)
        assert orchestrator.install_console_shortcut() is None
        assert orchestrator.get_summary()["shortcut"] is None


class TestCliFlag:
    """The operator's switch."""

    def test_the_default_is_no_shortcut(self):
        assert create_parser().parse_args(["install"]).shortcuts is False

    def test_the_flag_opts_in(self):
        assert create_parser().parse_args(["install", "--shortcuts"]).shortcuts is True

    def test_the_negative_flag_is_an_explicit_opt_out(self):
        assert create_parser().parse_args(["install", "--no-shortcuts"]).shortcuts is False

    def test_the_two_flags_contradict_each_other(self):
        with pytest.raises(SystemExit):
            create_parser().parse_args(["install", "--shortcuts", "--no-shortcuts"])

    def test_an_args_object_without_the_attribute_does_not_opt_in(self, capsys):
        """Older callers (and mocks) must not enable a write to the Desktop.

        ``Mock`` invents any attribute you ask for, so a truthiness test would
        switch this on by accident; ``is True`` is what keeps it opt-in.
        """
        args = Mock(
            all=False, components=None, recommended=True, dry_run=True,
            runtimes=["opencode"], force=False, skip_verification=False, json=False,
        )
        # Patch where cmd_install looks it up: it imports the class inside the
        # function, so patching the cli module's alias would be a no-op.
        with patch("se_installer.orchestrator.InstallerOrchestrator") as orchestrator_class:
            orchestrator_class.return_value.get_summary.return_value = {
                "total": 0, "success": 0, "failed": 0, "skipped": 0,
                "shortcut": None, "components": [],
            }
            assert cmd_install(args) == 0

        plan = orchestrator_class.call_args.kwargs.get("plan")
        assert plan is not None and plan.create_shortcuts is False

    def test_the_flag_reaches_the_plan(self, capsys):
        args = Mock(
            all=False, components=None, recommended=True, dry_run=True,
            runtimes=["opencode"], force=False, skip_verification=False,
            json=False, shortcuts=True,
        )
        with patch("se_installer.orchestrator.InstallerOrchestrator") as orchestrator_class:
            orchestrator_class.return_value.get_summary.return_value = {
                "total": 0, "success": 0, "failed": 0, "skipped": 0,
                "shortcut": {"created": True, "path": "/somewhere/SE Console.desktop"},
                "components": [],
            }
            assert cmd_install(args) == 0

        plan = orchestrator_class.call_args.kwargs.get("plan")
        assert plan.create_shortcuts is True
        assert "/somewhere/SE Console.desktop" in capsys.readouterr().out
