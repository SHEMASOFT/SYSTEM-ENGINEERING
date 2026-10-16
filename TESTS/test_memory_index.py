"""Memory index and lexical search tests (ADR-0027 Phase 2).

Hermetic: temporary directories only, no network, no external memory service.

The index is a cache with a contract, and these tests hold it to that contract:

  - The canonical JSON records stay the source of truth: the index can be
    deleted, corrupted or absent and search still answers.
  - ``refresh`` is cheap: unchanged files are never read again, because the
    inventory is built from ``stat`` metadata alone.
  - Search is incremental, filterable and scoped, returns compact hits
    (progressive disclosure) and agrees with the pure-Python fallback.
  - Without FTS5 the engine degrades to a scan instead of failing.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.memory import index as index_module  # noqa: E402
from se_core.memory.engine import MemoryEngine  # noqa: E402
from se_core.memory.index import (  # noqa: E402
    INDEX_RELATIVE_PATH,
    INDEX_SCHEMA_VERSION,
    MemoryIndex,
)

ALPHA = "PRJ-TEST-001"
BETA = "PRJ-TEST-002"


def _master(tmp):
    """A throwaway master root with two managed projects (distinct ids)."""
    root = Path(tmp) / "master"
    alpha = support.make_project(root / "PROJECTS" / "Alpha")
    beta = support.make_project(root / "PROJECTS" / "Beta")
    support.write_json(
        beta / "PROJECT.json",
        support.manifest(project_id=BETA, name="Beta Project"),
    )
    return root, alpha, beta


def _add(engine, project_id, summary, tags=None, type_="decision"):
    return engine.add(
        project_id=project_id,
        type=type_,
        content={"summary": summary},
        author="tester",
        tags=tags or [],
    )["memory_id"]


def _seed(engine):
    """Three records whose terms cannot be confused with one another."""
    _add(engine, ALPHA, "Adopt the derived SQLite FTS5 index for lexical retrieval", ["memory", "index"])
    _add(engine, ALPHA, "Canonical JSON records remain the source of truth", ["memory"])
    _add(engine, BETA, "Deployment uses a rolling restart strategy", ["deploy"])


def _index_path(root):
    return Path(root) / INDEX_RELATIVE_PATH


class IndexBuildTests(unittest.TestCase):
    def test_index_lives_in_the_derived_state_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _alpha, _beta = _master(tmp)
            index = MemoryIndex(root)
            self.assertEqual(index.path, _index_path(root))
            self.assertEqual(INDEX_RELATIVE_PATH.as_posix(), ".se/memory/index.db")

    def test_rebuild_indexes_every_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _alpha, _beta = _master(tmp)
            engine = MemoryEngine(root=root)
            _seed(engine)

            report = engine.refresh_index(rebuild=True)

            self.assertEqual(report["status"], "rebuilt")
            self.assertEqual(report["inserted"], 3)
            self.assertEqual(report["total"], 3)
            stats = engine.index_stats()
            self.assertTrue(stats["available"])
            self.assertEqual(stats["by_project"], {ALPHA: 2, BETA: 1})
            self.assertEqual(stats["schema_version"], INDEX_SCHEMA_VERSION)
            self.assertTrue(stats["built_at"])

    def test_refresh_is_incremental_and_reads_only_changed_files(self):
        """The core performance claim: unchanged files are never parsed again."""
        with tempfile.TemporaryDirectory() as tmp:
            root, _alpha, _beta = _master(tmp)
            engine = MemoryEngine(root=root)
            _seed(engine)

            index = MemoryIndex(root)
            revisions, paths = engine._index_scope()
            base = engine._entry_loader(revisions, paths)
            loads = []

            def counting_load(project_id, memory_id):
                loads.append((project_id, memory_id))
                return base(project_id, memory_id)

            index.sync(revisions, counting_load)
            self.assertEqual(len(loads), 3)

            # Nothing changed on disk: a second sync must parse nothing at all.
            index.sync(revisions, counting_load)
            self.assertEqual(len(loads), 3)

            engine.update("MEM-0002", ALPHA, {"content": {"summary": "Extra words appended to force a real change"}})
            revisions, paths = engine._index_scope()
            base = engine._entry_loader(revisions, paths)
            report = index.sync(revisions, counting_load)

            self.assertEqual(len(loads), 4)
            self.assertEqual(report["updated"], 1)
            self.assertEqual(report["inserted"], 0)
            self.assertEqual(report["deleted"], 0)

    def test_refresh_drops_records_whose_file_disappeared(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, alpha, _beta = _master(tmp)
            engine = MemoryEngine(root=root)
            _seed(engine)
            engine.refresh_index(rebuild=True)

            (alpha / "memories" / "MEM-0002.json").unlink()
            report = engine.refresh_index()

            self.assertEqual(report["deleted"], 1)
            self.assertEqual(report["total"], 2)
            self.assertEqual(engine.search("canonical")["hits"], [])

    def test_refresh_with_empty_inventory_empties_the_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _alpha, _beta = _master(tmp)
            engine = MemoryEngine(root=root)
            _seed(engine)

            index = MemoryIndex(root)
            revisions, paths = engine._index_scope()
            index.sync(revisions, engine._entry_loader(revisions, paths))
            report = index.sync({}, engine._entry_loader({}, {}))

            self.assertEqual(report["deleted"], 3)
            self.assertEqual(report["total"], 0)

    def test_unreadable_record_is_skipped_not_indexed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, alpha, _beta = _master(tmp)
            engine = MemoryEngine(root=root)
            _seed(engine)

            (alpha / "memories" / "MEM-9999.json").write_text("not json", encoding="utf-8")
            report = engine.refresh_index(rebuild=True)

            self.assertEqual(report["total"], 3)
            self.assertEqual(len(engine.search("fts5")["hits"]), 1)

    def test_drop_removes_the_index_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _alpha, _beta = _master(tmp)
            engine = MemoryEngine(root=root)
            _seed(engine)
            engine.refresh_index(rebuild=True)

            index = MemoryIndex(root)
            self.assertTrue(index.path.exists())
            self.assertTrue(index.drop())
            self.assertFalse(index.path.exists())
            self.assertFalse(index.drop())
            self.assertFalse(index.exists)

    def test_missing_index_is_built_on_first_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _alpha, _beta = _master(tmp)
            engine = MemoryEngine(root=root)
            _seed(engine)
            self.assertFalse(_index_path(root).exists())

            result = engine.search("fts5")

            self.assertEqual(result["backend"], "fts5")
            self.assertEqual(len(result["hits"]), 1)
            self.assertTrue(_index_path(root).exists())


class SearchTests(unittest.TestCase):
    def test_search_returns_compact_hits_best_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _alpha, _beta = _master(tmp)
            engine = MemoryEngine(root=root)
            _seed(engine)

            result = engine.search("fts5")

            self.assertEqual(result["schema_version"], "1")
            self.assertTrue(result["query_id"].startswith("MQS-"))
            self.assertEqual(result["backend"], "fts5")
            self.assertEqual(result["summary"], {"returned": 1, "by_type": {"decision": 1}})
            hit = result["hits"][0]
            self.assertEqual((hit["memory_id"], hit["project_id"], hit["type"]), ("MEM-0001", ALPHA, "decision"))
            self.assertIn("[fts5]", hit["snippet"].lower())
            # Progressive disclosure: a hit carries no record body.
            self.assertNotIn("content", hit)

    def test_search_is_scoped_by_project_and_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _alpha, _beta = _master(tmp)
            engine = MemoryEngine(root=root)
            _seed(engine)

            self.assertEqual(len(engine.search("memory")["hits"]), 2)
            self.assertEqual(len(engine.search("memory", project_id=ALPHA)["hits"]), 2)
            self.assertEqual(engine.search("memory", project_id=BETA)["hits"], [])
            self.assertEqual(len(engine.search("memory", types=["discovery"])["hits"]), 0)
            self.assertEqual(len(engine.search("memory", types=["decision"])["hits"]), 2)

    def test_search_requires_every_term(self):
        """AND semantics: a term nobody wrote suppresses the match."""
        with tempfile.TemporaryDirectory() as tmp:
            root, _alpha, _beta = _master(tmp)
            engine = MemoryEngine(root=root)
            _seed(engine)

            self.assertEqual(len(engine.search("fts5")["hits"]), 1)
            self.assertEqual(engine.search("fts5 canonical")["hits"], [])

    def test_search_is_cross_project_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _alpha, _beta = _master(tmp)
            engine = MemoryEngine(root=root)
            _seed(engine)

            hits = engine.search("rolling")["hits"]

            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0]["project_id"], BETA)

    def test_search_paginates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _alpha, _beta = _master(tmp)
            engine = MemoryEngine(root=root)
            _seed(engine)

            first = engine.search("memory", limit=1, offset=0)["hits"]
            second = engine.search("memory", limit=1, offset=1)["hits"]

            self.assertEqual(len(first), 1)
            self.assertEqual(len(second), 1)
            self.assertNotEqual(first[0]["memory_id"], second[0]["memory_id"])

    def test_search_rejects_a_query_without_terms(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _alpha, _beta = _master(tmp)
            engine = MemoryEngine(root=root)
            _seed(engine)

            for empty in ("", "   ", "!!!"):
                with self.assertRaises(ValueError):
                    engine.search(empty)

    def test_hit_can_be_resolved_to_the_full_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _alpha, _beta = _master(tmp)
            engine = MemoryEngine(root=root)
            _seed(engine)

            hit = engine.search("rolling")["hits"][0]
            record = engine.get(hit["memory_id"], hit["project_id"])

            self.assertIsNotNone(record)
            self.assertIn("rolling", record["content"]["summary"])

    def test_search_result_ignores_a_term_inside_a_metadata_key(self):
        """Only content and tags are searchable, not field names."""
        with tempfile.TemporaryDirectory() as tmp:
            root, _alpha, _beta = _master(tmp)
            engine = MemoryEngine(root=root)
            _seed(engine)

            # "summary" is a structural key, present in every record but written
            # by none of them as content.
            self.assertEqual(engine.search("summary")["hits"], [])

    def test_tags_are_searchable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _alpha, _beta = _master(tmp)
            engine = MemoryEngine(root=root)
            _seed(engine)

            hits = engine.search("deploy")["hits"]

            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0]["project_id"], BETA)


class RebuildDeterminismTests(unittest.TestCase):
    def test_rebuild_is_reproducible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _alpha, _beta = _master(tmp)
            engine = MemoryEngine(root=root)
            _seed(engine)

            engine.refresh_index(rebuild=True)
            first_stats = engine.index_stats()
            first_hits = [h["memory_id"] for h in engine.search("memory")["hits"]]

            engine.refresh_index(rebuild=True)
            second_stats = engine.index_stats()
            second_hits = [h["memory_id"] for h in engine.search("memory")["hits"]]

            self.assertEqual(first_stats["entries"], second_stats["entries"])
            self.assertEqual(first_stats["by_project"], second_stats["by_project"])
            self.assertEqual(first_hits, second_hits)

    def test_index_matches_the_canonical_records(self):
        """No record is lost and none is invented: the index is a mirror."""
        with tempfile.TemporaryDirectory() as tmp:
            root, _alpha, _beta = _master(tmp)
            engine = MemoryEngine(root=root)
            _seed(engine)

            engine.refresh_index(rebuild=True)

            on_disk = {
                (record.project_id, record.memory_id)
                for _dir, record in engine._iter_records()
            }
            stats = engine.index_stats()
            self.assertEqual(stats["entries"], len(on_disk))
            self.assertEqual(sum(stats["by_project"].values()), len(on_disk))

            # Every canonical record is reachable through its own content. IDs are
            # not searchable text: they are resolved with ``get``, not guessed at.
            for term in ("fts5", "canonical", "rolling"):
                hits = engine.search(term)["hits"]
                self.assertEqual(len(hits), 1, term)
                self.assertIn((hits[0]["project_id"], hits[0]["memory_id"]), on_disk)


class DegradationTests(unittest.TestCase):
    def test_without_fts5_search_falls_back_to_a_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _alpha, _beta = _master(tmp)
            engine = MemoryEngine(root=root)
            _seed(engine)

            with mock.patch.object(index_module, "fts5_available", return_value=False):
                result = engine.search("rolling")
                stats = engine.index_stats()
                refresh = engine.refresh_index(rebuild=True)

            self.assertEqual(result["backend"], "scan")
            self.assertFalse(result["index"]["available"])
            self.assertEqual(len(result["hits"]), 1)
            self.assertEqual(result["hits"][0]["project_id"], BETA)
            self.assertIn("[rolling]", result["hits"][0]["snippet"].lower())
            self.assertFalse(stats["available"])
            self.assertEqual(refresh["status"], "unavailable")
            # Degrading must not leave a half-built file behind.
            self.assertFalse(_index_path(root).exists())

    def test_both_backends_answer_the_same_question_the_same_way(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _alpha, _beta = _master(tmp)
            engine = MemoryEngine(root=root)
            _seed(engine)

            indexed = engine.search("canonical")["hits"]

            with mock.patch.object(index_module, "fts5_available", return_value=False):
                scanned = engine.search("canonical")["hits"]

            # Scores are backend-relative, but the answer must not be.
            self.assertEqual(
                [hit["memory_id"] for hit in indexed],
                [hit["memory_id"] for hit in scanned],
            )
            for hit in indexed + scanned:
                self.assertIn("[canonical]", hit["snippet"].lower())

    def test_corrupt_index_self_heals_and_keeps_answering(self):
        """A cache is never data: a damaged file must cost one rebuild, at most."""
        with tempfile.TemporaryDirectory() as tmp:
            root, _alpha, _beta = _master(tmp)
            engine = MemoryEngine(root=root)
            _seed(engine)
            engine.refresh_index(rebuild=True)

            index = MemoryIndex(root)
            index.drop()
            index.path.write_bytes(b"this is not a sqlite database")

            result = engine.search("fts5")

            self.assertEqual(result["backend"], "fts5")
            self.assertEqual(len(result["hits"]), 1)
            self.assertEqual(engine.index_stats()["entries"], 3)

    def test_fallback_requires_no_index_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _alpha, _beta = _master(tmp)
            engine = MemoryEngine(root=root)
            _seed(engine)

            with mock.patch.object(index_module, "fts5_available", return_value=False):
                self.assertEqual(engine.search("fts5")["backend"], "scan")
            self.assertFalse(_index_path(root).exists())


class CliGuardTests(unittest.TestCase):
    """The CLI fails closed on an unusable search request (no index work done)."""

    def test_search_without_terms_fails(self):
        code, out = support.run_cli("memory", "search", "--query", "   ")
        self.assertEqual(code, 1, out)
        self.assertIn("--query is required", out)

    def test_search_requires_the_query_flag(self):
        code, _out = support.run_cli("memory", "search")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
