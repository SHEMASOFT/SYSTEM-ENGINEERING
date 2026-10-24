"""Acceptance scenarios for ``se upgrade`` (contract: audit §6.10/§6.11).

The approved contract (``DOCS/internal/upgrade-readiness-audit-2026-10-22.md``)
defines twelve acceptance criteria. This file maps the executable scenarios to
them:

* **AC1** - clean N->N+1 upgrade: exit 0, ``VERSION`` == target, doctor PASS,
  restorable config/state, verifiable snapshot (T1).
* **AC2** - dirty tree: exit 1, zero writes, ``HEAD`` unchanged (T2).
* **AC3** - divergent branches: exit 1, no merge commit, ``HEAD`` unchanged (T3).
* **AC4** - offline: ``--check`` reports ``UNKNOWN`` without a fatal error and
  the upgrade writes nothing (T4).
* **AC5** - failing migration: snapshot restored byte-for-byte, state intact,
  ``HEAD`` unchanged, exit 1 (T5).
* **AC6** - ``sync`` fails after the advance: full rollback, hashes match,
  exit 1 (T6).
* **AC7** - without ``--include-projects``: the ``PROJECTS/`` tree hash is
  identical before and after (T7).
* **AC8** - with ``--include-projects``: the snapshot contains memories and
  valid hashes (T7/AC8).
* **AC9** - re-running at the target: no-op, exit 0, no new snapshot (T9).
* **AC10** - interruption (kill) between steps: the next start detects
  ``.se/upgrade-in-progress.json`` and ``--recover`` restores it (T8/T10).
* **AC11** - EOL: an LF ``opencode.jsonc`` stays LF after install/uninstall
  (regression covered by ``TESTS/test_mcpconfig.py``).
* **AC12** - a server written by SE never becomes ``foreign`` after a ``sync``
  failure (T6/T12).

T2 and T4 use a scripted git runner (no repository). The remaining scenarios
use :class:`TempUpgradeRepo`: a local repository under a temporary directory,
so they never touch this repository. ``git`` is only used inside that temporary
directory and the tests are skipped when git is not on ``PATH``.
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

from se_core import lifecycle_state as lc  # noqa: E402
from se_core import mcpconfig  # noqa: E402
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

FAILING_MIGRATION = """\
ID = "001_fail"


def migrate(root, context):
    raise RuntimeError("injected migration failure")
"""

# AC5 variant: the migration creates the runtime files the repository did not
# have, then aborts. A rollback must remove them again.
FAILING_MIGRATION_WITH_RUNTIME_FILES = """\
import json
from pathlib import Path

ID = "001_fail"


def migrate(root, context):
    root = Path(root)
    state = root / ".se" / "lifecycle-state.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(
        json.dumps({"schema_version": "1", "servers": {"ghost": {}}}),
        encoding="utf-8",
    )
    (root / ".se" / "migrations.json").write_text(
        json.dumps({"schema_version": "1", "applied": []}), encoding="utf-8"
    )
    (root / "opencode.jsonc").write_text(
        '{"mcp": {"servers": {"ghost": {"type": "local"}}}}\\n',
        encoding="utf-8",
    )
    raise RuntimeError("injected migration failure")
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


class FakeStepRunner:
    """Records orchestrated ``se adapter``/``se sync``/``se doctor`` calls."""

    def __init__(self, *, fail_on=(), doctor_status="PASS", on_sync=None):
        self.fail_on = set(fail_on)
        self.doctor_status = doctor_status
        self.on_sync = on_sync
        self.calls: list[dict] = []

    def __call__(self, argv, *, cwd=None):
        self.calls.append({"argv": list(argv), "cwd": str(cwd) if cwd else None})
        if "doctor" in argv:
            return FakeResult(0, json.dumps({"status": self.doctor_status}), "")
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


def which_opencode(name):
    return "opencode"


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
        "recover": False,
    }
    base.update(over)
    return types.SimpleNamespace(**base)


def run_cmd(args, *, runner, which=which_all):
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = upgrade.cmd_upgrade(args, git_runner=runner, which=which)
    return code, buffer.getvalue()


def run_upgrade_cmd(args, *, step_runner=None, which=which_opencode):
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = upgrade.cmd_upgrade(
            args, which=which, step_runner=step_runner
        )
    return code, buffer.getvalue()


def tree_fingerprint(root):
    """Hash every non-``.git`` file under ``root`` (proves zero SE writes).

    ``git status`` may refresh ``.git/index``; that is git's own bookkeeping, not
    an SE write, so it is excluded.
    """
    root = Path(root)
    fingerprint = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative == ".git" or relative.startswith(".git/"):
            continue
        fingerprint[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return fingerprint


def manifest_of(snapshot):
    return json.loads((Path(snapshot) / "manifest.json").read_text(encoding="utf-8"))


class TempUpgradeRepo:
    """Minimal local git fixture; never touches this repository or the network."""

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

    def rev_parse(self, ref):
        return self._run("rev-parse", ref).stdout.strip()

    def rev_list_merges(self):
        return self._run("rev-list", "--merges", "--all").stdout.strip()

    def reset_hard(self, ref):
        self._run("reset", "--hard", ref)

    def checkout(self, ref, *, new_branch=None):
        args = ["checkout"]
        if new_branch:
            args += ["-b", new_branch]
        args.append(ref)
        self._run(*args)

    def remote_add(self, name, url):
        self._run("remote", "add", name, url)

    def push(self, *refs):
        self._run("push", *refs)


def _write_version_tree(
    repo,
    version,
    *,
    failing_migration=False,
    with_config=True,
    with_state=True,
):
    repo.write("VERSION", version + "\n")
    repo.write(
        "SYSTEM.json",
        json.dumps(
            {"schema_version": "1", "master_system_version": version}, indent=2
        )
        + "\n",
    )
    if with_config:
        repo.write("opencode.jsonc", CONFIG)
    if with_state:
        state = lc.new_state(
            se_version=version, os_name="windows", target=str(repo.root)
        )
        lc.save_state(state, repo.root)
    if failing_migration:
        repo.write(
            "MIGRATIONS/001_fail.py",
            failing_migration
            if isinstance(failing_migration, str)
            else FAILING_MIGRATION,
        )


def build_repo(
    root,
    *,
    with_failing_migration=False,
    with_config=True,
    with_state=True,
):
    """0.1.0 + tag v0.1.0, then 0.2.0 + tag v0.2.0, then back to v0.1.0."""
    repo = TempUpgradeRepo(root).init()
    _write_version_tree(repo, "0.1.0", with_config=with_config, with_state=with_state)
    repo.commit("baseline 0.1.0")
    repo.tag("v0.1.0")
    _write_version_tree(
        repo,
        "0.2.0",
        failing_migration=with_failing_migration,
        with_config=with_config,
        with_state=with_state,
    )
    repo.commit("release 0.2.0")
    repo.tag("v0.2.0")
    repo.reset_hard("v0.1.0")
    return repo


# --------------------------------------------------------------------------- #
# Scripted scenarios (no repository)
# --------------------------------------------------------------------------- #


class UpgradeAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.target = make_target(self.root / "target")

    def tearDown(self):
        self._tmp.cleanup()

    def test_T2_dirty_tree_blocks_with_zero_writes(self):
        """T2 - AC2: dirty tree => BLOCKED, exit 1, zero writes, HEAD untouched."""
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
        """T4 - AC4: offline + no local tags => NO_TAGS/UNKNOWN, exit 0, no writes."""
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


# --------------------------------------------------------------------------- #
# Real-git scenarios (temporary repository only)
# --------------------------------------------------------------------------- #


@unittest.skipUnless(shutil.which("git"), "git is not available on PATH")
class UpgradeExecutionAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()

    def tearDown(self):
        self._tmp.cleanup()

    def test_T1_clean_upgrade_advances_to_target(self):
        """T1 - AC1: offline ff-only upgrade; snapshot verifies; sync runs."""
        repo = build_repo(self.root / "repo")
        steps = FakeStepRunner()

        code, output = run_upgrade_cmd(
            make_args(project=str(repo.root), offline=True), step_runner=steps
        )

        self.assertEqual(code, 0, output)
        self.assertIn("Status: PASS", output)
        self.assertEqual((repo.root / "VERSION").read_text().strip(), "0.2.0")
        self.assertEqual(repo.head(), repo.rev_parse("v0.2.0^{commit}"))
        self.assertFalse(upgrade.marker_path(repo.root).exists())
        history = upgrade.read_history(repo.root)
        self.assertEqual(history[-1]["status"], "success")
        self.assertEqual(history[-1]["to"], "0.2.0")
        self.assertTrue(upgrade.verify_snapshot(history[-1]["snapshot"])["ok"])
        self.assertTrue(any("sync" in call["argv"] for call in steps.calls))

    def test_T1b_remote_fetch_then_fast_forward(self):
        """T1b - AC1: with a local bare remote, fetch runs before the ff."""
        bare = self.root / "remote.git"
        subprocess.run(
            [shutil.which("git"), "init", "--bare", str(bare)],
            capture_output=True,
            text=True,
            check=True,
        )
        repo = build_repo(self.root / "repo")
        repo.remote_add("origin", str(bare))
        repo.push("origin", "main")
        repo.push("origin", "--tags")

        steps = FakeStepRunner()
        code, output = run_upgrade_cmd(
            make_args(project=str(repo.root)), step_runner=steps
        )

        self.assertEqual(code, 0, output)
        self.assertEqual((repo.root / "VERSION").read_text().strip(), "0.2.0")
        self.assertEqual(repo.head(), repo.rev_parse("v0.2.0^{commit}"))

    def test_T3_divergent_branches_are_blocked(self):
        """T3 - AC3: divergent branch => FAIL, no merge commit, HEAD unchanged."""
        repo = TempUpgradeRepo(self.root / "repo").init()
        _write_version_tree(repo, "0.1.0")
        repo.commit("baseline")
        repo.tag("v0.1.0")
        repo.checkout("main", new_branch="topic")
        repo.write("topic.txt", "topic\n")
        repo.commit("topic work")
        topic_head = repo.head()
        repo.checkout("main")
        _write_version_tree(repo, "0.2.0")
        repo.commit("release")
        repo.tag("v0.2.0")
        repo.checkout("topic")
        merges_before = repo.rev_list_merges()

        code, output = run_upgrade_cmd(
            make_args(project=str(repo.root), offline=True),
            step_runner=FakeStepRunner(),
        )

        self.assertEqual(code, 1, output)
        self.assertIn("Status: FAIL", output)
        self.assertEqual(repo.head(), topic_head)
        self.assertEqual(repo.rev_list_merges(), merges_before)
        self.assertFalse(upgrade.marker_path(repo.root).exists())
        history = upgrade.read_history(repo.root)
        self.assertEqual(history[-1]["status"], "rolled_back")

    def test_T5_failing_migration_rolls_back(self):
        """T5 - AC5: a raising migration restores config/state/HEAD byte-for-byte."""
        repo = build_repo(self.root / "repo", with_failing_migration=True)
        config_before = (repo.root / "opencode.jsonc").read_bytes()
        state_before = (repo.root / ".se" / "lifecycle-state.json").read_bytes()
        head_before = repo.head()

        code, output = run_upgrade_cmd(
            make_args(project=str(repo.root), offline=True),
            step_runner=FakeStepRunner(),
        )

        self.assertEqual(code, 1, output)
        self.assertIn("migration 001_fail failed", output)
        self.assertEqual((repo.root / "VERSION").read_text().strip(), "0.1.0")
        self.assertEqual(repo.head(), head_before)
        self.assertEqual(
            (repo.root / "opencode.jsonc").read_bytes(), config_before
        )
        self.assertEqual(
            (repo.root / ".se" / "lifecycle-state.json").read_bytes(),
            state_before,
        )
        self.assertFalse(upgrade.marker_path(repo.root).exists())
        history = upgrade.read_history(repo.root)
        self.assertEqual(history[-1]["status"], "rolled_back")

    def test_T5b_failing_migration_removes_created_state_and_ledger(self):
        """T5b - AC5: state/ledger created by a failing migration are removed."""
        repo = build_repo(
            self.root / "repo",
            with_failing_migration=FAILING_MIGRATION_WITH_RUNTIME_FILES,
            with_state=False,
        )
        config_before = (repo.root / "opencode.jsonc").read_bytes()
        head_before = repo.head()
        self.assertFalse((repo.root / ".se" / "lifecycle-state.json").exists())
        self.assertFalse((repo.root / ".se" / "migrations.json").exists())

        code, output = run_upgrade_cmd(
            make_args(project=str(repo.root), offline=True),
            step_runner=FakeStepRunner(),
        )

        self.assertEqual(code, 1, output)
        self.assertIn("migration 001_fail failed", output)
        self.assertEqual((repo.root / "VERSION").read_text().strip(), "0.1.0")
        self.assertEqual(repo.head(), head_before)
        self.assertEqual(
            (repo.root / "opencode.jsonc").read_bytes(), config_before
        )
        self.assertFalse((repo.root / ".se" / "lifecycle-state.json").exists())
        self.assertFalse((repo.root / ".se" / "migrations.json").exists())
        self.assertFalse(upgrade.marker_path(repo.root).exists())
        history = upgrade.read_history(repo.root)
        self.assertEqual(history[-1]["status"], "rolled_back")
        self.assertEqual(history[-1]["rollback"]["errors"], [])

    def test_T6_and_T12_sync_failure_rolls_back_without_foreign(self):
        """T6/T12 - AC6/AC12: partial sync write is rolled back; no foreign left."""
        repo = build_repo(self.root / "repo")
        config_before = (repo.root / "opencode.jsonc").read_bytes()
        state_before = (repo.root / ".se" / "lifecycle-state.json").read_bytes()

        def partial_sync(cwd):
            target = Path(cwd)
            (target / "opencode.jsonc").write_text(
                json.dumps(
                    {
                        "mcp": {
                            "servers": {
                                "se-skill-server": {
                                    "type": "local",
                                    "command": ["x"],
                                },
                                "foreign-a": {
                                    "type": "local",
                                    "command": ["/opt/foreign"],
                                },
                            }
                        }
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            state = lc.load_state(target)
            if state is not None:
                state["servers"]["se-skill-server"] = {
                    "declared": "x",
                    "source": "fixture",
                    "scope": "project",
                }
                lc.save_state(state, target)

        steps = FakeStepRunner(fail_on={"sync"}, on_sync=partial_sync)
        code, output = run_upgrade_cmd(
            make_args(project=str(repo.root), offline=True), step_runner=steps
        )

        self.assertEqual(code, 1, output)
        self.assertIn("sync step failed", output)
        self.assertEqual(
            (repo.root / "opencode.jsonc").read_bytes(), config_before
        )
        self.assertEqual(
            (repo.root / ".se" / "lifecycle-state.json").read_bytes(),
            state_before,
        )
        self.assertFalse(upgrade.marker_path(repo.root).exists())

        # T12: the restored config does not contain the server and the state
        # does not register it, so a later sync cannot classify it as foreign.
        config = mcpconfig.read_config(repo.root / "opencode.jsonc")
        names = {item["name"] for item in mcpconfig.list_servers(config)}
        self.assertNotIn("se-skill-server", names)
        state = lc.load_state(repo.root)
        self.assertEqual(state["servers"], {})
        history = upgrade.read_history(repo.root)
        self.assertEqual(history[-1]["status"], "rolled_back")

    def test_T6b_sync_failure_removes_created_config_and_state(self):
        """T6b - AC5: config/state created by a failing sync are removed."""
        repo = build_repo(
            self.root / "repo", with_config=False, with_state=False
        )
        head_before = repo.head()
        self.assertFalse((repo.root / "opencode.jsonc").exists())
        self.assertFalse((repo.root / ".se" / "lifecycle-state.json").exists())

        def creating_sync(cwd):
            target = Path(cwd)
            (target / "opencode.jsonc").write_text(
                json.dumps(
                    {"mcp": {"servers": {"se-skill-server": {"type": "local"}}}}
                ),
                encoding="utf-8",
            )
            state = lc.new_state(
                se_version="0.1.0", os_name="windows", target=str(target)
            )
            state["servers"]["se-skill-server"] = {
                "declared": "x",
                "source": "fixture",
                "scope": "project",
            }
            lc.save_state(state, target)

        steps = FakeStepRunner(fail_on={"sync"}, on_sync=creating_sync)
        code, output = run_upgrade_cmd(
            make_args(project=str(repo.root), offline=True), step_runner=steps
        )

        self.assertEqual(code, 1, output)
        self.assertIn("sync step failed", output)
        self.assertFalse((repo.root / "opencode.jsonc").exists())
        self.assertFalse((repo.root / ".se" / "lifecycle-state.json").exists())
        self.assertFalse((repo.root / ".se" / "migrations.json").exists())
        self.assertEqual(repo.head(), head_before)
        self.assertEqual((repo.root / "VERSION").read_text().strip(), "0.1.0")
        self.assertFalse(upgrade.marker_path(repo.root).exists())
        self.assertEqual(
            upgrade.read_history(repo.root)[-1]["status"], "rolled_back"
        )

    def test_T7_projects_untouched_by_default_and_AC8_on_request(self):
        """T7/AC8 - AC7/AC8: PROJECTS/ is an invariant unless opted in."""
        repo = build_repo(self.root / "repo")
        memory = repo.root / "PROJECTS" / "mem.md"
        memory.parent.mkdir(parents=True)
        memory.write_text("# memory\n", encoding="utf-8")
        before = tree_fingerprint(repo.root / "PROJECTS")

        code, output = run_upgrade_cmd(
            make_args(project=str(repo.root), offline=True),
            step_runner=FakeStepRunner(),
        )

        self.assertEqual(code, 0, output)
        self.assertEqual(tree_fingerprint(repo.root / "PROJECTS"), before)
        history = upgrade.read_history(repo.root)
        manifest = manifest_of(history[-1]["snapshot"])
        self.assertFalse(
            any(
                entry["path"].startswith("PROJECTS/")
                for entry in manifest["files"]
            )
        )

        # AC8: a second repository, this time with --include-projects.
        repo2 = build_repo(self.root / "repo2")
        memory2 = repo2.root / "PROJECTS" / "mem.md"
        memory2.parent.mkdir(parents=True)
        memory2.write_text("# memory\n", encoding="utf-8")

        code, output = run_upgrade_cmd(
            make_args(
                project=str(repo2.root), offline=True, include_projects=True
            ),
            step_runner=FakeStepRunner(),
        )

        self.assertEqual(code, 0, output)
        history2 = upgrade.read_history(repo2.root)
        manifest2 = manifest_of(history2[-1]["snapshot"])
        entries = {entry["path"]: entry for entry in manifest2["files"]}
        self.assertIn("PROJECTS/mem.md", entries)
        self.assertEqual(
            entries["PROJECTS/mem.md"]["sha256"],
            hashlib.sha256(memory2.read_bytes()).hexdigest(),
        )
        self.assertTrue(upgrade.verify_snapshot(history2[-1]["snapshot"])["ok"])

    def test_T8_interrupted_upgrade_is_detected_and_recovered(self):
        """T8 - AC10: marker + advanced HEAD => BLOCKED, then --recover restores."""
        repo = build_repo(self.root / "repo")
        head_before = repo.head()
        snapshot = upgrade.create_snapshot(
            repo.root,
            from_version="0.1.0",
            to_version="0.2.0",
            git_head=head_before,
        )
        marker = {
            "schema_version": "1",
            "from": "0.1.0",
            "to": "0.2.0",
            "tag": "v0.2.0",
            "git_head_before": head_before,
            "snapshot": snapshot["snapshot_dir"],
            "started_at": "2026-10-23T01:20:00Z",
            "phase": "sync",
        }
        upgrade.write_marker(repo.root, marker)
        repo.reset_hard("v0.2.0")
        self.assertEqual((repo.root / "VERSION").read_text().strip(), "0.2.0")

        code, output = run_upgrade_cmd(
            make_args(project=str(repo.root), offline=True),
            step_runner=FakeStepRunner(),
        )

        self.assertEqual(code, 1, output)
        self.assertIn("interrupted upgrade detected", output)
        self.assertTrue(upgrade.marker_path(repo.root).exists())
        self.assertEqual((repo.root / "VERSION").read_text().strip(), "0.2.0")

        code, output = run_upgrade_cmd(
            make_args(project=str(repo.root), offline=True, recover=True),
            step_runner=FakeStepRunner(),
        )

        self.assertEqual(code, 0, output)
        self.assertIn("Status: PASS", output)
        self.assertEqual((repo.root / "VERSION").read_text().strip(), "0.1.0")
        self.assertEqual(repo.head(), head_before)
        self.assertFalse(upgrade.marker_path(repo.root).exists())
        history = upgrade.read_history(repo.root)
        self.assertEqual(history[-1]["status"], "recovered")

    def test_T8b_recover_without_git_head_before_is_blocked(self):
        """T8b - AC10: a marker without git_head_before cannot be recovered."""
        repo = build_repo(self.root / "repo")
        head_before = repo.head()
        snapshot = upgrade.create_snapshot(
            repo.root,
            from_version="0.1.0",
            to_version="0.2.0",
            git_head=head_before,
        )
        marker = {
            "schema_version": "1",
            "from": "0.1.0",
            "to": "0.2.0",
            "tag": "v0.2.0",
            "snapshot": snapshot["snapshot_dir"],
            "started_at": "2026-10-23T01:20:00Z",
            "phase": "sync",
        }
        upgrade.write_marker(repo.root, marker)
        repo.reset_hard("v0.2.0")
        head_after_advance = repo.head()

        code, output = run_upgrade_cmd(
            make_args(project=str(repo.root), offline=True, recover=True),
            step_runner=FakeStepRunner(),
        )

        self.assertEqual(code, 1, output)
        self.assertIn("no git_head_before", output)
        self.assertIn("Status: BLOCKED", output)
        self.assertEqual(repo.head(), head_after_advance)
        self.assertEqual((repo.root / "VERSION").read_text().strip(), "0.2.0")
        self.assertTrue(upgrade.marker_path(repo.root).exists())
        self.assertFalse(
            (repo.root / ".se" / "upgrade-history.jsonl").exists()
        )

    def test_T9_up_to_date_is_info_and_creates_no_snapshot(self):
        """T9 - AC9: already at the newest tag => INFO, no new backup directory."""
        repo = build_repo(self.root / "repo")
        repo.reset_hard("v0.2.0")
        backups = repo.root / ".se" / "backups"
        before = (
            sorted(path.name for path in backups.iterdir())
            if backups.is_dir()
            else []
        )

        code, output = run_upgrade_cmd(
            make_args(project=str(repo.root), offline=True),
            step_runner=FakeStepRunner(),
        )

        self.assertEqual(code, 0, output)
        self.assertIn("Status: INFO", output)
        self.assertIn("UP_TO_DATE", output)
        after = (
            sorted(path.name for path in backups.iterdir())
            if backups.is_dir()
            else []
        )
        self.assertEqual(after, before)

    def test_T10_marker_plus_check_is_blocked_without_writes(self):
        """T10 - AC10: --check with a marker => BLOCKED and zero writes."""
        repo = build_repo(self.root / "repo")
        upgrade.write_marker(
            repo.root,
            {
                "schema_version": "1",
                "from": "0.1.0",
                "to": "0.2.0",
                "tag": "v0.2.0",
                "git_head_before": repo.head(),
                "snapshot": "not-used",
                "started_at": "2026-10-23T01:20:00Z",
                "phase": "sync",
            },
        )
        before = tree_fingerprint(repo.root)

        code, output = run_upgrade_cmd(
            make_args(project=str(repo.root), check=True),
            step_runner=FakeStepRunner(),
        )

        self.assertEqual(code, 1, output)
        self.assertIn("Status: BLOCKED", output)
        self.assertEqual(tree_fingerprint(repo.root), before)


if __name__ == "__main__":
    unittest.main()
