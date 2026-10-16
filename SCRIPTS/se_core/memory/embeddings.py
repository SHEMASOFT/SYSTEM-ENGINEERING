"""Optional local semantic reranker for memory search (ADR-0027 phase 5).

Lexical retrieval (FTS5, or the pure-Python scan) decides *what* comes back;
this module only decides *in what order*. That split is deliberate: a reranker
cannot invent a hit, so semantic search can never hide a record the lexical pass
found, and it can never surface one the lexical pass did not.

Design rules, all load-bearing:

* **No network, no service, no per-query cost.** The model is a word-vector text
  file the operator puts under ``.se/models/`` (or points at with
  ``SE_MEMORY_EMBEDDINGS``). Nothing here ever downloads it and nothing here
  calls out of the process.
* **The dependency-free path is the reference.** The algorithm is plain Python
  and always works. ``numpy`` is an optional accelerator that only changes how
  many vectors fit in memory, never the ranking; a model too large for the
  dependency-free path is refused with a clear error instead of thrashing.
* **Ordering is rank fusion, not score arithmetic.** Lexical scores are
  backend-relative (negated bm25, or term frequency on the scan fallback) and
  are not comparable, so the two rankings are fused by reciprocal rank. Nothing
  needs normalising and a backend change cannot silently re-weight results.
* **Absence is not failure.** No model means no rerank and a stated reason. A
  model that is *configured but broken* is an error, because a typo in a path
  must not look like "not installed".

Vocabulary comes from :func:`se_core.memory.index.tokenize`, so both backends
tokenise identically and the same term cannot mean two things.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .index import tokenize

MODEL_ENV_VAR = "SE_MEMORY_EMBEDDINGS"
MODEL_RELATIVE_PATH = Path(".se") / "models" / "word-vectors.vec"

# Limits for the dependency-free path. Python floats cost roughly an order of
# magnitude more per cell than a numpy float32 array, so a full-size model is a
# memory problem, not a correctness one: it is refused with the fix in the
# message rather than allowed to exhaust the machine.
MAX_PYTHON_VOCAB = 50_000
MAX_PYTHON_DIM = 2_048
MAX_PYTHON_CELLS = 4_000_000

# Reciprocal-rank-fusion constant. The standard value: large enough that the
# difference between rank 1 and rank 2 is a nudge rather than a verdict, small
# enough that a candidate ranked well by both signals still wins.
RANK_CONSTANT = 60

# One loaded model per process is enough, and bounding the cache keeps a
# long-lived process from accumulating every model it has ever seen. The key
# includes mtime and size, so editing a model reloads it.
_SPACE_CACHE: Dict[Tuple[str, int, int], "VectorSpace"] = {}


class EmbeddingError(ValueError):
    """The embedding model is missing, unreadable, malformed or too large.

    Subclasses ``ValueError`` so the CLI's existing ``ValueError -> FAIL`` guard
    reports it as a failed command rather than a traceback.
    """


def numpy_module() -> Any:
    """The numpy module, or ``None`` when it is not installed.

    Probed on every call instead of cached: importing is what costs, and a
    caller that patches the module away (tests, or an operator without numpy)
    must see the real state of the interpreter.
    """
    try:
        import numpy  # noqa: PLC0415
    except Exception:
        return None
    return numpy


def parse_vectors(text: str) -> Tuple[int, Dict[str, List[float]]]:
    """Parse word-vector text into ``(dim, {token: vector})``.

    Accepts the classic text format with or without its ``count dim`` header,
    ignores blank lines and ``#`` comments, and skips rows that do not match the
    detected dimension. Skipping is deliberate: real vector files carry stray
    lines, and one bad row must not cost a whole model.
    """
    vectors: Dict[str, List[float]] = {}
    dim: Optional[int] = None
    first_line_seen = False

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if not first_line_seen:
            first_line_seen = True
            # `count dim` header. The count is not trusted: the file is the
            # source of truth and a wrong count would otherwise truncate it.
            if len(parts) == 2 and all(p.lstrip("-").isdigit() for p in parts):
                continue
        token = parts[0]
        try:
            values = [float(p) for p in parts[1:]]
        except ValueError:
            continue
        if not values:
            continue
        if dim is None:
            dim = len(values)
        if len(values) != dim:
            continue
        vectors[token] = values

    if dim is None or not vectors:
        raise EmbeddingError("no usable vectors found in the model file")
    return dim, vectors


def _normalise(values: Sequence[float]) -> Optional[List[float]]:
    """Unit-length copy of ``values``, or ``None`` when it has no direction."""
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0.0:
        return None
    return [value / norm for value in values]


def cosine(left: Optional[Sequence[float]], right: Optional[Sequence[float]]) -> float:
    """Cosine similarity, ``0.0`` for a missing or zero-length vector.

    Returning a score instead of raising keeps "nothing in common" and "nothing
    to compare" on the same code path, which is what lets a candidate with no
    representable text simply forgo its semantic component.
    """
    if not left or not right:
        return 0.0
    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for a, b in zip(left, right):
        dot += a * b
        left_norm += a * a
        right_norm += b * b
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / math.sqrt(left_norm * right_norm)


@dataclass
class VectorSpace:
    """A loaded word-vector model: tokens, matrix and how the matrix is stored."""

    source: Path
    dim: int
    tokens: Dict[str, int]
    matrix: Any
    backend: str

    @property
    def size(self) -> int:
        """Number of vectors in the model."""
        return len(self.tokens)

    def embed(self, terms: Sequence[str]) -> Optional[List[float]]:
        """Unit vector for ``terms``, or ``None`` when none of them is known.

        Vectors are summed before normalisation, which weights a term by how
        often it occurs. Unknown terms are skipped so unseen vocabulary degrades
        the embedding instead of losing it; a text with nothing known has no
        vector at all, which callers can tell apart from a zero-similarity one.
        """
        indices = [self.tokens[term] for term in terms if term in self.tokens]
        if not indices:
            return None

        if self.backend == "numpy":
            summed = self.matrix[indices].sum(axis=0)
            return _normalise([float(value) for value in summed])

        accumulated = [0.0] * self.dim
        for index in indices:
            row = self.matrix[index]
            for position in range(self.dim):
                accumulated[position] += row[position]
        return _normalise(accumulated)

    def describe(self) -> str:
        return (
            f"{self.backend} dim={self.dim} vocab={self.size} "
            f"({Path(self.source).name})"
        )


def load_vectors(path: Path) -> VectorSpace:
    """Read and load a model file, choosing the numpy path when available."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise EmbeddingError(f"cannot read embedding model {path}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise EmbeddingError(f"embedding model {path} is not valid UTF-8 text: {exc}") from exc

    dim, table = parse_vectors(text)
    rows = list(table.values())
    tokens = {token: index for index, token in enumerate(table)}

    numpy = numpy_module()
    if numpy is None:
        cells = len(rows) * dim
        if (
            len(rows) > MAX_PYTHON_VOCAB
            or dim > MAX_PYTHON_DIM
            or cells > MAX_PYTHON_CELLS
        ):
            raise EmbeddingError(
                f"embedding model {path.name} holds {len(rows)} vectors of "
                f"dimension {dim} ({cells} values), which the dependency-free "
                f"path will not load into Python floats; install numpy "
                f"(pip install numpy) or use a smaller model"
            )
        return VectorSpace(path, dim, tokens, rows, "python")

    matrix = numpy.array(rows, dtype=numpy.float32)
    return VectorSpace(path, dim, tokens, matrix, "numpy")


def resolve_model_path(root: Path) -> Optional[Path]:
    """Locate the model, or ``None`` when none is installed.

    An explicit ``SE_MEMORY_EMBEDDINGS`` is obeyed or refused, never ignored: a
    typo there would otherwise be indistinguishable from "no model installed"
    and would disable semantic search in silence.
    """
    configured = os.environ.get(MODEL_ENV_VAR)
    if configured:
        path = Path(configured).expanduser()
        if not path.is_file():
            raise EmbeddingError(
                f"{MODEL_ENV_VAR} points at {path}, which is not a file"
            )
        return path

    candidate = Path(root) / MODEL_RELATIVE_PATH
    return candidate if candidate.is_file() else None


def load_space(root: Path) -> Optional[VectorSpace]:
    """Load the model for an engine root, or ``None`` when there is none."""
    path = resolve_model_path(root)
    if path is None:
        return None

    try:
        stat = path.stat()
    except OSError as exc:
        raise EmbeddingError(f"cannot stat embedding model {path}: {exc}") from exc

    key = (str(path), stat.st_mtime_ns, stat.st_size)
    cached = _SPACE_CACHE.get(key)
    if cached is not None:
        return cached

    space = load_vectors(path)
    _SPACE_CACHE.clear()
    _SPACE_CACHE[key] = space
    return space


class SemanticReranker:
    """Reorders lexical candidates by meaning, fusing lexical and semantic rank.

    Recall belongs to the lexical pass; this class only reorders what it is
    given, so it cannot introduce a hit. Fusion is by reciprocal rank, which
    keeps the two incomparable score scales apart and makes the order a pure
    function of the two rankings.
    """

    def __init__(self, space: VectorSpace, rank_constant: int = RANK_CONSTANT):
        self.space = space
        self.rank_constant = rank_constant

    @classmethod
    def from_root(cls, root: Path) -> Optional["SemanticReranker"]:
        """The reranker for an engine root, or ``None`` when no model is installed.

        Raises :class:`EmbeddingError` when a model is configured but unusable.
        """
        space = load_space(root)
        return cls(space) if space is not None else None

    def describe(self) -> str:
        return self.space.describe()

    def similarity(self, query_vector: Sequence[float], text: str) -> Optional[float]:
        """Cosine between an already-embedded query and a candidate's text."""
        if not text:
            return None
        vector = self.space.embed(tokenize(text))
        if vector is None:
            return None
        return cosine(query_vector, vector)

    def rerank(
        self,
        query: str,
        hits: Sequence[Dict[str, Any]],
        texts: Mapping[Tuple[str, str], str],
    ) -> List[Dict[str, Any]]:
        """Return ``hits`` reordered, annotated with how each one was ranked.

        Why a hit moved is left visible on purpose: the lexical score that the
        backend produced is preserved as ``lexical_score``, the similarity that
        was measured is kept as ``semantic_score``, and ``score`` becomes the
        fused value that actually decided the order. Order is total and
        reproducible: ties fall back to the lexical rank.
        """
        query_vector = self.space.embed(tokenize(query))
        if query_vector is None or not hits:
            # The query has no representable meaning, so there is nothing to
            # rerank by; the lexical order stands untouched.
            return list(hits)

        scored: List[Dict[str, Any]] = []
        for position, hit in enumerate(hits, start=1):
            key = (hit.get("project_id"), hit.get("memory_id"))
            similarity = self.similarity(query_vector, texts.get(key, ""))
            scored.append(
                {
                    "hit": hit,
                    "lexical_rank": position,
                    "similarity": similarity,
                }
            )

        ranked = sorted(
            (candidate for candidate in scored if candidate["similarity"] is not None),
            key=lambda candidate: (-candidate["similarity"], candidate["lexical_rank"]),
        )
        for rank, candidate in enumerate(ranked, start=1):
            candidate["semantic_rank"] = rank

        for candidate in scored:
            fused = 1.0 / (self.rank_constant + candidate["lexical_rank"])
            if candidate.get("semantic_rank"):
                fused += 1.0 / (self.rank_constant + candidate["semantic_rank"])
            candidate["fused"] = fused

        scored.sort(key=lambda candidate: (-candidate["fused"], candidate["lexical_rank"]))

        results: List[Dict[str, Any]] = []
        for candidate in scored:
            hit = dict(candidate["hit"])
            hit["lexical_score"] = hit.pop("score", None)
            hit["score"] = round(candidate["fused"], 8)
            if candidate["similarity"] is not None:
                hit["semantic_score"] = round(candidate["similarity"], 6)
            results.append(hit)
        return results
