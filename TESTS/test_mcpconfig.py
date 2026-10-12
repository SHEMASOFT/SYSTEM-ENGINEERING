"""Tests for ``se_core/mcpconfig.py`` (jsonc reading + surgical removal)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core import mcpconfig  # noqa: E402


class ConfigPathTests(unittest.TestCase):
    def test_prefers_existing_jsonc(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "opencode.json").write_text("{}", encoding="utf-8")
            (root / "opencode.jsonc").write_text("{}", encoding="utf-8")
            self.assertEqual(mcpconfig.config_path(root), root / "opencode.jsonc")

    def test_falls_back_to_json_when_no_jsonc(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "opencode.json").write_text("{}", encoding="utf-8")
            self.assertEqual(mcpconfig.config_path(root), root / "opencode.json")

    def test_default_name_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(mcpconfig.config_path(root), root / "opencode.jsonc")


class ParseJsoncTests(unittest.TestCase):
    def test_strips_line_and_block_comments(self):
        text = '{\n // line\n "a": 1, /* block */ "b": 2,\n}'
        self.assertEqual(mcpconfig.parse_jsonc(text), {"a": 1, "b": 2})

    def test_tolerates_trailing_commas(self):
        self.assertEqual(mcpconfig.parse_jsonc('{"a": 1,}'), {"a": 1})

    def test_tolerates_bom(self):
        self.assertEqual(mcpconfig.parse_jsonc('\ufeff{"a": 1}'), {"a": 1})

    def test_string_containing_comments_is_preserved(self):
        text = '{"url": "https://x//y", "note": "a // not a comment"}'
        self.assertEqual(mcpconfig.parse_jsonc(text), {"url": "https://x//y", "note": "a // not a comment"})

    def test_invalid_json_raises(self):
        with self.assertRaises(ValueError):
            mcpconfig.parse_jsonc("{ not json")

    def test_non_object_root_raises(self):
        with self.assertRaises(ValueError):
            mcpconfig.parse_jsonc("[1, 2]")

    def test_read_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "opencode.jsonc"
            path.write_text('{"mcp": {}} // comment', encoding="utf-8")
            self.assertEqual(mcpconfig.read_config(path), {"mcp": {}})


class ListServersTests(unittest.TestCase):
    def test_lists_v2_and_legacy_with_scopes(self):
        cfg = {
            "mcp": {"servers": {"b2": {"type": "local"}, "a2": {"type": "local"}}},
            "mcpServers": {"leg": {"command": ["x"]}},
        }
        view = mcpconfig.list_servers(cfg)
        self.assertEqual(
            [(item["name"], item["scope"]) for item in view],
            [("leg", "legacy"), ("a2", "v2"), ("b2", "v2")],
        )

    def test_server_names_unified(self):
        cfg = {
            "mcp": {"servers": {"shared": {}, "only-v2": {}}},
            "mcpServers": {"shared": {"command": ["x"]}, "only-legacy": {"command": ["y"]}},
        }
        self.assertEqual(
            mcpconfig.server_names(cfg), {"shared", "only-v2", "only-legacy"}
        )

    def test_empty_config(self):
        self.assertEqual(mcpconfig.list_servers({}), [])
        self.assertEqual(mcpconfig.server_names({}), set())


class RemoveServerTextTests(unittest.TestCase):
    SETUP = '{\n  // header comment\n  "mcp": {\n    "servers": {\n      "keep": {"type": "local", "command": ["x"]},\n      "gone": {"type": "local", "command": ["y"]},\n    },\n  },\n  "mcpServers": {},\n}'

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.path = self.root / "opencode.jsonc"

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, text):
        self.path.write_text(text, encoding="utf-8")

    def test_removes_v2_entry_and_preserves_other_bytes(self):
        self._write(self.SETUP)
        result = mcpconfig.remove_server_text(self.path, "gone", target=self.root)
        self.assertEqual(result["removed"], ["v2"])
        self.assertTrue(result["changed"])
        self.assertEqual(result["errors"], [])
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("// header comment", text)
        self.assertIn('"keep"', text)
        self.assertNotIn('"gone"', text)

    def test_backup_written_into_se_backups(self):
        self._write(self.SETUP)
        result = mcpconfig.remove_server_text(self.path, "gone", target=self.root)
        self.assertTrue(result["backup"])
        backup = Path(result["backup"])
        self.assertEqual(backup.parent, self.root / ".se" / "backups")
        self.assertTrue(backup.exists())
        self.assertEqual(backup.read_text(encoding="utf-8"), self.SETUP)

    def test_removes_legacy_entry(self):
        text = '{"mcpServers": {"gone": {"command": ["legacy"]}, "keep": {"command": ["x"]}}}'
        self._write(text)
        result = mcpconfig.remove_server_text(self.path, "gone", target=self.root)
        self.assertEqual(result["removed"], ["legacy"])
        parsed = mcpconfig.read_config(self.path)
        self.assertNotIn("gone", parsed["mcpServers"])
        self.assertIn("keep", parsed["mcpServers"])

    def test_removes_from_both_scopes(self):
        text = (
            '{"mcp": {"servers": {"gone": {"type": "local"}}},'
            ' "mcpServers": {"gone": {"command": ["x"]}, "keep": {"command": ["k"]}}}'
        )
        self._write(text)
        result = mcpconfig.remove_server_text(self.path, "gone", target=self.root)
        self.assertEqual(sorted(result["removed"]), ["legacy", "v2"])
        parsed = mcpconfig.read_config(self.path)
        self.assertNotIn("gone", parsed["mcp"]["servers"])
        self.assertNotIn("gone", parsed["mcpServers"])
        self.assertIn("keep", parsed["mcpServers"])

    def test_absent_server_is_noop_without_errors(self):
        self._write(self.SETUP)
        result = mcpconfig.remove_server_text(self.path, "nope", target=self.root)
        self.assertFalse(result["changed"])
        self.assertEqual(result["removed"], [])
        self.assertEqual(result["errors"], [])

    def test_missing_file_reports_error(self):
        result = mcpconfig.remove_server_text(self.root / "missing.jsonc", "x", target=self.root)
        self.assertEqual(result["errors"], [f"config file not found: {self.root / 'missing.jsonc'}"])

    def test_unparseable_file_is_never_rewritten(self):
        self._write("{ this is not json")
        result = mcpconfig.remove_server_text(self.path, "x", target=self.root)
        self.assertTrue(result["errors"])
        self.assertFalse(result["changed"])
        self.assertEqual(self.path.read_text(encoding="utf-8"), "{ this is not json")

    def test_non_object_server_fails_closed(self):
        self._write('{"mcp": {"servers": {"bad": "just-a-string"}}}')
        result = mcpconfig.remove_server_text(self.path, "bad", target=self.root)
        self.assertTrue(result["errors"])
        self.assertFalse(result["changed"])
        self.assertIn("not an object literal", result["errors"][0])

    def test_other_servers_untouched_after_removal(self):
        text = (
            '{"mcp": {"servers": {"gone": {"type": "local", "command": ["y"]},'
            ' "keep": {"type": "local", "command": ["x", "--flag"], "environment": {"K": "V"}}}}}'
        )
        self._write(text)
        mcpconfig.remove_server_text(self.path, "gone", target=self.root)
        parsed = mcpconfig.read_config(self.path)
        self.assertEqual(
            parsed["mcp"]["servers"]["keep"],
            {"type": "local", "command": ["x", "--flag"], "environment": {"K": "V"}},
        )


class AddServerTextTests(unittest.TestCase):
    SETUP = (
        "{\n"
        '  "mcp": {\n'
        '    "servers": {\n'
        '      "keep": {\n'
        '        "type": "local",\n'
        '        "command": ["x"]\n'
        "      }\n"
        "    }\n"
        "  },\n"
        "  // trailing comment\n"
        "}\n"
    )

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.path = self.root / "opencode.jsonc"

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, text):
        self.path.write_text(text, encoding="utf-8")

    def test_updating_existing_server_keeps_indentation(self):
        # Regression: the update path used to splice the json.dumps output with
        # no re-indentation, deforming the config on every `se install`.
        self._write(self.SETUP)
        result = mcpconfig.add_server_text(
            self.path, "keep", {"type": "local", "command": ["y", "--flag"]}, target=self.root
        )
        self.assertEqual(result["errors"], [])
        self.assertTrue(result["updated"])
        self.assertEqual(
            self.path.read_text(encoding="utf-8"),
            "{\n"
            '  "mcp": {\n'
            '    "servers": {\n'
            '      "keep": {\n'
            '        "type": "local",\n'
            '        "command": [\n'
            '          "y",\n'
            '          "--flag"\n'
            "        ]\n"
            "      }\n"
            "    }\n"
            "  },\n"
            "  // trailing comment\n"
            "}\n",
        )

    def test_adds_new_server_with_matching_indentation(self):
        self._write(self.SETUP)
        result = mcpconfig.add_server_text(
            self.path, "added", {"type": "local", "command": ["z"]}, target=self.root
        )
        self.assertEqual(result["errors"], [])
        self.assertTrue(result["added"])
        self.assertEqual(
            self.path.read_text(encoding="utf-8"),
            "{\n"
            '  "mcp": {\n'
            '    "servers": {\n'
            '      "keep": {\n'
            '        "type": "local",\n'
            '        "command": ["x"]\n'
            "      },\n"
            '      "added": {\n'
            '        "type": "local",\n'
            '        "command": [\n'
            '          "z"\n'
            "        ]\n"
            "      }\n"
            "    }\n"
            "  },\n"
            "  // trailing comment\n"
            "}\n",
        )

    def test_creates_minimal_config_when_absent(self):
        result = mcpconfig.add_server_text(self.path, "srv", {"type": "local"}, target=self.root)
        self.assertEqual(result["errors"], [])
        self.assertTrue(result["added"])
        self.assertEqual(mcpconfig.read_config(self.path)["mcp"]["servers"]["srv"], {"type": "local"})

    def test_unparseable_file_fails_closed(self):
        self._write("{ this is not json")
        result = mcpconfig.add_server_text(self.path, "srv", {"type": "local"}, target=self.root)
        self.assertTrue(result["errors"])
        self.assertFalse(result["changed"])
        self.assertEqual(self.path.read_text(encoding="utf-8"), "{ this is not json")

    def test_other_servers_untouched(self):
        self._write(self.SETUP)
        mcpconfig.add_server_text(
            self.path, "added", {"type": "local", "command": ["z"]}, target=self.root
        )
        parsed = mcpconfig.read_config(self.path)
        self.assertEqual(parsed["mcp"]["servers"]["keep"], {"type": "local", "command": ["x"]})


class BackupConfigTests(unittest.TestCase):
    def test_backup_config_with_deterministic_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "opencode.jsonc"
            path.write_text('{"a": 1}', encoding="utf-8")
            backup = mcpconfig.backup_config(path, target=root, label="engram", timestamp="20261009T120000Z")
            self.assertEqual(backup.name, "engram-20261009T120000Z.jsonc")
            self.assertTrue(backup.exists())
            self.assertEqual(backup.read_text(encoding="utf-8"), '{"a": 1}')


if __name__ == "__main__":
    unittest.main()