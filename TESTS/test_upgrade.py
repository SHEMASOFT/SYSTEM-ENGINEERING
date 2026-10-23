"""Unit tests for ``se_core/upgrade.py``.

Hermetic: temporary directories only, no network, no real git. Every git
interaction goes through an injected scripted runner, so the tests also pin the
exact argv the module builds (``git ls-remote --tags --refs origin``,
``git --no-optional-locks status --porcelain --untracked-files=no``,
``git tag --list``,
``git merge --ff-only <tag>``, ``git reset --hard <commit>``).

Coverage: SemVer/tag selection (with and without the ``v`` prefix), the
migration runner and its ledger, snapshot/restore, marker/history helpers,
``rollback_upgrade`` and the ``--check`` / ``--recover`` / execute flows.
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
from se_core.cli import build_parser  # noqa: E402

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


class ExecutionFakeGit(FakeGit):
    """Fake git that also models ``rev-parse`` / ``fetch`` / ``merge`` / ``reset``.

    It never touches a repository: ``merge`` only advances the simulated HEAD,
    and ``reset`` only moves it back.
    """

    def __init__(
        self,
        *,
        head="a" * 40,
        tag_commit="b" * 40,
        merge_rc=0,
        fetch_rc=0,
        reset_rc=0,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.head = head
        self.tag_commit = tag_commit
        self.merge_rc = merge_rc
        self.fetch_rc = fetch_rc
        self.reset_rc = reset_rc

    def __call__(self, argv, **kwargs):
        if "rev-parse" in argv:
            self.calls.append(list(argv))
            ref = argv[2] if len(argv) > 2 else "HEAD"
            if ref == "HEAD":
                return FakeResult(0, self.head + "\n", "")
            if ref.endswith("^{commit}"):
                return FakeResult(0, self.tag_commit + "\n", "")
            return FakeResult(0, self.head + "\n", "")
        if "merge" in argv:
            self.calls.append(list(argv))
            if self.merge_rc == 0:
                self.head = self.tag_commit
            return FakeResult(self.merge_rc, "", "not possible to fast-forward")
        if "fetch" in argv:
            self.calls.append(list(argv))
            return FakeResult(self.fetch_rc, "", "")
        if "reset" in argv:
            self.calls.append(list(argv))
            if self.reset_rc == 0:
                self.head = argv[-1]
            return FakeResult(self.reset_rc, "", "")
        return super().__call__(argv, **kwargs)


class FakeStepRunner:
    """Records ``se adapter`` / ``se sync`` / ``se doctor`` invocations."""

    def __init__(
        self,
        *,
        fail_on=(),
        doctor_status="PASS",
        doctor_summary=None,
        doctor_checks=None,
        doctor_rc=0,
        on_sync=None,
    ):
        self.fail_on = set(fail_on)
        self.doctor_status = doctor_status
        self.doctor_summary = doctor_summary
        self.doctor_checks = doctor_checks
        self.doctor_rc = doctor_rc
        self.on_sync = on_sync
        self.calls: list[dict] = []

    def __call__(self, argv, *, cwd=None):
        self.calls.append({"argv": list(argv), "cwd": str(cwd) if cwd else None})
        if "doctor" in argv:
            payload = {"status": self.doctor_status}
            if self.doctor_summary is not None or self.doctor_checks is not None:
                payload["details"] = {}
                if self.doctor_summary is not None:
                    payload["details"]["summary"] = self.doctor_summary
                if self.doctor_checks is not None:
                    payload["details"]["checks"] = self.doctor_checks
            return FakeResult(self.doctor_rc, json.dumps(payload), "")
        if "sync" in argv:
            if self.on_sync is not None:
                self.on_sync(cwd)
            if "sync" in self.fail_on:
                return FakeResult(1, "", "injected sync failure")
        if "adapter" in argv and "adapter" in self.fail_on:
            return FakeResult(1, "", "injected adapter failure")
        return FakeResult(0, "", "")


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
        "recover": False,
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
            ["git", "ls-remote", "--tags", "--refs", "origin"],
        )

    def test_accepts_tags_without_the_v_prefix(self):
        runner = FakeGit(
            remote_tags=(
                "1111111111111111111111111111111111111111\trefs/tags/0.10.1\n"
                "2222222222222222222222222222222222222222\trefs/tags/v0.10.2\n"
            )
        )
        result = upgrade.list_remote_tags(runner)
        self.assertEqual(result["tags"], ["0.10.1", "v0.10.2"])

    def test_prereleases_are_listed_but_filtered_by_selection(self):
        runner = FakeGit(
            remote_tags="1111111111111111111111111111111111111111\trefs/tags/v0.10.2-rc1\n"
        )
        result = upgrade.list_remote_tags(runner)
        self.assertEqual(result["tags"], ["v0.10.2-rc1"])

    def test_ignores_non_version_tags_and_deduplicates(self):
        runner = FakeGit(
            remote_tags=(
                "1111111111111111111111111111111111111111\trefs/tags/latest\n"
                "2222222222222222222222222222222222222222\trefs/tags/v0.10.2\n"
                "3333333333333333333333333333333333333333\trefs/tags/v0.10.2\n"
                "4444444444444444444444444444444444444444\trefs/tags/1.2\n"
            )
        )
        result = upgrade.list_remote_tags(runner)
        self.assertEqual(result["tags"], ["v0.10.2"])

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
        self.assertEqual(runner.calls[0], ["git", "tag", "--list"])

    def test_local_tags_without_v_are_accepted(self):
        result = upgrade.list_local_tags(FakeGit(local_tags="0.10.1\n0.10.2\n"))
        self.assertEqual(result["tags"], ["0.10.1", "0.10.2"])


class FindTagForVersionTests(unittest.TestCase):
    def test_prefers_the_v_prefixed_tag(self):
        self.assertEqual(
            upgrade.find_tag_for_version(["0.10.2", "v0.10.2"], "0.10.2"),
            "v0.10.2",
        )

    def test_falls_back_to_the_unprefixed_tag(self):
        self.assertEqual(
            upgrade.find_tag_for_version(["0.10.2"], "0.10.2"), "0.10.2"
        )

    def test_prerelease_tag_is_found(self):
        self.assertEqual(
            upgrade.find_tag_for_version(["v0.10.2-rc1"], "0.10.2-rc1"),
            "v0.10.2-rc1",
        )

    def test_missing_version_returns_none(self):
        self.assertIsNone(upgrade.find_tag_for_version(["v0.10.1"], "0.10.2"))
        self.assertIsNone(upgrade.find_tag_for_version([], "0.10.2"))
        self.assertIsNone(upgrade.find_tag_for_version(["v1.0.0"], None))


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

    def test_work_tree_probe_cannot_refresh_the_git_index(self):
        """``--check`` must not let git write ``.git/index`` behind our back."""
        make_target(self.root)
        runner = FakeGit()
        self._run(runner)
        status_calls = [call for call in runner.calls if "status" in call]
        self.assertEqual(len(status_calls), 1)
        self.assertEqual(
            status_calls[0],
            [
                "git",
                "--no-optional-locks",
                "status",
                "--porcelain",
                "--untracked-files=no",
            ],
        )

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

    def test_manifest_records_present_paths_as_not_absent(self):
        result = self._create()
        # Config and state exist; only the migration ledger is absent.
        self.assertEqual(result["manifest"]["absent"], [".se/migrations.json"])
        self.assertEqual(result["absent"], [".se/migrations.json"])

    def test_manifest_absent_is_empty_when_all_canonical_paths_exist(self):
        ledger = lc.state_dir(self.root) / "migrations.json"
        ledger.write_text('{"schema_version": "1", "applied": []}\n', encoding="utf-8")
        result = self._create()
        self.assertEqual(result["manifest"]["absent"], [])
        paths = {entry["path"] for entry in result["manifest"]["files"]}
        self.assertIn(".se/migrations.json", paths)

    def test_manifest_lists_every_absent_canonical_path(self):
        empty = Path(self._tmp.name) / "empty"
        make_target(empty)  # neither config nor state
        result = upgrade.create_snapshot(
            empty,
            from_version="0.10.1",
            to_version="0.10.2",
            git_head="abc1234",
            now=NOW,
        )
        self.assertEqual(
            result["manifest"]["absent"],
            ["opencode.jsonc", ".se/lifecycle-state.json", ".se/migrations.json"],
        )
        self.assertEqual(result["manifest"]["files"], [])

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
# absent paths
# --------------------------------------------------------------------------- #


class AbsentPathTests(unittest.TestCase):
    """Files created by the upgrade are removed only when they were absent."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        make_target(self.root)  # no config, no state, no ledger
        self.snapshot = upgrade.create_snapshot(
            self.root,
            from_version="0.10.1",
            to_version="0.10.2",
            git_head="a" * 40,
            now=NOW,
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_removes_only_paths_that_were_absent(self):
        config = self.root / "opencode.jsonc"
        state = lc.state_path(self.root)
        state.parent.mkdir(parents=True, exist_ok=True)
        config.write_text("{}\n", encoding="utf-8")
        state.write_text('{"schema_version": "1"}\n', encoding="utf-8")
        ledger = lc.state_dir(self.root) / "migrations.json"
        ledger.write_text('{"schema_version": "1", "applied": []}\n', encoding="utf-8")

        result = upgrade._remove_absent_paths(
            self.root, self.snapshot["snapshot_dir"]
        )

        self.assertEqual(result["errors"], [])
        self.assertEqual(
            result["removed"],
            ["opencode.jsonc", ".se/lifecycle-state.json", ".se/migrations.json"],
        )
        self.assertFalse(config.exists())
        self.assertFalse(state.exists())
        self.assertFalse(ledger.exists())

    def test_keeps_files_that_were_present_in_the_snapshot(self):
        config = self.root / "opencode.jsonc"
        config.write_text("{}\n", encoding="utf-8")
        snapshot = upgrade.create_snapshot(
            self.root,
            from_version="0.10.1",
            to_version="0.10.2",
            git_head="a" * 40,
            now=NOW,
        )
        config.write_text('{"changed": true}\n', encoding="utf-8")
        state = lc.state_path(self.root)
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text('{"schema_version": "1"}\n', encoding="utf-8")

        result = upgrade._remove_absent_paths(self.root, snapshot["snapshot_dir"])

        self.assertEqual(result["errors"], [])
        self.assertEqual(result["removed"], [".se/lifecycle-state.json"])
        self.assertTrue(config.exists())

    def test_refuses_paths_outside_the_target(self):
        outside = Path(self._tmp.name) / "outside.txt"
        outside.write_text("do not delete", encoding="utf-8")
        manifest_path = Path(self.snapshot["manifest_path"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["absent"] = ["../outside.txt", str(outside)]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        result = upgrade._remove_absent_paths(
            self.root, self.snapshot["snapshot_dir"]
        )

        self.assertEqual(result["removed"], [])
        self.assertEqual(len(result["errors"]), 2)
        self.assertTrue(any("escapes the target" in e for e in result["errors"]))
        self.assertTrue(any("absolute" in e for e in result["errors"]))
        self.assertTrue(outside.exists())

    def test_refuses_to_remove_a_directory(self):
        manifest_path = Path(self.snapshot["manifest_path"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["absent"] = [".se"]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        result = upgrade._remove_absent_paths(
            self.root, self.snapshot["snapshot_dir"]
        )

        self.assertEqual(result["removed"], [])
        self.assertTrue(any("directory" in e for e in result["errors"]))
        self.assertTrue(lc.state_dir(self.root).is_dir())

    def test_rollback_removes_files_created_after_the_snapshot(self):
        marker = {
            "schema_version": "1",
            "from": "0.10.1",
            "to": "0.10.2",
            "tag": "v0.10.2",
            "git_head_before": "a" * 40,
            "snapshot": self.snapshot["snapshot_dir"],
            "started_at": "2026-10-23T01:20:00Z",
            "phase": "sync",
        }
        config = self.root / "opencode.jsonc"
        state = lc.state_path(self.root)
        state.parent.mkdir(parents=True, exist_ok=True)
        config.write_text('{"mcp": {"servers": {}}}\n', encoding="utf-8")
        state.write_text('{"schema_version": "1"}\n', encoding="utf-8")
        upgrade.write_marker(self.root, marker)

        result = upgrade.rollback_upgrade(
            self.root, marker, git_runner=ExecutionFakeGit(head="a" * 40)
        )

        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(
            result["removed_absent"],
            ["opencode.jsonc", ".se/lifecycle-state.json"],
        )
        self.assertFalse(config.exists())
        self.assertFalse(state.exists())
        self.assertFalse(upgrade.marker_path(self.root).exists())

    def test_manifest_without_absent_is_a_noop(self):
        manifest_path = Path(self.snapshot["manifest_path"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        del manifest["absent"]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        result = upgrade._remove_absent_paths(
            self.root, self.snapshot["snapshot_dir"]
        )

        self.assertEqual(result, {"removed": [], "errors": []})


# --------------------------------------------------------------------------- #
# migrations
# --------------------------------------------------------------------------- #


MIGRATION_TEMPLATE = """\
ID = {identifier!r}

def migrate(root, context):
    with open(root / "order.txt", "a", encoding="utf-8") as handle:
        handle.write({identifier!r} + "\\n")
    return {{"id": {identifier!r}}}
"""


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.migrations = self.root / "MIGRATIONS"
        self.migrations.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, name, text):
        path = self.migrations / name
        path.write_text(text, encoding="utf-8")
        return path

    def _run(self, **over):
        kwargs = {
            "from_version": "0.10.1",
            "to_version": "0.10.2",
            "now": NOW,
            "git_head_before": "a" * 40,
        }
        kwargs.update(over)
        return upgrade.run_migrations(self.root, **kwargs)

    def test_absent_directory_is_a_noop(self):
        empty = self.root / "missing"
        result = upgrade.run_migrations(
            self.root,
            from_version="0.10.1",
            to_version="0.10.2",
            migrations_dir=empty,
            now=NOW,
        )
        self.assertEqual(result, {"applied": [], "skipped": [], "errors": []})

    def test_import_leaves_no_pycache_in_the_target(self):
        self._write("001_a.py", MIGRATION_TEMPLATE.format(identifier="001_a"))
        previous = sys.dont_write_bytecode
        sys.dont_write_bytecode = False
        try:
            result = self._run()
        finally:
            sys.dont_write_bytecode = previous
        self.assertEqual(result["applied"], ["001_a"])
        self.assertFalse((self.migrations / "__pycache__").exists())

    def test_applies_in_filename_order_and_writes_the_ledger(self):
        self._write("002_b.py", MIGRATION_TEMPLATE.format(identifier="002_b"))
        self._write("001_a.py", MIGRATION_TEMPLATE.format(identifier="001_a"))
        self._write("_ignored.py", "raise RuntimeError('must not be imported')\n")

        result = self._run()

        self.assertEqual(result["applied"], ["001_a", "002_b"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(
            (self.root / "order.txt").read_text(encoding="utf-8").splitlines(),
            ["001_a", "002_b"],
        )
        ledger = json.loads(
            (self.root / ".se" / "migrations.json").read_text(encoding="utf-8")
        )
        self.assertEqual(ledger["schema_version"], "1")
        self.assertEqual(
            [entry["id"] for entry in ledger["applied"]], ["001_a", "002_b"]
        )
        self.assertTrue(all(entry["version"] == "0.10.2" for entry in ledger["applied"]))
        self.assertTrue(all(entry["applied_at"] for entry in ledger["applied"]))

    def test_second_run_skips_already_applied_ids(self):
        self._write("001_a.py", MIGRATION_TEMPLATE.format(identifier="001_a"))
        self._run()
        result = self._run()
        self.assertEqual(result["applied"], [])
        self.assertEqual(result["skipped"], ["001_a"])
        self.assertEqual(
            (self.root / "order.txt").read_text(encoding="utf-8").splitlines(),
            ["001_a"],
        )

    def test_duplicate_id_is_an_error_and_nothing_runs(self):
        self._write("001_a.py", MIGRATION_TEMPLATE.format(identifier="dup"))
        self._write("002_b.py", MIGRATION_TEMPLATE.format(identifier="dup"))
        result = self._run()
        self.assertEqual(result["applied"], [])
        self.assertTrue(any("duplicate migration ID" in e for e in result["errors"]))
        self.assertFalse((self.root / "order.txt").exists())

    def test_module_without_id_is_an_error(self):
        self._write(
            "001_a.py",
            "def migrate(root, context):\n    return {}\n",
        )
        result = self._run()
        self.assertEqual(result["applied"], [])
        self.assertTrue(any("non-empty string ID" in e for e in result["errors"]))

    def test_module_without_callable_migrate_is_an_error(self):
        self._write("001_a.py", "ID = '001_a'\nmigrate = 42\n")
        result = self._run()
        self.assertEqual(result["applied"], [])
        self.assertTrue(any("not callable" in e for e in result["errors"]))

    def test_raising_migration_propagates_with_id_and_message(self):
        self._write(
            "001_fail.py",
            "ID = '001_fail'\n\n"
            "def migrate(root, context):\n"
            "    raise RuntimeError('injected migration failure')\n",
        )
        with self.assertRaises(upgrade.MigrationError) as raised:
            self._run()
        self.assertIn("001_fail", str(raised.exception))
        self.assertIn("injected migration failure", str(raised.exception))
        self.assertFalse((self.root / ".se" / "migrations.json").exists())

    def test_invalid_ledger_is_an_error(self):
        self._write("001_a.py", MIGRATION_TEMPLATE.format(identifier="001_a"))
        ledger = self.root / ".se" / "migrations.json"
        ledger.parent.mkdir(parents=True)
        ledger.write_text("{ not json", encoding="utf-8")
        result = self._run()
        self.assertEqual(result["applied"], [])
        self.assertTrue(any("ledger unreadable" in e for e in result["errors"]))

    def test_unsupported_ledger_schema_is_an_error(self):
        self._write("001_a.py", MIGRATION_TEMPLATE.format(identifier="001_a"))
        ledger = self.root / ".se" / "migrations.json"
        ledger.parent.mkdir(parents=True)
        ledger.write_text(
            json.dumps({"schema_version": "2", "applied": []}), encoding="utf-8"
        )
        result = self._run()
        self.assertEqual(result["applied"], [])
        self.assertTrue(any("schema_version" in e for e in result["errors"]))


# --------------------------------------------------------------------------- #
# marker / history / rollback
# --------------------------------------------------------------------------- #


class MarkerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self._tmp.cleanup()

    def test_write_read_delete_roundtrip(self):
        marker = {"schema_version": "1", "phase": "fetch"}
        upgrade.write_marker(self.root, marker)
        self.assertEqual(upgrade.read_marker(self.root), marker)
        self.assertTrue(upgrade.marker_path(self.root).exists())
        self.assertTrue(upgrade.delete_marker(self.root))
        self.assertIsNone(upgrade.read_marker(self.root))

    def test_unreadable_marker_reads_as_none(self):
        upgrade.marker_path(self.root).parent.mkdir(parents=True)
        upgrade.marker_path(self.root).write_text("{ not json", encoding="utf-8")
        self.assertIsNone(upgrade.read_marker(self.root))

    def test_recover_without_marker_is_info(self):
        args = make_args(project=str(self.root), recover=True)
        code, output = run_cmd(args, git_runner=FakeGit(), which=which_all)
        self.assertEqual(code, 0)
        self.assertIn("nothing to recover", output)
        self.assertIn("Status: INFO", output)
        self.assertFalse((self.root / ".se").exists())

    def test_recover_without_git_head_before_is_blocked_and_keeps_the_marker(self):
        make_target(self.root)
        snapshot = upgrade.create_snapshot(
            self.root,
            from_version="0.10.1",
            to_version="0.10.2",
            git_head="a" * 40,
            now=NOW,
        )
        marker = {
            "schema_version": "1",
            "from": "0.10.1",
            "to": "0.10.2",
            "tag": "v0.10.2",
            "snapshot": snapshot["snapshot_dir"],
            "phase": "sync",
        }
        upgrade.write_marker(self.root, marker)
        runner = ExecutionFakeGit(head="b" * 40)

        code, output = run_cmd(
            make_args(project=str(self.root), recover=True),
            git_runner=runner,
            which=which_all,
        )

        self.assertEqual(code, 1)
        self.assertIn("no git_head_before", output)
        self.assertIn("Status: BLOCKED", output)
        self.assertTrue(upgrade.marker_path(self.root).exists())
        self.assertEqual(runner.head, "b" * 40)
        self.assertEqual(runner.calls, [])


class RollbackTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        make_target(self.root, config=CONFIG, state=sample_state())
        self.snapshot = upgrade.create_snapshot(
            self.root,
            from_version="0.10.1",
            to_version="0.10.2",
            git_head="a" * 40,
            now=NOW,
        )
        self.config_bytes = (self.root / "opencode.jsonc").read_bytes()
        self.marker = {
            "schema_version": "1",
            "from": "0.10.1",
            "to": "0.10.2",
            "tag": "v0.10.2",
            "git_head_before": "a" * 40,
            "snapshot": self.snapshot["snapshot_dir"],
            "started_at": "2026-10-23T01:20:00Z",
            "phase": "sync",
        }
        upgrade.write_marker(self.root, self.marker)

    def tearDown(self):
        self._tmp.cleanup()

    def test_resets_only_when_head_changed_and_restores_hashes(self):
        (self.root / "opencode.jsonc").write_text("changed", encoding="utf-8")
        runner = ExecutionFakeGit(head="b" * 40)
        result = upgrade.rollback_upgrade(self.root, self.marker, git_runner=runner)
        self.assertTrue(result["ok"], result["errors"])
        self.assertTrue(result["git_reset"])
        self.assertEqual(result["head_after"], "a" * 40)
        self.assertEqual(
            (self.root / "opencode.jsonc").read_bytes(), self.config_bytes
        )
        self.assertFalse(upgrade.marker_path(self.root).exists())
        history = upgrade.read_history(self.root)
        self.assertEqual(history[-1]["status"], "rolled_back")

    def test_no_reset_when_head_did_not_move(self):
        runner = ExecutionFakeGit(head="a" * 40)
        result = upgrade.rollback_upgrade(self.root, self.marker, git_runner=runner)
        self.assertTrue(result["ok"], result["errors"])
        self.assertFalse(result["git_reset"])
        self.assertFalse(any("reset" in call for call in runner.calls))

    def test_corrupt_snapshot_aborts_before_any_reset(self):
        snapshot = Path(self.snapshot["snapshot_dir"])
        (snapshot / "opencode.jsonc").write_text("tampered", encoding="utf-8")
        runner = ExecutionFakeGit(head="b" * 40)
        result = upgrade.rollback_upgrade(self.root, self.marker, git_runner=runner)
        self.assertFalse(result["ok"])
        self.assertFalse(result["git_reset"])
        self.assertFalse(any("reset" in call for call in runner.calls))
        self.assertTrue(any("sha256 mismatch" in e for e in result["errors"]))
        # Fail-closed: the marker stays so the operator can retry.
        self.assertTrue(upgrade.marker_path(self.root).exists())


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

    def test_check_blocked_json_exposes_top_level_blockers(self):
        code, output = self._run(FakeGit(status=" M SCRIPTS/x.py\n"), json=True)
        self.assertEqual(code, 1)
        payload = json.loads(output)
        self.assertEqual(payload["status"], "BLOCKED")
        self.assertTrue(payload["blockers"])
        self.assertIn("uncommitted", payload["blockers"][0])
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
        make_target(self.root, config=CONFIG, state=sample_state())

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, runner, *, steps=None, **over):
        args = make_args(project=str(self.root), offline=True, **over)
        return run_cmd(
            args,
            git_runner=runner,
            which=which_all,
            step_runner=steps or FakeStepRunner(),
        )

    def test_execute_success_advances_and_removes_the_marker(self):
        runner = ExecutionFakeGit(
            local_tags="v0.10.1\nv0.10.2\n", head="a" * 40, tag_commit="b" * 40
        )
        steps = FakeStepRunner()
        code, output = self._run(runner, steps=steps)

        self.assertEqual(code, 0, output)
        self.assertIn("Status: PASS", output)
        self.assertFalse(upgrade.marker_path(self.root).exists())
        self.assertEqual(runner.head, "b" * 40)
        self.assertTrue(any("merge" in call for call in runner.calls))
        self.assertFalse(any("fetch" in call for call in runner.calls))
        self.assertTrue(
            any("adapter" in call["argv"] for call in steps.calls)
        )
        self.assertTrue(any("sync" in call["argv"] for call in steps.calls))
        self.assertTrue(any("doctor" in call["argv"] for call in steps.calls))
        history = upgrade.read_history(self.root)
        self.assertEqual(history[-1]["status"], "success")
        self.assertEqual(history[-1]["to"], "0.10.2")
        self.assertTrue(
            upgrade.verify_snapshot(history[-1]["snapshot"])["ok"]
        )

    def test_execute_online_fetches_before_the_fast_forward(self):
        runner = ExecutionFakeGit(
            remote_tags="abc\trefs/tags/v0.10.2\n",
            head="a" * 40,
            tag_commit="b" * 40,
        )
        args = make_args(project=str(self.root))
        code, output = run_cmd(
            args,
            git_runner=runner,
            which=which_all,
            step_runner=FakeStepRunner(),
        )
        self.assertEqual(code, 0, output)
        self.assertTrue(any("fetch" in call for call in runner.calls))

    def test_merge_failure_rolls_back_without_reset(self):
        runner = ExecutionFakeGit(
            local_tags="v0.10.1\nv0.10.2\n", head="a" * 40, merge_rc=1
        )
        code, output = self._run(runner)

        self.assertEqual(code, 1)
        self.assertIn("Status: FAIL", output)
        self.assertFalse(any("reset" in call for call in runner.calls))
        self.assertFalse(upgrade.marker_path(self.root).exists())
        history = upgrade.read_history(self.root)
        self.assertEqual(history[-1]["status"], "rolled_back")

    def test_fetch_failure_rolls_back(self):
        runner = ExecutionFakeGit(
            remote_tags="abc\trefs/tags/v0.10.2\n", fetch_rc=1
        )
        args = make_args(project=str(self.root))
        code, output = run_cmd(
            args,
            git_runner=runner,
            which=which_all,
            step_runner=FakeStepRunner(),
        )
        self.assertEqual(code, 1)
        self.assertIn("git fetch failed", output)
        self.assertFalse(any("reset" in call for call in runner.calls))
        self.assertFalse(upgrade.marker_path(self.root).exists())

    def test_doctor_non_pass_rolls_back(self):
        runner = ExecutionFakeGit(
            local_tags="v0.10.1\nv0.10.2\n", head="a" * 40, tag_commit="b" * 40
        )
        steps = FakeStepRunner(doctor_status="FAIL")
        code, output = self._run(runner, steps=steps)
        self.assertEqual(code, 1)
        self.assertIn("doctor reported status 'FAIL'", output)
        self.assertFalse(upgrade.marker_path(self.root).exists())
        self.assertEqual(runner.head, "a" * 40)

    def test_doctor_warn_with_zero_fail_completes_and_records_warning(self):
        """WARN is advisory: the upgrade lands and the WARN checks are named."""
        runner = ExecutionFakeGit(
            local_tags="v0.10.1\nv0.10.2\n", head="a" * 40, tag_commit="b" * 40
        )
        checks = [
            {
                "id": "root_hygiene",
                "status": "WARN",
                "detail": "MIGRATIONS unregistered",
            },
            {
                "id": "self_containment",
                "status": "WARN",
                "detail": "6 guidance hits",
            },
            {
                "id": "baseline_ledger",
                "status": "WARN",
                "detail": "ledger inactive",
            },
            {"id": "fourth_warn", "status": "WARN", "detail": "must not appear"},
            {"id": "structure", "status": "PASS", "detail": "18 directories"},
        ]
        summary = {"PASS": 17, "WARN": 4, "FAIL": 0}
        steps = FakeStepRunner(
            doctor_status="WARN", doctor_summary=summary, doctor_checks=checks
        )
        args = make_args(project=str(self.root), offline=True, json=True)
        code, output = run_cmd(
            args, git_runner=runner, which=which_all, step_runner=steps
        )

        self.assertEqual(code, 0, output)
        payload = json.loads(output)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(
            payload["details"]["doctor"],
            {"status": "WARN", "summary": summary},
        )
        self.assertEqual(len(payload["warnings"]), 1)
        warning = payload["warnings"][0]
        self.assertTrue(warning.startswith("doctor reported WARN: root_hygiene: "))
        self.assertIn("self_containment: 6 guidance hits", warning)
        self.assertIn("baseline_ledger: ledger inactive", warning)
        self.assertNotIn("fourth_warn", warning)
        self.assertFalse(upgrade.marker_path(self.root).exists())
        self.assertEqual(runner.head, "b" * 40)
        self.assertEqual(upgrade.read_history(self.root)[-1]["status"], "success")

    def test_doctor_warn_with_fail_rolls_back(self):
        """A WARN envelope that still reports FAIL must roll the upgrade back."""
        runner = ExecutionFakeGit(
            local_tags="v0.10.1\nv0.10.2\n", head="a" * 40, tag_commit="b" * 40
        )
        steps = FakeStepRunner(
            doctor_status="WARN",
            doctor_summary={"PASS": 15, "WARN": 1, "FAIL": 1},
            doctor_checks=[
                {"id": "self_containment", "status": "WARN", "detail": "w"},
                {"id": "contracts", "status": "FAIL", "detail": "broken"},
            ],
        )
        code, output = self._run(runner, steps=steps)

        self.assertEqual(code, 1)
        self.assertIn("doctor reported 1 FAIL check(s)", output)
        self.assertFalse(upgrade.marker_path(self.root).exists())
        self.assertEqual(runner.head, "a" * 40)
        self.assertEqual(
            upgrade.read_history(self.root)[-1]["status"], "rolled_back"
        )

    def test_up_to_date_is_info_without_a_snapshot(self):
        runner = ExecutionFakeGit(local_tags="v0.10.1\n")
        code, output = self._run(runner)
        self.assertEqual(code, 0)
        self.assertIn("Status: INFO", output)
        self.assertIn("UP_TO_DATE", output)
        self.assertFalse((self.root / ".se" / "backups").exists())

    def test_interrupted_marker_blocks_before_any_git_call(self):
        upgrade.write_marker(self.root, {"schema_version": "1"})
        runner = ExecutionFakeGit(local_tags="v0.10.1\nv0.10.2\n")
        code, output = self._run(runner)
        self.assertEqual(code, 1)
        self.assertIn("interrupted upgrade detected", output)
        self.assertIn("se upgrade --recover", output)
        self.assertEqual(runner.calls, [])
        self.assertTrue(upgrade.marker_path(self.root).exists())

    def test_execute_json_envelope(self):
        runner = ExecutionFakeGit(
            local_tags="v0.10.1\nv0.10.2\n", head="a" * 40, tag_commit="b" * 40
        )
        args = make_args(project=str(self.root), offline=True, json=True)
        code, output = run_cmd(
            args,
            git_runner=runner,
            which=which_all,
            step_runner=FakeStepRunner(),
        )
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["details"]["selection"]["target"], "0.10.2")
        self.assertEqual(payload["details"]["git_head_after"], "b" * 40)
        self.assertEqual(payload["blockers"], [])

    def test_dry_run_behaves_like_check(self):
        code, output = run_cmd(
            make_args(project=str(self.root), dry_run=True),
            git_runner=FakeGit(remote_tags="abc\trefs/tags/v0.10.2\n"),
            which=which_all,
        )
        self.assertEqual(code, 0)
        self.assertIn("se upgrade (dry-run)", output)
        self.assertIn("Target version: 0.10.2", output)
        self.assertFalse((self.root / ".se" / "backups").exists())


class UpgradeParserTests(unittest.TestCase):
    """The CLI surface: ``--recover`` exists and never implies a plan mode."""

    def test_recover_is_wired_to_cmd_upgrade(self):
        args = build_parser().parse_args(["upgrade", "--recover"])
        self.assertTrue(args.recover)
        self.assertFalse(args.check)
        self.assertFalse(args.dry_run)
        self.assertIs(args.func, upgrade.cmd_upgrade)

    def test_plan_flags_do_not_set_recover(self):
        for flag in ("--check", "--dry-run"):
            with self.subTest(flag=flag):
                args = build_parser().parse_args(["upgrade", flag])
                self.assertFalse(args.recover)
        self.assertTrue(
            build_parser().parse_args(["upgrade", "--check"]).check
        )
        self.assertTrue(
            build_parser().parse_args(["upgrade", "--dry-run"]).dry_run
        )


if __name__ == "__main__":
    unittest.main()
