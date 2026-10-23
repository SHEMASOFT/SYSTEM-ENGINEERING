"""Tests for ``se_core.transaction`` (byte-level config + state journals).

Hermetic: every test works inside a ``tempfile.TemporaryDirectory``; no locks,
no processes, no real runtime.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: F401,E402  (puts SCRIPTS on sys.path)

from se_core import lifecycle_state as lc  # noqa: E402
from se_core import transaction  # noqa: E402


FIXED_NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


class BeginTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.target = Path(self._tmp.name).resolve()

    def tearDown(self):
        self._tmp.cleanup()

    def test_manifest_records_existing_and_absent_files(self):
        existing = self.target / "opencode.jsonc"
        existing.write_bytes(b'{"mcp": {"servers": {}}}\n')
        missing = self.target / ".se" / "lifecycle-state.json"

        journal = transaction.begin(
            self.target, "sync", [existing, missing], now=FIXED_NOW
        )

        self.assertEqual(journal["schema_version"], "1")
        self.assertEqual(journal["operation"], "sync")
        self.assertEqual(journal["status"], "open")
        self.assertEqual(journal["created_at"], "2026-01-02T03:04:05Z")
        self.assertEqual(journal["target"], str(self.target))
        self.assertTrue(Path(journal["manifest_path"]).exists())
        self.assertEqual(len(journal["files"]), 2)

        present, absent = journal["files"]
        self.assertEqual(present["path"], "opencode.jsonc")
        self.assertTrue(present["existed"])
        self.assertEqual(len(present["sha256"]), 64)
        self.assertEqual(present["bytes"], len(b'{"mcp": {"servers": {}}}\n'))
        self.assertIsNotNone(present["copy"])
        self.assertTrue((Path(journal["journal_dir"]) / present["copy"]).is_file())

        self.assertEqual(absent["path"], ".se/lifecycle-state.json")
        self.assertFalse(absent["existed"])
        self.assertEqual(absent["sha256"], "")
        self.assertEqual(absent["bytes"], 0)
        self.assertIsNone(absent["copy"])

    def test_same_second_collision_uses_incrementing_sequence(self):
        first = transaction.begin(self.target, "sync", [], now=FIXED_NOW)
        second = transaction.begin(self.target, "sync", [], now=FIXED_NOW)
        self.assertTrue(Path(first["journal_dir"]).name.endswith("-01"))
        self.assertTrue(Path(second["journal_dir"]).name.endswith("-02"))
        self.assertNotEqual(first["journal_dir"], second["journal_dir"])
        self.assertTrue(Path(first["manifest_path"]).is_file())
        self.assertTrue(Path(second["manifest_path"]).is_file())

    def test_manifest_is_written_as_lf(self):
        journal = transaction.begin(self.target, "install", [], now=FIXED_NOW)
        raw = Path(journal["manifest_path"]).read_bytes()
        self.assertNotIn(b"\r\n", raw)


class RollbackTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.target = Path(self._tmp.name).resolve()

    def tearDown(self):
        self._tmp.cleanup()

    def test_rollback_restores_existing_file_bytes_and_hashes(self):
        path = self.target / "opencode.jsonc"
        original = b'{\n  "mcp": {"servers": {}}\n}\n'
        path.write_bytes(original)
        journal = transaction.begin(self.target, "sync", [path], now=FIXED_NOW)

        path.write_bytes(b'{"mcp": {"servers": {"leak": {}}}}\n')
        result = transaction.rollback(journal)

        self.assertTrue(result["ok"], result)
        self.assertEqual(path.read_bytes(), original)
        self.assertIn("opencode.jsonc", result["restored"])
        self.assertEqual(result["hashes"]["opencode.jsonc"], journal["files"][0]["sha256"])
        self.assertEqual(result["changed_since_begin"], ["opencode.jsonc"])
        self.assertEqual(result["errors"], [])

    def test_rollback_removes_a_file_created_after_begin(self):
        missing = self.target / "opencode.jsonc"
        journal = transaction.begin(self.target, "sync", [missing], now=FIXED_NOW)
        self.assertFalse(missing.exists())

        missing.write_bytes(b'{"mcp": {"servers": {"created": {}}}}\n')
        result = transaction.rollback(journal)

        self.assertTrue(result["ok"], result)
        self.assertFalse(missing.exists())
        self.assertIn("opencode.jsonc", result["removed"])
        self.assertEqual(result["restored"], [])

    def test_rollback_of_unchanged_file_is_ok_and_not_reported_as_changed(self):
        path = self.target / "state.json"
        path.write_bytes(b"original")
        journal = transaction.begin(self.target, "sync", [path], now=FIXED_NOW)

        result = transaction.rollback(journal)

        self.assertTrue(result["ok"], result)
        self.assertEqual(path.read_bytes(), b"original")
        self.assertEqual(result["changed_since_begin"], [])
        self.assertEqual(result["restored"], ["state.json"])

    def test_rollback_marks_the_journal_rolled_back(self):
        path = self.target / "state.json"
        path.write_bytes(b"original")
        journal = transaction.begin(self.target, "sync", [path], now=FIXED_NOW)
        transaction.rollback(journal)
        manifest = json.loads(Path(journal["manifest_path"]).read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "rolled_back")


class CommitTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.target = Path(self._tmp.name).resolve()

    def tearDown(self):
        self._tmp.cleanup()

    def test_commit_marks_committed_and_keeps_bytes(self):
        path = self.target / "opencode.jsonc"
        path.write_bytes(b"before")
        journal = transaction.begin(self.target, "sync", [path], now=FIXED_NOW)
        path.write_bytes(b"after")

        committed = transaction.commit(journal)

        self.assertEqual(committed["status"], "committed")
        self.assertEqual(path.read_bytes(), b"after")
        manifest = json.loads(Path(journal["manifest_path"]).read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "committed")
        self.assertEqual(manifest["files"], journal["files"])


class RecoverOpenTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.target = Path(self._tmp.name).resolve()

    def tearDown(self):
        self._tmp.cleanup()

    def test_recovers_open_journal_and_leaves_committed_untouched(self):
        open_path = self.target / "opencode.jsonc"
        open_path.write_bytes(b"open-original")
        open_journal = transaction.begin(self.target, "sync", [open_path], now=FIXED_NOW)
        open_path.write_bytes(b"open-mutated")

        committed_path = self.target / "committed.json"
        committed_path.write_bytes(b"committed-original")
        committed_journal = transaction.begin(
            self.target, "sync", [committed_path], now=FIXED_NOW
        )
        committed_path.write_bytes(b"committed-mutated")
        transaction.commit(committed_journal)

        result = transaction.recover_open(self.target)

        self.assertEqual(result["errors"], [])
        self.assertEqual(result["recovered"], [open_journal["journal_dir"]])
        self.assertEqual(open_path.read_bytes(), b"open-original")
        # the committed journal is an audit record: its file is not restored
        self.assertEqual(committed_path.read_bytes(), b"committed-mutated")
        manifest = json.loads(
            Path(committed_journal["manifest_path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["status"], "committed")

    def test_operation_filter_only_recovers_matching_journals(self):
        sync_path = self.target / "sync.txt"
        sync_path.write_bytes(b"sync-original")
        sync_journal = transaction.begin(self.target, "sync", [sync_path], now=FIXED_NOW)
        sync_path.write_bytes(b"sync-mutated")

        install_path = self.target / "install.txt"
        install_path.write_bytes(b"install-original")
        install_journal = transaction.begin(
            self.target, "install", [install_path], now=FIXED_NOW
        )
        install_path.write_bytes(b"install-mutated")

        result = transaction.recover_open(self.target, operation="install")

        self.assertEqual(result["recovered"], [install_journal["journal_dir"]])
        self.assertEqual(install_path.read_bytes(), b"install-original")
        self.assertEqual(sync_path.read_bytes(), b"sync-mutated")
        manifest = json.loads(
            Path(sync_journal["manifest_path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["status"], "open")

    def test_no_backups_directory_is_a_noop(self):
        result = transaction.recover_open(self.target)
        self.assertEqual(result, {"recovered": [], "errors": [], "results": []})
        self.assertFalse((self.target / ".se").exists())


class ListOpenTests(unittest.TestCase):
    """``list_open`` is read-only: it only reports journals that need recovery."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.target = Path(self._tmp.name).resolve()

    def tearDown(self):
        self._tmp.cleanup()

    def test_returns_only_open_journals_without_mutating_anything(self):
        path = self.target / "opencode.jsonc"
        path.write_bytes(b"original")
        open_journal = transaction.begin(self.target, "sync", [path], now=FIXED_NOW)

        committed_path = self.target / "other.json"
        committed_path.write_bytes(b"other")
        committed_journal = transaction.begin(
            self.target, "install", [committed_path], now=FIXED_NOW
        )
        transaction.commit(committed_journal)

        file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest_hash = hashlib.sha256(
            Path(open_journal["manifest_path"]).read_bytes()
        ).hexdigest()
        listing_before = sorted(p.name for p in lc.backup_dir(self.target).iterdir())

        journals = transaction.list_open(self.target)

        self.assertEqual(
            [journal["journal_dir"] for journal in journals],
            [open_journal["journal_dir"]],
        )
        self.assertEqual(journals[0]["manifest_path"], open_journal["manifest_path"])
        # read-only: file bytes, manifest bytes and the backups tree are intact
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), file_hash)
        self.assertEqual(
            hashlib.sha256(
                Path(open_journal["manifest_path"]).read_bytes()
            ).hexdigest(),
            manifest_hash,
        )
        self.assertEqual(
            sorted(p.name for p in lc.backup_dir(self.target).iterdir()),
            listing_before,
        )
        manifest = json.loads(
            Path(open_journal["manifest_path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["status"], "open")

    def test_respects_the_operation_filter(self):
        sync_journal = transaction.begin(self.target, "sync", [], now=FIXED_NOW)
        install_journal = transaction.begin(
            self.target, "install", [], now=FIXED_NOW
        )

        self.assertEqual(
            [
                journal["journal_dir"]
                for journal in transaction.list_open(
                    self.target, operation="install"
                )
            ],
            [install_journal["journal_dir"]],
        )
        self.assertEqual(
            {
                journal["journal_dir"]
                for journal in transaction.list_open(self.target)
            },
            {sync_journal["journal_dir"], install_journal["journal_dir"]},
        )

    def test_no_backups_directory_returns_empty_without_creating_it(self):
        self.assertEqual(transaction.list_open(self.target), [])
        self.assertFalse((self.target / ".se").exists())


if __name__ == "__main__":
    unittest.main()
