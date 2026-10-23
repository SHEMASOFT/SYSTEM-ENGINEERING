"""Unit tests for ``se_core/upgrade.py`` (read-only planning phase).

Hermetic: temporary directories only, no network, no real git. Every git
interaction goes through an injected scripted runner, so the tests also pin the
exact argv the module builds (``git ls-remote --tags --refs origin v*``,
``git status --porcelain --untracked-files=no``, ``git tag --list v*``).
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402,F401  (puts SCRIPTS on sys.path)

from se_core import lifecycle_state as lc  # noqa: E402
from se_core import mcpconfig  # noqa: E402
from se_core import upgrade  # noqa: E402

NOW = datetime(2026, 10, 23, 1, 20, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Fakes / helpers
# --------------------------------------------------------------------------- #


class FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FakeGit:
    """Scripted git runner: records argv, returns canned output, never writes."""

    def __init__(
        self,
        *,
        status="",
        returncode=0,
        stderr="",
        remote_tags="",
        local_tags="",
        raises=None,
    ):
        self.status = status
        self.returncode = returncode
        self.stderr = stderr
        self.remote_tags = remote_tags
        self.local_tags = local_tags
        self.raises = raises
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        if self.raises is not None:
            raise self.raises
        if "status" in argv:
            return FakeResult(self.returncode, self.status, self.stderr)
        if "ls-remote" in argv:
            return FakeResult(self.returncode, self.remote_tags, self.stderr)
        if "tag" in argv:
            return FakeResult(self.returncode, self.local_tags, self.stderr)
        return FakeResult(0, "", "")

    @property
    def commands(self):
        return [" ".join(call) for call in self.calls]


def which_all(name):
    return name


def which_without(*missing):
    def which(name):
        return None if name in missing else name

    return which


def make_target(
    root,
    *,
    version="0.10.1",
    config=None,
    state=None,
    system_version=None,
    marker=False,
):
    """Create a minimal, clean upgrade target (VERSION + SYSTEM.json)."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "VERSION").write_text(version + "\n", encoding="utf-8")
    (root / "SYSTEM.json").write_text(
        json.dumps(
            {
                "schema_version": "1",
                "master_system_version": system_version or version,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if config is not None:
        (root / "opencode.jsonc").write_text(config, encoding="utf-8")
    if state is not None:
        lc.save_state(state, root)
    if marker:
        lc.state_dir(root).mkdir(parents=True, exist_ok=True)
        (lc.state_dir(root) / upgrade.UPGRADE_MARKER).write_text("{}", encoding="utf-8")
    return root


def sample_state(version="0.10.1"):
    return lc.new_state(
        se_version=version,
        os_name="test",
        target=".",
        scope="project",
    )


def make_args(**over):
    base = {
        "project": None,
        "check": False,
        "dry_run": False,
        "json": False,
        "offline": False,
        "git_path": None,
        "include_projects": False,
        "allow_downgrade": False,
        "allow_prerelease": False,
        "no_sync": False,
    }
    base.update(over)
    return types.SimpleNamespace(**base)


def run_cmd(args, **kwargs):
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = upgrade.cmd_upgrade(args, **kwargs)
    return code, buffer.getvalue()


CONFIG = """{
  // keep this comment
  "mcp": {
    "servers": {
      "foreign-a": {"type": "local", "command": ["x"]}
    }
  }
}
"""


# --------------------------------------------------------------------------- #
# parse_semver
# --------------------------------------------------------------------------- #


class ParseSemverTests(unittest.TestCase):
    def test_accepts_plain_and_v_prefixed(self):
        self.assertEqual(upgrade.parse_semver("1.2.3"), (1, 2, 3))
        self.assertEqual(upgrade.parse_semver("v0.10.1"), (0, 10, 1))
        self.assertEqual(upgrade.parse_semver("  v10.20.30 "), (10, 20, 30))

    def test_rejects_prerelease_and_build_metadata(self):
        for text in ("1.2.3-rc1", "v1.2.3-beta.2", "1.2.3+build.5"):
            self.assertIsNone(upgrade.parse_semver(text), text)

    def test_rejects_garbage(self):
        for text in ("", "1.2", "1.2.3.4", "abc", "v", "1..3", "v1.2.x"):
            self.assertIsNone(upgrade.parse_semver(text), text)
        self.assertIsNone(upgrade.parse_semver(None))
        self.assertIsNone(upgrade.parse_semver(123))


# --------------------------------------------------------------------------- #
# select_target_version
# --------------------------------------------------------------------------- #


class SelectTargetVersionTests(unittest.TestCase):
    def test_newer_tag_is_selected(self):
        result = upgrade.select_target_version(["v0.10.1", "v0.10.2"], "0.10.1")
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["target"], "0.10.2")

    def test_equal_tag_is_up_to_date(self):
        result = upgrade.select_target_version(["v0.10.1"], "0.10.1")
        self.assertEqual(result["status"], "UP_TO_DATE")
        self.assertIsNone(result["target"])

    def test_older_tag_is_downgrade_blocked(self):
        result = upgrade.select_target_version(["v0.9.0"], "0.10.1")
        self.assertEqual(result["status"], "DOWNGRADE_BLOCKED")
        self.assertIsNone(result["target"])

    def test_downgrade_allowed(self):
        result = upgrade.select_target_version(
            ["v0.9.0"], "0.10.1", allow_downgrade=True
        )
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["target"], "0.9.0")

    def test_prerelease_ignored_by_default(self):
        result = upgrade.select_target_version(["v0.10.2-rc1"], "0.10.1")
        self.assertEqual(result["status"], "NO_TAGS")
        self.assertIsNone(result["target"])

    def test_prerelease_allowed(self):
        result = upgrade.select_target_version(
            ["v0.10.2-rc1"], "0.10.1", allow_prerelease=True
        )
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["target"], "0.10.2-rc1")

    def test_stable_release_wins_over_prerelease_of_same_core(self):
        result = upgrade.select_target_version(
            ["v0.10.2-rc1", "v0.10.2"], "0.10.1", allow_prerelease=True
        )
        self.assertEqual(result["target"], "0.10.2")

    def test_empty_and_garbage_tags_are_no_tags(self):
        for tags in ([], ["latest"], ["v1.2"], [None]):
            result = upgrade.select_target_version(tags, "0.10.1")
            self.assertEqual(result["status"], "NO_TAGS", tags)

    def test_refs_tags_prefix_is_accepted(self):
        result = upgrade.select_target_version(
            ["refs/tags/v0.10.2"], "0.10.1"
        )
        self.assertEqual(result["target"], "0.10.2")

    def test_invalid_current_version_raises(self):
        with self.assertRaises(ValueError):
            upgrade.select_target_version(["v1.0.0"], "not-a-version")


# --------------------------------------------------------------------------- #
# list_remote_tags / list_local_tags
# --------------------------------------------------------------------------- #


class ListRemoteTagsTests(unittest.TestCase):
    def test_success_parses_refs_and_builds_the_documented_argv(self):
        runner = FakeGit(
            remote_tags=(
                "1111111111111111111111111111111111111111\trefs/tags/v0.10.1\n"
                "2222222222222222222222222222222222222222\trefs/tags/v0.10.2\n"
            )
        )
        result = upgrade.list_remote_tags(runner)
        self.assertEqual(result, {"tags": ["v0.10.1", "v0.10.2"], "error": None})
        self.assertEqual(
            runner.calls[0],
            ["git", "ls-remote", "--tags", "--refs", "origin", "v*"],
        )

    def test_nonzero_exit_reports_error(self):
        runner = FakeGit(returncode=128, stderr="fatal: no remote")
        result = upgrade.list_remote_tags(runner)
        self.assertEqual(result["tags"], [])
        self.assertIn("no remote", result["error"])

    def test_empty_output_is_not_an_error(self):
        result = upgrade.list_remote_tags(FakeGit(remote_tags=""))
        self.assertEqual(result, {"tags": [], "error": None})

    def test_runner_exception_is_reported(self):
        result = upgrade.list_remote_tags(FakeGit(raises=OSError("boom")))
        self.assertEqual(result["tags"], [])
        self.assertIn("boom", result["error"])

    def test_offline_local_tags_use_git_tag_not_ls_remote(self):
        runner = FakeGit(local_tags="v0.10.1\nv0.10.2\n")
        result = upgrade.list_local_tags(runner)
        self.assertEqual(result["tags"], ["v0.10.1", "v0.10.2"])
        self.assertEqual(runner.calls[0], ["git", "tag", "--list", "v*"])


# --------------------------------------------------------------------------- #
# preflight
# --------------------------------------------------------------------------- #


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, runner=None, **over):
        kwargs = {
            "git_runner": runner or FakeGit(),
            "current_version": "0.10.1",
            "which": which_all,
        }
        kwargs.update(over)
        return upgrade.preflight(self.root, **kwargs)

    def _check(self, result, name):
        return next(item for item in result["checks"] if item["name"] == name)

    def test_clean_target_passes_every_check(self):
        make_target(self.root, config=CONFIG, state=sample_state())
        result = self._run()
        self.assertEqual(result["status"], "PASS", result["blockers"])
        self.assertEqual(result["blockers"], [])
        self.assertTrue(all(c["status"] == "PASS" for c in result["checks"]))

    def test_no_config_or_state_is_not_a_blocker(self):
        make_target(self.root)
        result = self._run()
        self.assertEqual(result["status"], "PASS", result["blockers"])
        self.assertEqual(self._check(result, "config")["status"], "PASS")
        self.assertEqual(self._check(result, "state")["status"], "PASS")

    def test_dirty_tree_blocks(self):
        make_target(self.root)
        result = self._run(FakeGit(status=" M SCRIPTS/se_core/cli.py\n"))
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(self._check(result, "work_tree")["status"], "BLOCKED")
        self.assertTrue(any("uncommitted" in blocker for blocker in result["blockers"]))

    def test_git_status_failure_blocks(self):
        make_target(self.root)
        result = self._run(FakeGit(returncode=128, stderr="fatal: not a git repository"))
        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(any("not a git repository" in b for b in result["blockers"]))

    def test_git_runner_exception_blocks(self):
        make_target(self.root)
        result = self._run(FakeGit(raises=OSError("no subprocess")))
        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(any("git status failed" in b for b in result["blockers"]))

    def test_missing_git_blocks(self):
        make_target(self.root)
        result = self._run(which=which_without("git"))
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(self._check(result, "git")["status"], "BLOCKED")

    def test_missing_version_blocks(self):
        make_target(self.root)
        (self.root / "VERSION").unlink()
        result = self._run()
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(self._check(result, "version")["status"], "BLOCKED")

    def test_current_version_mismatch_blocks(self):
        make_target(self.root, version="0.10.1")
        result = self._run(current_version="0.10.0")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(any("expected current version" in b for b in result["blockers"]))

    def test_system_json_mismatch_blocks(self):
        make_target(self.root, system_version="0.9.9")
        result = self._run()
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(self._check(result, "system_json")["status"], "BLOCKED")

    def test_unparseable_config_blocks(self):
        make_target(self.root, config="{ this is not json")
        result = self._run()
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(self._check(result, "config")["status"], "BLOCKED")

    def test_corrupt_state_blocks(self):
        make_target(self.root)
        (lc.state_dir(self.root)).mkdir(parents=True)
        lc.state_path(self.root).write_text("{ not json", encoding="utf-8")
        result = self._run()
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(self._check(result, "state")["status"], "BLOCKED")

    def test_unsupported_state_schema_blocks(self):
        make_target(self.root)
        (lc.state_dir(self.root)).mkdir(parents=True)
        lc.state_path(self.root).write_text(
            json.dumps({"schema_version": "2", "servers": {}}), encoding="utf-8"
        )
        result = self._run()
        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(any("schema_version" in b for b in result["blockers"]))

    def test_missing_opencode_blocks(self):
        make_target(self.root)
        result = self._run(which=which_without("opencode"))
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(self._check(result, "opencode")["status"], "BLOCKED")

    def test_no_sync_skips_opencode(self):
        make_target(self.root)
        result = self._run(which=which_without("opencode"), require_opencode=False)
        self.assertEqual(result["status"], "PASS", result["blockers"])

    def test_interrupted_upgrade_marker_blocks(self):
        make_target(self.root, marker=True)
        result = self._run()
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(self._check(result, "upgrade_marker")["status"], "BLOCKED")

    def test_preflight_never_creates_se_dir(self):
        make_target(self.root)
        self._run()
        self.assertFalse((self.root / ".se").exists())


# --------------------------------------------------------------------------- #
# snapshot / verify / restore
# --------------------------------------------------------------------------- #


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        make_target(self.root, config=CONFIG, state=sample_state())
        self.config_bytes = (self.root / "opencode.jsonc").read_bytes()
        self.state_bytes = lc.state_path(self.root).read_bytes()

    def tearDown(self):
        self._tmp.cleanup()

    def _create(self, **over):
        kwargs = {
            "from_version": "0.10.1",
            "to_version": "0.10.2",
            "git_head": "abc1234",
            "now": NOW,
        }
        kwargs.update(over)
        return upgrade.create_snapshot(self.root, **kwargs)

    def test_creates_snapshot_with_manifest_and_copies(self):
        result = self._create()
        snapshot = Path(result["snapshot_dir"])
        self.assertEqual(
            snapshot.name, "upgrade-0.10.1-to-0.10.2-20261023T012000Z-01"
        )
        self.assertEqual(snapshot.parent, lc.backup_dir(self.root))
        manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema_version"], "1")
        self.assertEqual(manifest["operation"], "upgrade")
        self.assertEqual(manifest["from_version"], "0.10.1")
        self.assertEqual(manifest["to_version"], "0.10.2")
        self.assertEqual(manifest["created_at"], "2026-10-23T01:20:00Z")
        self.assertEqual(manifest["git_head_before"], "abc1234")
        self.assertEqual(manifest["state_schema"], "1")
        self.assertFalse(manifest["include_projects"])
        paths = {entry["path"] for entry in manifest["files"]}
        self.assertEqual(paths, {"opencode.jsonc", ".se/lifecycle-state.json"})
        self.assertEqual((snapshot / "opencode.jsonc").read_bytes(), self.config_bytes)
        self.assertEqual(
            (snapshot / ".se" / "lifecycle-state.json").read_bytes(), self.state_bytes
        )
        self.assertEqual(upgrade.verify_snapshot(snapshot), {"ok": True, "errors": []})

    def test_same_second_snapshots_do_not_collide(self):
        first = self._create()
        second = self._create()
        self.assertNotEqual(first["snapshot_dir"], second["snapshot_dir"])
        self.assertTrue(first["snapshot_dir"].endswith("-01"))
        self.assertTrue(second["snapshot_dir"].endswith("-02"))

    def test_verify_detects_altered_bytes(self):
        result = self._create()
        snapshot = Path(result["snapshot_dir"])
        (snapshot / "opencode.jsonc").write_text("tampered", encoding="utf-8")
        verification = upgrade.verify_snapshot(snapshot)
        self.assertFalse(verification["ok"])
        self.assertTrue(any("sha256 mismatch" in e for e in verification["errors"]))

    def test_verify_detects_missing_manifest(self):
        verification = upgrade.verify_snapshot(self.root / "missing")
        self.assertFalse(verification["ok"])
        self.assertTrue(any("manifest not found" in e for e in verification["errors"]))

    def test_restore_refuses_to_overwrite_unrecorded_changes(self):
        result = self._create()
        (self.root / "opencode.jsonc").write_text("changed by someone else", encoding="utf-8")
        restore = upgrade.restore_snapshot(result["snapshot_dir"])
        self.assertFalse(restore["ok"])
        self.assertNotIn("opencode.jsonc", restore["restored"])
        self.assertIn("opencode.jsonc", restore["skipped"])
        self.assertEqual(
            (self.root / "opencode.jsonc").read_text(encoding="utf-8"),
            "changed by someone else",
        )
        # The untouched state file is still restored (it matches the snapshot).
        self.assertIn(".se/lifecycle-state.json", restore["restored"])

    def test_restore_with_force_restores_original_bytes(self):
        result = self._create()
        (self.root / "opencode.jsonc").write_text("changed by someone else", encoding="utf-8")
        restore = upgrade.restore_snapshot(result["snapshot_dir"], force=True)
        self.assertTrue(restore["ok"], restore["errors"])
        self.assertEqual(
            (self.root / "opencode.jsonc").read_bytes(), self.config_bytes
        )
        self.assertIn("opencode.jsonc", restore["hashes"])

    def test_restore_restores_missing_file(self):
        result = self._create()
        (self.root / "opencode.jsonc").unlink()
        restore = upgrade.restore_snapshot(result["snapshot_dir"])
        self.assertTrue(restore["ok"], restore["errors"])
        self.assertEqual(
            (self.root / "opencode.jsonc").read_bytes(), self.config_bytes
        )

    def test_restore_does_not_delete_extra_files(self):
        result = self._create()
        extra = self.root / "keep-me.txt"
        extra.write_text("extra", encoding="utf-8")
        restore = upgrade.restore_snapshot(result["snapshot_dir"])
        self.assertTrue(restore["ok"], restore["errors"])
        self.assertTrue(extra.exists())

    def test_restore_refuses_a_corrupt_snapshot(self):
        result = self._create()
        snapshot = Path(result["snapshot_dir"])
        (snapshot / "opencode.jsonc").write_text("tampered", encoding="utf-8")
        restore = upgrade.restore_snapshot(snapshot)
        self.assertFalse(restore["ok"])
        self.assertTrue(any("sha256 mismatch" in e for e in restore["errors"]))

    def test_projects_are_excluded_by_default(self):
        memory = self.root / "PROJECTS" / "PRJ-1" / "memories" / "MEM-1.json"
        memory.parent.mkdir(parents=True)
        memory.write_text('{"id": "MEM-1"}\n', encoding="utf-8")
        result = self._create()
        paths = {entry["path"] for entry in result["manifest"]["files"]}
        self.assertNotIn("PROJECTS/PRJ-1/memories/MEM-1.json", paths)
        self.assertFalse((Path(result["snapshot_dir"]) / "PROJECTS").exists())

    def test_include_projects_copies_and_hashes_every_file(self):
        memory = self.root / "PROJECTS" / "PRJ-1" / "memories" / "MEM-1.json"
        memory.parent.mkdir(parents=True)
        memory.write_text('{"id": "MEM-1"}\n', encoding="utf-8")
        result = self._create(include_projects=True)
        entries = {entry["path"]: entry for entry in result["manifest"]["files"]}
        self.assertIn("PROJECTS/PRJ-1/memories/MEM-1.json", entries)
        self.assertEqual(entries["PROJECTS/PRJ-1/memories/MEM-1.json"]["bytes"], len(memory.read_bytes()))
        self.assertTrue(result["manifest"]["include_projects"])
        self.assertTrue(upgrade.verify_snapshot(result["snapshot_dir"])["ok"])


# --------------------------------------------------------------------------- #
# cmd_upgrade (read-only planning)
# --------------------------------------------------------------------------- #


class CmdUpgradeCheckTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        make_target(self.root, config=CONFIG)

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, runner=None, **over):
        runner = runner or FakeGit(remote_tags="abc\trefs/tags/v0.10.2\n")
        args = make_args(project=str(self.root), check=True, **over)
        return run_cmd(args, git_runner=runner, which=which_all)

    def test_check_reports_the_newer_target_and_writes_nothing(self):
        code, output = self._run()
        self.assertEqual(code, 0)
        self.assertIn("Target version: 0.10.2", output)
        self.assertIn("Status: PASS", output)
        self.assertFalse((self.root / ".se").exists())
        self.assertEqual(
            sorted(path.name for path in self.root.iterdir()),
            ["SYSTEM.json", "VERSION", "opencode.jsonc"],
        )

    def test_check_json_envelope(self):
        code, output = self._run(json=True)
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload["report"], "se.report/1")
        self.assertEqual(payload["operation"], "upgrade")
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["details"]["selection"]["target"], "0.10.2")
        self.assertEqual(payload["details"]["writes"], [])
        self.assertFalse((self.root / ".se").exists())

    def test_check_without_tags_is_unknown_and_non_fatal(self):
        code, output = self._run(FakeGit(remote_tags=""))
        self.assertEqual(code, 0)
        self.assertIn("NO_TAGS", output)
        self.assertIn("Status: UNKNOWN", output)
        self.assertFalse((self.root / ".se").exists())

    def test_check_offline_never_calls_ls_remote(self):
        runner = FakeGit(local_tags="")
        code, output = self._run(runner, offline=True)
        self.assertEqual(code, 0)
        self.assertIn("Status: UNKNOWN", output)
        self.assertTrue(all("ls-remote" not in command for command in runner.commands))
        self.assertTrue(any("tag --list" in command for command in runner.commands))

    def test_check_offline_uses_local_tags(self):
        code, output = self._run(FakeGit(local_tags="v0.10.2\n"), offline=True)
        self.assertEqual(code, 0)
        self.assertIn("Target version: 0.10.2", output)

    def test_check_dirty_tree_blocks_and_writes_nothing(self):
        code, output = self._run(FakeGit(status=" M SCRIPTS/x.py\n"))
        self.assertEqual(code, 1)
        self.assertIn("Status: BLOCKED", output)
        self.assertFalse((self.root / ".se").exists())

    def test_check_downgrade_is_blocked(self):
        code, output = self._run(FakeGit(remote_tags="abc\trefs/tags/v0.9.0\n"))
        self.assertEqual(code, 1)
        self.assertIn("DOWNGRADE_BLOCKED", output)

    def test_check_downgrade_allowed(self):
        code, output = self._run(
            FakeGit(remote_tags="abc\trefs/tags/v0.9.0\n"), allow_downgrade=True
        )
        self.assertEqual(code, 0)
        self.assertIn("Target version: 0.9.0", output)

    def test_check_up_to_date_is_info(self):
        code, output = self._run(FakeGit(remote_tags="abc\trefs/tags/v0.10.1\n"))
        self.assertEqual(code, 0)
        self.assertIn("UP_TO_DATE", output)
        self.assertIn("Status: INFO", output)

    def test_check_prerelease_requires_the_flag(self):
        runner = FakeGit(remote_tags="abc\trefs/tags/v0.10.2-rc1\n")
        code, output = self._run(runner)
        self.assertEqual(code, 0)
        self.assertIn("Status: UNKNOWN", output)
        code, output = self._run(runner, allow_prerelease=True)
        self.assertEqual(code, 0)
        self.assertIn("Target version: 0.10.2-rc1", output)

    def test_check_requires_opencode_unless_no_sync(self):
        args = make_args(project=str(self.root), check=True)
        runner = FakeGit(remote_tags="abc\trefs/tags/v0.10.2\n")
        code, output = run_cmd(
            args, git_runner=runner, which=which_without("opencode")
        )
        self.assertEqual(code, 1)
        self.assertIn("opencode", output)
        args.no_sync = True
        code, output = run_cmd(
            args, git_runner=runner, which=which_without("opencode")
        )
        self.assertEqual(code, 0)

    def test_check_with_git_path_uses_it(self):
        args = make_args(project=str(self.root), check=True, git_path="C:/git.exe")
        code, _output = run_cmd(
            args,
            git_runner=FakeGit(remote_tags="abc\trefs/tags/v0.10.2\n"),
            which=which_without("git"),
        )
        self.assertEqual(code, 0)


class CmdUpgradeExecuteTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        make_target(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_execute_mode_is_blocked_without_any_write(self):
        runner = FakeGit(remote_tags="abc\trefs/tags/v0.10.2\n")
        code, output = run_cmd(
            make_args(project=str(self.root)), git_runner=runner, which=which_all
        )
        self.assertEqual(code, 1)
        self.assertIn("upgrade execution not implemented in this phase", output)
        self.assertIn("Status: BLOCKED", output)
        self.assertEqual(runner.calls, [])
        self.assertFalse((self.root / ".se").exists())

    def test_execute_mode_json_envelope(self):
        code, output = run_cmd(
            make_args(project=str(self.root), json=True),
            git_runner=FakeGit(),
            which=which_all,
        )
        self.assertEqual(code, 1)
        payload = json.loads(output)
        self.assertEqual(payload["status"], "BLOCKED")
        self.assertEqual(
            payload["details"]["blockers"],
            ["upgrade execution not implemented in this phase"],
        )
        self.assertFalse((self.root / ".se").exists())

    def test_dry_run_behaves_like_check(self):
        code, output = run_cmd(
            make_args(project=str(self.root), dry_run=True),
            git_runner=FakeGit(remote_tags="abc\trefs/tags/v0.10.2\n"),
            which=which_all,
        )
        self.assertEqual(code, 0)
        self.assertIn("se upgrade (dry-run)", output)
        self.assertIn("Target version: 0.10.2", output)
        self.assertFalse((self.root / ".se").exists())


if __name__ == "__main__":
    unittest.main()
