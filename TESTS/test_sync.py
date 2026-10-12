"""Tests for ``se sync`` (declared-vs-registered-vs-actual reconciliation)."""

from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core import install, lifecycle_state as lc, mcpconfig  # noqa: E402
from se_core import sync  # noqa: E402


class FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FakeRunner:
    def __init__(self, result=None):
        self.calls = []
        self.result = result or FakeResult(0)

    def __call__(self, command):
        self.calls.append(list(command))
        return self.result


def make_template(name="demo-server", key=None, args=("-m", "demo"), env=None, template="TEMPLATES/mcp/demo-server.json.tmpl"):
    return {
        "key": key or name,
        "name": name,
        "command": "python",
        "args": list(args),
        "env": dict(env or {}),
        "template": template,
    }


def make_args(project, dry_run=False, json=False):
    return types.SimpleNamespace(project=str(project), dry_run=dry_run, json=json)


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #


class DeclaredViewTests(unittest.TestCase):
    def test_declared_view_maps_name_to_spec_and_hash(self):
        templates = [make_template(name="demo", args=("${SE_ROOT}/x",))]
        view = sync.declared_view(
            templates, se_root="/se", project="/proj", project_id="PRJ-X", interpreter="python"
        )
        self.assertIn("demo", view)
        spec = view["demo"]["spec"]
        self.assertEqual(spec["command"], ["python", "/se/x"])
        self.assertEqual(view["demo"]["template"], templates[0])
        self.assertEqual(view["demo"]["hash"], lc.spec_hash(spec))

    def test_env_values_resolved_in_env_mode(self):
        templates = [make_template(name="demo", env={"KEY": "${SE_ROOT}/cache"})]
        view = sync.declared_view(
            templates, se_root="/se", project="/proj", project_id="PRJ-X", interpreter="python"
        )
        self.assertEqual(
            view["demo"]["spec"]["environment"], {"KEY": "/se/cache"}
        )


class EntryMatchesTests(unittest.TestCase):
    SPEC = {"name": "demo", "command": ["python", "-m", "demo"], "environment": {"K": "V"}}

    def test_v2_shape_matches(self):
        actual = {"type": "local", "command": ["python", "-m", "demo"], "environment": {"K": "V"}}
        self.assertTrue(sync.entry_matches(actual, self.SPEC, legacy=False))

    def test_v2_string_command_matches(self):
        actual = {"type": "local", "command": "python -m demo", "environment": {"K": "V"}}
        self.assertTrue(sync.entry_matches(actual, self.SPEC, legacy=False))

    def test_v2_env_mismatch_does_not_match(self):
        actual = {"type": "local", "command": ["python", "-m", "demo"], "environment": {"K": "OTHER"}}
        self.assertFalse(sync.entry_matches(actual, self.SPEC, legacy=False))

    def test_legacy_shape_matches(self):
        actual = {"command": "python -m demo", "args": [], "env": {"K": "V"}}
        self.assertTrue(sync.entry_matches(actual, self.SPEC, legacy=True))

    def test_legacy_command_mismatch_does_not_match(self):
        actual = {"command": "python", "args": ["-m", "other"], "env": {"K": "V"}}
        self.assertFalse(sync.entry_matches(actual, self.SPEC, legacy=True))

    def test_non_dict_does_not_match(self):
        self.assertFalse(sync.entry_matches("str", self.SPEC, legacy=False))


class ReconcileTests(unittest.TestCase):
    DECLARED = {
        "server-a": {"spec": {"name": "server-a", "command": ["x"], "environment": {}}, "hash": "ha"},
        "server-b": {"spec": {"name": "server-b", "command": ["x"], "environment": {}}, "hash": "hb"},
        "server-c": {"spec": {"name": "server-c", "command": ["x"], "environment": {}}, "hash": "hc"},
        "server-d": {"spec": {"name": "server-d", "command": ["old"], "environment": {}}, "hash": "hd"},
    }

    def _state(self, names):
        state = {
            "schema_version": "1",
            "servers": {
                name: {"declared": self.DECLARED[name]["hash"], "scope": "project", "source": "s"}
                for name in names
            },
        }
        return state

    def test_missing_declared_registers(self):
        report = sync.reconcile(declared=self.DECLARED, state=None, cfg={})
        self.assertEqual(
            sorted(entry["name"] for entry in report["register"]),
            ["server-a", "server-b", "server-c", "server-d"],
        )

    def test_present_without_state_is_foreign(self):
        cfg = {"mcp": {"servers": {"server-a": {"command": ["x"]}}}}
        report = sync.reconcile(declared=self.DECLARED, state=None, cfg=cfg)
        foreign = {entry["name"]: entry for entry in report["foreign"]}
        self.assertIn("server-a", foreign)
        self.assertEqual(foreign["server-a"]["scopes"], ["v2"])

    def test_legacy_presence_is_foreign_not_duplicated(self):
        cfg = {"mcpServers": {"server-a": {"command": "x"}}}
        report = sync.reconcile(declared=self.DECLARED, state=None, cfg=cfg)
        self.assertEqual(len(report["register"]), 3)
        foreign = {entry["name"]: entry for entry in report["foreign"]}
        self.assertEqual(foreign["server-a"]["scopes"], ["legacy"])

    def test_matching_state_and_actual_is_up_to_date(self):
        cfg = {"mcp": {"servers": {"server-a": {"command": ["x"]}}}}
        report = sync.reconcile(declared=self.DECLARED, state=self._state(["server-a"]), cfg=cfg)
        self.assertEqual([entry["name"] for entry in report["up_to_date"]], ["server-a"])
        self.assertEqual(
            sorted(entry["name"] for entry in report["register"]),
            ["server-b", "server-c", "server-d"],
        )
        self.assertEqual(report["foreign"], [])

    def test_se_owned_changed_in_v2_re_registers(self):
        cfg = {"mcp": {"servers": {"server-d": {"command": ["OLD"]}}}}
        report = sync.reconcile(declared=self.DECLARED, state=self._state(["server-d"]), cfg=cfg)
        self.assertEqual([entry["name"] for entry in report["update"]], ["server-d"])
        self.assertEqual(report["update"][0]["action"], "re-register")

    def test_se_owned_in_legacy_only_is_reported_not_duplicated(self):
        cfg = {"mcpServers": {"server-d": {"command": "old-version"}}}
        report = sync.reconcile(declared=self.DECLARED, state=self._state(["server-d"]), cfg=cfg)
        entry = report["update"][0]
        self.assertEqual(entry["name"], "server-d")
        self.assertEqual(entry["action"], "report_only")
        self.assertIn("legacy", entry["reason"])

    def test_state_without_declaration_is_orphan(self):
        state = {
            "schema_version": "1",
            "servers": {"ghost": {"declared": "x", "scope": "project", "source": "s"}},
        }
        report = sync.reconcile(declared=self.DECLARED, state=state, cfg={})
        self.assertEqual([entry["name"] for entry in report["orphan"]], ["ghost"])
        self.assertEqual(report["orphan"][0]["action"], "report_only")


class RenderSyncTests(unittest.TestCase):
    def test_render_is_deterministic(self):
        report = {
            "target": "/t", "dry_run": True, "declared": ["a", "b"],
            "actions": {"register": [{"name": "a", "reason": "r"}], "update": [],
                        "foreign": [], "orphan": [], "up_to_date": [{"name": "b", "reason": "ok"}]},
            "applied": {"register": [], "update": []}, "skipped": [], "failures": [],
            "status": "PASS",
        }
        self.assertEqual(sync.render_sync(report), sync.render_sync(report))

    def test_render_mentions_foreign(self):
        report = {
            "target": "/t", "dry_run": True, "declared": [],
            "actions": {"register": [], "update": [], "foreign": [
                {"name": "pre", "reason": "x"}], "orphan": [], "up_to_date": []},
            "applied": {"register": [], "update": []}, "skipped": [], "failures": [],
            "status": "PASS",
        }
        self.assertIn("Foreign/pre-existing", sync.render_sync(report))


# --------------------------------------------------------------------------- #
# End-to-end command
# --------------------------------------------------------------------------- #


class CmdSyncTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)
        self.runner = FakeRunner()
        self.which = lambda name: name in ("python", "opencode")

    def tearDown(self):
        self._tmp.cleanup()

    def _args(self, dry_run=False, json=False):
        return make_args(self.project, dry_run=dry_run, json=json)

    def _run(self, dry_run=False):
        return sync.cmd_sync(
            self._args(dry_run=dry_run), platform_name="windows", runner=self.runner, which=self.which
        )

    def _skill_spec(self):
        templates = install.load_mcp_templates(support.REPO_ROOT)
        skill = next(t for t in templates if t["key"] == "skill-server")
        return skill, install.resolved_server_spec(
            skill,
            se_root=support.REPO_ROOT,
            project=self.project,
            project_id=install.read_project_id(self.project),
            interpreter="python",
        )

    def test_dry_run_does_not_invoke_runner(self):
        code = self._run(dry_run=True)
        self.assertEqual(code, 0)
        self.assertEqual(self.runner.calls, [])
        self.assertFalse(lc.state_path(self.project).exists())

    def test_apply_registers_and_records_state(self):
        code, out = self._capture(self._run)
        self.assertEqual(code, 0, out)
        state = lc.load_state(self.project)
        self.assertIsNotNone(state)
        self.assertIn("se-skill-server", state["servers"])
        self.assertEqual(len(state["servers"]["se-skill-server"]["declared"]), 64)
        self.assertTrue(self.runner.calls)

    def _capture(self, func):
        import contextlib
        import io

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = func()
        return code, buffer.getvalue()

    def test_second_run_matching_config_is_noop(self):
        templates = install.load_mcp_templates(support.REPO_ROOT)
        project_id = install.read_project_id(self.project)
        cfg_servers = {}
        state_map = {}
        for template in templates:
            spec = install.resolved_server_spec(
                template, se_root=support.REPO_ROOT, project=self.project,
                project_id=project_id, interpreter="python",
            )
            cfg_servers[spec["name"]] = {
                "type": "local", "command": spec["command"], "environment": spec["environment"],
            }
            state_map[spec["name"]] = {"declared": lc.spec_hash(spec), "source": template["template"], "scope": "project"}
        support.write_json(
            self.project / "opencode.jsonc",
            {"mcp": {"servers": cfg_servers}},
        )
        state = lc.new_state(se_version=lc.read_se_version(support.REPO_ROOT), os_name="windows", target=str(self.project))
        state["servers"] = state_map
        lc.save_state(state, self.project)

        code, out = self._capture(self._run)
        self.assertEqual(code, 0, out)
        self.assertIn("Up to date", out)
        self.assertIn("Applied: nothing", out)
        self.assertEqual(self.runner.calls, [])

    def test_legacy_entry_is_never_duplicated_into_v2(self):
        templates = install.load_mcp_templates(support.REPO_ROOT)
        engram = next(t for t in templates if t["key"] == "engram")
        existing = {
            "command": "engram",
            "args": ["mcp", "--tools=agent"],
            "env": {"ENGRAM_PROJECT": install.read_project_id(self.project)},
        }
        support.write_json(
            self.project / "opencode.jsonc",
            {"mcp": {"servers": {}}, "mcpServers": {"engram": existing}},
        )
        code, out = self._capture(lambda: self._run(dry_run=True))
        self.assertEqual(code, 0, out)
        self.assertIn("Foreign/pre-existing", out)
        self.assertIn("engram", out)
        parsed = mcpconfig.read_config(self.project / "opencode.jsonc")
        self.assertNotIn("engram", parsed["mcp"]["servers"])

    def test_corrupt_state_is_blocked(self):
        path = lc.state_path(self.project)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ corrupt", encoding="utf-8")
        code, out = self._capture(lambda: self._run(dry_run=True))
        self.assertEqual(code, 1, out)
        self.assertIn("BLOCKED", out)
        self.assertEqual(self.runner.calls, [])


if __name__ == "__main__":
    unittest.main()