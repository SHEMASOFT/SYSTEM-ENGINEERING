"""Memory injection through the intelligence layer (ADR-0027 phase 6).

Hermetic: a temporary engine root, a temporary project, a copy of the real
schemas so the emitted envelope is validated against the contract that ships.
No network, no model download, no writes to the repository.

What these tests pin down:

  - a run with no topics behaves exactly as it always did: the context still
    reports totals, types and the most recent memories, and relevance is empty
    rather than absent;
  - a stated topic selects the memories that match it, with the snippet that
    makes the injection useful and without leaking whole records;
  - topics are searched independently and merged in the order they were given,
    deduplicated, and capped so the injected context stays bounded;
  - an unmatched topic is not a failure, and a topic nothing can be matched from
    is dropped instead of refusing to start a session;
  - the run is read-only with respect to project state -- the point of injecting
    through the existing pipeline is that memory arrives without a write;
  - the emitted envelope validates against the real ``intelligence_result``
    schema, so the new block is part of the contract rather than beside it;
  - the backend and the reranker that answered are reported, because an empty
    hit list must not be confused with no search engine at all.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.intelligence.engine import IntelligenceEngine, _one_or_mixed  # noqa: E402
from se_core.memory import embeddings  # noqa: E402
from se_core.memory import index as index_module  # noqa: E402
from se_core.memory.embeddings import MODEL_ENV_VAR  # noqa: E402
from se_core.memory.engine import MemoryEngine  # noqa: E402
from se_core.schemas import validate  # noqa: E402

PROJECT_ID = "PRJ-TEST-001"

# The same synthetic 2-D space the phase 5 tests use: `core` lies along the
# direction of the query `auth deploy`, so a topic can be shown to rerank.
VECTORS = """# synthetic space for tests (never a real model)
4 2
auth 1.0 0.0
deploy 0.0 1.0
core 0.70710678 0.70710678
near_deploy 0.2 0.98
"""


def snapshot(root: Path) -> dict:
    """Every file under ``root`` with its size, mtime and content hash."""
    state = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        stat = path.stat()
        state[str(path.relative_to(root))] = (
            stat.st_size,
            stat.st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
    return state


class IntelligenceMemoryTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "master"
        # The engine validates its envelope against the schemas of its own root,
        # so a throwaway root needs a real copy to be validated the same way.
        shutil.copytree(support.REPO_ROOT / "SCHEMAS", self.root / "SCHEMAS")
        self.project_dir = support.make_project(self.root / "PROJECTS" / "Alpha", state="ACTIVE")
        self.memory = MemoryEngine(root=self.root)
        self.intelligence = IntelligenceEngine(root=self.root)

        embeddings._SPACE_CACHE.clear()
        self.addCleanup(embeddings._SPACE_CACHE.clear)

        # No test here should depend on whether the developer happens to have a
        # model installed or SE_MEMORY_EMBEDDINGS set.
        env = mock.patch.dict(os.environ)
        env.start()
        os.environ.pop(MODEL_ENV_VAR, None)
        self.addCleanup(env.stop)

    # -- helpers ---------------------------------------------------------

    def add(self, type_: str, title: str, summary: str) -> str:
        return self.memory.add(
            PROJECT_ID, type_, {"title": title, "summary": summary}, "tester"
        )["memory_id"]

    def install_model(self) -> Path:
        path = self.root / embeddings.MODEL_RELATIVE_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(VECTORS, encoding="utf-8")
        return path

    def run_intelligence(self, **over):
        kwargs = {"project_id": PROJECT_ID}
        kwargs.update(over)
        return self.intelligence.run(**kwargs)

    def relevance(self, **over):
        return self.run_intelligence(**over)["memory_context"]["relevance"]

    def assert_valid(self, result):
        errors = validate(result, support.schemas().get("intelligence_result", {}))
        self.assertEqual(errors, [])


class ContextShapeTests(IntelligenceMemoryTestCase):
    def test_a_run_without_topics_reports_empty_relevance(self):
        self.add("decision", "Indice", "decision sobre el indice lexico")
        relevance = self.relevance()

        self.assertEqual(relevance["queries"], [])
        self.assertEqual(relevance["hits"], [])
        self.assertIsNone(relevance["backend"])
        self.assertIsNone(relevance["reranker"])

    def test_the_legacy_context_is_unchanged(self):
        first = self.add("decision", "Indice", "decision sobre el indice lexico")
        second = self.add("discovery", "Gates", "hallazgo sobre gates")

        context = self.run_intelligence()["memory_context"]

        self.assertEqual(context["total"], 2)
        self.assertEqual(context["by_type"], {"decision": 1, "discovery": 1})
        self.assertEqual(
            sorted(entry["memory_id"] for entry in context["recent"]),
            sorted([first, second]),
        )
        self.assertEqual(
            sorted(entry["title"] for entry in context["recent"]),
            ["Gates", "Indice"],
        )

    def test_no_memories_yields_an_empty_but_valid_context(self):
        result = self.run_intelligence(memory_topics=["indice"])

        context = result["memory_context"]
        self.assertEqual(context["total"], 0)
        self.assertEqual(context["recent"], [])
        self.assertEqual(context["relevance"]["hits"], [])
        self.assert_valid(result)

    def test_the_result_validates_against_the_shipped_schema(self):
        self.add("decision", "Indice", "decision sobre el indice lexico")
        self.assert_valid(self.run_intelligence(memory_topics=["indice"]))

    def test_the_context_can_be_built_without_the_full_pipeline(self):
        """The session-start convention calls this directly."""
        memory_id = self.add("decision", "Indice", "decision sobre el indice lexico")

        context = self.intelligence.memory_context(PROJECT_ID, topics=["indice"])

        self.assertEqual(context["total"], 1)
        self.assertEqual(
            [hit["memory_id"] for hit in context["relevance"]["hits"]], [memory_id]
        )


class RelevanceTests(IntelligenceMemoryTestCase):
    def test_a_topic_selects_the_matching_memory(self):
        matching = self.add("decision", "Indice FTS5", "decision sobre el indice lexico")
        self.add("discovery", "Gates", "hallazgo sobre gates y transiciones")

        relevance = self.relevance(memory_topics=["indice lexico"])

        self.assertEqual(relevance["queries"], ["indice lexico"])
        self.assertEqual([hit["memory_id"] for hit in relevance["hits"]], [matching])

    def test_a_hit_carries_a_snippet_and_no_whole_record(self):
        self.add("decision", "Indice FTS5", "decision sobre el indice lexico y su vigencia")

        hit = self.relevance(memory_topics=["indice"])["hits"][0]

        self.assertEqual(
            sorted(hit.keys()), ["memory_id", "score", "snippet", "type"]
        )
        self.assertIn("indice", hit["snippet"].lower())

    def test_topics_are_searched_independently_and_merged_in_order(self):
        first = self.add("decision", "Indice", "decision sobre el indice lexico")
        second = self.add("discovery", "Gates", "hallazgo sobre gates")

        relevance = self.relevance(memory_topics=["indice", "gates"])

        self.assertEqual(relevance["queries"], ["indice", "gates"])
        self.assertEqual(
            [hit["memory_id"] for hit in relevance["hits"]], [first, second]
        )

    def test_a_memory_matching_two_topics_is_injected_once(self):
        shared = self.add("decision", "Indice", "decision sobre el indice y sobre gates")

        relevance = self.relevance(memory_topics=["indice", "gates"])

        self.assertEqual([hit["memory_id"] for hit in relevance["hits"]], [shared])

    def test_the_merged_list_is_capped(self):
        self.add("decision", "Indice", "decision sobre el indice lexico")
        self.add("discovery", "Gates", "hallazgo sobre gates")

        relevance = self.relevance(memory_topics=["indice", "gates"], memory_limit=1)

        self.assertEqual(len(relevance["hits"]), 1)

    def test_an_unmatched_topic_is_not_a_failure(self):
        self.add("decision", "Indice", "decision sobre el indice lexico")

        relevance = self.relevance(memory_topics=["zzzznothing"])

        self.assertEqual(relevance["queries"], ["zzzznothing"])
        self.assertEqual(relevance["hits"], [])
        # It was searched: the engine that answered is still reported.
        self.assertIsNotNone(relevance["backend"])

    def test_a_topic_nothing_can_be_matched_from_is_dropped(self):
        self.add("decision", "Indice", "decision sobre el indice lexico")

        relevance = self.relevance(memory_topics=["!!!", "indice"])

        self.assertEqual(relevance["queries"], ["indice"])
        self.assertEqual(len(relevance["hits"]), 1)

    def test_blank_topics_are_ignored(self):
        self.add("decision", "Indice", "decision sobre el indice lexico")

        relevance = self.relevance(memory_topics=["", "   ", "indice"])

        self.assertEqual(relevance["queries"], ["indice"])

    def test_the_backend_that_answered_is_reported(self):
        self.add("decision", "Indice", "decision sobre el indice lexico")

        self.assertEqual(self.relevance(memory_topics=["indice"])["backend"], "fts5")

        with mock.patch.object(index_module, "fts5_available", return_value=False):
            self.assertEqual(
                self.relevance(memory_topics=["indice"])["backend"], "scan"
            )

    def test_the_reranker_is_reported_when_a_model_is_installed(self):
        self.add("decision", "Auth", "auth deploy core")

        without = self.relevance(memory_topics=["auth deploy"])
        self.assertIsNone(without["reranker"])

        self.install_model()
        with_model = self.relevance(memory_topics=["auth deploy"])

        expected = "numpy" if embeddings.numpy_module() is not None else "python"
        self.assertEqual(with_model["reranker"], expected)
        self.assertEqual(len(with_model["hits"]), 1)

    def test_deprecated_memories_are_not_injected(self):
        kept = self.add("decision", "Indice", "decision sobre el indice lexico")
        gone = self.add("decision", "Indice viejo", "decision sobre el indice lexico")
        self.memory.update(gone, PROJECT_ID, {"state": "deprecated"})

        relevance = self.relevance(memory_topics=["indice"])

        self.assertEqual([hit["memory_id"] for hit in relevance["hits"]], [kept])


class ReadOnlyTests(IntelligenceMemoryTestCase):
    def test_the_run_writes_nothing_under_the_project(self):
        self.add("decision", "Indice", "decision sobre el indice lexico")
        self.add("discovery", "Gates", "hallazgo sobre gates")
        before = snapshot(self.project_dir)

        self.run_intelligence(memory_topics=["indice", "gates"], memory_limit=5)

        self.assertEqual(snapshot(self.project_dir), before)

    def test_the_run_writes_nothing_even_with_a_reranker(self):
        self.add("decision", "Auth", "auth deploy core")
        self.install_model()
        before = snapshot(self.project_dir)

        self.run_intelligence(memory_topics=["auth deploy"])

        self.assertEqual(snapshot(self.project_dir), before)


class OneOrMixedTests(unittest.TestCase):
    """The reporting helper, pinned directly: disagreement must not look like agreement."""

    def test_nothing_is_reported_as_nothing(self):
        self.assertIsNone(_one_or_mixed([]))
        self.assertIsNone(_one_or_mixed(["", ""]))

    def test_one_value_is_reported_as_itself(self):
        self.assertEqual(_one_or_mixed(["fts5"]), "fts5")
        self.assertEqual(_one_or_mixed(["fts5", "fts5"]), "fts5")

    def test_disagreement_is_reported_as_mixed(self):
        self.assertEqual(_one_or_mixed(["fts5", "scan"]), "mixed")


class IntelligenceCliTests(unittest.TestCase):
    """CLI surface, without touching the repository's own state."""

    def test_the_memory_flags_parse_before_the_project_is_resolved(self):
        code, out = support.run_cli(
            "intelligence",
            "--project",
            "PROJECTS/none",
            "--memory",
            "indice",
            "--memory",
            "gates",
            "--memory-limit",
            "5",
        )
        self.assertEqual(code, 1, out)
        self.assertIn("no PROJECT.json", out)

    def test_the_memory_limit_must_be_a_number(self):
        code, out = support.run_cli(
            "intelligence", "--project", "PROJECTS/none", "--memory-limit", "many"
        )
        self.assertEqual(code, 2, out)

    def test_the_memory_flag_is_optional(self):
        code, out = support.run_cli("intelligence", "--project", "PROJECTS/none")
        self.assertEqual(code, 1, out)
        self.assertIn("no PROJECT.json", out)


if __name__ == "__main__":
    unittest.main()
