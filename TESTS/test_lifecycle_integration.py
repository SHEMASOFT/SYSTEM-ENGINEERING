"""Full-cycle integration test for the SE lifecycle.

This is deliberately NOT a unit test. It drives ``se install`` -> ``se sync`` ->
``se update`` -> ``se uninstall`` as ONE integrated lifecycle against a temporary
sandbox target, emulating the runtime boundary with an in-process fake so no real
``opencode`` CLI is ever spawned and no real configuration is ever touched.

Hermeticity:

* the target project lives in a ``tempfile.TemporaryDirectory``;
* the SE root (the canonical ``TEMPLATES/mcp`` source + ``VERSION``) is a sandbox
  copy under the same temp dir, injected into ``install`` / ``sync`` / ``update``
  so the test never reads or writes the repository's canonical source;
* ``se install`` writes the runtime config directly (surgical, byte-preserving);
  the injected :class:`FakeOpencode` emulates the runtime boundary for the
  ``sync`` / ``update`` / ``uninstall`` phases and can be switched to fail on
  demand to exercise the rollback path.

Assertions are on observable artifacts (config bytes, lifecycle state file,
exit codes) rather than on private internals.
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core import commands  # noqa: E402
from se_core import install  # noqa: E402
from se_core import lifecycle_state as lc  # noqa: E402
from se_core import mcpconfig  # noqa: E402
from se_core import sync  # noqa: E402
from se_core import uninstall  # noqa: E402
from se_core import update as update_lifecycle  # noqa: E402

#: Sandbox runtime config seeded with a pre-existing (foreign) MCP entry and a
#: comment. SE must register alongside it and later remove only what it owns.
SKELETON = """{
  // sandbox: a pre-existing (foreign) MCP entry that SE must never rewrite
  "mcp": {
    "servers": {
      "foreign-server": {
        "type": "local",
        "command": ["/opt/foreign/bin/server"],
        "environment": {
          "FOREIGN_TOKEN": "keep-me-verbatim-9f3a"
        }
      }
    }
  }
}
"""

FOREIGN_MARKER = "keep-me-verbatim-9f3a"
SE_SERVERS = ["context7", "filesystem", "se-skill-server"]


class FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


# --------------------------------------------------------------------------- #
# Minimal, independent jsonc navigation for the fake runtime
# --------------------------------------------------------------------------- #


def _skip_ws(text, i):
    n = len(text)
    while i < n:
        if text[i] in " \t\r\n":
            i += 1
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j == -1 else j + 1
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j == -1 else j + 2
            continue
        break
    return i


def _skip_string(text, i):
    i += 1
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == '"':
            return i + 1
        i += 1
    raise ValueError("unterminated string")


def _value_end(text, i):
    ch = text[i]
    if ch == '"':
        return _skip_string(text, i)
    if ch in "{[":
        close = "}" if ch == "{" else "]"
        depth = 0
        n = len(text)
        while i < n:
            c = text[i]
            if c == '"':
                i = _skip_string(text, i)
                continue
            if c == ch:
                depth += 1
            elif c == close:
                depth -= 1
                if depth == 0:
                    return i + 1
            i += 1
        raise ValueError("unterminated container")
    j = i
    while j < len(text) and text[j] not in ",}] \t\r\n":
        j += 1
    return j


def _locate(text, obj_start, obj_end, key):
    """Return ``(key_start, value_start, value_end)`` for a top-level property."""
    i = obj_start + 1
    while i < obj_end:
        i = _skip_ws(text, i)
        while i < obj_end and text[i] == ",":
            i = _skip_ws(text, i + 1)
        if i >= obj_end or text[i] == "}":
            return None
        if text[i] != '"':
            raise AssertionError(f"unexpected token at {i}: {text[i]!r}")
        key_end = _skip_string(text, i)
        found = text[i + 1 : key_end - 1]
        j = _skip_ws(text, key_end)
        if j >= len(text) or text[j] != ":":
            raise AssertionError("malformed property (expected ':')")
        v_start = _skip_ws(text, j + 1)
        v_end = _value_end(text, v_start)
        if found == key:
            return i, v_start, v_end
        i = v_end
    return None


def _servers_span(text):
    root_start = _skip_ws(text, 0)
    root_end = _value_end(text, root_start)
    mcp = _locate(text, root_start, root_end, "mcp")
    if mcp is None:
        return None
    servers = _locate(text, mcp[1], mcp[2], "servers")
    if servers is None:
        return None
    return servers[1], servers[2]


def _server_block(text, name):
    """Return the exact ``key: value`` byte span of ``name`` inside mcp.servers."""
    span = _servers_span(text)
    assert span is not None, "sandbox config has no mcp.servers object"
    found = _locate(text, span[0], span[1], name)
    assert found is not None, f"{name} not found in mcp.servers"
    return text[found[0] : found[2]]


class FakeOpencode:
    """In-process emulation of ``opencode mcp add`` against a sandbox config.

    Parses exactly the argv that :func:`install.build_registrations` emits and
    edits only the added/updated server's own span, so every other byte in the
    file - foreign entries and comments included - is preserved. ``fail_on`` names
    servers whose registration should fail (returncode 1) to exercise rollback.
    """

    def __init__(self, config_path, fail_on=()):
        self.config_path = Path(config_path)
        self.fail_on = set(fail_on)
        self.calls = []

    def __call__(self, command):
        command = list(command)
        self.calls.append(command)
        if "--help" in command:
            return FakeResult(0, stdout="--global  Register into the user config")
        name, spec = self._parse(command)
        if name in self.fail_on:
            return FakeResult(1, stderr=f"injected registration failure for {name}")
        self._upsert(name, spec)
        return FakeResult(0)

    @staticmethod
    def _parse(command):
        assert command[:3] == ["opencode", "mcp", "add"], command
        rest = command[3:]
        environment = {}
        i = 0
        while i < len(rest):
            token = rest[i]
            if token == "--env":
                key, _, value = rest[i + 1].partition("=")
                environment[key] = value
                i += 2
                continue
            if token == "--global":
                i += 1
                continue
            break
        name = rest[i]
        assert rest[i + 1] == "--", rest
        spec = {"type": "local", "command": list(rest[i + 2 :]), "environment": environment}
        return name, spec

    def _upsert(self, name, spec):
        text = (
            self.config_path.read_text(encoding="utf-8")
            if self.config_path.exists()
            else SKELETON
        )
        span = _servers_span(text)
        assert span is not None, "sandbox config has no mcp.servers object"
        block = json.dumps(spec)
        found = _locate(text, span[0], span[1], name)
        if found is not None:
            key_start, v_start, v_end = found
            text = text[:v_start] + block + text[v_end:]
        else:
            insert_at = span[0] + 1
            text = (
                text[:insert_at]
                + f'\n      {json.dumps(name)}: {block},\n      '
                + text[insert_at:]
            )
        self.config_path.write_text(text, encoding="utf-8")


# --------------------------------------------------------------------------- #
# Full cycle
# --------------------------------------------------------------------------- #


class LifecycleCycleTests(unittest.TestCase):
    PRESENT = ("python", "python3", "node", "npx", "opencode")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.target = self.base / "target"
        self.target.mkdir()
        self.se_root = self._make_sandbox_se_root(self.base / "se-root")
        self.config = self.target / "opencode.jsonc"
        self.which = lambda name: name if name in self.PRESENT else None
        self._patches = [
            mock.patch.object(install, "repo_root", return_value=self.se_root),
            mock.patch.object(sync, "repo_root", return_value=self.se_root),
            mock.patch.object(update_lifecycle, "repo_root", return_value=self.se_root),
        ]
        for patch in self._patches:
            patch.start()

    def tearDown(self):
        for patch in self._patches:
            patch.stop()
        self._tmp.cleanup()

    # -- helpers ----------------------------------------------------------- #

    @staticmethod
    def _make_sandbox_se_root(se_root):
        (se_root / "TEMPLATES" / "mcp").mkdir(parents=True)
        version = (support.REPO_ROOT / "VERSION").read_text(encoding="utf-8")
        (se_root / "VERSION").write_text(version, encoding="utf-8")
        for src in (support.REPO_ROOT / "TEMPLATES" / "mcp").glob("*.json.tmpl"):
            shutil.copy2(src, se_root / "TEMPLATES" / "mcp" / src.name)
        return se_root

    def _template_path(self, key):
        return self.se_root / "TEMPLATES" / "mcp" / f"{key}.json.tmpl"

    def _mutate_template(self, key, mutate):
        path = self._template_path(key)
        data = json.loads(path.read_text(encoding="utf-8"))
        mutate(data)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _declared_spec(self, name):
        templates = install.load_mcp_templates(self.se_root)
        template = next(t for t in templates if t["name"] == name)
        return install.resolved_server_spec(
            template,
            se_root=self.se_root,
            project=self.target,
            project_id=install.read_project_id(self.target),
            interpreter="python3",
        )

    def _capture(self, func):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = func()
        return code, buffer.getvalue()

    def _install_args(self, dry_run=False, json_out=False):
        return types.SimpleNamespace(**{
            "project": str(self.target), "global": False, "no_register": False,
            "generate_adapter": False, "dry_run": dry_run, "json": json_out,
            "with_": None,
        })

    def _sync_args(self, dry_run=False, json_out=False):
        return types.SimpleNamespace(project=str(self.target), dry_run=dry_run, json=json_out)

    def _update_args(self, dry_run=False, json_out=False):
        return types.SimpleNamespace(project=str(self.target), dry_run=dry_run, json=json_out)

    def _uninstall_args(self, apply=False, dry_run=False, json_out=False):
        return types.SimpleNamespace(
            project=str(self.target), apply=apply, dry_run=dry_run, json=json_out
        )

    def _names(self):
        return {item["name"] for item in mcpconfig.list_servers(mcpconfig.read_config(self.config))}

    # -- phases ------------------------------------------------------------ #

    def _phase_install(self):
        # the sandbox config ships with a pre-existing (foreign) entry + comment;
        # SE's direct-write registration must keep both untouched
        self.config.write_text(SKELETON, encoding="utf-8")
        fake = FakeOpencode(self.config)
        code, out = self._capture(
            lambda: install.run(
                self._install_args(), platform_name="windows", runner=fake, which=self.which
            )
        )
        self.assertEqual(code, 0, out)
        # installation writes the runtime config directly (no `opencode mcp add`
        # shell-out), so the injected runner is never called
        self.assertEqual(fake.calls, [])

        # state written where the lifecycle expects it
        self.assertTrue(lc.state_path(self.target).exists())
        state = lc.load_state(self.target)
        self.assertIsNotNone(state)
        self.assertEqual(sorted(state["servers"]), sorted(SE_SERVERS))
        self.assertEqual(state["scope"], "project")
        self.assertEqual(state["runtime"], "opencode")
        self.assertTrue(all(len(rec["declared"]) == 64 for rec in state["servers"].values()))

        # config carries the SE entries AND keeps the foreign entry
        self.assertTrue(self.config.exists())
        self.assertEqual(self._names(), set(SE_SERVERS) | {"foreign-server"})
        self.assertIn(FOREIGN_MARKER, self.config.read_text(encoding="utf-8"))
        return state

    def _phase_sync_idempotent(self):
        config_before = self.config.read_bytes()
        state_before = lc.state_path(self.target).read_bytes()
        for _ in range(2):
            fake = FakeOpencode(self.config)
            code, out = self._capture(
                lambda: sync.cmd_sync(
                    self._sync_args(), platform_name="windows", runner=fake, which=self.which
                )
            )
            self.assertEqual(code, 0, out)
            self.assertIn("Up to date", out)
            self.assertIn("Applied: nothing", out)
            self.assertEqual(fake.calls, [], "a no-op sync must not register anything")
        self.assertEqual(self.config.read_bytes(), config_before)
        self.assertEqual(lc.state_path(self.target).read_bytes(), state_before)

    def _phase_update_noop(self):
        config_before = self.config.read_bytes()
        state_before = lc.state_path(self.target).read_bytes()
        fake = FakeOpencode(self.config)
        code, out = self._capture(
            lambda: update_lifecycle.cmd_update(
                self._update_args(), platform_name="windows", runner=fake, which=self.which
            )
        )
        self.assertEqual(code, 0, out)
        self.assertIn("No changes", out)
        self.assertEqual(fake.calls, [])
        self.assertEqual(self.config.read_bytes(), config_before)
        self.assertEqual(lc.state_path(self.target).read_bytes(), state_before)

    def _phase_sync_changed_spec(self):
        self._mutate_template("skill-server", lambda d: d["args"].append("--verbose"))
        new_spec = self._declared_spec("se-skill-server")
        fake = FakeOpencode(self.config)
        code, out = self._capture(
            lambda: sync.cmd_sync(
                self._sync_args(), platform_name="windows", runner=fake, which=self.which
            )
        )
        self.assertEqual(code, 0, out)
        self.assertIn("SE-owned changed", out)
        self.assertEqual(len(fake.calls), 1)
        self.assertIn("se-skill-server", fake.calls[0])

        state = lc.load_state(self.target)
        self.assertEqual(state["servers"]["se-skill-server"]["declared"], lc.spec_hash(new_spec))
        entry = mcpconfig.read_config(self.config)["mcp"]["servers"]["se-skill-server"]
        self.assertEqual(entry["command"], new_spec["command"])

    def _phase_update_changed_spec(self):
        self._mutate_template("context7", lambda d: d["args"].append("--verbose"))
        new_spec = self._declared_spec("context7")
        fake = FakeOpencode(self.config)
        code, out = self._capture(
            lambda: update_lifecycle.cmd_update(
                self._update_args(), platform_name="windows", runner=fake, which=self.which
            )
        )
        self.assertEqual(code, 0, out)
        self.assertEqual(len(fake.calls), 1, out)
        self.assertIn("Applied: context7", out)
        self.assertIn("Backups:", out)

        state = lc.load_state(self.target)
        self.assertEqual(state["servers"]["context7"]["declared"], lc.spec_hash(new_spec))
        entry = mcpconfig.read_config(self.config)["mcp"]["servers"]["context7"]
        self.assertEqual(entry["command"], new_spec["command"])
        backups = list((self.target / ".se" / "backups").glob("*"))
        self.assertTrue(backups, "update must back up config + state before applying")

    def _phase_update_failure_rollback(self):
        self._mutate_template("filesystem", lambda d: d["args"].append("--extra"))
        config_before = self.config.read_bytes()
        state_before = lc.state_path(self.target).read_bytes()

        fake = FakeOpencode(self.config, fail_on={"filesystem"})
        code, out = self._capture(
            lambda: update_lifecycle.cmd_update(
                self._update_args(json_out=True),
                platform_name="windows",
                runner=fake,
                which=self.which,
            )
        )
        self.assertEqual(code, 1, out)
        details = json.loads(out)["details"]
        self.assertEqual(details["status"], "BLOCKED")
        self.assertTrue(details["rollback"]["config_restored"])
        self.assertTrue(details["rollback"]["state_restored"])
        self.assertEqual(len(details["rollback"]["config_before_hash"]), 64)
        self.assertEqual(len(details["rollback"]["state_before_hash"]), 64)

        # the whole point of rollback: the pre-update bytes are back, both files
        self.assertEqual(self.config.read_bytes(), config_before)
        self.assertEqual(lc.state_path(self.target).read_bytes(), state_before)

        # restore the sandbox declared source so the remaining lifecycle is clean
        self._mutate_template("filesystem", lambda d: d["args"].remove("--extra"))

    def _phase_uninstall_plan(self):
        config_before = self.config.read_bytes()
        state_before = lc.state_path(self.target).read_bytes()
        backups_before = sorted((self.target / ".se" / "backups").glob("*"))

        code, out = self._capture(
            lambda: uninstall.cmd_uninstall(self._uninstall_args(), platform_name="windows")
        )
        self.assertEqual(code, 0, out)
        self.assertIn("Would remove", out)
        self.assertIn("foreign-server", out)

        self.assertEqual(self.config.read_bytes(), config_before)
        self.assertEqual(lc.state_path(self.target).read_bytes(), state_before)
        self.assertEqual(sorted((self.target / ".se" / "backups").glob("*")), backups_before)

    def _phase_uninstall_apply(self):
        config_before = self.config.read_bytes()
        foreign_block_before = _server_block(self.config.read_text(encoding="utf-8"), "foreign-server")

        code, out = self._capture(
            lambda: uninstall.cmd_uninstall(
                self._uninstall_args(apply=True), platform_name="windows"
            )
        )
        self.assertEqual(code, 0, out)
        self.assertIn("Removed", out)

        config_after = self.config.read_text(encoding="utf-8")
        # ONLY the SE-owned servers were removed...
        self.assertEqual(self._names(), {"foreign-server"})
        # ...and the foreign entry is preserved byte-for-byte
        self.assertIn(foreign_block_before, config_after)
        self.assertIn(FOREIGN_MARKER, config_after)
        self.assertNotEqual(config_after, config_before.decode("utf-8"))
        for name in SE_SERVERS:
            self.assertNotIn(f'"{name}"', config_after)

        # state audit trail + backup + retained .se/
        state = lc.load_state(self.target)
        self.assertEqual(state["servers"], {})
        self.assertEqual({entry["name"] for entry in state["uninstalled"]}, set(SE_SERVERS))
        self.assertTrue((self.target / ".se").exists())
        self.assertTrue(lc.state_path(self.target).exists())
        self.assertTrue(list((self.target / ".se" / "backups").glob("*")))

    def test_full_lifecycle_cycle(self):
        """install -> sync (no-op) -> update (no-op) -> change -> failure -> uninstall."""
        self._phase_install()
        self._phase_sync_idempotent()
        self._phase_update_noop()
        self._phase_sync_changed_spec()
        self._phase_update_changed_spec()
        self._phase_update_failure_rollback()
        self._phase_uninstall_plan()
        self._phase_uninstall_apply()

        # end state consistent: config holds exactly the foreign entry, state is
        # empty of managed servers but keeps the removal audit
        parsed = mcpconfig.read_config(self.config)
        self.assertEqual(
            [item["name"] for item in mcpconfig.list_servers(parsed)], ["foreign-server"]
        )
        state = lc.load_state(self.target)
        self.assertEqual(state["schema_version"], "1")
        self.assertEqual(state["servers"], {})
        self.assertEqual(len(state["uninstalled"]), len(SE_SERVERS))


class DualModeUpdateDispatchTests(unittest.TestCase):
    """``se update`` is one command with two modes; the no-record form is the lifecycle."""

    def test_no_record_dispatches_to_lifecycle_update(self):
        args = types.SimpleNamespace(record=None)
        with mock.patch("se_core.update.cmd_update", return_value=42) as patched:
            self.assertEqual(commands.cmd_update(args), 42)
            patched.assert_called_once_with(args)

    def test_record_without_id_is_a_usage_error(self):
        args = types.SimpleNamespace(record="task", record_id=None)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = commands.cmd_update(args)
        self.assertEqual(code, 1)
        self.assertIn("record id is required", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
