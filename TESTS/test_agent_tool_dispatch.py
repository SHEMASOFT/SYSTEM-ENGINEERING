"""Tool dispatch and path-sandbox tests for the internal AgentRunner.

The internal route (``se subagent`` / ``se orchestrate execute`` without
``--native``) used to return a placeholder error for every tool call, so an
agent could neither read nor write anything. These tests pin the replacement
contract:

* agents that declare no ``tools`` receive ``read``/``list``/``search`` and,
  only when permitted, ``write``;
* every tool returns ``COMPLETED`` with data or ``ERROR`` with an actionable
  message, never a fabricated success;
* reads are confined to the project dir and the engine root, writes to the
  project dir, with ``..`` traversal and absolute escapes rejected.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.agents.runner import AgentRunner  # noqa: E402


REPO_ROOT = Path(support.REPO_ROOT)


class AgentToolDispatchTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "project"
        self.project.mkdir()
        # A directory that is guaranteed to be outside both the project and
        # the engine root. It is only used to assert escapes are rejected.
        self._outside_tmp = tempfile.TemporaryDirectory()
        self.outside = Path(self._outside_tmp.name)

    def tearDown(self):
        self._tmp.cleanup()
        self._outside_tmp.cleanup()

    def _runner(self, agent: str = "implementer") -> AgentRunner:
        return AgentRunner(
            agent_name=agent,
            project_dir=self.project,
            root=REPO_ROOT,
        )

    @staticmethod
    def _tool_names(runner: AgentRunner):
        return [tool["function"]["name"] for tool in runner.tools]

    # 1. Baseline toolset for an agent that declares no `tools`.
    def test_default_tools_include_write_for_implementer(self):
        runner = self._runner("implementer")
        names = self._tool_names(runner)
        for expected in ("read", "list", "search", "write"):
            self.assertIn(expected, names)

    # 2. Agents without IMPLEMENT/WRITE_DOCS do not get `write`.
    #
    # The task named `reviewer`, but AGENTS/reviewer/agent.json currently
    # grants WRITE_DOCS (verified by reading the file), so per the mandated
    # rule it does get `write`. `explorer` is the real agent that lacks both
    # IMPLEMENT and WRITE_DOCS.
    def test_no_write_tool_without_write_permission(self):
        runner = self._runner("explorer")
        names = self._tool_names(runner)
        self.assertIn("read", names)
        self.assertIn("list", names)
        self.assertIn("search", names)
        self.assertNotIn("write", names)

        path = self.project / "should-not-exist.txt"
        result = runner._invoke_tool(
            "write", {"path": str(path), "content": "nope"}, {}
        )
        self.assertEqual(result["status"], "ERROR")
        self.assertIn("IMPLEMENT", result["error"])
        self.assertIn("WRITE_DOCS", result["error"])
        self.assertFalse(path.exists())

    # 3. read of a file inside the project succeeds.
    def test_read_inside_project(self):
        target = self.project / "notes.txt"
        target.write_text("hello sandbox\n", encoding="utf-8")

        result = self._runner()._invoke_tool(
            "read", {"path": "notes.txt"}, {}
        )

        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["output"], "hello sandbox\n")
        self.assertEqual(Path(result["path"]), target.resolve())

    # 4. read of an absolute path outside project and engine root is rejected.
    def test_read_outside_project_and_root_is_rejected(self):
        target = self.outside / "secret.txt"
        target.write_text("outside\n", encoding="utf-8")

        result = self._runner()._invoke_tool(
            "read", {"path": str(target)}, {}
        )

        self.assertEqual(result["status"], "ERROR")
        self.assertIn(str(target), result["error"])
        self.assertIn("escape", result["error"].lower())

    # 5. `..` traversal is rejected.
    def test_read_traversal_is_rejected(self):
        target = self.project.parent / "traversal.txt"
        target.write_text("nope\n", encoding="utf-8")

        result = self._runner()._invoke_tool(
            "read", {"path": "../../traversal.txt"}, {}
        )

        self.assertEqual(result["status"], "ERROR")
        self.assertIn("escape", result["error"].lower())

    # 6. write inside the project works; write outside is rejected untouched.
    def test_write_inside_project(self):
        result = self._runner()._invoke_tool(
            "write",
            {"path": "nested/out.txt", "content": "written\n"},
            {},
        )

        self.assertEqual(result["status"], "COMPLETED")
        target = self.project / "nested" / "out.txt"
        self.assertTrue(target.is_file())
        self.assertEqual(target.read_text(encoding="utf-8"), "written\n")
        self.assertEqual(result["bytes"], len("written\n".encode("utf-8")))
        self.assertEqual(Path(result["path"]), target.resolve())

    def test_write_outside_project_is_rejected(self):
        target = self.outside / "evil.txt"

        result = self._runner()._invoke_tool(
            "write", {"path": str(target), "content": "evil"}, {}
        )

        self.assertEqual(result["status"], "ERROR")
        self.assertIn(str(target), result["error"])
        self.assertFalse(target.exists())

    # 7. list returns sorted name/type entries and rejects a file.
    def test_list_directory_is_sorted(self):
        (self.project / "b.txt").write_text("b", encoding="utf-8")
        (self.project / "a_dir").mkdir()
        (self.project / "c.py").write_text("c", encoding="utf-8")

        result = self._runner()._invoke_tool(
            "list", {"path": str(self.project)}, {}
        )

        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(
            result["output"],
            [
                {"name": "a_dir", "type": "dir"},
                {"name": "b.txt", "type": "file"},
                {"name": "c.py", "type": "file"},
            ],
        )

    def test_list_on_file_returns_error(self):
        target = self.project / "file.txt"
        target.write_text("x", encoding="utf-8")

        result = self._runner()._invoke_tool(
            "list", {"path": str(target)}, {}
        )

        self.assertEqual(result["status"], "ERROR")
        self.assertIn("not a directory", result["error"].lower())

    # 8. search reports the 1-based line number and rejects invalid regexes.
    def test_search_reports_line_number(self):
        seeded = self.project / "pkg" / "data.txt"
        seeded.parent.mkdir()
        seeded.write_text("first line\nsecond NEEDLE\nthird\n", encoding="utf-8")

        result = self._runner()._invoke_tool(
            "search",
            {"pattern": "NEEDLE", "path": str(self.project), "include": "*.txt"},
            {},
        )

        self.assertEqual(result["status"], "COMPLETED")
        self.assertFalse(result["truncated"])
        self.assertEqual(len(result["output"]), 1)
        match = result["output"][0]
        self.assertEqual(match["line"], 2)
        self.assertEqual(match["text"], "second NEEDLE")
        self.assertEqual(match["path"], "pkg/data.txt")

    def test_search_invalid_regex_returns_error(self):
        result = self._runner()._invoke_tool(
            "search", {"pattern": "([unclosed"}, {}
        )

        self.assertEqual(result["status"], "ERROR")
        self.assertIn("Invalid regex", result["error"])

    # 9. bash is a loud error and executes nothing.
    def test_bash_is_not_available(self):
        marker = self.project / "bash-ran.txt"

        result = self._runner()._invoke_tool(
            "bash", {"command": f"echo hi > {marker}"}, {}
        )

        self.assertEqual(result["status"], "ERROR")
        self.assertNotEqual(result.get("status"), "COMPLETED")
        self.assertIn("not available", result["error"])
        self.assertFalse(marker.exists())

    # 10. _execute_tool_calls aggregates COMPLETED and FAILED correctly.
    def test_execute_tool_calls_completed(self):
        target = self.project / "input.txt"
        target.write_text("payload\n", encoding="utf-8")
        tool_calls = [
            {
                "id": "1",
                "function": {
                    "name": "read",
                    "arguments": json.dumps({"path": str(target)}),
                },
            }
        ]

        result = self._runner()._execute_tool_calls(tool_calls, {})

        self.assertEqual(result["status"], "COMPLETED")
        self.assertTrue(result["tool_results"])
        self.assertEqual(result["tool_results"][0]["name"], "read")

    def test_execute_tool_calls_failed(self):
        outside = self.outside / "nope.txt"
        outside.write_text("outside\n", encoding="utf-8")
        tool_calls = [
            {
                "id": "1",
                "function": {
                    "name": "read",
                    "arguments": json.dumps({"path": str(outside)}),
                },
            }
        ]

        result = self._runner()._execute_tool_calls(tool_calls, {})

        self.assertEqual(result["status"], "FAILED")
        self.assertIn("Tool execution failed", result["error"])


if __name__ == "__main__":
    unittest.main()
