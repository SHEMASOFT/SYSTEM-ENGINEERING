"""Semantic reranker tests (ADR-0027 phase 5).

Hermetic: temporary directories, a synthetic vector file written by the test, no
network, no model download, no numpy requirement.

What these tests pin down:

  - a model the operator installs is used, its absence is not an error, and a
    path that is configured but broken is an error rather than a silent absence;
  - the reranker **reorders** lexical candidates and can never add or lose one:
    recall stays lexical, so semantic similarity alone cannot surface a record;
  - both lexical backends (FTS5 and the pure-Python scan) feed the reranker the
    same text and produce the same order, so the ranking does not depend on
    which cache happened to be available;
  - reranking costs no record parsing: the candidate text comes from the index
    the lexical pass already used;
  - the fusion rule is reciprocated rank, pinned here as arithmetic rather than
    only observed through an example.
"""

from __future__ import annotations

import contextlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.memory import embeddings  # noqa: E402
from se_core.memory import index as index_module  # noqa: E402
from se_core.memory.embeddings import (  # noqa: E402
    MODEL_ENV_VAR,
    EmbeddingError,
    SemanticReranker,
    VectorSpace,
    cosine,
    load_space,
    load_vectors,
    parse_vectors,
    resolve_model_path,
)
from se_core.memory.engine import MemoryEngine  # noqa: E402

ALPHA = "PRJ-TEST-001"

# A synthetic 2-D space. `core` sits on the diagonal (the direction of the
# query `auth deploy`), `nearby` sits near, but not on, it. Two dimensions
# are enough to make the intended ranking decidable by hand.
VECTORS = """# synthetic space for tests (never a real model)
4 2
auth 1.0 0.0
deploy 0.0 1.0
core 0.70710678 0.70710678
nearby 0.2 0.98
"""


@contextlib.contextmanager
def no_model_env():
    """Run with no ``SE_MEMORY_EMBEDDINGS``, whatever the developer has set."""
    with mock.patch.dict(os.environ):
        os.environ.pop(MODEL_ENV_VAR, None)
        yield


class EmbeddingTestCase(unittest.TestCase):
    def setUp(self):
        # The loaded-model cache is process-wide by design; clear it so one test
        # cannot hand another a model it did not install.
        embeddings._SPACE_CACHE.clear()
        self.addCleanup(embeddings._SPACE_CACHE.clear)

    def install_model(self, root: Path, text: str = VECTORS) -> Path:
        path = Path(root) / embeddings.MODEL_RELATIVE_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def make_root(self, tmp: str) -> Path:
        root = Path(tmp) / "master"
        support.make_project(root / "PROJECTS" / "Alpha")
        return root


class ParseVectorsTests(unittest.TestCase):
    def test_header_is_optional_and_not_trusted(self):
        with_header = parse_vectors("2 2\na 1 0\nb 0 1\n")
        without_header = parse_vectors("a 1 0\nb 0 1\n")
        self.assertEqual(with_header, without_header)
        self.assertEqual(with_header[0], 2)

    def test_a_wrong_header_count_does_not_truncate_the_model(self):
        dim, table = parse_vectors("999 2\na 1 0\nb 0 1\nc 1 1\n")
        self.assertEqual(dim, 2)
        self.assertEqual(sorted(table), ["a", "b", "c"])

    def test_comments_and_blank_lines_are_ignored(self):
        dim, table = parse_vectors("# a comment\n\na 1 0\n\n# another\nb 0 1\n")
        self.assertEqual(dim, 2)
        self.assertEqual(sorted(table), ["a", "b"])

    def test_malformed_rows_are_skipped_not_fatal(self):
        text = "a 1 0\nb 0 1\nTOO MANY 1 0 1\nc nope\nd 0.5 0.5\n"
        dim, table = parse_vectors(text)
        self.assertEqual(dim, 2)
        self.assertEqual(sorted(table), ["a", "b", "d"])

    def test_a_row_with_the_wrong_width_is_skipped(self):
        dim, table = parse_vectors("a 1 0\nb 1 0 0\nc 0 1\n")
        self.assertEqual(dim, 2)
        self.assertEqual(sorted(table), ["a", "c"])

    def test_the_last_definition_of_a_token_wins(self):
        _dim, table = parse_vectors("a 1 0\nb 0 1\na 0 1\n")
        self.assertEqual(table["a"], [0.0, 1.0])

    def test_crlf_line_endings_are_tolerated(self):
        dim, table = parse_vectors("2 2\r\na 1 0\r\nb 0 1\r\n")
        self.assertEqual(dim, 2)
        self.assertEqual(sorted(table), ["a", "b"])

    def test_empty_or_unusable_text_is_an_error(self):
        for text in ("", "\n\n", "# only comments\n", "garbage without numbers\n"):
            with self.subTest(text=repr(text)):
                with self.assertRaises(EmbeddingError):
                    parse_vectors(text)


class VectorSpaceTests(unittest.TestCase):
    def space(self) -> VectorSpace:
        dim, table = parse_vectors(VECTORS)
        return VectorSpace(
            source=Path("synthetic.vec"),
            dim=dim,
            tokens={token: position for position, token in enumerate(table)},
            matrix=list(table.values()),
            backend="python",
        )

    def test_embed_returns_a_unit_vector(self):
        vector = self.space().embed(["auth"])
        self.assertIsNotNone(vector)
        self.assertAlmostEqual(sum(value * value for value in vector), 1.0, places=9)
        self.assertAlmostEqual(vector[0], 1.0, places=9)

    def test_embed_skips_unknown_terms(self):
        space = self.space()
        mixed = space.embed(["auth", "not_in_the_model"])
        self.assertEqual(mixed, space.embed(["auth"]))

    def test_embed_returns_nothing_when_no_term_is_known(self):
        self.assertIsNone(self.space().embed(["nothing", "known", "here"]))
        self.assertIsNone(self.space().embed([]))

    def test_repetition_weights_the_direction(self):
        """A term used twice pulls the vector: this is the term-frequency weighting."""
        space = self.space()
        once = space.embed(["auth", "deploy"])
        twice = space.embed(["auth", "auth", "deploy"])
        self.assertAlmostEqual(once[0], once[1], places=9)
        self.assertGreater(twice[0], twice[1])

    def test_a_zero_vector_has_no_direction(self):
        dim, table = parse_vectors("a 0 0\nb 1 0\n")
        space = VectorSpace(
            source=Path("z.vec"),
            dim=dim,
            tokens={token: position for position, token in enumerate(table)},
            matrix=list(table.values()),
            backend="python",
        )
        self.assertIsNone(space.embed(["a"]))

    def test_cosine_of_a_vector_with_itself_is_one(self):
        space = self.space()
        vector = space.embed(["auth", "deploy"])
        self.assertAlmostEqual(cosine(vector, vector), 1.0, places=9)

    def test_cosine_of_orthogonal_vectors_is_zero(self):
        space = self.space()
        self.assertAlmostEqual(cosine(space.embed(["auth"]), space.embed(["deploy"])), 0.0, places=9)

    def test_cosine_of_missing_vectors_is_zero(self):
        self.assertEqual(cosine(None, [1.0, 0.0]), 0.0)
        self.assertEqual(cosine([1.0, 0.0], None), 0.0)
        self.assertEqual(cosine([], []), 0.0)
        self.assertEqual(cosine([0.0, 0.0], [1.0, 0.0]), 0.0)


class LoadVectorsTests(EmbeddingTestCase):
    def test_missing_file_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(EmbeddingError):
                load_vectors(Path(tmp) / "absent.vec")

    def test_backend_reflects_whether_numpy_is_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            space = load_vectors(self.install_model(tmp))
            expected = "numpy" if embeddings.numpy_module() is not None else "python"
            self.assertEqual(space.backend, expected)
            self.assertEqual(space.dim, 2)
            self.assertEqual(space.size, 4)

    def test_the_dependency_free_path_refuses_a_model_that_is_too_large(self):
        """The guard must name the fix instead of exhausting memory."""
        with tempfile.TemporaryDirectory() as tmp:
            path = self.install_model(tmp)
            with mock.patch.object(embeddings, "numpy_module", return_value=None):
                with mock.patch.object(embeddings, "MAX_PYTHON_CELLS", 4):
                    with self.assertRaises(EmbeddingError) as caught:
                        load_vectors(path)
            self.assertIn("numpy", str(caught.exception))

    def test_a_large_model_is_accepted_when_numpy_is_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.install_model(tmp)
            with mock.patch.object(embeddings, "numpy_module", return_value=None):
                with mock.patch.object(embeddings, "MAX_PYTHON_CELLS", 999):
                    space = load_vectors(path)
            self.assertEqual(space.backend, "python")

    def test_a_small_model_loads_without_numpy(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.install_model(tmp)
            with mock.patch.object(embeddings, "numpy_module", return_value=None):
                space = load_vectors(path)
            self.assertEqual(space.backend, "python")
            self.assertIn("dim=2", space.describe())


class ModelResolutionTests(EmbeddingTestCase):
    def test_no_model_anywhere_resolves_to_nothing(self):
        with tempfile.TemporaryDirectory() as tmp, no_model_env():
            self.assertIsNone(resolve_model_path(self.make_root(tmp)))
            self.assertIsNone(load_space(self.make_root(tmp)))
            self.assertIsNone(SemanticReranker.from_root(self.make_root(tmp)))

    def test_the_convention_path_is_used_when_present(self):
        with tempfile.TemporaryDirectory() as tmp, no_model_env():
            root = self.make_root(tmp)
            installed = self.install_model(root)
            self.assertEqual(resolve_model_path(root), installed)
            self.assertIsNotNone(SemanticReranker.from_root(root))

    def test_an_explicit_path_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_root(tmp)
            elsewhere = Path(tmp) / "elsewhere.vec"
            elsewhere.write_text(VECTORS, encoding="utf-8")
            with mock.patch.dict(os.environ, {MODEL_ENV_VAR: str(elsewhere)}):
                self.assertEqual(resolve_model_path(root), elsewhere)

    def test_an_explicit_path_that_does_not_exist_is_refused(self):
        """A typo must not look like 'no model installed'."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_root(tmp)
            missing = Path(tmp) / "typo.vec"
            with mock.patch.dict(os.environ, {MODEL_ENV_VAR: str(missing)}):
                # The convention model exists, and still the bad path wins the
                # argument: it is reported, never silently ignored.
                self.install_model(root)
                with self.assertRaises(EmbeddingError):
                    resolve_model_path(root)

    def test_a_loaded_model_is_cached_by_revision(self):
        with tempfile.TemporaryDirectory() as tmp, no_model_env():
            root = self.make_root(tmp)
            self.install_model(root)
            first = load_space(root)
            self.assertIs(load_space(root), first)

    def test_a_changed_model_is_reloaded(self):
        with tempfile.TemporaryDirectory() as tmp, no_model_env():
            root = self.make_root(tmp)
            path = self.install_model(root)
            first = load_space(root)
            path.write_text(VECTORS.replace("core", "kernel"), encoding="utf-8")
            os.utime(path, (0, 0))
            second = load_space(root)
            self.assertIsNot(second, first)
            self.assertIn("kernel", second.tokens)


class RerankArithmeticTests(EmbeddingTestCase):
    """The fusion rule, pinned as arithmetic instead of inferred from a run."""

    def space(self) -> VectorSpace:
        dim, table = parse_vectors(VECTORS)
        return VectorSpace(
            source=Path("synthetic.vec"),
            dim=dim,
            tokens={token: position for position, token in enumerate(table)},
            matrix=list(table.values()),
            backend="python",
        )

    def hit(self, memory_id: str, score: float) -> dict:
        return {
            "memory_id": memory_id,
            "project_id": ALPHA,
            "type": "decision",
            "created_at": "2026-01-01T00:00:00Z",
            "state": "active",
            "tags": [],
            "score": score,
            "snippet": "",
        }

    def test_scores_are_reciprocal_rank_fusions(self):
        reranker = SemanticReranker(self.space(), rank_constant=60)
        hits = [self.hit("MEM-0001", 9.0), self.hit("MEM-0002", 8.0)]
        texts = {
            (ALPHA, "MEM-0001"): "auth deploy auth",   # rows on the diagonal-ish
            (ALPHA, "MEM-0002"): "auth deploy core",   # exactly the query direction
        }

        result = reranker.rerank("auth deploy", hits, texts)

        # MEM-0002 is semantically first and lexically second:
        #   1/(60+2) + 1/(60+1)
        # MEM-0001 is lexically first and semantically second:
        #   1/(60+1) + 1/(60+2)
        # which is a tie, so the lexical rank decides and the order is preserved.
        expected = round(1 / 62 + 1 / 61, 8)
        self.assertEqual(result[0]["score"], expected)
        self.assertEqual(result[1]["score"], expected)
        self.assertEqual([hit["memory_id"] for hit in result], ["MEM-0001", "MEM-0002"])

    def test_the_lexical_score_survives_as_lexical_score(self):
        reranker = SemanticReranker(self.space())
        hits = [self.hit("MEM-0001", 9.5)]
        result = reranker.rerank("auth deploy", hits, {(ALPHA, "MEM-0001"): "auth deploy"})
        self.assertEqual(result[0]["lexical_score"], 9.5)
        self.assertAlmostEqual(result[0]["semantic_score"], 1.0, places=6)
        self.assertNotEqual(result[0]["score"], 9.5)

    def test_a_candidate_with_no_representable_text_keeps_only_its_lexical_rank(self):
        reranker = SemanticReranker(self.space())
        hits = [self.hit("MEM-0001", 5.0), self.hit("MEM-0002", 4.0)]
        texts = {(ALPHA, "MEM-0002"): "auth deploy"}
        result = reranker.rerank("auth deploy", hits, texts)

        scored = {hit["memory_id"]: hit for hit in result}
        self.assertNotIn("semantic_score", scored["MEM-0001"])
        self.assertEqual(scored["MEM-0001"]["score"], round(1 / 61, 8))
        self.assertIn("semantic_score", scored["MEM-0002"])
        self.assertGreater(scored["MEM-0002"]["score"], scored["MEM-0001"]["score"])

    def test_a_query_with_no_representable_meaning_leaves_the_order_alone(self):
        dim, table = parse_vectors("a 0 0\nb 1 0\n")
        space = VectorSpace(
            source=Path("z.vec"),
            dim=dim,
            tokens={token: position for position, token in enumerate(table)},
            matrix=list(table.values()),
            backend="python",
        )
        hits = [self.hit("MEM-0001", 3.0), self.hit("MEM-0002", 2.0)]
        result = SemanticReranker(space).rerank("a", hits, {})

        self.assertEqual([hit["memory_id"] for hit in result], ["MEM-0001", "MEM-0002"])
        self.assertEqual(result[0]["score"], 3.0)
        self.assertNotIn("semantic_score", result[0])

    def test_empty_input_is_returned_unchanged(self):
        self.assertEqual(SemanticReranker(self.space()).rerank("auth", [], {}), [])


@unittest.skipUnless(embeddings.numpy_module() is not None, "numpy is not installed")
class NumpyBackendTests(EmbeddingTestCase):
    """Runs wherever numpy exists; skipped on a bare interpreter."""

    def test_numpy_and_the_reference_path_agree(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.install_model(tmp)
            with_numpy = load_vectors(path)
            with mock.patch.object(embeddings, "numpy_module", return_value=None):
                reference = load_vectors(path)

            self.assertEqual(with_numpy.backend, "numpy")
            self.assertEqual(reference.backend, "python")
            for terms in (["auth"], ["auth", "deploy"], ["auth", "auth", "deploy"], ["core"]):
                left = with_numpy.embed(terms)
                right = reference.embed(terms)
                self.assertIsNotNone(left)
                for a, b in zip(left, right):
                    self.assertAlmostEqual(a, b, places=6)


class SearchRerankTests(EmbeddingTestCase):
    """End-to-end through the engine, on a throwaway root."""

    def build(self, tmp: str):
        """Three lexically-matching records plus one that only *means* the query.

        Lexical order is X, Y, Z (term frequency, strictly decreasing, so it
        cannot depend on timestamps).
        Semantic order is Y, Z, X.
        Fused order must be Y, X, Z: Y is promoted past X, and only the semantic
        signal can explain that.

        Z deliberately uses `nearby` rather than `near_deploy`: FTS5 splits on
        the underscore, so the latter would add a second `deploy` term, tie Y
        on bm25 and make the fixture depend on the creation timestamps.
        """
        root = self.make_root(tmp)
        engine = MemoryEngine(root=root)
        x = engine.add(ALPHA, "decision", {"summary": "auth auth auth deploy"}, "t")["memory_id"]
        y = engine.add(ALPHA, "decision", {"summary": "auth auth deploy core"}, "t")["memory_id"]
        z = engine.add(ALPHA, "decision", {"summary": "auth deploy nearby"}, "t")["memory_id"]
        w = engine.add(ALPHA, "discovery", {"summary": "core core core"}, "t")["memory_id"]
        return root, engine, x, y, z, w

    def order(self, result):
        return [hit["memory_id"] for hit in result["hits"]]

    def test_without_a_model_search_is_lexical_and_says_so(self):
        with tempfile.TemporaryDirectory() as tmp, no_model_env():
            root, engine, x, y, z, _w = self.build(tmp)
            result = engine.search("auth deploy")

            self.assertEqual(self.order(result), [x, y, z])
            self.assertFalse(result["reranker"]["used"])
            self.assertIsNone(result["reranker"]["model"])
            self.assertIn(str(embeddings.MODEL_RELATIVE_PATH), result["reranker"]["reason"])

    def test_a_model_promotes_a_candidate_the_lexical_pass_ranked_lower(self):
        with tempfile.TemporaryDirectory() as tmp, no_model_env():
            root, engine, x, y, z, _w = self.build(tmp)
            self.install_model(root)

            lexical = engine.search("auth deploy", rerank=False)
            reranked = engine.search("auth deploy")

            self.assertEqual(self.order(lexical), [x, y, z])
            self.assertEqual(self.order(reranked), [y, x, z])
            self.assertTrue(reranked["reranker"]["used"])
            self.assertEqual(reranked["reranker"]["backend"], "python"
                             if embeddings.numpy_module() is None else "numpy")

    def test_the_semantic_scores_explain_the_new_order(self):
        with tempfile.TemporaryDirectory() as tmp, no_model_env():
            root, engine, x, y, z, _w = self.build(tmp)
            self.install_model(root)

            scores = {
                hit["memory_id"]: hit["semantic_score"]
                for hit in engine.search("auth deploy")["hits"]
            }
            self.assertGreater(scores[y], scores[z])
            self.assertGreater(scores[z], scores[x])

    def test_reranking_never_surfaces_a_record_the_lexical_pass_missed(self):
        """The contract that makes this a reranker and not a retriever."""
        with tempfile.TemporaryDirectory() as tmp, no_model_env():
            root, engine, _x, _y, _z, w = self.build(tmp)
            self.install_model(root)

            result = engine.search("auth deploy")

            self.assertNotIn(w, self.order(result))
            # It is not an absence of signal: `w` is a perfect semantic match.
            reranker = SemanticReranker.from_root(root)
            self.assertAlmostEqual(
                reranker.similarity(
                    reranker.space.embed(["auth", "deploy"]), "core core core"
                ),
                1.0,
                places=6,
            )

    def test_both_backends_agree_on_the_reranked_order(self):
        with tempfile.TemporaryDirectory() as tmp, no_model_env():
            root, engine, _x, y, _z, _w = self.build(tmp)
            self.install_model(root)

            indexed = engine.search("auth deploy")
            with mock.patch.object(index_module, "fts5_available", return_value=False):
                scanned = engine.search("auth deploy")

            self.assertEqual(indexed["backend"], "fts5")
            self.assertEqual(scanned["backend"], "scan")
            self.assertEqual(self.order(indexed), self.order(scanned))
            self.assertEqual(self.order(indexed)[0], y)

    def test_reranking_parses_no_record(self):
        """Candidate text comes from the index, so no JSON is re-read to rerank."""
        with tempfile.TemporaryDirectory() as tmp, no_model_env():
            root, engine, _x, y, _z, _w = self.build(tmp)
            self.install_model(root)
            engine.refresh_index(rebuild=True)

            with mock.patch.object(
                MemoryEngine,
                "_iter_records",
                side_effect=AssertionError("reranking must not scan records"),
            ):
                result = engine.search("auth deploy")

            self.assertEqual(self.order(result)[0], y)

    def test_the_index_supplies_the_candidate_text(self):
        with tempfile.TemporaryDirectory() as tmp, no_model_env():
            root, engine, x, y, z, _w = self.build(tmp)
            self.install_model(root)
            engine.refresh_index(rebuild=True)

            asked: list = []
            original = index_module.MemoryIndex.text_map

            def spy(self, keys):
                asked.append(list(keys))
                return original(self, keys)

            with mock.patch.object(index_module.MemoryIndex, "text_map", spy):
                engine.search("auth deploy")

            self.assertEqual(len(asked), 1)
            self.assertEqual(
                sorted(asked[0]), sorted([(ALPHA, x), (ALPHA, y), (ALPHA, z)])
            )

    def test_disabling_the_reranker_is_explicit_and_explained(self):
        with tempfile.TemporaryDirectory() as tmp, no_model_env():
            root, engine, x, y, z, _w = self.build(tmp)
            self.install_model(root)

            result = engine.search("auth deploy", rerank=False)

            self.assertEqual(self.order(result), [x, y, z])
            self.assertFalse(result["reranker"]["used"])
            self.assertIn("disabled", result["reranker"]["reason"])

    def test_demanding_a_reranker_without_a_model_fails_loudly(self):
        with tempfile.TemporaryDirectory() as tmp, no_model_env():
            _root, engine, _x, _y, _z, _w = self.build(tmp)
            with self.assertRaises(ValueError) as caught:
                engine.search("auth deploy", rerank=True)
            self.assertIn("no embedding model", str(caught.exception))

    def test_a_broken_model_path_degrades_when_optional_and_fails_when_demanded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, engine, x, y, z, _w = self.build(tmp)
            missing = Path(tmp) / "typo.vec"
            with mock.patch.dict(os.environ, {MODEL_ENV_VAR: str(missing)}):
                optional = engine.search("auth deploy")
                self.assertEqual(self.order(optional), [x, y, z])
                self.assertFalse(optional["reranker"]["used"])
                self.assertIn("not a file", optional["reranker"]["reason"])

                with self.assertRaises(ValueError):
                    engine.search("auth deploy", rerank=True)

    def test_the_candidate_window_bounds_what_can_be_promoted(self):
        """The window is the cost bound: outside it, no amount of meaning helps."""
        with tempfile.TemporaryDirectory() as tmp, no_model_env():
            root, engine, x, y, _z, _w = self.build(tmp)
            self.install_model(root)

            wide = engine.search("auth deploy", limit=1, candidates=50)
            narrow = engine.search("auth deploy", limit=1, candidates=1)

            self.assertEqual(self.order(wide), [y])
            self.assertEqual(self.order(narrow), [x])
            self.assertEqual(wide["reranker"]["candidates"], 50)
            self.assertEqual(narrow["reranker"]["candidates"], 1)

    def test_paging_is_applied_after_reranking(self):
        with tempfile.TemporaryDirectory() as tmp, no_model_env():
            root, engine, x, y, z, _w = self.build(tmp)
            self.install_model(root)

            first = engine.search("auth deploy", limit=1, offset=0)
            second = engine.search("auth deploy", limit=1, offset=1)
            third = engine.search("auth deploy", limit=1, offset=2)

            self.assertEqual(self.order(first), [y])
            self.assertEqual(self.order(second), [x])
            self.assertEqual(self.order(third), [z])

    def test_the_result_reports_how_the_ranking_was_produced(self):
        with tempfile.TemporaryDirectory() as tmp, no_model_env():
            root, engine, _x, _y, _z, _w = self.build(tmp)
            path = self.install_model(root)

            report = engine.search("auth deploy")["reranker"]

            self.assertTrue(report["used"])
            self.assertEqual(report["model"], str(path))
            self.assertEqual(report["candidates"], 50)
            self.assertIsNone(report["reason"])

    def test_repeated_searches_return_the_same_order(self):
        with tempfile.TemporaryDirectory() as tmp, no_model_env():
            root, engine, _x, _y, _z, _w = self.build(tmp)
            self.install_model(root)

            first = self.order(engine.search("auth deploy"))
            second = self.order(engine.search("auth deploy"))

            self.assertEqual(first, second)

    def test_deprecated_records_stay_out_of_a_reranked_search(self):
        with tempfile.TemporaryDirectory() as tmp, no_model_env():
            root, engine, x, y, z, _w = self.build(tmp)
            self.install_model(root)
            engine.update(y, ALPHA, {"state": "deprecated"})

            result = engine.search("auth deploy")

            self.assertNotIn(y, self.order(result))
            self.assertEqual(self.order(result), [x, z])

    def test_a_type_filter_still_applies_before_reranking(self):
        with tempfile.TemporaryDirectory() as tmp, no_model_env():
            root, engine, x, y, z, _w = self.build(tmp)
            self.install_model(root)

            result = engine.search("auth deploy", types=["decision"])

            self.assertEqual(sorted(self.order(result)), sorted([x, y, z]))


class SearchCliTests(unittest.TestCase):
    """CLI surface, without touching the repository's own state."""

    def test_semantic_flags_are_mutually_exclusive(self):
        code, out = support.run_cli(
            "memory", "search", "--query", "x", "--semantic", "--no-semantic"
        )
        self.assertEqual(code, 2, out)

    def test_demanding_semantics_with_a_broken_model_path_fails_before_searching(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ, {MODEL_ENV_VAR: str(Path(tmp) / "absent.vec")}
        ):
            code, out = support.run_cli(
                "memory", "search", "--query", "memory", "--semantic"
            )
        self.assertEqual(code, 1, out)
        self.assertIn("not a file", out)

    def test_the_new_flags_parse_before_the_project_is_resolved(self):
        for flag in ("--semantic", "--no-semantic"):
            with self.subTest(flag=flag):
                code, out = support.run_cli(
                    "memory", "search",
                    "--query", "x",
                    "--project", "PROJECTS/none",
                    flag,
                )
                self.assertEqual(code, 1, out)
                self.assertIn("no PROJECT.json", out)


if __name__ == "__main__":
    unittest.main()
