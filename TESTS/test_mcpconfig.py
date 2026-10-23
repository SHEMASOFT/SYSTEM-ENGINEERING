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
            backup = mcpconfig.backup_config(path, target=root, label="context7", timestamp="20261009T120000Z")
            self.assertEqual(backup.name, "context7-20261009T120000Z.jsonc")
            self.assertTrue(backup.exists())
            self.assertEqual(backup.read_text(encoding="utf-8"), '{"a": 1}')


class LineEndingPreservationTests(unittest.TestCase):
    """AC11: a rewrite must preserve the file's detected EOL style byte-for-byte.

    ``Path.read_text`` normalizes CRLF to LF; the writers used to call
    ``Path.write_text`` without ``newline``, which re-translated the WHOLE file
    to the platform default (CRLF on Windows). These assertions are on raw bytes,
    so they fail on the platform where the defect was reachable and still pin the
    contract everywhere else.
    """

    LF_SETUP = (
        "{\n"
        "  // header comment\n"
        '  "mcp": {\n'
        '    "servers": {\n'
        '      "foreign-a": {"type": "local", "command": ["x"]}\n'
        "    }\n"
        "  },\n"
        '  "theme": "dark"\n'
        "}\n"
    )

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.path = self.root / "opencode.jsonc"

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, text):
        # Binary write: never let the test host translate the seeded EOLs.
        self.path.write_bytes(text.encode("utf-8"))

    def _raw(self):
        return self.path.read_bytes()

    def _assert_lf_only(self):
        raw = self._raw()
        self.assertNotIn(b"\r", raw)
        self.assertTrue(raw.endswith(b"\n"))

    def _assert_crlf_only(self):
        raw = self._raw()
        self.assertIn(b"\r\n", raw)
        self.assertNotIn(b"\r\r", raw)
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))

    def test_detect_newline_helper(self):
        self.assertEqual(mcpconfig._detect_newline("a\r\nb\r\n"), "\r\n")
        self.assertEqual(mcpconfig._detect_newline("a\nb\n"), "\n")
        self.assertEqual(mcpconfig._detect_newline(""), "\n")

    def test_lf_file_stays_lf_after_add(self):
        self._write(self.LF_SETUP)
        result = mcpconfig.add_server_text(
            self.path, "added", {"type": "local", "command": ["z"]}, target=self.root
        )
        self.assertEqual(result["errors"], [])
        self.assertTrue(result["added"])
        self._assert_lf_only()
        parsed = mcpconfig.read_config(self.path)
        self.assertIn("added", parsed["mcp"]["servers"])
        self.assertIn("foreign-a", parsed["mcp"]["servers"])
        self.assertEqual(parsed["theme"], "dark")
        self.assertIn("// header comment", self.path.read_text(encoding="utf-8"))

    def test_crlf_file_stays_crlf_after_add(self):
        self._write(self.LF_SETUP.replace("\n", "\r\n"))
        result = mcpconfig.add_server_text(
            self.path, "added", {"type": "local", "command": ["z"]}, target=self.root
        )
        self.assertEqual(result["errors"], [])
        self._assert_crlf_only()
        parsed = mcpconfig.read_config(self.path)
        self.assertIn("added", parsed["mcp"]["servers"])
        self.assertEqual(parsed["theme"], "dark")
        self.assertIn("// header comment", self.path.read_text(encoding="utf-8"))

    def test_crlf_file_stays_crlf_when_updating_existing_server(self):
        self._write(self.LF_SETUP.replace("\n", "\r\n"))
        result = mcpconfig.add_server_text(
            self.path, "foreign-a", {"type": "local", "command": ["y"]}, target=self.root
        )
        self.assertEqual(result["errors"], [])
        self.assertTrue(result["updated"])
        self._assert_crlf_only()
        parsed = mcpconfig.read_config(self.path)
        self.assertEqual(parsed["mcp"]["servers"]["foreign-a"]["command"], ["y"])

    def test_new_file_is_lf(self):
        result = mcpconfig.add_server_text(
            self.path, "srv", {"type": "local"}, target=self.root
        )
        self.assertEqual(result["errors"], [])
        self._assert_lf_only()
        self.assertEqual(
            mcpconfig.read_config(self.path)["mcp"]["servers"]["srv"],
            {"type": "local"},
        )

    def test_remove_preserves_lf(self):
        self._write(self.LF_SETUP)
        result = mcpconfig.remove_server_text(self.path, "foreign-a", target=self.root)
        self.assertEqual(result["errors"], [])
        self.assertTrue(result["changed"])
        self._assert_lf_only()
        self.assertNotIn("foreign-a", mcpconfig.read_config(self.path)["mcp"]["servers"])

    def test_remove_preserves_crlf(self):
        self._write(self.LF_SETUP.replace("\n", "\r\n"))
        result = mcpconfig.remove_server_text(self.path, "foreign-a", target=self.root)
        self.assertEqual(result["errors"], [])
        self.assertTrue(result["changed"])
        self._assert_crlf_only()
        self.assertNotIn("foreign-a", mcpconfig.read_config(self.path)["mcp"]["servers"])

    def test_comments_and_foreign_entries_survive_a_crlf_rewrite(self):
        setup = (
            "{\r\n"
            "  // header: do not lose me\r\n"
            "  /* block: nor me */\r\n"
            '  "mcp": {\r\n'
            '    "servers": {\r\n'
            '      "foreign-a": {\r\n'
            '        "type": "local",\r\n'
            '        "command": ["/opt/foreign", "--keep"]\r\n'
            "      }\r\n"
            "    }\r\n"
            "  },\r\n"
            '  "theme": "dark"\r\n'
            "}\r\n"
        )
        self._write(setup)
        result = mcpconfig.add_server_text(
            self.path, "se-test", {"type": "local", "command": ["z"]}, target=self.root
        )
        self.assertEqual(result["errors"], [])
        self._assert_crlf_only()
        parsed = mcpconfig.read_config(self.path)
        self.assertEqual(
            parsed["mcp"]["servers"]["foreign-a"],
            {"type": "local", "command": ["/opt/foreign", "--keep"]},
        )
        self.assertEqual(parsed["theme"], "dark")
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("// header: do not lose me", text)
        self.assertIn("/* block: nor me */", text)

    def test_re_add_does_not_duplicate_the_server(self):
        self._write(self.LF_SETUP.replace("\n", "\r\n"))
        for _ in range(2):
            result = mcpconfig.add_server_text(
                self.path, "added", {"type": "local", "command": ["z"]}, target=self.root
            )
            self.assertEqual(result["errors"], [])
        self._assert_crlf_only()
        raw = self._raw()
        self.assertEqual(raw.count(b'"added"'), 1)
        parsed = mcpconfig.read_config(self.path)
        self.assertEqual(
            list(parsed["mcp"]["servers"]).count("added"), 1
        )


if __name__ == "__main__":
    unittest.main()