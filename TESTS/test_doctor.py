"""Doctor tests."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.doctor import (  # noqa: E402
    check_baseline_ledger,
    check_root_hygiene,
    check_secrets,
    check_self_containment,
    run_doctor,
)


class DoctorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = run_doctor(support.REPO_ROOT)

    def test_report_shape(self):
        self.assertIn("results", self.report)
        self.assertIn("summary", self.report)
        self.assertIn("ok", self.report)

    def test_statuses_are_valid(self):
        for result in self.report["results"]:
            self.assertIn(result["status"], {"PASS", "WARN", "FAIL"})

    def test_summary_matches_results(self):
        for status in ("PASS", "WARN", "FAIL"):
            expected = sum(1 for r in self.report["results"] if r["status"] == status)
            self.assertEqual(self.report["summary"][status], expected)

    def test_no_failures(self):
        self.assertEqual(self.report["summary"]["FAIL"], 0, self.report["results"])
        self.assertTrue(self.report["ok"])

    def test_expected_checks_present(self):
        ids = {r["id"] for r in self.report["results"]}
        for required in [
            "structure", "required_files", "root_hygiene", "configuration", "schema_index",
            "system_refs", "schema_syntax", "json_integrity", "runtime",
            "jsonschema", "git_available", "git_repo", "secrets", "self_containment",
            "adapter", "capabilities", "project_alignment", "baseline_ledger",
        ]:
            self.assertIn(required, ids)

    def test_doctor_on_empty_dir_fails_structure(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            report = run_doctor(Path(tmp))
            by_id = {r["id"]: r for r in report["results"]}
            self.assertEqual(by_id["structure"]["status"], "FAIL")
            self.assertFalse(report["ok"])


class RootHygieneTests(unittest.TestCase):
    """The root layout contract is fail-closed on unexpected files.

    Each case builds a throwaway root so the assertion covers the contract itself,
    not the current contents of the repository.
    """

    def _check(self, entries):
        """Run check_root_hygiene against a throwaway root holding `entries`.

        A trailing "/" creates a directory; anything else becomes a file.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            for name in entries:
                path = Path(tmp) / name.rstrip("/")
                if name.endswith("/"):
                    path.mkdir()
                else:
                    path.write_text("x", encoding="utf-8")
            return check_root_hygiene(Path(tmp))

    def test_unexpected_file_fails_closed(self):
        status, detail = self._check(["README.md", "stray.py"])
        self.assertEqual(status, "FAIL")
        self.assertIn("stray.py", detail)

    def test_unexpected_directory_warns(self):
        status, detail = self._check(["CORE/", "SCRIPTS/", "MY_LAB/"])
        self.assertEqual(status, "WARN")
        self.assertIn("MY_LAB", detail)

    def test_file_outranks_directory(self):
        status, detail = self._check(["MY_LAB/", "stray.py"])
        self.assertEqual(status, "FAIL")
        self.assertIn("stray.py", detail)

    def test_runtime_noise_is_ignored(self):
        status, _ = self._check(["README.md", "__pycache__/", ".pytest_cache/", "run.log"])
        self.assertEqual(status, "PASS")

    def test_git_metadata_is_not_an_unexpected_entry(self):
        # `.git` is repository infrastructure. Running `git init` must not turn the
        # hygiene check red on the very directory it was built to keep clean.
        status, _ = self._check(["README.md", ".git/"])
        self.assertEqual(status, "PASS")

    def test_declared_layout_passes(self):
        status, _ = self._check(["README.md", "VERSION", "CORE/", "MASTER SYSTEM/"])
        self.assertEqual(status, "PASS")


class BaselineLedgerTests(unittest.TestCase):
    """Each ledger state must map to a severity the operator can act on.

    The temp root has no real baseline, so the baseline and the ledger are written
    by hand: the JSONL is the artifact under test, and building it through
    `_record_coverage_baseline_rebase` would only exercise the happy path of the
    very writer whose output the check is supposed to judge.
    """

    ALPHA = "DOCS/reference/alpha.md"

    def _root(self, alpha_hash, log_entry=None):
        """Throwaway root holding a baseline for `alpha_hash` and an optional ledger line."""
        import json
        import tempfile

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        docs = root / "DOCS"
        docs.mkdir(parents=True, exist_ok=True)
        support.write_json(
            docs / "coverage-baseline.json",
            {
                "version": 1,
                "documents": {"reference": [{"path": self.ALPHA, "hash": alpha_hash}]},
            },
        )
        if log_entry is not None:
            (docs / "coverage-baseline.log.jsonl").write_text(
                json.dumps(log_entry) + "\n", encoding="utf-8"
            )
        return root

    def _entry(self, changes):
        return {
            "at": "2026-01-01T00:00:00Z",
            "record_type": "coverage_baseline",
            "record_id": "2026-01-01T00:00:00Z-0001",
            "by": "tester",
            "reason": "alpha was rewritten",
            "changes": changes,
        }

    def test_matching_entry_passes(self):
        root = self._root("bbb2", self._entry([{"path": self.ALPHA, "from": "aaa1", "to": "bbb2"}]))

        status, detail = check_baseline_ledger(root)

        self.assertEqual(status, "PASS", detail)
        self.assertIn("2026-01-01T00:00:00Z-0001", detail)

    def test_missing_ledger_warns_because_the_control_is_inactive(self):
        root = self._root("bbb2")

        status, detail = check_baseline_ledger(root)

        self.assertEqual(status, "WARN", detail)
        self.assertIn("coverage-baseline.log.jsonl", detail)

    def test_entry_without_verification_warns(self):
        root = self._root("bbb2", self._entry([]))

        status, detail = check_baseline_ledger(root)

        self.assertEqual(status, "WARN", detail)
        self.assertIn("2026-01-01T00:00:00Z-0001", detail)

    def test_hand_edited_baseline_fails(self):
        root = self._root(
            "deadbeefdeadbeef",
            self._entry([{"path": self.ALPHA, "from": "aaa1", "to": "bbb2"}]),
        )

        status, detail = check_baseline_ledger(root)

        self.assertEqual(status, "FAIL", detail)
        self.assertIn(self.ALPHA, detail)


class SelfContainmentSurfaceTests(unittest.TestCase):
    """A forbidden token is a dependency on an operational surface and only
    provenance elsewhere, and the report always states the true scale."""

    def _root_with(self, rel: str, body: str) -> Path:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        return root

    def test_dependency_surface_hit_fails(self):
        root = self._root_with("SCRIPTS/se_core/leak.json",
                               '{"path": "D:/somehost/system"}\n')
        status, detail = check_self_containment(root)
        self.assertEqual(status, "FAIL")
        self.assertIn("dependency", detail)

    def test_guidance_hit_warns_but_states_the_count(self):
        """A reference in a document a reader would follow is not a defect, but
        it is not clean either: we own that document, so it stays a WARN. The
        count must stay exact so the scale is never hidden."""
        root = self._root_with("DOCS/reference/architecture.md",
                               "the system lives at /mnt/d/somehost/system\n")
        status, detail = check_self_containment(root)
        self.assertEqual(status, "WARN")
        self.assertIn("1 guidance hit(s)", detail)
        self.assertIn("none on operational surfaces", detail)

    def test_declared_record_tree_reports_pass_with_exact_count(self):
        """A declared record tree is history, not guidance. It must not WARN --
        rewriting it would fabricate evidence -- but the exact count stays
        visible so the scale is never hidden."""
        root = self._root_with("DOCS/checkpoints/001/REPORT.md",
                               "ran on servidor-ia at the time\n")
        status, detail = check_self_containment(root)
        self.assertEqual(status, "PASS")
        self.assertIn("1 record hit(s)", detail)
        self.assertIn("none in live guidance", detail)

    def test_undeclared_tree_is_never_treated_as_record(self):
        """The record allowlist is declared, not inferred. A tree that is not
        named keeps warning so it cannot accumulate host paths silently."""
        root = self._root_with("DOCS/reference/misc-notes.md",
                               "moved from D:/somehost/system\n")
        status, detail = check_self_containment(root)
        self.assertEqual(status, "WARN")
        self.assertIn("guidance hit(s)", detail)

    def test_exact_file_record_declared_reports_pass(self):
        """An exactly-named historical report is a declared record: it must not
        WARN, and the exact count must stay visible so the scale is never hidden."""
        root = self._root_with(
            "DOCS/reference/execution-engine-v1-real-execution-probe-report.md",
            "probe at D:/somehost/EXECUTION-ENGINE-V1-TEST\n")
        status, detail = check_self_containment(root)
        self.assertEqual(status, "PASS", detail)
        self.assertIn("1 record hit(s)", detail)
        self.assertIn("none in live guidance", detail)

    def test_undeclared_same_family_sibling_still_warns(self):
        """Exact-path record declaration must not leak by naming family: a sibling
        that was never declared keeps WARNing so it cannot accumulate silently."""
        root = self._root_with(
            "DOCS/reference/long-run-test-v2-plan.md",
            "probe at D:/somehost/LONG-RUN-TEST-V2\n")
        status, detail = check_self_containment(root)
        self.assertEqual(status, "WARN", detail)
        self.assertIn("guidance hit(s)", detail)
        self.assertIn("none on operational surfaces", detail)

    def test_locally_declared_project_tree_reports_pass(self):
        """A site-local declaration (gitignored `.se/doctor-record-roots.json`)
        makes a deployed managed project's evidence report as record, not
        guidance. Undeclared managed projects keep WARNing (test_project_policy)."""
        root = self._root_with(
            "PROJECTS/SHEMASEG/evidence/EVD-0001.json",
            '{"command": "se init --dir D:\\\\SHEMASEG"}\n')
        support.write_json(root / "PROJECTS" / "SHEMASEG" / "PROJECT.json",
                           support.manifest())
        (root / ".se").mkdir()
        (root / ".se" / "doctor-record-roots.json").write_text(
            '["PROJECTS/SHEMASEG"]\n', encoding="utf-8")
        status, detail = check_self_containment(root)
        self.assertEqual(status, "PASS", detail)
        self.assertIn("1 record hit(s)", detail)
        self.assertIn("none in live guidance", detail)

    def test_root_manifest_counts_as_dependency(self):
        root = self._root_with("SYSTEM.json", '{"repository": "/mnt/d/somehost/x"}\n')
        status, _ = check_self_containment(root)
        self.assertEqual(status, "FAIL")

    def test_report_states_total_not_truncated_count(self):
        root = self._root_with("DOCS/reference/move-relocation-batch-1.md",
                               "".join("servidor-ia line %d\n" % i for i in range(40)))
        status, detail = check_self_containment(root)
        self.assertEqual(status, "PASS")
        self.assertIn("40 record hit(s)", detail)
        self.assertIn("+35 more", detail)

    def test_clean_root_passes(self):
        root = self._root_with("README.md", "nothing external here\n")
        status, _ = check_self_containment(root)
        self.assertEqual(status, "PASS")

    def test_dependency_takes_precedence_over_provenance(self):
        root = self._root_with("DOCS/report.md", "servidor-ia history\n")
        (root / "MASTER SYSTEM").mkdir()
        (root / "MASTER SYSTEM" / "MANIFEST.json").write_text(
            '{"repository": "D:/host/x"}\n', encoding="utf-8")
        status, detail = check_self_containment(root)
        self.assertEqual(status, "FAIL")
        self.assertIn("1 dependency hit(s)", detail)
        self.assertIn("guidance hits: 1", detail)


    def test_jsonc_surface_is_scanned(self):
        """opencode.jsonc declares MCP paths, so the scan has to be able to read it."""
        root = self._root_with("opencode.jsonc", '{"args": ["D:/host/x"]}\n')
        status, detail = check_self_containment(root)
        self.assertEqual(status, "FAIL")
        self.assertIn("opencode.jsonc:1", detail)

    def test_token_list_covers_windows_and_wsl_paths(self):
        for body, label in (('"p": "/mnt/d/x"', "wsl"), ('"p": "D:/x"', "win-slash"),
                            ('"p": "D:\\\\x"', "win-backslash")):
            with self.subTest(label):
                root = self._root_with("SYSTEM.json", body + "\n")
                status, _ = check_self_containment(root)
                self.assertEqual(status, "FAIL")

class SecretScanTests(unittest.TestCase):
    """The secret scan follows the repository's own answer to what it publishes.

    `.gitignore` is what git ships, so the same file name means two different
    things on either side of an ignore rule: a local workspace copy is not
    published, while a tracked copy is -- even when a pattern matches it, because
    `git add --force` is exactly how a published file ends up matching one.

    Every case builds a throwaway repository, so the assertion covers the contract
    instead of the contents of this checkout.
    """

    def _isolated_env(self, root):
        """No user or system git configuration: a machine's global ignore rules
        must not decide what these tests see."""
        absent = str(root / "absent-gitconfig")
        return mock.patch.dict(
            os.environ, {"GIT_CONFIG_GLOBAL": absent, "GIT_CONFIG_SYSTEM": absent}
        )

    def _run_git(self, root, *args):
        return subprocess.run(
            ["git", "-C", str(root)] + list(args),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )

    def _root(self, repo=True, gitignore=None, files=(), forced=()):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        for rel in list(files) + list(forced):
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("TOKEN=1\n", encoding="utf-8")
        if gitignore is not None:
            (root / ".gitignore").write_text(gitignore, encoding="utf-8")
        if repo:
            with self._isolated_env(root):
                self._run_git(root, "init", "-q")
                for rel in forced:
                    self._run_git(root, "add", "--force", "--", rel)
        return root

    def test_ignored_local_env_is_not_a_published_secret(self):
        """The exact shape of a local managed project: an ignored workspace whose
        `.env` this repository never publishes."""
        root = self._root(gitignore="PROJECTS/*\n", files=["PROJECTS/LOCAL/.env"])
        support.write_json(root / "PROJECTS" / "LOCAL" / "PROJECT.json", support.manifest())

        with self._isolated_env(root):
            status, detail = check_secrets(root)

        self.assertEqual(status, "PASS", detail)
        self.assertIn("1 gitignored local file(s) not published", detail)

    def test_unpublished_but_unignored_env_still_fails(self):
        """Untracked is not the same as unpublished: a file git would add is a
        defect of the published tree, so it is still reported."""
        root = self._root(files=[".env"])

        with self._isolated_env(root):
            status, detail = check_secrets(root)

        self.assertEqual(status, "FAIL", detail)
        self.assertIn(".env", detail)

    def test_forced_tracked_env_is_published_and_still_fails(self):
        """A matching ignore rule must not disarm the scan: `git add --force`
        publishes a file anyway, and then it is shipped."""
        root = self._root(gitignore="*.env\n", forced=[".env"])

        with self._isolated_env(root):
            status, detail = check_secrets(root)

        self.assertEqual(status, "FAIL", detail)

    def test_missing_git_reports_instead_of_passing(self):
        """Without git the check cannot know what is published, so it fails
        closed on what it did find."""
        root = self._root(gitignore="PROJECTS/*\n", files=["PROJECTS/LOCAL/.env"])
        support.write_json(root / "PROJECTS" / "LOCAL" / "PROJECT.json", support.manifest())

        with self._isolated_env(root), mock.patch("shutil.which", return_value=None):
            status, detail = check_secrets(root)

        self.assertEqual(status, "FAIL", detail)

    def test_no_repository_reports_instead_of_passing(self):
        """A directory outside version control publishes nothing, and cannot say
        so on its own: the scan keeps reporting rather than assuming."""
        root = self._root(repo=False, files=[".env"])

        with self._isolated_env(root):
            status, detail = check_secrets(root)

        self.assertEqual(status, "FAIL", detail)


if __name__ == "__main__":
    unittest.main()
