"""T20: global lexical search over projects, memory and records."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
CONSOLE_ROOT = os.path.dirname(HERE)
sys.path.insert(0, CONSOLE_ROOT)

from console import api, project_memory, read_cache, read_model, se_cli, se_reader  # noqa: E402

PROJECT = "PROJECTS/demo"


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.patcher = mock.patch.object(read_cache, "get", side_effect=lambda k, p: p())
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_short_query_is_refused(self):
        status, body = api.api_search({"q": "a"})
        self.assertEqual(status, 400)
        self.assertIn("2 and 200", body["message"])

    def test_search_matches_all_three_sources(self):
        projects = {"projects": [{"rel_path": PROJECT, "dir_name": "demo", "management": "MANAGED"}]}
        memory = {
            "notes": [{"id": "n1", "text": "needle in a memory note"}],
            "next_steps": [{"id": "s1", "text": "unrelated step"}],
        }
        records = {
            "records": [
                {"id": "R-1", "data": {"title": "needle in a canonical record"}},
                {"id": "R-2", "data": {"title": "nothing here"}},
            ]
        }
        def records_for(project_path, rtype):
            return records if rtype == "TASK" else {"records": []}

        with (
            mock.patch.object(read_model, "build_project_list", return_value=projects),
            mock.patch.object(project_memory, "load_memory", return_value=memory),
            mock.patch.object(se_reader, "load_records", side_effect=records_for),
        ):
            status, body = api.api_search({"q": "needle"})

        self.assertEqual(status, 200)
        self.assertEqual({r["kind"] for r in body["results"]}, {"memory", "record"})
        self.assertEqual(body["count"], 2)
        self.assertFalse(body["truncated"])
        self.assertIn("needle", body["results"][0]["snippet"])

    def test_project_name_is_searchable(self):
        projects = {"projects": [{"rel_path": PROJECT, "dir_name": "demo"}]}
        with (
            mock.patch.object(read_model, "build_project_list", return_value=projects),
            mock.patch.object(project_memory, "load_memory", return_value={}),
            mock.patch.object(se_reader, "load_records", return_value={"records": []}),
        ):
            status, body = api.api_search({"q": "demo"})
        self.assertEqual(status, 200)
        self.assertEqual([r["kind"] for r in body["results"]][:1], ["project"])

    def test_memory_get_uses_the_canonical_root(self):
        """Regression: the memory endpoints used an undefined `_SE_ROOT`."""
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "PROJECTS", "demo"))
            envelope = {"report": "se.report/1", "status": "PASS"}
            with (
                mock.patch.object(api, "SE_ROOT", tmp),
                mock.patch.object(
                    se_cli, "run_se", return_value=(envelope, {"argv": []})
                ) as run,
            ):
                status, body = api.api_memory_get({"project": PROJECT, "memory_id": "n1"})
            self.assertEqual(status, 200)
            self.assertEqual(body["status"], "PASS")
            self.assertEqual(
                run.call_args[0][0],
                ["memory", "get", "--project", os.path.join(tmp, PROJECT), "--memory-id", "n1", "--json"],
            )


if __name__ == "__main__":
    unittest.main()
