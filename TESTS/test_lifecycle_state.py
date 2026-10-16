"""Tests for ``se_core/lifecycle_state.py`` (``.se/lifecycle-state.json`` v1)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core import lifecycle_state as lc  # noqa: E402


class StatePathTests(unittest.TestCase):
    def test_path_helpers(self):
        target = Path("t")
        self.assertEqual(lc.state_dir(target), target / ".se")
        self.assertEqual(lc.backup_dir(target), target / ".se" / "backups")
        self.assertEqual(lc.state_path(target), target / ".se" / "lifecycle-state.json")

    def test_backup_dir_under_state_dir(self):
        self.assertEqual(lc.backup_dir("t"), lc.state_dir("t") / "backups")


class NewStateTests(unittest.TestCase):
    def test_new_state_shape(self):
        state = lc.new_state(se_version="0.1.0", os_name="windows", target="/tmp/x", scope="project")
        self.assertEqual(state["schema_version"], "1")
        self.assertEqual(state["se_version"], "0.1.0")
        self.assertEqual(state["os"], "windows")
        self.assertEqual(state["target"], "/tmp/x")
        self.assertEqual(state["scope"], "project")
        self.assertEqual(state["runtime"], "opencode")
        self.assertEqual(state["servers"], {})
        self.assertIsNone(state["adapter"])
        self.assertEqual(state["uninstalled"], [])


class RoundTripTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.target = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_save_and_load_roundtrip(self):
        state = lc.new_state(se_version="0.1.0", os_name="linux", target=str(self.target))
        lc.record_server(state, "context7", declared="abc123", source="TEMPLATES/mcp/context7.json.tmpl")
        lc.save_state(state, self.target)
        self.assertTrue(lc.state_path(self.target).exists())
        loaded = lc.load_state(self.target)
        self.assertEqual(loaded["se_version"], "0.1.0")
        self.assertIn("context7", loaded["servers"])
        self.assertEqual(loaded["servers"]["context7"]["declared"], "abc123")

    def test_load_state_missing_is_none(self):
        self.assertIsNone(lc.load_state(self.target))

    def test_load_state_corrupt_is_none(self):
        path = lc.state_path(self.target)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ not json", encoding="utf-8")
        self.assertIsNone(lc.load_state(self.target))

    def test_load_state_wrong_schema_is_none(self):
        path = lc.state_path(self.target)
        path.parent.mkdir(parents=True, exist_ok=True)
        support.write_json(path, {"schema_version": "999", "servers": {}})
        self.assertIsNone(lc.load_state(self.target))

    def test_load_state_missing_servers_map_is_none(self):
        path = lc.state_path(self.target)
        path.parent.mkdir(parents=True, exist_ok=True)
        support.write_json(path, {"schema_version": "1"})
        self.assertIsNone(lc.load_state(self.target))

    def test_save_is_atomic_json(self):
        state = lc.new_state(se_version="0.1.0", os_name="windows", target=str(self.target))
        lc.save_state(state, self.target)
        data = json.loads(lc.state_path(self.target).read_text(encoding="utf-8"))
        self.assertEqual(data["schema_version"], "1")


class ServerAuditTests(unittest.TestCase):
    def setUp(self):
        self.state = lc.new_state(se_version="0.1.0", os_name="windows", target="/tmp/x")

    def test_record_server_adds_entry(self):
        lc.record_server(
            self.state, "context7", declared="h1", source="TEMPLATES/mcp/context7.json.tmpl",
            registered_at="2026-10-09T00:00:00Z",
        )
        entry = self.state["servers"]["context7"]
        self.assertEqual(entry["declared"], "h1")
        self.assertEqual(entry["source"], "TEMPLATES/mcp/context7.json.tmpl")
        self.assertEqual(entry["scope"], "project")
        self.assertEqual(entry["registered_at"], "2026-10-09T00:00:00Z")

    def test_record_server_refreshes_existing(self):
        lc.record_server(self.state, "context7", declared="h1", source="s1")
        lc.record_server(self.state, "context7", declared="h2", source="s2")
        self.assertEqual(self.state["servers"]["context7"]["declared"], "h2")

    def test_remove_server_moves_to_audit(self):
        lc.record_server(self.state, "context7", declared="h1", source="s1")
        entry = lc.remove_server(self.state, "context7", removed_at="2026-10-09T00:00:00Z")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["name"], "context7")
        self.assertEqual(entry["removed_at"], "2026-10-09T00:00:00Z")
        self.assertEqual(entry["declared"], "h1")
        self.assertNotIn("context7", self.state["servers"])
        self.assertEqual(self.state["uninstalled"], [entry])

    def test_remove_server_unknown_returns_none(self):
        self.assertIsNone(lc.remove_server(self.state, "missing"))

    def test_audit_trail_preserved_after_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            state = lc.new_state(se_version="0.1.0", os_name="windows", target=str(target))
            lc.record_server(state, "context7", declared="h1", source="s1")
            lc.remove_server(state, "context7")
            lc.save_state(state, target)
            loaded = lc.load_state(target)
            self.assertEqual(len(loaded["uninstalled"]), 1)
            self.assertEqual(loaded["uninstalled"][0]["name"], "context7")


class SpecHashTests(unittest.TestCase):
    def test_canonical_regardless_of_key_order(self):
        a = {"name": "context7", "command": ["context7", "mcp"], "environment": {"K": "V"}}
        b = {"environment": {"K": "V"}, "command": ["context7", "mcp"], "name": "context7"}
        self.assertEqual(lc.spec_hash(a), lc.spec_hash(b))

    def test_different_spec_different_hash(self):
        a = {"name": "context7", "command": ["context7", "mcp"], "environment": {}}
        b = {"name": "context7", "command": ["context7", "mcp", "extra"], "environment": {}}
        self.assertNotEqual(lc.spec_hash(a), lc.spec_hash(b))

    def test_hash_is_sha256_hex(self):
        self.assertEqual(len(lc.spec_hash({"name": "x"})), 64)


class ReadSeVersionTests(unittest.TestCase):
    def test_reads_version_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "VERSION").write_text("0.42.0\n", encoding="utf-8")
            self.assertEqual(lc.read_se_version(root), "0.42.0")


if __name__ == "__main__":
    unittest.main()