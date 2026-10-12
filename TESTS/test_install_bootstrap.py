"""Hermetic tests for the ``se install --bootstrap`` bridge.

``run_bootstrap_installer`` (in :mod:`se_core.install`) shells out to the
``se-installer`` package as a subprocess. Every test below replaces
``subprocess.run`` so no external process, package or network is ever touched.
"""

from __future__ import annotations

import types
import unittest
from pathlib import Path
from unittest import mock

from se_core import install


def _completed(returncode: int = 0, stdout: str = "", stderr: str = ""):
    return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


class RunBootstrapInstallerTests(unittest.TestCase):
    """Contract of the bootstrapping subprocess step."""

    def test_missing_installer_returns_install_hint(self):
        with mock.patch.object(
            install.subprocess, "run", side_effect=FileNotFoundError
        ) as run:
            code, summary = install.run_bootstrap_installer(project=".")
        self.assertEqual(code, 1)
        self.assertIn("pip install -e SE-INSTALLER", summary["error"])
        run.assert_called_once()

    def test_timeout_returns_clean_error(self):
        exc = install.subprocess.TimeoutExpired("se-installer", timeout=300)
        with mock.patch.object(install.subprocess, "run", side_effect=exc):
            code, summary = install.run_bootstrap_installer(project=".")
        self.assertEqual(code, 1)
        self.assertIn("timed out", summary["error"])

    def test_parses_json_summary_from_stdout_tail(self):
        stdout = 'some human output\n{"component": "se_core", "ok": true}\n'
        with mock.patch.object(
            install.subprocess, "run", return_value=_completed(stdout=stdout)
        ):
            code, summary = install.run_bootstrap_installer(project=".")
        self.assertEqual(code, 0)
        self.assertEqual(summary, {"component": "se_core", "ok": True})

    def test_nonzero_exit_reports_stderr(self):
        with mock.patch.object(
            install.subprocess,
            "run",
            return_value=_completed(returncode=4, stderr="boom"),
        ):
            code, summary = install.run_bootstrap_installer(project=".")
        self.assertEqual(code, 4)
        self.assertEqual(summary["error"], "boom")

    def test_command_layout_with_explicit_components_and_runtimes(self):
        captured: dict = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["cwd"] = kwargs.get("cwd")
            return _completed(stdout='{"status": "planned"}')

        project = Path("proj")
        with mock.patch.object(install.subprocess, "run", side_effect=fake_run):
            code, _summary = install.run_bootstrap_installer(
                components=" context7 , filesystem ",
                runtimes="opencode",
                dry_run=True,
                project=project,
            )

        self.assertEqual(code, 0)
        cmd = captured["cmd"]
        self.assertEqual(cmd[0], install.sys.executable)
        self.assertEqual(cmd[1], "-m")
        self.assertEqual(cmd[2], "se_installer.cli")
        self.assertIn("--components", cmd)
        comps = cmd[cmd.index("--components") + 1 : cmd.index("--runtimes")]
        self.assertEqual(comps, ["context7", "filesystem"])
        self.assertIn("--dry-run", cmd)
        self.assertIn("--json", cmd)
        self.assertEqual(captured["cwd"], str(project))

    def test_command_layout_with_recommended_default(self):
        captured: dict = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return _completed(stdout='{"status": "planned"}')

        with mock.patch.object(install.subprocess, "run", side_effect=fake_run):
            code, _summary = install.run_bootstrap_installer(project=".")
        self.assertEqual(code, 0)
        cmd = captured["cmd"]
        self.assertIn("--recommended", cmd)
        self.assertNotIn("--components", cmd)


if __name__ == "__main__":
    unittest.main()