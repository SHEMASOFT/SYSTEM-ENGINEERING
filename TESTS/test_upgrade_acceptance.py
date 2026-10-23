"""Acceptance scenarios T1-T8 for ``se upgrade`` (contract: audit §6.10/§6.11).

The approved contract (``DOCS/internal/upgrade-readiness-audit-2026-10-22.md``)
defines twelve acceptance criteria. This file maps the executable scenarios to
them:

* **AC1** - clean N->N+1 upgrade: exit 0, ``VERSION`` == target, doctor PASS,
  restorable config/state, verifiable snapshot (T1).
* **AC2** - dirty tree: exit 1, zero writes, ``HEAD`` unchanged (T2, implemented).
* **AC3** - divergent branches: exit 1, no merge commit, ``HEAD`` unchanged (T3).
* **AC4** - offline: ``--check`` reports ``UNKNOWN`` without a fatal error and
  the upgrade writes nothing (T4, implemented).
* **AC5** - failing migration: snapshot restored byte-for-byte, state intact,
  ``HEAD`` unchanged, exit 1 (T5).
* **AC6** - ``sync`` fails after the advance: full rollback, hashes match,
  exit 1 (T6).
* **AC7** - without ``--include-projects``: the ``PROJECTS/`` tree hash is
  identical before and after (T7).
* **AC8** - with ``--include-projects``: the snapshot contains memories and
  valid hashes (T7).
* **AC9** - re-running at the target: no-op, exit 0, no new snapshot (T1).
* **AC10** - interruption (kill) between steps: the next start detects
  ``.se/upgrade-in-progress.json`` and offers resume/rollback (T8).
* **AC11** - EOL: an LF ``opencode.jsonc`` stays LF after install/uninstall
  (regression covered by ``TESTS/test_mcpconfig.py``).
* **AC12** - a server written by SE never becomes ``foreign`` after a ``sync``
  failure (exit 1 and exception variants) (T6).

Only T2 and T4 are executable today: the skeleton phase is read-only and
``se upgrade`` deliberately refuses execution. The remaining scenarios are
written as executable scripts and marked ``skip`` until the execution phase
lands; they use :class:`TempGitRepo` so they never touch this repository or the
network.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402,F401  (puts SCRIPTS on sys.path)

from se_core import upgrade  # noqa: E402

CONFIG = """{
  // acceptance fixture: a foreign entry SE must preserve
  "mcp": {
    "servers": {
      "foreign-a": {"type": "local", "command": ["/opt/foreign"]}
    }
  }
}
"""


# --------------------------------------------------------------------------- #
# Hermetic helpers
# --------------------------------------------------------------------------- #


class FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class ScriptedGit:
    """Canned git runner: no repository, no network, no writes."""

    def __init__(self, *, status="", remote_tags="", local_tags="", returncode=0, stderr=""):
        self.status = status
        self.remote_tags = remote_tags
        self.local_tags = local_tags
        self.returncode = returncode
        self.stderr = stderr
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
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


def make_target(root, *, version="0.10.1", config=CONFIG):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "VERSION").write_text(version + "\n", encoding="utf-8")
    (root / "SYSTEM.json").write_text(
        json.dumps(
            {"schema_version": "1", "master_system_version": version}, indent=2
        )
        + "\n",
        encoding="utf-8",
    )
    if config is not None:
        (root / "opencode.jsonc").write_text(config, encoding="utf-8")
    return root


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


def run_cmd(args, *, runner, which=which_all):
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = upgrade.cmd_upgrade(args, git_runner=runner, which=which)
    return code, buffer.getvalue()


def tree_fingerprint(root):
    """Hash every file under ``root`` (proves a command performed zero writes)."""
    root = Path(root)
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class TempGitRepo:
    """Minimal local git fixture for the pending execution scenarios.

    Never used by the executable tests today. It creates a repository under a
    temporary directory and raises ``SkipTest`` when git is not available, so it
    can never touch this repository or the network.
    """

    def __init__(self, root):
        self.root = Path(root)
        self.git = shutil.which("git")

    def _run(self, *args):
        if not self.git:
            raise unittest.SkipTest("git is not available on PATH")
        return subprocess.run(
            [self.git, *args],
            cwd=str(self.root),
            capture_output=True,
            text=True,
            check=True,
        )

    def init(self, branch="main"):
        self.root.mkdir(parents=True, exist_ok=True)
        self._run("init", "-b", branch)
        self._run("config", "user.email", "acceptance@example.test")
        self._run("config", "user.name", "Acceptance")
        return self

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def commit(self, message):
        self._run("add", "-A")
        self._run("commit", "-m", message)

    def tag(self, name):
        self._run("tag", name)

    def head(self):
        return self._run("rev-parse", "HEAD").stdout.strip()

    def checkout(self, ref, *, new_branch=None):
        args = ["checkout"]
        if new_branch:
            args += ["-b", new_branch]
        args.append(ref)
        self._run(*args)


# --------------------------------------------------------------------------- #
# Executable scenarios
# --------------------------------------------------------------------------- #


class UpgradeAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.target = make_target(self.root / "target")

    def tearDown(self):
        self._tmp.cleanup()

    def test_T2_dirty_tree_blocks_with_zero_writes(self):
        """T2 - AC2: dirty tree => BLOCKED, exit 1, zero writes, HEAD untouched.

        The runner reports a modified tracked file. ``se upgrade --check`` must
        stop at the preflight, report the blocker and create nothing (no
        ``.se/``, no snapshot, no backup).
        """
        before = tree_fingerprint(self.target)
        runner = ScriptedGit(status=" M SCRIPTS/se_core/cli.py\n")

        code, output = run_cmd(
            make_args(project=str(self.target), check=True),
            runner=runner,
        )

        self.assertEqual(code, 1)
        self.assertIn("Status: BLOCKED", output)
        self.assertIn("uncommitted", output)
        self.assertEqual(tree_fingerprint(self.target), before)
        self.assertFalse((self.target / ".se").exists())

    def test_T4_offline_without_tags_is_unknown_with_zero_writes(self):
        """T4 - AC4: offline + no local tags => NO_TAGS/UNKNOWN, exit 0, no writes.

        ``--offline`` must never invoke ``git ls-remote`` and must not assume a
        version. The absence of tags is informational (UNKNOWN), not a fatal
        error, and the command still writes nothing.
        """
        before = tree_fingerprint(self.target)
        runner = ScriptedGit(local_tags="")

        code, output = run_cmd(
            make_args(project=str(self.target), check=True, offline=True, json=True),
            runner=runner,
        )

        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload["status"], "UNKNOWN")
        self.assertEqual(payload["details"]["selection"]["status"], "NO_TAGS")
        self.assertIsNone(payload["details"]["selection"]["target"])
        self.assertTrue(
            all("ls-remote" not in command for command in runner.commands)
        )
        self.assertEqual(tree_fingerprint(self.target), before)
        self.assertFalse((self.target / ".se").exists())

    # ------------------------------------------------------------------ #
    # Pending execution phase
    # ------------------------------------------------------------------ #

    @unittest.skip("pending upgrade execution")
    def test_T1_clean_upgrade_advances_to_target(self):
        """T1 - AC1/AC9: two commits + tags v0.10.1/v0.10.2 -> ff-only upgrade.

        Script: create a temp repo with commit A (VERSION 0.10.1, tag v0.10.1)
        and commit B (VERSION 0.10.2, tag v0.10.2); run ``se upgrade --project
        <repo> --no-sync``; assert exit 0, ``VERSION`` == "0.10.2", HEAD == the
        v0.10.2 commit, ``se doctor`` PASS, the snapshot verifies, and config /
        state can be restored. Re-running at the target is a no-op (exit 0, no
        new snapshot) - AC9.
        """
        repo = TempGitRepo(self.root / "repo").init()
        repo.write("VERSION", "0.10.1\n")
        repo.commit("baseline 0.10.1")
        repo.tag("v0.10.1")
        baseline = repo.head()
        repo.write("VERSION", "0.10.2\n")
        repo.commit("release 0.10.2")
        repo.tag("v0.10.2")
        # Execution is not implemented yet: this scenario stays skipped.
        self.fail(f"T1 pending upgrade execution (baseline {baseline})")

    @unittest.skip("pending upgrade execution")
    def test_T3_divergent_branches_are_blocked(self):
        """T3 - AC3: divergent branch => BLOCKED, no merge commit, HEAD unchanged.

        Script: create ``main`` with tag v0.10.1, branch ``topic`` with a local
        commit, then a new ``main`` commit; run the upgrade from ``topic``;
        assert exit 1, HEAD still the topic commit, and no merge commit exists
        (``git rev-list --merges`` unchanged).
        """
        repo = TempGitRepo(self.root / "repo").init()
        repo.write("VERSION", "0.10.1\n")
        repo.commit("baseline")
        repo.tag("v0.10.1")
        repo.checkout("main", new_branch="topic")
        repo.write("topic.txt", "topic\n")
        repo.commit("topic work")
        topic_head = repo.head()
        self.fail(f"T3 pending upgrade execution (topic head {topic_head})")

    @unittest.skip("pending upgrade execution")
    def test_T5_failing_migration_rolls_back(self):
        """T5 - AC5: migration raises => snapshot restored byte-for-byte.

        Script: install a fixture migration whose ``apply`` raises after the
        code advance; snapshot config/state before; run the upgrade; assert
        exit 1, ``VERSION`` back to the original, state and config bytes equal
        the snapshot hashes, and HEAD == ``git_head_before``.
        """
        self.fail("T5 pending upgrade execution (migrations are not implemented)")

    @unittest.skip("pending upgrade execution")
    def test_T6_sync_failure_rolls_back_without_losing_ownership(self):
        """T6 - AC6/AC12: sync exit 1 (and exception) => full rollback.

        Script: inject a fake ``opencode mcp add`` runner that fails on the
        second server (exit 1) and, in a second variant, raises. Assert exit 1,
        config and state bytes equal the snapshot, hashes match, and no server
        written by SE is classified as ``foreign`` on the next ``sync``.
        """
        self.fail("T6 pending upgrade execution (sync rollback is not implemented)")

    @unittest.skip("pending upgrade execution")
    def test_T7_projects_invariant_and_include_projects(self):
        """T7 - AC7/AC8: PROJECTS/ untouched by default, snapshotted on request.

        Script: hash the ``PROJECTS/`` tree before/after a default upgrade
        (must be identical); repeat with ``--include-projects`` and assert the
        snapshot contains ``PROJECTS/<id>/memories/*.json`` with valid hashes.
        """
        memory = self.target / "PROJECTS" / "PRJ-1" / "memories" / "MEM-1.json"
        memory.parent.mkdir(parents=True)
        memory.write_text('{"id": "MEM-1"}\n', encoding="utf-8")
        before = tree_fingerprint(self.target / "PROJECTS")
        self.fail(f"T7 pending upgrade execution (projects hash {before})")

    @unittest.skip("pending upgrade execution")
    def test_T8_interrupted_upgrade_is_detected_on_restart(self):
        """T8 - AC10: kill between apply and save => marker => resume/rollback.

        Script: start an upgrade with a runner that kills the process after the
        first applied step; on the next invocation assert
        ``.se/upgrade-in-progress.json`` is detected, the command refuses to
        continue silently and offers resume/rollback with the snapshot path.
        """
        marker = self.target / ".se" / upgrade.UPGRADE_MARKER
        self.fail(f"T8 pending upgrade execution (marker path {marker})")


if __name__ == "__main__":
    unittest.main()
