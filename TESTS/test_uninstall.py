"""Tests for ``se uninstall`` (plan-by-default, SE-owned surgical removal)."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core import lifecycle_state as lc  # noqa: E402
from se_core import mcpconfig  # noqa: E402
from se_core import uninstall  # noqa: E402


def make_args(project, apply=False, dry_run=False, json=False):
    return types.SimpleNamespace(project=str(project), apply=apply, dry_run=dry_run, json=json)


def write_state(target: Path, names):
    state = lc.new_state(se_version="0.10.0", os_name="windows", target=str(target))
    for index, name in enumerate(names):
        lc.record_server(
            state, name,
            declared=f"{index:064x}",
            source="TEMPLATES/mcp/sample.json.tmpl",
            registered_at="2026-10-09T00:00:00Z",
        )
    lc.save_state(state, target)
    return state


class PlanUninstallTests(unittest.TestCase):
    def test_classifies_managed_in_config_state_only_and_foreign(self):
        state = {
            "schema_version": "1",
            "servers": {
                "both": {"declared": "h", "source": "s", "scope": "project"},
                "absent": {"declared": "h", "source": "s", "scope": "project"},
            },
        }
        cfg = {
            "mcp": {"servers": {"both": {"type": "local"}, "foreign-v2": {"type": "local"}}},
            "mcpServers": {"foreign-legacy": {"command": ["x"]}},
        }
        plan = uninstall.plan_uninstall(state, cfg)
        self.assertEqual(plan["managed"], ["absent", "both"])
        self.assertEqual(plan["in_config"], ["both"])
        self.assertEqual(plan["state_only"], ["absent"])
        self.assertEqual(
            [(entry["name"], entry["scopes"]) for entry in plan["foreign"]],
            [("foreign-legacy", ["legacy"]), ("foreign-v2", ["v2"])],
        )

    def test_empty_state_has_no_foreign(self):
        plan = uninstall.plan_uninstall({"schema_version": "1", "servers": {}}, {})
        self.assertEqual(plan["managed"], [])
        self.assertEqual(plan["foreign"], [])

    def test_foreign_only_when_not_managed(self):
        cfg = {"mcp": {"servers": {"x": {}}}}
        plan = uninstall.plan_uninstall(None, cfg)
        self.assertEqual(plan["managed"], [])
        self.assertEqual([entry["name"] for entry in plan["foreign"]], ["x"])


class RenderUninstallTests(unittest.TestCase):
    REPORT = {
        "target": "/t", "dry_run": True, "managed": ["a", "b"], "in_config": ["a"],
        "state_only": ["b"], "foreign": [{"name": "z", "scopes": ["v2"]}],
        "removed": [], "backups": {}, "errors": [], "blockers": [], "status": "PASS",
    }

    def test_render_is_deterministic(self):
        self.assertEqual(uninstall.render_uninstall(self.REPORT), uninstall.render_uninstall(self.REPORT))

    def test_render_shows_managed_and_dry_run(self):
        text = uninstall.render_uninstall(self.REPORT)
        self.assertIn("dry-run", text)
        self.assertIn("a", text)
        self.assertIn("Would remove", text)


class CmdUninstallTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _capture(self, func):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = func()
        return code, buffer.getvalue()

    def _run(self, **over):
        kwargs = {"project": self.project, "apply": False, "dry_run": False, "json": False}
        kwargs.update(over)
        return uninstall.cmd_uninstall(make_args(**kwargs), platform_name="windows")

    def test_nothing_managed_when_no_state(self):
        code, out = self._capture(self._run)
        self.assertEqual(code, 0, out)
        self.assertIn("nothing managed", out)

    def test_cli_nothing_managed_exit_zero(self):
        code, out = support.run_cli("uninstall", "--project", str(self.project))
        self.assertEqual(code, 0, out)
        self.assertIn("nothing managed", out)

    def test_dry_run_mutates_nothing(self):
        write_state(self.project, ["managed-a"])
        config = self.project / "opencode.jsonc"
        config.write_text(
            '{"mcp": {"servers": {"managed-a": {"type": "local", "command": ["x"]}}}}',
            encoding="utf-8",
        )
        state_before = lc.state_path(self.project).read_bytes()
        config_before = config.read_bytes()
        code, out = self._capture(lambda: self._run(dry_run=True))
        self.assertEqual(code, 0, out)
        self.assertIn("Would remove", out)
        self.assertEqual(lc.state_path(self.project).read_bytes(), state_before)
        self.assertEqual(config.read_bytes(), config_before)

    def test_corrupt_state_is_blocked(self):
        path = lc.state_path(self.project)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ corrupt", encoding="utf-8")
        code, out = self._capture(self._run)
        self.assertEqual(code, 1, out)
        self.assertIn("BLOCKED", out)

    def test_unparseable_config_is_blocked(self):
        write_state(self.project, ["managed-a"])
        (self.project / "opencode.jsonc").write_text("{ bad json", encoding="utf-8")
        code, out = self._capture(lambda: self._run(apply=True))
        self.assertEqual(code, 1, out)
        self.assertIn("BLOCKED", out)

    def test_apply_removes_only_managed_and_keeps_foreign(self):
        write_state(self.project, ["managed-a", "managed-legacy"])
        config = self.project / "opencode.jsonc"
        config.write_text(
            '{\n'
            '  "mcp": {"servers": {\n'
            '    "managed-a": {"type": "local", "command": ["a"]},\n'
            '    "foreign-x": {"type": "local", "command": ["fx"]},\n'
            '  }},\n'
            '  "mcpServers": {"managed-legacy": {"command": "legacy", "args": ["--x"]}},\n'
            '}\n',
            encoding="utf-8",
        )
        code, out = self._capture(lambda: self._run(apply=True))
        self.assertEqual(code, 0, out)
        self.assertIn("Removed", out)
        parsed = mcpconfig.read_config(self.project / "opencode.jsonc")
        self.assertNotIn("managed-a", parsed["mcp"]["servers"])
        self.assertNotIn("managed-legacy", parsed["mcpServers"])
        self.assertEqual(list(parsed["mcp"]["servers"]), ["foreign-x"])

        state = lc.load_state(self.project)
        self.assertEqual(state["servers"], {})
        uninstalled = {entry["name"] for entry in state["uninstalled"]}
        self.assertEqual(uninstalled, {"managed-a", "managed-legacy"})
        backups = (self.project / ".se" / "backups").glob("*")
        self.assertTrue(list(backups))

    def test_apply_keeps_backup_of_removed_server(self):
        write_state(self.project, ["managed-a"])
        (self.project / "opencode.jsonc").write_text(
            '{"mcp": {"servers": {"managed-a": {"type": "local", "command": ["x"]}}}}',
            encoding="utf-8",
        )
        self._run(apply=True)
        backups = list((self.project / ".se" / "backups").glob("managed-a-*.jsonc"))
        self.assertEqual(len(backups), 1)
        self.assertIn("managed-a", backups[0].read_text(encoding="utf-8"))

    def test_missing_config_file_is_state_only_cleanup(self):
        write_state(self.project, ["managed-a"])
        code, out = self._capture(lambda: self._run(apply=True))
        self.assertEqual(code, 0, out)
        self.assertIn("State-only", out)
        state = lc.load_state(self.project)
        self.assertEqual(state["servers"], {})
        self.assertEqual(len(state["uninstalled"]), 1)
        self.assertFalse((self.project / "opencode.jsonc").exists())

    def test_json_envelope_shape(self):
        write_state(self.project, ["managed-a"])
        (self.project / "opencode.jsonc").write_text(
            '{"mcp": {"servers": {"managed-a": {"type": "local", "command": ["x"]}}}}',
            encoding="utf-8",
        )
        code, out = self._capture(lambda: self._run(dry_run=True, json=True))
        self.assertEqual(code, 0, out)
        envelope = json.loads(out)
        self.assertEqual(envelope["report"], "se.report/1")
        self.assertEqual(envelope["operation"], "uninstall")
        self.assertEqual(envelope["details"]["dry_run"], True)

    def test_apply_never_deletes_state_dir(self):
        write_state(self.project, ["managed-a"])
        (self.project / "opencode.jsonc").write_text(
            '{"mcp": {"servers": {"managed-a": {"type": "local", "command": ["x"]}}}}',
            encoding="utf-8",
        )
        code = self._run(apply=True)
        self.assertEqual(code, 0)
        self.assertTrue(lc.state_dir(self.project).exists())
        self.assertTrue(lc.state_path(self.project).exists())


if __name__ == "__main__":
    unittest.main()