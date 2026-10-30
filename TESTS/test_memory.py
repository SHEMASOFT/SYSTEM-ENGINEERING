"""Memory engine tests (ADR-0027 Phase 1: persist link/update/supersede).

Hermetic: temporary directories only, no network, no external memory service.

Covers the contract the internal memory engine must honour now that the local
JSON record is the single source of truth:
  - ``add`` validates and persists atomically (LF, schema-checked).
  - ``update`` persists changes, bumps ``updated_at``, preserves identity fields,
    and rejects unknown/immutable fields without touching the file.
  - ``link`` writes symmetric relations on both records, is idempotent and
    ordered, and rejects self-links, unknown verbs and dangling targets.
  - ``supersede`` writes both inverse fields consistently and refuses cycles.
  - ``get``/``query`` read through the canonical record files.
  - The CLI guards fail closed instead of raising.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.memory.engine import MemoryEngine  # noqa: E402
from se_core.paths import now_utc  # noqa: E402


def _master(tmp):
    """Build a throwaway master root with one (or two) managed projects."""
    root = Path(tmp) / "master"
    project = root / "PROJECTS" / "TestApp"
    support.make_project(project)
    return root, project


def _record_file(project, memory_id):
    return project / "memories" / f"{memory_id}.json"


def _read(project, memory_id):
    return json.loads(_record_file(project, memory_id).read_text(encoding="utf-8"))


def _add(engine, **over):
    data = {
        "project_id": "PRJ-TEST-001",
        "type": "decision",
        "content": {"summary": "Use JSON records as the source of truth."},
        "author": "tester",
    }
    data.update(over)
    return engine.add(**data)


class MemoryAddTests(unittest.TestCase):
    def test_add_creates_a_valid_record_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, project = _master(tmp)
            engine = MemoryEngine(root=root)

            result = _add(engine)

            self.assertEqual(result["status"], "created")
            path = _record_file(project, result["memory_id"])
            self.assertTrue(path.exists())
            record = _read(project, result["memory_id"])
            self.assertEqual(record["memory_id"], "MEM-0001")
            self.assertEqual(record["project_id"], "PRJ-TEST-001")
            self.assertEqual(record["author"], "tester")
            self.assertEqual(record["schema_version"], "1")

    def test_add_assigns_sequential_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = _master(tmp)
            engine = MemoryEngine(root=root)

            first = _add(engine)["memory_id"]
            second = _add(engine)["memory_id"]

            self.assertEqual((first, second), ("MEM-0001", "MEM-0002"))

    def test_add_writes_lf_newlines(self):
        """Regression: the old writer used text mode and produced CRLF on Windows."""
        with tempfile.TemporaryDirectory() as tmp:
            root, project = _master(tmp)
            engine = MemoryEngine(root=root)

            memory_id = _add(engine)["memory_id"]

            raw = _record_file(project, memory_id).read_bytes()
            self.assertNotIn(b"\r\n", raw)
            self.assertTrue(raw.endswith(b"\n"))

    def test_add_rejects_unknown_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = _master(tmp)
            engine = MemoryEngine(root=root)
            with self.assertRaises(ValueError):
                _add(engine, project_id="PRJ-DOES-NOT-EXIST")

    def test_add_rejects_type_outside_schema_enum(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, project = _master(tmp)
            engine = MemoryEngine(root=root)
            with self.assertRaises(ValueError):
                _add(engine, type="nonsense")
            self.assertFalse((project / "memories").exists())

    def test_add_validates_against_the_real_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, project = _master(tmp)
            engine = MemoryEngine(root=root)
            memory_id = _add(engine)["memory_id"]
            record = _read(project, memory_id)
            from se_core.schemas import validate

            self.assertEqual(validate(record, support.schemas()["memory_record"]), [])


class MemoryUpdateTests(unittest.TestCase):
    def test_update_persists_content_and_bumps_updated_at(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, project = _master(tmp)
            engine = MemoryEngine(root=root)
            memory_id = _add(engine)["memory_id"]
            created_at = _read(project, memory_id)["created_at"]

            before = now_utc()
            result = engine.update(
                memory_id,
                "PRJ-TEST-001",
                {"content": {"summary": "updated"}, "tags": ["memory"], "confidence": 0.7},
            )
            after = now_utc()

            self.assertEqual(result["status"], "updated")
            record = _read(project, memory_id)
            self.assertEqual(record["content"], {"summary": "updated"})
            self.assertEqual(record["tags"], ["memory"])
            self.assertEqual(record["confidence"], 0.7)
            self.assertEqual(record["created_at"], created_at)
            self.assertIn(record["updated_at"], (before, after))

    def test_update_rejects_immutable_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, project = _master(tmp)
            engine = MemoryEngine(root=root)
            memory_id = _add(engine)["memory_id"]
            before = _record_file(project, memory_id).read_bytes()

            with self.assertRaises(ValueError):
                engine.update(memory_id, "PRJ-TEST-001", {"memory_id": "MEM-9999"})

            self.assertEqual(_record_file(project, memory_id).read_bytes(), before)

    def test_update_rejects_unknown_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = _master(tmp)
            engine = MemoryEngine(root=root)
            memory_id = _add(engine)["memory_id"]
            with self.assertRaises(ValueError):
                engine.update(memory_id, "PRJ-TEST-001", {"not_a_field": 1})

    def test_update_missing_memory_fails_without_creating_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, project = _master(tmp)
            engine = MemoryEngine(root=root)
            with self.assertRaises(ValueError):
                engine.update("MEM-0404", "PRJ-TEST-001", {"confidence": 0.5})
            self.assertFalse(_record_file(project, "MEM-0404").exists())


class MemoryLinkTests(unittest.TestCase):
    def _two(self, engine):
        return _add(engine)["memory_id"], _add(engine)["memory_id"]

    def test_link_is_symmetric_and_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, project = _master(tmp)
            engine = MemoryEngine(root=root)
            a, b = self._two(engine)

            result = engine.link(a, b, "related", "PRJ-TEST-001")

            self.assertEqual(result["status"], "linked")
            self.assertEqual(_read(project, a)["related_memories"], [b])
            self.assertEqual(_read(project, b)["related_memories"], [a])

    def test_link_is_idempotent_and_ordered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, project = _master(tmp)
            engine = MemoryEngine(root=root)
            a, b = self._two(engine)

            engine.link(a, b, "compatible", "PRJ-TEST-001")
            engine.link(a, b, "compatible", "PRJ-TEST-001")

            self.assertEqual(_read(project, a)["related_memories"], [b])

    def test_link_requires_a_project_scope(self):
        """Memory IDs are project-scoped: a write without a scope is refused."""
        with tempfile.TemporaryDirectory() as tmp:
            root, project = _master(tmp)
            engine = MemoryEngine(root=root)
            a, b = self._two(engine)
            before = _record_file(project, a).read_bytes()

            with self.assertRaises(ValueError):
                engine.link(a, b)

            self.assertEqual(_record_file(project, a).read_bytes(), before)

    def test_link_rejects_self(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = _master(tmp)
            engine = MemoryEngine(root=root)
            a = _add(engine)["memory_id"]
            with self.assertRaises(ValueError):
                engine.link(a, a, "related", "PRJ-TEST-001")

    def test_link_rejects_unknown_relation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = _master(tmp)
            engine = MemoryEngine(root=root)
            a, b = self._two(engine)
            with self.assertRaises(ValueError):
                engine.link(a, b, "vibes_with", "PRJ-TEST-001")

    def test_link_rejects_dangling_target_without_touching_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, project = _master(tmp)
            engine = MemoryEngine(root=root)
            a = _add(engine)["memory_id"]
            before = _record_file(project, a).read_bytes()

            with self.assertRaises(ValueError):
                engine.link(a, "MEM-0404", "related", "PRJ-TEST-001")

            self.assertEqual(_record_file(project, a).read_bytes(), before)

    def test_link_supersedes_delegates_to_supersede(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, project = _master(tmp)
            engine = MemoryEngine(root=root)
            superseded = _add(engine)["memory_id"]
            replacement = _add(engine)["memory_id"]

            # "replacement supersedes superseded": the replacement is the new one.
            engine.link(replacement, superseded, "supersedes", "PRJ-TEST-001")

            self.assertEqual(_read(project, superseded)["superseded_by"], replacement)
            self.assertEqual(_read(project, replacement)["supersedes"], superseded)

    def test_link_superseded_by_delegates_to_supersede(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, project = _master(tmp)
            engine = MemoryEngine(root=root)
            superseded = _add(engine)["memory_id"]
            replacement = _add(engine)["memory_id"]

            # "superseded is superseded_by replacement": same edge, opposite view.
            engine.link(superseded, replacement, "superseded_by", "PRJ-TEST-001")

            self.assertEqual(_read(project, superseded)["superseded_by"], replacement)
            self.assertEqual(_read(project, replacement)["supersedes"], superseded)


class MemorySupersedeTests(unittest.TestCase):
    def test_supersede_writes_both_inverse_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, project = _master(tmp)
            engine = MemoryEngine(root=root)
            old = _add(engine)["memory_id"]
            new = _add(engine)["memory_id"]

            result = engine.supersede(old, new, "PRJ-TEST-001")

            self.assertEqual(result, {"status": "superseded", "old": old, "new": new})
            self.assertEqual(_read(project, old)["superseded_by"], new)
            self.assertEqual(_read(project, new)["supersedes"], old)

    def test_supersede_rejects_self(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = _master(tmp)
            engine = MemoryEngine(root=root)
            a = _add(engine)["memory_id"]
            with self.assertRaises(ValueError):
                engine.supersede(a, a)

    def test_supersede_rejects_a_replacement_that_is_already_superseded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = _master(tmp)
            engine = MemoryEngine(root=root)
            first = _add(engine)["memory_id"]
            second = _add(engine)["memory_id"]
            third = _add(engine)["memory_id"]

            engine.supersede(first, second, "PRJ-TEST-001")  # first is superseded by second

            with self.assertRaises(ValueError):
                # first is itself already superseded: it cannot become a replacement.
                engine.supersede(third, first, "PRJ-TEST-001")

    def test_supersede_rejects_changing_an_existing_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = _master(tmp)
            engine = MemoryEngine(root=root)
            first = _add(engine)["memory_id"]
            second = _add(engine)["memory_id"]
            third = _add(engine)["memory_id"]

            engine.supersede(first, second, "PRJ-TEST-001")

            with self.assertRaises(ValueError):
                engine.supersede(first, third, "PRJ-TEST-001")  # already superseded by second

    def test_supersede_missing_memory_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = _master(tmp)
            engine = MemoryEngine(root=root)
            a = _add(engine)["memory_id"]
            with self.assertRaises(ValueError):
                engine.supersede(a, "MEM-0404", "PRJ-TEST-001")


class MemoryReadTests(unittest.TestCase):
    def test_get_requires_a_project_scope(self):
        """IDs are project-scoped, so an unscoped lookup returns nothing."""
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = _master(tmp)
            engine = MemoryEngine(root=root)
            memory_id = _add(engine)["memory_id"]

            self.assertIsNone(engine.get(memory_id))
            found = engine.get(memory_id, "PRJ-TEST-001")
            self.assertIsNotNone(found)
            self.assertEqual(found["memory_id"], memory_id)

    def test_get_returns_none_for_missing_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = _master(tmp)
            engine = MemoryEngine(root=root)
            self.assertIsNone(engine.get("MEM-0404", "PRJ-TEST-001"))

    def test_query_lists_and_counts_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = _master(tmp)
            engine = MemoryEngine(root=root)
            _add(engine, type="decision")
            _add(engine, type="discovery")

            result = engine.query(project_id="PRJ-TEST-001")

            self.assertEqual(result["summary"]["total"], 2)
            self.assertEqual(result["summary"]["by_type"], {"decision": 1, "discovery": 1})

    def test_query_filters_by_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = _master(tmp)
            engine = MemoryEngine(root=root)
            _add(engine, type="decision")
            _add(engine, type="discovery")

            result = engine.query(project_id="PRJ-TEST-001", types=["discovery"])

            self.assertEqual(result["summary"]["total"], 1)
            self.assertEqual(result["memories"][0]["type"], "discovery")


class MemoryEngineIsolationTests(unittest.TestCase):
    def test_two_engines_do_not_share_a_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root_a, project_a = _master(tmp)
            engine_a = MemoryEngine(root=root_a)
            memory_id = _add(engine_a)["memory_id"]

            root_b = Path(tmp) / "other-master"
            project_b = root_b / "PROJECTS" / "TestApp"
            support.make_project(project_b)
            engine_b = MemoryEngine(root=root_b)

            self.assertIsNone(engine_b.get(memory_id, "PRJ-TEST-001"))
            self.assertIsNotNone(engine_a.get(memory_id, "PRJ-TEST-001"))
            self.assertTrue(_record_file(project_a, memory_id).exists())


class MemoryCrossProjectSafetyTests(unittest.TestCase):
    """Regression: a scoped write must never reach another project with the same IDs."""

    def test_scoped_write_does_not_reach_a_peer_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, project_a = _master(tmp)
            engine = MemoryEngine(root=root)
            a = _add(engine)["memory_id"]
            b = _add(engine)["memory_id"]

            # A second project that also owns MEM-0001/MEM-0002.
            project_b = support.make_project(root / "PROJECTS" / "OtherApp")
            support.write_json(
                project_b / "PROJECT.json",
                support.manifest(project_id="PRJ-OTHER-001", name="Other"),
            )
            _add(engine, project_id="PRJ-OTHER-001")
            _add(engine, project_id="PRJ-OTHER-001")
            peer_before = _record_file(project_b, a).read_bytes()

            engine.link(a, b, "related", "PRJ-TEST-001")

            # The peer project is byte-for-byte untouched.
            self.assertEqual(_record_file(project_b, a).read_bytes(), peer_before)
            self.assertEqual(_read(project_a, a)["related_memories"], [b])

    def test_scoped_reads_resolve_each_project_separately(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, project_a = _master(tmp)
            engine = MemoryEngine(root=root)
            _add(engine, content={"who": "project-a"})

            project_b = support.make_project(root / "PROJECTS" / "OtherApp")
            support.write_json(
                project_b / "PROJECT.json",
                support.manifest(project_id="PRJ-OTHER-001", name="Other"),
            )
            _add(engine, project_id="PRJ-OTHER-001", content={"who": "project-b"})

            self.assertEqual(engine.get("MEM-0001", "PRJ-TEST-001")["content"], {"who": "project-a"})
            self.assertEqual(engine.get("MEM-0001", "PRJ-OTHER-001")["content"], {"who": "project-b"})


class MemoryCliGuardTests(unittest.TestCase):
    """The CLI surface fails closed at parse time (argparse exit code 2)."""

    def test_link_requires_a_project_scope(self):
        code, out = support.run_cli(
            "memory", "link", "--memory-id", "MEM-0001", "--related-id", "MEM-0002"
        )
        self.assertEqual(code, 2, out)

    def test_link_rejects_unknown_relation_at_parse_time(self):
        code, out = support.run_cli(
            "memory", "link",
            "--memory-id", "MEM-0001",
            "--related-id", "MEM-0002",
            "--project", "PROJECTS/none",
            "--relation", "vibes_with",
        )
        self.assertEqual(code, 2, out)

    def test_update_rejects_invalid_json(self):
        code, out = support.run_cli(
            "memory", "update", "--memory-id", "MEM-0001",
            "--project", "PROJECTS/none", "--updates", "{not json}",
        )
        self.assertEqual(code, 1, out)
        self.assertIn("invalid --updates JSON", out)

    def test_supersede_requires_a_project_scope(self):
        code, out = support.run_cli(
            "memory", "supersede", "--memory-id", "MEM-0001", "--new-id", "MEM-0002"
        )
        self.assertEqual(code, 2, out)


class MemoryIntegrityTests(unittest.TestCase):
    """Regression tests for Stage 1: durable writes and corrupt-record visibility."""

    def test_write_json_atomic_produces_valid_complete_json(self):
        """write_json_atomic must produce a parseable, complete file (fsync safety)."""
        import tempfile
        from pathlib import Path
        from se_core.paths import write_json_atomic
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "record.json"
            data = {"memory_id": "MEM-0001", "content": {"summary": "test"}, "tags": ["a", "b"]}
            write_json_atomic(path, data)
            self.assertTrue(path.exists())
            raw = path.read_text(encoding="utf-8")
            self.assertTrue(raw.endswith("\n"), "file must end with newline")
            parsed = json.loads(raw)
            self.assertEqual(parsed["memory_id"], "MEM-0001")
            self.assertEqual(parsed["content"]["summary"], "test")
            self.assertEqual(parsed["tags"], ["a", "b"])

    def test_corrupt_record_emits_warning_and_does_not_crash(self):
        """A corrupt memory file must produce a warning on stderr, not be silently ignored."""
        import io
        import contextlib
        with tempfile.TemporaryDirectory() as tmp:
            root, project = _master(tmp)
            engine = MemoryEngine(root=root)
            _add(engine)  # creates MEM-0001

            # Corrupt the record
            corrupt = _record_file(project, "MEM-0001")
            corrupt.write_text("{not valid json", encoding="utf-8")

            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                result = engine.query(project_id="PRJ-TEST-001")

            self.assertEqual(result["summary"]["total"], 0, "corrupt record must be excluded")
            self.assertIn("WARN", buf.getvalue(), "warning must be emitted to stderr")
            self.assertIn("corrupt", buf.getvalue().lower(), "warning must mention corrupt")


class MemoryTTLGCTests(unittest.TestCase):
    """Tests for P3-B.1 TTL/GC: memory expiration and garbage collection."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root, project = _master(self._tmp.name)
        self.root = root
        self.project = project
        self.project_id = "PRJ-TEST-001"
        self.engine = MemoryEngine(root=root)

    def tearDown(self):
        self._tmp.cleanup()

    def _add_memory(self, **kwargs):
        """Helper to add a memory with default values."""
        return self.engine.add(
            project_id=self.project_id,
            type="decision",
            content=kwargs.get("content", {"data": "test"}),
            author="test",
            scope="project",
            tags=kwargs.get("tags", []),
            ttl_days=kwargs.get("ttl_days"),
            gc_protected=kwargs.get("gc_protected", False),
            state=kwargs.get("state", "archived"),  # Default to archived for GC tests
        )

    def test_ttl_days_creates_expires_at(self):
        """Memory with ttl_days gets expires_at computed."""
        result = self._add_memory(ttl_days=7)
        mem_id = result["memory_id"]

        record = self.engine.get(mem_id, self.project_id)
        self.assertIsNotNone(record)
        self.assertIsNotNone(record.get("expires_at"))

        # expires_at should be ~7 days from created_at
        from datetime import datetime
        created = datetime.fromisoformat(record["created_at"].replace('Z', '+00:00'))
        expires = datetime.fromisoformat(record["expires_at"].replace('Z', '+00:00'))
        diff = (expires - created).days
        self.assertEqual(diff, 7)

    def test_gc_protected_prevents_deletion(self):
        """Memory with gc_protected=true is skipped by GC."""
        self._add_memory(content={"data": "protected"}, gc_protected=True)
        self._add_memory(content={"data": "unprotected"}, gc_protected=False)

        # Make both eligible via older_than_days
        from datetime import datetime, timedelta
        old_date = (datetime.utcnow() - timedelta(days=10)).isoformat() + 'Z'
        
        # Manually update created_at for both to be old
        for mem_file in (self.project / "memories").glob("*.json"):
            record = json.loads(mem_file.read_text(encoding="utf-8"))
            record["created_at"] = old_date
            mem_file.write_text(json.dumps(record, indent=2), encoding="utf-8")

        # Run GC with older_than_days=5
        result = self.engine.gc(project_id=self.project_id, older_than_days=5, dry_run=False)
        
        # Only unprotected should be deleted
        self.assertEqual(result["deleted_count"], 1)
        self.assertEqual(result["skipped_protected"], 1)

    def test_gc_dry_run_reports_only(self):
        """GC with dry_run=True only reports, doesn't delete."""
        self._add_memory(content={"data": "to_delete"})

        # Make it old
        from datetime import datetime, timedelta
        old_date = (datetime.utcnow() - timedelta(days=10)).isoformat() + 'Z'
        for mem_file in (self.project / "memories").glob("*.json"):
            record = json.loads(mem_file.read_text(encoding="utf-8"))
            record["created_at"] = old_date
            mem_file.write_text(json.dumps(record, indent=2), encoding="utf-8")

        result = self.engine.gc(project_id=self.project_id, older_than_days=5, dry_run=True)
        
        self.assertEqual(result["deleted_count"], 1)
        self.assertEqual(result["dry_run"], True)
        # File should still exist
        self.assertEqual(len(list((self.project / "memories").glob("*.json"))), 1)

    def test_gc_tag_filter(self):
        """GC only considers memories matching ALL tags in tag_filter."""
        self._add_memory(content={"data": "match"}, tags=["tag1", "tag2"])
        self._add_memory(content={"data": "no_match"}, tags=["tag1"])

        # Make both old
        from datetime import datetime, timedelta
        old_date = (datetime.utcnow() - timedelta(days=10)).isoformat() + 'Z'
        for mem_file in (self.project / "memories").glob("*.json"):
            record = json.loads(mem_file.read_text(encoding="utf-8"))
            record["created_at"] = old_date
            mem_file.write_text(json.dumps(record, indent=2), encoding="utf-8")

        # GC with tag_filter=["tag2"] - only first should match
        result = self.engine.gc(project_id=self.project_id, older_than_days=5, tag_filter=["tag2"], dry_run=False)
        
        self.assertEqual(result["deleted_count"], 1)

    def test_gc_state_filter(self):
        """GC only considers memories in specified states."""
        self._add_memory(content={"data": "active"}, state="active")
        self._add_memory(content={"data": "archived"}, tags=["archived"], state="archived")

        # Make both old
        from datetime import datetime, timedelta
        old_date = (datetime.utcnow() - timedelta(days=10)).isoformat() + 'Z'
        for mem_file in (self.project / "memories").glob("*.json"):
            record = json.loads(mem_file.read_text(encoding="utf-8"))
            record["created_at"] = old_date
            # State is already set correctly via _add_memory
            mem_file.write_text(json.dumps(record, indent=2), encoding="utf-8")

        # Default state_filter is ["archived", "deprecated"]
        result = self.engine.gc(project_id=self.project_id, older_than_days=5, dry_run=False)
        
        # Only archived should be deleted
        self.assertEqual(result["deleted_count"], 1)

    def test_gc_expires_at(self):
        """GC deletes memories with expires_at in the past."""
        self._add_memory(content={"data": "expired"}, ttl_days=1)
        self._add_memory(content={"data": "valid"}, ttl_days=365)

        # Manually set expires_at to past for first memory
        from datetime import datetime, timedelta
        past = (datetime.utcnow() - timedelta(days=1)).isoformat() + 'Z'
        future = (datetime.utcnow() + timedelta(days=1)).isoformat() + 'Z'
        
        for mem_file in (self.project / "memories").glob("*.json"):
            record = json.loads(mem_file.read_text(encoding="utf-8"))
            if record["content"]["data"] == "expired":
                record["expires_at"] = past
            else:
                record["expires_at"] = future
            mem_file.write_text(json.dumps(record, indent=2), encoding="utf-8")

        result = self.engine.gc(project_id=self.project_id, dry_run=False)
        
        self.assertEqual(result["deleted_count"], 1)
        # The expired one should be deleted
        deleted_ids = result["deleted_ids"]
        remaining = self.engine.get(deleted_ids[0], self.project_id)
        self.assertIsNone(remaining)


if __name__ == "__main__":
    unittest.main()
