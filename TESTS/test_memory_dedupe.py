"""Memory dedupe and governance tests (ADR-0027 Phase 4).

Hermetic: temporary directories only, no network, no external memory service.

Phase 4 gives the record its identity and lifecycle semantics:

  - ``topic_key`` is an explicit upsert key: a repeated save of the same topic
    revises the record in place instead of piling up copies.
  - exact dedupe is opt-in, because identical text can still be two genuinely
    distinct records and a plain ``add`` must never silently swallow one.
  - ``state`` is a real lifecycle, not a label: ``deprecated`` is a soft delete
    and stays out of ``query``/``search`` unless asked for by name.
  - the schema and the derived index both carry the new fields, and a format
    change in the index is repaired by reindexing rather than by mixing layouts.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.memory import index as index_module  # noqa: E402
from se_core.memory.engine import MemoryEngine  # noqa: E402
from se_core.memory.index import INDEX_SCHEMA_VERSION, MemoryIndex  # noqa: E402
from se_core.paths import now_utc  # noqa: E402

ALPHA = "PRJ-TEST-001"
BETA = "PRJ-TEST-002"


def _master(tmp):
    root = Path(tmp) / "master"
    support.make_project(root / "PROJECTS" / "Alpha")
    beta = support.make_project(root / "PROJECTS" / "Beta")
    support.write_json(beta / "PROJECT.json", support.manifest(project_id=BETA))
    return root


def _add(engine, **over):
    data = {
        "project_id": ALPHA,
        "type": "decision",
        "content": {"summary": "Use FTS5 as a derived index"},
        "author": "tester",
    }
    data.update(over)
    return engine.add(**data)


def _records(engine, project_id=ALPHA):
    return engine.query(project_id=project_id, state="active")["memories"]


class TopicKeyUpsertTests(unittest.TestCase):
    def test_topic_key_revises_in_place(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = MemoryEngine(root=_master(tmp))

            first = _add(engine, topic_key="index-choice")
            second = _add(engine, topic_key="index-choice", content={"summary": "Revised"})

            self.assertEqual(first["status"], "created")
            self.assertEqual(second["status"], "revised")
            self.assertEqual(first["memory_id"], second["memory_id"])
            self.assertEqual(second["revision_count"], 1)

            record = engine.get(first["memory_id"], ALPHA)
            self.assertEqual(record["content"], {"summary": "Revised"})
            self.assertEqual(record["revision_count"], 1)
            self.assertEqual(len(_records(engine)), 1)

    def test_revision_count_grows_with_each_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = MemoryEngine(root=_master(tmp))

            memory_id = None
            for revision in range(4):
                result = _add(engine, topic_key="repeat", content={"n": revision})
                memory_id = result["memory_id"]

            record = engine.get(memory_id, ALPHA)
            self.assertEqual(record["revision_count"], 3)
            self.assertEqual(record["content"], {"n": 3})
            self.assertEqual(len(_records(engine)), 1)

    def test_revision_updates_last_seen_and_timestamps(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = MemoryEngine(root=_master(tmp))

            memory_id = _add(engine, topic_key="seen")["memory_id"]
            before = engine.get(memory_id, ALPHA)

            _add(engine, topic_key="seen", content={"summary": "again"})
            after = engine.get(memory_id, ALPHA)

            self.assertEqual(after["created_at"], before["created_at"])
            self.assertIsNotNone(after["last_seen_at"])
            self.assertGreaterEqual(after["updated_at"], before["updated_at"])
            self.assertEqual(before["last_seen_at"], None)

    def test_topic_key_is_scoped_to_a_project(self):
        """The same key in another project is another memory, not a revision.

        IDs are project-scoped, so both records are legitimately ``MEM-0001``:
        what must differ is the record each project resolves, and the first
        project's record must be left completely alone.
        """
        with tempfile.TemporaryDirectory() as tmp:
            engine = MemoryEngine(root=_master(tmp))

            alpha = _add(engine, topic_key="shared-topic", content={"summary": "alpha"})
            beta = _add(engine, project_id=BETA, topic_key="shared-topic")

            self.assertEqual(beta["status"], "created")
            self.assertEqual(len(_records(engine, ALPHA)), 1)
            self.assertEqual(len(_records(engine, BETA)), 1)

            untouched = engine.get(alpha["memory_id"], ALPHA)
            self.assertEqual(untouched["revision_count"], 0)
            self.assertEqual(untouched["content"], {"summary": "alpha"})
            self.assertEqual(engine.get(beta["memory_id"], BETA)["project_id"], BETA)

    def test_memory_ids_restart_in_each_project(self):
        """The addressing contract: ``MEM-XXXX`` is unique per project, not globally."""
        with tempfile.TemporaryDirectory() as tmp:
            engine = MemoryEngine(root=_master(tmp))

            alpha = _add(engine)
            beta = _add(engine, project_id=BETA)

            self.assertEqual(alpha["memory_id"], "MEM-0001")
            self.assertEqual(beta["memory_id"], "MEM-0001")
            # Same ID, different projects: reads must not guess which one is meant.
            self.assertEqual(engine.get("MEM-0001", ALPHA)["project_id"], ALPHA)
            self.assertEqual(engine.get("MEM-0001", BETA)["project_id"], BETA)

    def test_revised_record_is_persisted_not_just_returned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _master(tmp)
            engine = MemoryEngine(root=root)

            memory_id = _add(engine, topic_key="persisted")["memory_id"]
            _add(engine, topic_key="persisted", content={"summary": "on disk"}, tags=["t"])

            # A second engine, reading the files, must see the same thing.
            reopened = MemoryEngine(root=root).get(memory_id, ALPHA)
            self.assertEqual(reopened["content"], {"summary": "on disk"})
            self.assertEqual(reopened["tags"], ["t"])
            self.assertEqual(reopened["revision_count"], 1)

    def test_deprecated_records_do_not_capture_the_topic_key(self):
        """A soft-deleted memory must not absorb new saves of its topic."""
        with tempfile.TemporaryDirectory() as tmp:
            engine = MemoryEngine(root=_master(tmp))

            old = _add(engine, topic_key="retired")["memory_id"]
            engine.update(old, ALPHA, {"state": "deprecated"})

            new = _add(engine, topic_key="retired")

            self.assertEqual(new["status"], "created")
            self.assertNotEqual(new["memory_id"], old)
            self.assertEqual(len(_records(engine)), 1)

    def test_plain_add_never_merges_identical_content(self):
        """Regression: dedupe must not hijack the plain create contract."""
        with tempfile.TemporaryDirectory() as tmp:
            engine = MemoryEngine(root=_master(tmp))

            first = _add(engine)
            second = _add(engine)

            self.assertEqual(first["status"], "created")
            self.assertEqual(second["status"], "created")
            self.assertNotEqual(first["memory_id"], second["memory_id"])
            self.assertEqual(len(_records(engine)), 2)


class ExactDedupeTests(unittest.TestCase):
    def test_dedupe_counts_repeats_instead_of_copying(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = MemoryEngine(root=_master(tmp))

            first = _add(engine, dedupe=True)
            second = _add(engine, dedupe=True)

            self.assertEqual(second["status"], "deduplicated")
            self.assertEqual(first["memory_id"], second["memory_id"])
            self.assertEqual(second["duplicate_count"], 1)

            record = engine.get(first["memory_id"], ALPHA)
            self.assertEqual(record["duplicate_count"], 1)
            self.assertIsNotNone(record["last_seen_at"])
            self.assertEqual(len(engine.query(project_id=ALPHA)["memories"]), 1)

    def test_dedupe_requires_the_same_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = MemoryEngine(root=_master(tmp))

            first = _add(engine, dedupe=True)
            other = _add(engine, dedupe=True, type="discovery")

            self.assertEqual(other["status"], "created")
            self.assertNotEqual(first["memory_id"], other["memory_id"])

    def test_dedupe_requires_the_same_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = MemoryEngine(root=_master(tmp))

            alpha = _add(engine, dedupe=True)
            beta = _add(engine, dedupe=True, project_id=BETA)

            self.assertEqual(beta["status"], "created")
            self.assertEqual(engine.get(alpha["memory_id"], ALPHA)["duplicate_count"], 0)
            self.assertEqual(engine.get(beta["memory_id"], BETA)["duplicate_count"], 0)
            self.assertEqual(len(_records(engine, ALPHA)), 1)
            self.assertEqual(len(_records(engine, BETA)), 1)

    def test_dedupe_ignores_deprecated_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = MemoryEngine(root=_master(tmp))

            first = _add(engine, dedupe=True)
            engine.update(first["memory_id"], ALPHA, {"state": "deprecated"})

            again = _add(engine, dedupe=True)

            self.assertEqual(again["status"], "created")
            self.assertNotEqual(again["memory_id"], first["memory_id"])

    def test_dedupe_does_not_confuse_different_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = MemoryEngine(root=_master(tmp))

            first = _add(engine, dedupe=True, content={"summary": "one"})
            second = _add(engine, dedupe=True, content={"summary": "two"})

            self.assertEqual(second["status"], "created")
            self.assertNotEqual(first["memory_id"], second["memory_id"])


class GovernanceFieldTests(unittest.TestCase):
    def test_state_and_review_after_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = MemoryEngine(root=_master(tmp))
            review = now_utc()

            memory_id = _add(engine, state="needs_review", review_after=review)["memory_id"]
            record = engine.get(memory_id, ALPHA)

            self.assertEqual(record["state"], "needs_review")
            self.assertEqual(record["review_after"], review)

    def test_new_fields_have_safe_defaults_for_legacy_files(self):
        """A record written before Phase 4 must still load."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _master(tmp)
            legacy = {
                "schema_version": "1",
                "memory_id": "MEM-0001",
                "project_id": ALPHA,
                "type": "decision",
                "scope": "project",
                "content": {"summary": "written before the new fields"},
                "tags": [],
                "confidence": 1.0,
                "created_at": now_utc(),
                "updated_at": now_utc(),
                "author": "tester",
                "source": "manual",
                "related_memories": [],
                "supersedes": None,
                "superseded_by": None,
                "metadata": {},
            }
            support.write_json(
                root / "PROJECTS" / "Alpha" / "memories" / "MEM-0001.json", legacy
            )

            engine = MemoryEngine(root=root)
            record = engine.get("MEM-0001", ALPHA)

            self.assertEqual(record["state"], "active")
            self.assertEqual(record["revision_count"], 0)
            self.assertEqual(record["duplicate_count"], 0)
            self.assertIsNone(record["topic_key"])
            self.assertIsNone(record["last_seen_at"])
            self.assertIsNone(record["review_after"])

    def test_legacy_record_is_readable_through_query_and_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _master(tmp)
            engine = MemoryEngine(root=root)
            memory_id = _add(engine, content={"summary": "legacy vocabulary"})["memory_id"]

            # Strip the Phase 4 fields from the file to emulate an older record.
            path = root / "PROJECTS" / "Alpha" / "memories" / f"{memory_id}.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            for field in (
                "topic_key",
                "revision_count",
                "duplicate_count",
                "last_seen_at",
                "review_after",
                "state",
            ):
                data.pop(field, None)
            support.write_json(path, data)

            self.assertEqual(len(engine.query(project_id=ALPHA)["memories"]), 1)
            self.assertEqual(len(engine.search("vocabulary")["hits"]), 1)

    def test_update_can_change_state_and_review_after(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = MemoryEngine(root=_master(tmp))
            memory_id = _add(engine)["memory_id"]
            review = now_utc()

            engine.update(memory_id, ALPHA, {"state": "archived", "review_after": review})
            record = engine.get(memory_id, ALPHA)

            self.assertEqual(record["state"], "archived")
            self.assertEqual(record["review_after"], review)

    def test_schema_accepts_the_new_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = MemoryEngine(root=_master(tmp))
            memory_id = _add(
                engine,
                topic_key="schema-check",
                revision_count=2,
                duplicate_count=1,
                last_seen_at=now_utc(),
                review_after=now_utc(),
                state="needs_review",
            )["memory_id"]
            # The write validates against the schema, so a successful record is
            # the assertion; re-validating makes the intent explicit.
            record = engine.get(memory_id, ALPHA)
            self.assertEqual(record["topic_key"], "schema-check")

    def test_schema_rejects_an_unknown_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = MemoryEngine(root=_master(tmp))
            with self.assertRaises(ValueError):
                _add(engine, state="sideways")


class SoftDeleteTests(unittest.TestCase):
    def test_query_hides_deprecated_records_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = MemoryEngine(root=_master(tmp))
            kept = _add(engine, content={"summary": "kept"})["memory_id"]
            gone = _add(engine, content={"summary": "gone"})["memory_id"]
            engine.update(gone, ALPHA, {"state": "deprecated"})

            ids = [m["memory_id"] for m in engine.query(project_id=ALPHA)["memories"]]

            self.assertEqual(ids, [kept])

    def test_query_can_ask_for_deprecated_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = MemoryEngine(root=_master(tmp))
            _add(engine, content={"summary": "kept"})
            gone = _add(engine, content={"summary": "gone"})["memory_id"]
            engine.update(gone, ALPHA, {"state": "deprecated"})

            ids = [
                m["memory_id"]
                for m in engine.query(project_id=ALPHA, state="deprecated")["memories"]
            ]

            self.assertEqual(ids, [gone])

    def test_soft_delete_keeps_the_file(self):
        """Deprecated means hidden, not destroyed."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _master(tmp)
            engine = MemoryEngine(root=root)
            memory_id = _add(engine)["memory_id"]
            engine.update(memory_id, ALPHA, {"state": "deprecated"})

            self.assertTrue(
                (root / "PROJECTS" / "Alpha" / "memories" / f"{memory_id}.json").exists()
            )

    def test_search_hides_deprecated_records_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = MemoryEngine(root=_master(tmp))
            gone = _add(engine, content={"summary": "vanishing keyword"})["memory_id"]
            engine.update(gone, ALPHA, {"state": "deprecated"})

            self.assertEqual(engine.search("vanishing")["hits"], [])
            self.assertEqual(len(engine.search("vanishing", include_deprecated=True)["hits"]), 1)

    def test_scan_fallback_also_hides_deprecated_records(self):
        """Both backends must honour the same lifecycle rules."""
        with tempfile.TemporaryDirectory() as tmp:
            engine = MemoryEngine(root=_master(tmp))
            gone = _add(engine, content={"summary": "vanishing keyword"})["memory_id"]
            engine.update(gone, ALPHA, {"state": "deprecated"})

            with mock.patch.object(index_module, "fts5_available", return_value=False):
                hidden = engine.search("vanishing")
                shown = engine.search("vanishing", include_deprecated=True)

            self.assertEqual(hidden["backend"], "scan")
            self.assertEqual(hidden["hits"], [])
            self.assertEqual(len(shown["hits"]), 1)

    def test_indexed_hits_carry_the_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = MemoryEngine(root=_master(tmp))
            _add(engine, content={"summary": "archived keyword"}, state="archived")

            hit = engine.search("archived")["hits"][0]

            self.assertEqual(hit["state"], "archived")


class IndexVersionTests(unittest.TestCase):
    def test_a_stale_index_format_is_reindexed_not_mixed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _master(tmp)
            engine = MemoryEngine(root=root)
            _add(engine, content={"summary": "versioned keyword"})
            engine.refresh_index(rebuild=True)

            index = MemoryIndex(root)
            conn = sqlite3.connect(index.path)
            try:
                conn.execute("UPDATE meta SET value='0' WHERE key='schema_version'")
                conn.commit()
            finally:
                conn.close()

            # The search repairs the file and still answers correctly.
            hits = engine.search("versioned")["hits"]

            self.assertEqual(len(hits), 1)
            self.assertEqual(engine.index_stats()["schema_version"], INDEX_SCHEMA_VERSION)
            self.assertEqual(engine.index_stats()["entries"], 1)

    def test_index_statistics_report_the_current_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = MemoryEngine(root=_master(tmp))
            _add(engine, content={"summary": "x"})

            engine.refresh_index(rebuild=True)

            self.assertEqual(
                engine.index_stats()["schema_version"], INDEX_SCHEMA_VERSION
            )


class CliParseTests(unittest.TestCase):
    """New flags fail closed at parse time, before any record is touched."""

    def test_add_rejects_an_unknown_state(self):
        code, _out = support.run_cli(
            "memory", "add",
            "--project", "PROJECTS/none",
            "--type", "decision",
            "--content", "{}",
            "--state", "sideways",
        )
        self.assertEqual(code, 2)

    def test_query_rejects_an_unknown_state(self):
        code, _out = support.run_cli("memory", "query", "--state", "sideways")
        self.assertEqual(code, 2)

    def test_add_accepts_the_new_flags(self):
        """A parse-level check: the flags exist and are wired to the handler."""
        code, out = support.run_cli(
            "memory", "add",
            "--project", "PROJECTS/none",
            "--type", "decision",
            "--content", "{}",
            "--topic-key", "k",
            "--state", "needs_review",
            "--dedupe",
        )
        # The project does not exist, so the command fails on its own terms and
        # not with a usage error: that is what proves the flags parsed.
        self.assertEqual(code, 1, out)
        self.assertIn("no PROJECT.json", out)


if __name__ == "__main__":
    unittest.main()
