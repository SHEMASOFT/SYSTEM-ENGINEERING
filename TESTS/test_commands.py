"""Command behaviour tests (hermetic, temporary project workspaces)."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.cli import build_parser, main  # noqa: E402

from se_core import commands  # noqa: E402


def run(*argv):
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main(list(argv))
    return code, buffer.getvalue()


class CommandTests(unittest.TestCase):
    def test_root_help_points_to_the_console(self):
        """SE-07: someone types `se console` and gets a bare error. The console is
        a separate read-only web app, so the root help must say where it lives."""
        text = build_parser().format_help()
        self.assertIn("SE-CONSOLE", text)

    def test_init_creates_valid_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "demo"
            code, out = run("init", "--dir", str(project), "--name", "Demo App",
                            "--owner", "alice", "--domains", "software")
            self.assertEqual(code, 0, out)
            manifest = json.loads((project / "PROJECT.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["project_id"].startswith("PRJ-"))
            self.assertEqual(manifest["lifecycle_state"], "DRAFT")
            code, out = run("validate", "--project", str(project))
            self.assertEqual(code, 0, out)

    def test_init_rejects_invalid_domain(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out = run("init", "--dir", str(Path(tmp) / "x"), "--name", "X",
                            "--owner", "o", "--domains", "Not A Domain")
            self.assertEqual(code, 2, out)

    def test_explore_advances_after_g0(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "demo"
            run("init", "--dir", str(project), "--name", "Demo", "--owner", "o")
            code, out = run("explore", "--project", str(project))
            self.assertEqual(code, 0, out)
            self.assertTrue((project / "discovery.json").exists())
            manifest = json.loads((project / "PROJECT.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["lifecycle_state"], "DISCOVERY")

    def test_gate_g0_passes_after_init(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "demo"
            run("init", "--dir", str(project), "--name", "Demo", "--owner", "o")
            code, out = run("gate", "--project", str(project), "--gate", "G0")
            self.assertEqual(code, 0, out)
            self.assertIn("Gate result: PASS", out)

    def test_gate_unknown_returns_usage_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "demo"
            run("init", "--dir", str(project), "--name", "Demo", "--owner", "o")
            code, out = run("gate", "--project", str(project), "--gate", "G42")
            self.assertEqual(code, 2, out)

    def test_plan_scaffolds_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "demo"
            run("init", "--dir", str(project), "--name", "Demo", "--owner", "o")
            support.write_json(project / "requirements" / "REQ-0001.json", support.requirement())
            code, out = run("plan", "--project", str(project), "--create-tasks")
            self.assertEqual(code, 0, out)
            tasks = list((project / "tasks").glob("TASK-*.json"))
            self.assertEqual(len(tasks), 1)

    def test_release_creation_and_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "demo"
            run("init", "--dir", str(project), "--name", "Demo", "--owner", "o")
            code, out = run("release", "--project", str(project), "--version", "0.1.0",
                            "--scope", "Initial", "--approve", "--by", "o")
            self.assertEqual(code, 0, out)
            release = json.loads((project / "releases" / "REL-0001.json").read_text(encoding="utf-8"))
            self.assertEqual(release["status"], "APPROVED")

    def test_review_reports_no_findings_for_clean_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "demo"
            run("init", "--dir", str(project), "--name", "Demo", "--owner", "o")
            code, out = run("review", "--project", str(project))
            self.assertEqual(code, 0, out)

    def test_review_detects_broken_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "demo"
            run("init", "--dir", str(project), "--name", "Demo", "--owner", "o")
            support.write_json(
                project / "tasks" / "TASK-0001.json",
                support.task(related_requirements=["REQ-9999"]),
            )
            code, out = run("review", "--project", str(project))
            self.assertEqual(code, 1, out)
            self.assertIn("unresolved reference", out)

    def test_doctor_command(self):
        code, out = run("doctor")
        self.assertEqual(code, 0, out)
        self.assertIn("Doctor summary", out)

    def test_delta_warn_flags_non_vocabulary_verb(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = root / "DOCS"
            docs.mkdir()
            (docs / "EXAMPLE.md").write_text(
                "## Delta\n- **ADDED** ok\n- **BOGUS** mal\n", encoding="utf-8")
            warnings = commands._doc_delta_warnings(root)
            self.assertEqual(len(warnings), 1, warnings)
            self.assertIn("BOGUS", warnings[0])

    def test_delta_warn_ignores_placeholders_and_clean_verbs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = root / "DOCS"
            docs.mkdir()
            (docs / "OK.md").write_text(
                "## Delta\n- **<TIPO>** ficha\n- **VERIFIED** suite\n", encoding="utf-8")
            (root / "SKILLS").mkdir()
            self.assertEqual(commands._doc_delta_warnings(root), [])

    def test_dangling_skill_ref_warn(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "SKILLS").mkdir()
            (root / "ARCH-X.md").write_text("referencia a SK-9999\n", encoding="utf-8")
            warnings = commands._doc_dangling_skill_refs(root)
            self.assertTrue(any("SK-9999" in w for w in warnings), warnings)

    def test_g5_report_includes_min_evidence_guidance(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "demo"
            run("init", "--dir", str(project), "--name", "Demo", "--owner", "o")
            support.write_json(project / "requirements" / "REQ-0001.json", support.requirement())
            code, out = run("gate", "--project", str(project), "--gate", "G5")
            self.assertIn("GUIDE: MIN_EVIDENCE", out)


class DanglingSkillRefTests(unittest.TestCase):
    """`_doc_dangling_skill_refs` must not confuse task ids with skill ids."""

    def _warnings(self, doc_text: str) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / "SKILLS" / "demo"
            skill.mkdir(parents=True)
            (skill / "SKILL.json").write_text(
                json.dumps({"schema_version": "1", "skill_id": "SK-0001", "name": "demo"}),
                encoding="utf-8",
            )
            docs = root / "DOCS"
            docs.mkdir()
            (docs / "note.md").write_text(doc_text, encoding="utf-8")
            return commands._doc_dangling_skill_refs(root)

    def test_declared_skill_id_is_not_dangling(self):
        self.assertEqual(self._warnings("uses SK-0001 today"), [])

    def test_task_ids_are_not_skill_references(self):
        # `TASK-0701` contains the substring `SK-0701`; an unanchored pattern
        # reported every one of these as a dangling skill reference.
        warnings = self._warnings("TASK-0701 closed after TASK-0099 and REQ-0501")
        self.assertEqual(warnings, [])

    def test_undeclared_skill_id_is_still_reported(self):
        warnings = self._warnings("applies SK-0009 but never SK-9999")
        self.assertEqual(len(warnings), 2)
        # `set(...)` iteration order is not stable, so assert on the whole result.
        self.assertIn("SK-0009", warnings[0] + warnings[1])
        self.assertIn("SK-9999", warnings[0] + warnings[1])


class DanglingAdrRefTests(unittest.TestCase):
    """`_doc_dangling_adr_refs` must catch a citation to a decision nobody recorded."""

    def _warnings(self, doc_text: str) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adr = root / "DOCS" / "adr"
            adr.mkdir(parents=True)
            (adr / "ADR-0001-demo.json").write_text(
                json.dumps({"schema_version": "1", "decision_id": "ADR-0001"}),
                encoding="utf-8",
            )
            docs = root / "DOCS"
            (docs / "note.md").write_text(doc_text, encoding="utf-8")
            return commands._doc_dangling_adr_refs(root)

    def test_declared_adr_id_is_not_dangling(self):
        self.assertEqual(self._warnings("supersedes ADR-0001"), [])

    def test_undeclared_adr_id_is_reported(self):
        warnings = self._warnings("recorded as ADR-0025")
        self.assertEqual(len(warnings), 1)
        self.assertIn("ADR-0025", warnings[0])

    def test_non_breaking_hyphen_is_not_a_miss(self):
        # The citation that survived in AUTO-04-REPORT.md used U+2011, so a plain
        # `ADR-\d{4}` pattern reported zero warnings and nothing flagged it.
        warnings = self._warnings("recorded as ADR\u20110025")
        self.assertEqual(len(warnings), 1)
        self.assertIn("ADR-0025", warnings[0])

    def test_declared_by_field_when_filename_drifted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adr = root / "DOCS" / "adr"
            adr.mkdir(parents=True)
            (adr / "ADR-0007-renamed.json").write_text(
                json.dumps({"schema_version": "1", "decision_id": "ADR-0007"}),
                encoding="utf-8",
            )
            (root / "DOCS" / "note.md").write_text("applies ADR-0007", encoding="utf-8")
            self.assertEqual(commands._doc_dangling_adr_refs(root), [])


class CoverageBaselineTest(unittest.TestCase):
    """The baseline generator and the coverage guardrail must share one shape."""

    @classmethod
    def setUpClass(cls):
        cls.payload = commands._compute_coverage_baseline(support.REPO_ROOT)
        cls.on_disk = json.loads(
            (support.REPO_ROOT / "DOCS" / "coverage-baseline.json").read_text(encoding="utf-8")
        )

    def test_emits_the_stored_artifact_shape(self):
        self.assertEqual(sorted(self.payload), sorted(self.on_disk))
        self.assertEqual(sorted(self.payload["documents"]), sorted(self.on_disk["documents"]))

    def test_every_entry_has_posix_path_and_16_char_hash(self):
        for category, entries in self.payload["documents"].items():
            for entry in entries:
                self.assertNotIn("\\", entry["path"], f"{category}/{entry['path']}")
                self.assertEqual(len(entry["hash"]), 16, entry["path"])

    def test_minimums_agree_with_the_stored_baseline(self):
        self.assertEqual(self.payload["minimums"], self.on_disk["minimums"])

    def test_every_category_meets_its_minimum(self):
        for name, minimum in self.payload["minimums"].items():
            self.assertGreaterEqual(len(self.payload["documents"][name]), minimum, name)


class CoverageBaselineLedgerTests(unittest.TestCase):
    """Rebasing the coverage baseline must be a governed, journalled operation.

    `coverage_count_test` compares the tree against `DOCS/coverage-baseline.json`,
    so a hand-written rebase destroys the only evidence that a document changed.
    These tests pin the ledger that makes that visible.
    """

    RESOLVER_CONFIG = {
        "version": 1,
        "mappings": [
            {
                "logical_name": "reference",
                "patterns": ["DOCS/reference/**/*.md"],
            },
            {
                "logical_name": "initiatives",
                "patterns": ["DOCS/initiatives/**/*.md"],
            },
            {
                "logical_name": "checkpoints",
                "patterns": ["DOCS/checkpoints/**/*.md"],
            },
            {
                "logical_name": "validation",
                "patterns": ["DOCS/validation/*.md"],
            },
        ],
    }

    ALPHA = "DOCS/reference/alpha.md"
    BETA = "DOCS/initiatives/beta.md"
    KEEP = "DOCS/checkpoints/keep.md"

    def _build_root(self, root: Path) -> Path:
        """Create a temp root whose baseline matches the documents on disk."""
        (root / "DOCS").mkdir(parents=True, exist_ok=True)
        support.write_json(root / "resolver-config.json", self.RESOLVER_CONFIG)
        for rel, body in (
            (self.ALPHA, "# Alpha\n\nversion one.\n"),
            (self.BETA, "# Beta\n\ncontent.\n"),
            (self.KEEP, "# Keep\n\nunchanged.\n"),
        ):
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
        support.write_json(
            root / "DOCS" / "coverage-baseline.json",
            commands._compute_coverage_baseline(root),
        )
        return root

    def _temp_root(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return self._build_root(Path(tmp.name) / "root")

    def _rewrite_doc(self, root: Path, rel: str, body: str) -> None:
        (root / rel).write_text(body, encoding="utf-8")

    def _ledger(self, root: Path) -> list[str]:
        path = Path(root) / commands.COVERAGE_BASELINE_LOG
        if not path.exists():
            return []
        return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _entries(self, root: Path) -> list[dict]:
        return [json.loads(line) for line in self._ledger(root)]

    def test_delta_reports_modified_added_and_lost_documents(self):
        old = {
            "documents": {
                "reference": [{"path": self.ALPHA, "hash": "aaa1"}, {"path": self.KEEP, "hash": "kkk1"}],
                "initiatives": [{"path": self.BETA, "hash": "bbb1"}],
            }
        }
        new = {
            "documents": {
                "reference": [{"path": self.ALPHA, "hash": "aaa2"}, {"path": self.KEEP, "hash": "kkk1"}],
                "initiatives": [],
                "checkpoints": [{"path": "DOCS/checkpoints/gamma.md", "hash": "ggg1"}],
            }
        }
        changes = commands._coverage_baseline_diff(old, new)
        self.assertEqual(
            changes,
            [
                {"path": "DOCS/checkpoints/gamma.md", "from": "", "to": "ggg1"},
                {"path": self.BETA, "from": "bbb1", "to": ""},
                {"path": self.ALPHA, "from": "aaa1", "to": "aaa2"},
            ],
        )

    def test_delta_tolerates_a_flat_path_to_hash_map(self):
        """The stored shape is nested per category, but the contract is path-keyed."""
        old = {"documents": {self.ALPHA: "aaa1"}}
        new = {"documents": {self.ALPHA: "aaa2"}}
        self.assertEqual(
            commands._coverage_baseline_diff(old, new),
            [{"path": self.ALPHA, "from": "aaa1", "to": "aaa2"}],
        )

    def test_rebase_without_reason_writes_nothing(self):
        root = self._temp_root()
        self._rewrite_doc(root, self.ALPHA, "# Alpha\n\nversion two.\n")
        baseline = root / "DOCS" / "coverage-baseline.json"
        before = baseline.read_text(encoding="utf-8")

        result = commands._record_coverage_baseline_rebase(root, "tester", "   ")

        self.assertFalse(result["written"])
        self.assertEqual(result["error"], "reason is required")
        self.assertEqual(self._ledger(root), [])
        self.assertEqual(baseline.read_text(encoding="utf-8"), before)

    def test_rebase_with_reason_appends_one_line_and_updates_the_baseline(self):
        root = self._temp_root()
        self._rewrite_doc(root, self.ALPHA, "# Alpha\n\nversion two.\n")

        result = commands._record_coverage_baseline_rebase(root, "tester", "alpha was rewritten")

        self.assertTrue(result["written"])
        self.assertEqual(result["path"], str(root / commands.COVERAGE_BASELINE_LOG))
        entries = self._entries(root)
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["record_type"], "coverage_baseline")
        self.assertEqual(entry["by"], "tester")
        self.assertEqual(entry["reason"], "alpha was rewritten")
        self.assertEqual(entry["changes"], result["changes"])
        change = entry["changes"][0]
        self.assertEqual(change["path"], self.ALPHA)
        self.assertTrue(change["from"], "a modified document must record its old hash")
        self.assertTrue(change["to"], "a modified document must record its new hash")
        self.assertNotEqual(change["from"], change["to"])

        on_disk = json.loads((root / "DOCS" / "coverage-baseline.json").read_text(encoding="utf-8"))
        recomputed = commands._compute_coverage_baseline(root)
        # ``created_at`` is a wall-clock timestamp, not content: the second may
        # tick between the rebase write and this recompute, which made this
        # assertion intermittently fail. Compare everything else.
        on_disk.pop("created_at", None)
        recomputed.pop("created_at", None)
        self.assertEqual(on_disk, recomputed)

    def test_rebase_without_changes_writes_nothing(self):
        root = self._temp_root()

        result = commands._record_coverage_baseline_rebase(root, "tester", "nothing moved")

        self.assertFalse(result["written"])
        self.assertEqual(result["changes"], [])
        self.assertEqual(self._ledger(root), [])

    def test_consecutive_rebases_get_distinct_record_ids(self):
        root = self._temp_root()
        self._rewrite_doc(root, self.ALPHA, "# Alpha\n\nversion two.\n")
        commands._record_coverage_baseline_rebase(root, "tester", "first")
        self._rewrite_doc(root, self.ALPHA, "# Alpha\n\nversion three.\n")
        commands._record_coverage_baseline_rebase(root, "tester", "second")

        entries = self._entries(root)
        self.assertEqual(len(entries), 2)
        self.assertNotEqual(entries[0]["record_id"], entries[1]["record_id"])
        self.assertLessEqual(entries[0]["at"], entries[1]["at"])

    def test_log_status_is_consistent_right_after_a_rebase(self):
        root = self._temp_root()
        self._rewrite_doc(root, self.ALPHA, "# Alpha\n\nversion two.\n")
        commands._record_coverage_baseline_rebase(root, "tester", "alpha was rewritten")

        status = commands._coverage_baseline_log_status(root)

        self.assertEqual(status["state"], "consistent", status["detail"])

    def test_log_status_reports_drift_after_a_hand_edited_baseline(self):
        root = self._temp_root()
        self._rewrite_doc(root, self.ALPHA, "# Alpha\n\nversion two.\n")
        commands._record_coverage_baseline_rebase(root, "tester", "alpha was rewritten")

        baseline_path = root / "DOCS" / "coverage-baseline.json"
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        for entry in baseline["documents"]["reference"]:
            if entry["path"] == self.ALPHA:
                entry["hash"] = "deadbeefdeadbeef"
        support.write_json(baseline_path, baseline)

        status = commands._coverage_baseline_log_status(root)

        self.assertEqual(status["state"], "drift")
        self.assertIn(self.ALPHA, status["detail"])
        self.assertIn("1", status["detail"])

    def test_log_status_is_unverified_when_the_last_entry_records_no_verification(self):
        # `_record_coverage_baseline_rebase` refuses to write a no-op entry, so an
        # empty `changes` list can only come from a hand-written ledger line. The
        # hash loop then runs zero times and the previous code answered
        # "consistent": a PASS that compared nothing, which reads as coverage the
        # baseline does not have.
        root = self._temp_root()
        log = root / commands.COVERAGE_BASELINE_LOG
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(
            json.dumps({
                "at": "2026-01-01T00:00:00Z",
                "record_type": "coverage_baseline",
                "record_id": "2026-01-01T00:00:00Z-0001",
                "by": "tester",
                "reason": "bootstrap ledger",
                "changes": [],
            }) + "\n",
            encoding="utf-8",
        )

        status = commands._coverage_baseline_log_status(root)

        self.assertNotEqual(status["state"], "consistent")
        self.assertEqual(status["state"], "unverified", status["detail"])
        self.assertIn("2026-01-01T00:00:00Z-0001", status["detail"])

    def test_log_status_treats_a_corrupt_line_as_drift(self):
        root = self._temp_root()
        log = root / commands.COVERAGE_BASELINE_LOG
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text('{"at": "2026-01-01T00:00:00Z", "record_ty\n', encoding="utf-8")

        status = commands._coverage_baseline_log_status(root)

        self.assertEqual(status["state"], "drift")
        self.assertIn("corrupt", status["detail"].lower())


if __name__ == "__main__":
    unittest.main()
