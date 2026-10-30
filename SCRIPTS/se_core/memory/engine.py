"""Memory Engine for SYSTEM-ENGINEERING.

Provides structured, queryable memory backed by canonical JSON records
(ADR-0003, ADR-0027). Supports project-scoped and cross-project operations.
"""

from __future__ import annotations

import json
import hashlib
import os
import random
import time
import unicodedata
import contextlib
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass

from ..paths import repo_root, now_utc, write_json_atomic
from ..schemas import load_schemas, validate
from ..artifacts import read_manifest
from .index import (
    INDEX_ERRORS,
    IndexEntry,
    MemoryIndex,
    flatten_content,
    tokenize,
)
from .embeddings import (
    MODEL_ENV_VAR,
    MODEL_RELATIVE_PATH,
    EmbeddingError,
    SemanticReranker,
)


@dataclass
class MemoryRecord:
    """In-memory representation of a memory record."""
    memory_id: str
    project_id: str
    type: str
    scope: str
    content: Dict[str, Any]
    tags: List[str]
    confidence: float
    created_at: str
    updated_at: str
    author: str
    source: str
    related_memories: List[str]
    supersedes: Optional[str]
    superseded_by: Optional[str]
    metadata: Dict[str, Any]
    topic_key: Optional[str] = None
    revision_count: int = 0
    duplicate_count: int = 0
    last_seen_at: Optional[str] = None
    review_after: Optional[str] = None
    state: str = "active"
    schema_version: str = "1"
    ttl_days: Optional[int] = None
    expires_at: Optional[str] = None
    gc_protected: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "memory_id": self.memory_id,
            "project_id": self.project_id,
            "type": self.type,
            "scope": self.scope,
            "content": self.content,
            "tags": self.tags,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "author": self.author,
            "source": self.source,
            "related_memories": self.related_memories,
            "supersedes": self.supersedes,
            "superseded_by": self.superseded_by,
            "metadata": self.metadata,
            "topic_key": self.topic_key,
            "revision_count": self.revision_count,
            "duplicate_count": self.duplicate_count,
            "last_seen_at": self.last_seen_at,
            "review_after": self.review_after,
            "state": self.state,
            "ttl_days": self.ttl_days,
            "expires_at": self.expires_at,
            "gc_protected": self.gc_protected,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryRecord":
        return cls(
            memory_id=data["memory_id"],
            project_id=data["project_id"],
            type=data["type"],
            scope=data.get("scope", "project"),
            content=data["content"],
            tags=data.get("tags", []),
            confidence=data.get("confidence", 1.0),
            created_at=data["created_at"],
            updated_at=data.get("updated_at", data["created_at"]),
            author=data["author"],
            source=data.get("source", "manual"),
            related_memories=data.get("related_memories", []),
            supersedes=data.get("supersedes"),
            superseded_by=data.get("superseded_by"),
            metadata=data.get("metadata", {}),
            topic_key=data.get("topic_key"),
            revision_count=data.get("revision_count", 0),
            duplicate_count=data.get("duplicate_count", 0),
            last_seen_at=data.get("last_seen_at"),
            review_after=data.get("review_after"),
            state=data.get("state", "active"),
            ttl_days=data.get("ttl_days"),
            expires_at=data.get("expires_at"),
            gc_protected=data.get("gc_protected", False),
        )


def _file_lock(lock_path: Path, timeout: float = 10.0):
    """Cross-platform file lock via atomic O_CREAT|O_EXCL.

    Returns a context manager. Raises TimeoutError if the lock cannot be
    acquired within ``timeout`` seconds.
    """
    @contextlib.contextmanager
    def _ctx():
        waited = False
        deadline = time.monotonic() + timeout
        while True:
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                break
            except FileExistsError:
                if time.monotonic() > deadline:
                    raise TimeoutError(f"Could not acquire lock: {lock_path}")
                waited = True
                time.sleep(0.05)
        try:
            yield waited
        finally:
            try:
                os.unlink(lock_path)
            except OSError:
                pass
    return _ctx()


class MemoryEngine:
    """Memory Engine over canonical JSON records (ADR-0003, ADR-0027).

    Provides CRUD operations for memory records with:
    - Project-scoped and cross-project queries
    - Lexical search through a derived, rebuildable FTS5 index, with a
      pure-Python scan as the fallback path (ADR-0027)
    - Relationship tracking (supersedes, related, compatible)
    - Tag-based filtering
    - Atomic, LF, schema-validated persistence
    """

    def __init__(self, root: Optional[Path] = None, global_store: Optional[Path] = None):
        self.root = Path(root) if root else repo_root()
        self.global_store = Path(global_store) if global_store else None
        self._schemas = None

    @property
    def schemas(self) -> Dict[str, Any]:
        if not hasattr(self, "_schemas") or self._schemas is None:
            self._schemas = load_schemas(repo_root())
        return self._schemas

    def add(
        self,
        project_id: str,
        type: str,
        content: Dict[str, Any],
        author: str,
        scope: str = "project",
        tags: Optional[List[str]] = None,
        confidence: float = 1.0,
        related_memories: Optional[List[str]] = None,
        supersedes: Optional[str] = None,
        source: str = "manual",
        metadata: Optional[Dict[str, Any]] = None,
        topic_key: Optional[str] = None,
        revision_count: int = 0,
        duplicate_count: int = 0,
        last_seen_at: Optional[str] = None,
        review_after: Optional[str] = None,
        state: str = "active",
        dedupe: bool = False,
        ttl_days: Optional[int] = None,
        gc_protected: bool = False,
    ) -> Dict[str, Any]:
        """Create a new memory record.

        Three shapes, chosen by the caller rather than guessed:

        * plain ``add`` appends a new record, always;
        * ``topic_key`` is an explicit upsert key: an existing active record in
          the same project is revised in place and its ``revision_count`` grows;
        * ``dedupe=True`` makes the call idempotent by content: an identical
          ``content`` in the same project and type is treated as the same memory
          and its ``duplicate_count``/``last_seen_at`` are updated instead of
          creating a copy.
        """
        # Validate project exists
        project_dir = self._find_project_dir(project_id)
        if not project_dir:
            raise ValueError(f"Project {project_id} not found")

        # Cross-process lock: prevents concurrent ID generation and
        # silent overwrites on topic_key upserts.
        mem_dir = project_dir / "memories"
        lock_path = project_dir / ".memory.lock"

        with _file_lock(lock_path) as waited:
                # Dedupe: topic_key is an upsert key, not an identity
            existing = None
            if topic_key:
                existing = self._find_by_topic_key(project_id, topic_key)
                if existing:
                    # Revision: update in place, bump counters
                    existing.revision_count += 1
                    existing.content = content
                    existing.tags = tags or existing.tags
                    existing.updated_at = now_utc()
                    existing.last_seen_at = now_utc()
                    self._prepare_for_write(existing)
                    self._write_record(project_dir, existing)
                    return {
                        "memory_id": existing.memory_id,
                        "status": "revised",
                        "revision_count": existing.revision_count,
                        "conflict": waited,
                    }

            # Exact dedupe: same content hash within same project+type. Opt-in, because
            # identical text can still be two genuinely distinct records and `add` must
            # not silently swallow one of them.
            if dedupe:
                content_hash = hashlib.sha256(
                    json.dumps(content, sort_keys=True).encode()
                ).hexdigest()
                for _dir, record in self._iter_records(project_id):
                    if record.type != type:
                        continue
                    if record.state == "deprecated":
                        continue
                    existing_hash = hashlib.sha256(
                        json.dumps(record.content, sort_keys=True).encode()
                    ).hexdigest()
                    if existing_hash == content_hash:
                        record.duplicate_count += 1
                        record.last_seen_at = now_utc()
                        self._prepare_for_write(record)
                        self._write_record(project_dir, record)
                        return {
                            "memory_id": record.memory_id,
                            "status": "deduplicated",
                            "duplicate_count": record.duplicate_count,
                        }

            # Generate ID
            memory_id = self._generate_memory_id(project_id)

            record = MemoryRecord(
                memory_id=memory_id,
                project_id=project_id,
                type=type,
                scope=scope,
                content=content,
                tags=tags or [],
                confidence=confidence,
                created_at=now_utc(),
                updated_at=now_utc(),
                author=author,
                source=source,
                related_memories=related_memories or [],
                supersedes=None,
                superseded_by=None,
                metadata=metadata or {},
                topic_key=topic_key,
                revision_count=revision_count,
                duplicate_count=duplicate_count,
                last_seen_at=last_seen_at,
                review_after=review_after,
                state=state,
                ttl_days=ttl_days,
                gc_protected=gc_protected,
            )

            # Compute expires_at if ttl_days provided
            if ttl_days is not None and ttl_days > 0:
                from datetime import datetime, timedelta
                created_dt = datetime.fromisoformat(record.created_at.replace('Z', '+00:00'))
                expires_dt = created_dt + timedelta(days=ttl_days)
                record.expires_at = expires_dt.isoformat().replace('+00:00', 'Z')

            # Validate and persist atomically (LF, no half-written record).
            self._write_record(project_dir, record)

            return {"memory_id": record.memory_id, "status": "created"}

    def query(
        self,
        project_id: Optional[str] = None,
        types: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        author: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        tags_mode: str = "any",
        state: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Query memories with filters.

        Deprecated records are soft-deleted: they stay on disk and out of the
        results unless ``state="deprecated"`` asks for them by name.
        """
        # The project memory files are the deterministic, auditable source of
        # truth (ADR-0003). The derived search index of ADR-0027 is a separate
        # concern and must not add latency or stderr noise to a plain query.
        memories = self._scan_local_memories(
            project_id, types, tags, author, since, until, tags_mode, state
        )

        # Apply pagination
        total = len(memories)
        memories = memories[offset:offset + limit]

        # Build summary
        by_type = {}
        by_author = {}
        for m in memories:
            by_type[m.type] = by_type.get(m.type, 0) + 1
            by_author[m.author] = by_author.get(m.author, 0) + 1

        return {
            "schema_version": "1",
            "query_id": f"MQR-{random.randint(1000, 9999):04d}",
            "project_id": project_id,
            "queried_at": now_utc(),
            "memories": [m.to_dict() for m in memories],
            "summary": {
                "total": total,
                "by_type": by_type,
                "by_author": by_author,
            },
        }

    def get(self, memory_id: str, project_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get a single memory by ID from the canonical record files.

        Requires a project scope: IDs are project-scoped, so without one the
        lookup is ambiguous and returns ``None`` (use :meth:`query` to list across
        projects).
        """
        _, record = self._load_record(memory_id, project_id)
        if record is None:
            return None
        return record.to_dict()

    def search(
        self,
        text: str,
        project_id: Optional[str] = None,
        types: Optional[List[str]] = None,
        limit: int = 10,
        offset: int = 0,
        include_deprecated: bool = False,
        rerank: Optional[bool] = None,
        candidates: int = 50,
    ) -> Dict[str, Any]:
        """Lexical search over memory records (ADR-0027), optionally reranked.

        Uses the derived FTS5 index when it is available and falls back to a
        pure-Python scan otherwise, so a result never depends on a cache being
        present. Hits are compact: fetch a full record with :meth:`get`.
        Deprecated (soft-deleted) records stay out unless asked for.

        ``rerank`` selects the optional local embedding reranker: ``None`` uses
        one if a model is installed, ``True`` demands one and fails without it,
        ``False`` disables it. The reranker only reorders a candidate window of
        ``candidates`` lexical hits, so it can never add or lose a hit, and the
        window is what bounds its cost.
        """
        terms = tokenize(text)
        if not terms:
            raise ValueError("search requires at least one searchable term")

        reranker, reranker_reason = self._semantic_reranker(rerank)

        index = MemoryIndex(self.root)
        revisions, paths = self._index_scope(project_id)

        # With a reranker the whole window must be fetched in one page, because
        # the order is only known after reranking; without one the backend keeps
        # doing the paging exactly as before, so nothing changes when it is off.
        window = max(limit + offset, candidates) if reranker else limit + offset
        fetch_offset = 0 if reranker else offset
        texts: Optional[Dict[Tuple[str, str], str]] = {} if reranker else None

        hits = self._indexed_search(
            index,
            revisions,
            paths,
            text,
            project_id,
            types,
            window,
            fetch_offset,
            include_deprecated,
            texts,
        )
        backend = "fts5"
        if hits is None:
            hits = self._lexical_search(
                text,
                project_id,
                types,
                window,
                fetch_offset,
                include_deprecated,
                texts,
            )
            backend = "scan"

        if reranker is not None:
            hits = reranker.rerank(text, hits, texts or {})
            hits = hits[offset:offset + limit]

        by_type: Dict[str, int] = {}
        for hit in hits:
            by_type[hit["type"]] = by_type.get(hit["type"], 0) + 1

        return {
            "schema_version": "1",
            "query_id": f"MQS-{random.randint(1000, 9999):04d}",
            "query": text,
            "project_id": project_id,
            "searched_at": now_utc(),
            "backend": backend,
            "index": {
                "available": index.available,
                "path": str(index.path),
                "used": backend == "fts5",
            },
            "reranker": {
                "used": reranker is not None,
                "model": str(reranker.space.source) if reranker is not None else None,
                "backend": reranker.space.backend if reranker is not None else None,
                "candidates": window if reranker is not None else 0,
                "reason": reranker_reason,
            },
            "limit": limit,
            "offset": offset,
            "hits": hits,
            "summary": {"returned": len(hits), "by_type": by_type},
        }

    def _semantic_reranker(
        self, rerank: Optional[bool]
    ) -> Tuple[Optional["SemanticReranker"], Optional[str]]:
        """Resolve the optional reranker, returning it and a reason when absent.

        ``None`` asks for the best available: an installed model is used and its
        absence is not an error. ``True`` is a demand and fails loudly, because
        answering with a different ranking than the one that was asked for would
        be worse than refusing to answer.
        """
        if rerank is False:
            return None, "semantic reranking disabled by the caller"
        try:
            reranker = SemanticReranker.from_root(self.root)
        except EmbeddingError as exc:
            if rerank is True:
                raise ValueError(str(exc))
            return None, str(exc)
        if reranker is None:
            reason = (
                f"no embedding model at {MODEL_RELATIVE_PATH} "
                f"(set {MODEL_ENV_VAR} to point at one)"
            )
            if rerank is True:
                raise ValueError(f"semantic reranking requested but {reason}")
            return None, reason
        return reranker, None

    def _indexed_search(
        self,
        index: "MemoryIndex",
        revisions: Dict[Tuple[str, str], str],
        paths: Dict[Tuple[str, str], Path],
        text: str,
        project_id: Optional[str],
        types: Optional[List[str]],
        limit: int,
        offset: int,
        include_deprecated: bool = False,
        texts: Optional[Dict[Tuple[str, str], str]] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        """Search through the derived index, or ``None`` to fall back to a scan.

        The index is a cache, so an unusable file is discarded and rebuilt once
        before giving up: losing the index must never lose a result. When
        ``texts`` is given it is filled with each hit's indexed text, so a
        reranker can score candidates without reading a single record file.
        """
        if not index.available:
            return None

        load = self._entry_loader(revisions, paths)
        for attempt in (0, 1):
            try:
                index.sync(revisions, load)
                hits = index.search(
                    text,
                    project_id=project_id,
                    types=types,
                    limit=limit,
                    offset=offset,
                    include_deprecated=include_deprecated,
                )
                if texts is not None:
                    texts.update(
                        index.text_map(
                            (hit["project_id"], hit["memory_id"]) for hit in hits
                        )
                    )
                return hits
            except INDEX_ERRORS:
                if attempt == 1:
                    return None
                index.drop()
        return None

    def _lexical_search(
        self,
        text: str,
        project_id: Optional[str],
        types: Optional[List[str]],
        limit: int,
        offset: int,
        include_deprecated: bool = False,
        texts: Optional[Dict[Tuple[str, str], str]] = None,
    ) -> List[Dict[str, Any]]:
        """Pure-Python fallback, used when FTS5 is missing or the index fails.

        Scores by term frequency and requires every query term to be present,
        mirroring the index's AND semantics so callers see one contract whichever
        backend answered. ``texts`` is filled from the haystack this scan already
        built, so a reranker costs no extra parsing here either.
        """
        terms = tokenize(text)
        ranked: List[Tuple[float, str, str, Any, str]] = []

        for _project_dir, record in self._iter_records(project_id):
            if types and record.type not in types:
                continue
            if not include_deprecated and record.state == "deprecated":
                continue
            haystack = flatten_content(record.content) + " " + " ".join(record.tags)
            counts = Counter(tokenize(haystack))
            if not all(term in counts for term in terms):
                continue
            score = float(sum(counts[term] for term in terms))
            ranked.append((score, record.created_at, record.memory_id, record, haystack))

        # Stable sorts applied least-significant first: score desc, then newest
        # first, then id, so the order is total and reproducible.
        ranked.sort(key=lambda item: item[2])
        ranked.sort(key=lambda item: item[1], reverse=True)
        ranked.sort(key=lambda item: item[0], reverse=True)

        hits: List[Dict[str, Any]] = []
        for score, _created_at, _memory_id, record, haystack in ranked[
            offset:offset + limit
        ]:
            if texts is not None:
                texts[(record.project_id, record.memory_id)] = haystack
            hits.append(
                {
                    "memory_id": record.memory_id,
                    "project_id": record.project_id,
                    "type": record.type,
                    "created_at": record.created_at,
                    "state": record.state,
                    "tags": list(record.tags),
                    "score": round(score, 6),
                    "snippet": self._snippet(haystack, terms),
                }
            )
        return hits

    @staticmethod
    def _fold_with_offsets(text: str) -> Tuple[str, List[int]]:
        """The tokenizer's view of ``text`` plus each folded char's origin.

        ``offsets[i]`` is the index in ``text`` of the character that produced
        folded character ``i``, so a match found on folded text can be
        highlighted in the original spelling (``decision`` -> ``decisión``).
        """
        chars: List[str] = []
        offsets: List[int] = []
        for position, char in enumerate(text):
            for folded in unicodedata.normalize("NFD", char).lower():
                if unicodedata.combining(folded):
                    continue
                chars.append(folded)
                offsets.append(position)
        return "".join(chars), offsets

    @staticmethod
    def _snippet(text: str, terms: List[str], width: int = 90) -> str:
        """A short highlighted window around the first matching term.

        Mirrors the shape of FTS5 ``snippet()`` (``[match]``, ``…`` at the cut)
        so a caller cannot tell which backend produced it. Matching uses the
        same folded terms as the search, so an unaccented query brackets the
        accented word it matched rather than returning a window with no mark.
        """
        if not text:
            return ""
        folded, offsets = MemoryEngine._fold_with_offsets(text)
        found = [
            position
            for position in (folded.find(term) for term in terms)
            if position >= 0
        ]
        start = max(0, offsets[min(found)] - width // 3) if found else 0
        window = text[start:start + width].strip()

        if window:
            folded_window, window_offsets = MemoryEngine._fold_with_offsets(window)
            spans: List[Tuple[int, int]] = []
            for term in terms:
                position = folded_window.find(term)
                while position >= 0:
                    spans.append(
                        (
                            window_offsets[position],
                            window_offsets[position + len(term) - 1] + 1,
                        )
                    )
                    position = folded_window.find(term, position + len(term))
            merged: List[Tuple[int, int]] = []
            for span in sorted(spans):
                if merged and span[0] <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(merged[-1][1], span[1]))
                else:
                    merged.append(span)
            for span_start, span_end in reversed(merged):
                window = (
                    window[:span_start]
                    + "["
                    + window[span_start:span_end]
                    + "]"
                    + window[span_end:]
                )

        if start > 0:
            window = "…" + window
        if start + width < len(text):
            window = window + " …"
        return window

    # Relations: symmetric verbs are written on both records; directional verbs
    # are the two inverse views of one edge and delegate to `supersede`, so the
    # `supersedes` / `superseded_by` pair can never disagree.
    SYMMETRIC_RELATIONS = ("related", "compatible")
    DIRECTIONAL_RELATIONS = ("supersedes", "superseded_by")

    def link(
        self,
        memory_id: str,
        related_memory_id: str,
        relation: str = "related",
        project_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record a relation between two existing memories and persist it.

        Symmetric relations are written on both records so a lookup from either
        side sees the link. The directional verbs delegate to ``supersede`` so the
        inverse fields can never drift apart. An unknown verb is rejected instead
        of being stored as if it meant something.
        """
        if memory_id == related_memory_id:
            raise ValueError("a memory cannot be linked to itself")

        if relation in self.DIRECTIONAL_RELATIONS:
            if relation == "supersedes":
                return self.supersede(related_memory_id, memory_id, project_id=project_id)
            return self.supersede(memory_id, related_memory_id, project_id=project_id)

        if relation not in self.SYMMETRIC_RELATIONS:
            raise ValueError(
                f"unsupported relation {relation!r}; expected one of "
                f"{self.SYMMETRIC_RELATIONS + self.DIRECTIONAL_RELATIONS}"
            )

        left_dir, left = self._require_record(memory_id, project_id)
        right_dir, right = self._require_record(related_memory_id, project_id)

        for directory, record, other in (
            (left_dir, left, right),
            (right_dir, right, left),
        ):
            related = list(record.related_memories)
            if other.memory_id not in related:
                related.append(other.memory_id)
            record.related_memories = sorted(related)
            self._prepare_for_write(record)
            self._write_record(directory, record)

        return {
            "status": "linked",
            "memory_id": memory_id,
            "related_to": related_memory_id,
            "relation": relation,
        }

    def update(
        self,
        memory_id: str,
        project_id: str,
        updates: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Apply a partial update to a memory record and persist it.

        Identity fields are rejected rather than ignored: a caller trying to
        rewrite ``memory_id`` or ``created_at`` has a bug that must surface.
        """
        immutable = {"memory_id", "project_id", "created_at", "schema_version"}
        rejected = sorted(set(updates) & immutable)
        if rejected:
            raise ValueError(f"cannot update immutable field(s): {', '.join(rejected)}")

        project_dir, record = self._require_record(memory_id, project_id)
        for key, value in updates.items():
            if not hasattr(record, key):
                raise ValueError(f"unknown memory field: {key}")
            setattr(record, key, value)

        self._prepare_for_write(record)
        self._write_record(project_dir, record)
        return {"status": "updated", "memory_id": memory_id}

    def supersede(
        self,
        old_memory_id: str,
        new_memory_id: str,
        project_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Mark ``old_memory_id`` as superseded by ``new_memory_id``.

        Both records are written so the inverse fields stay consistent. A memory
        cannot supersede itself, and a replacement that is itself already
        superseded would create a chain this model does not describe.
        """
        if old_memory_id == new_memory_id:
            raise ValueError("a memory cannot supersede itself")

        old_dir, old = self._require_record(old_memory_id, project_id)
        new_dir, new = self._require_record(new_memory_id, project_id)

        if new.superseded_by:
            raise ValueError(
                f"memory {new_memory_id} is already superseded by {new.superseded_by}"
            )
        if old.superseded_by and old.superseded_by != new_memory_id:
            raise ValueError(
                f"memory {old_memory_id} is already superseded by {old.superseded_by}"
            )

        old.superseded_by = new_memory_id
        new.supersedes = old_memory_id
        self._prepare_for_write(old)
        self._prepare_for_write(new)
        self._write_record(old_dir, old)
        self._write_record(new_dir, new)

        return {"status": "superseded", "old": old_memory_id, "new": new_memory_id}

    def _find_project_dir(self, project_id: str) -> Optional[Path]:
        """Find project directory by project_id under this engine's root."""
        for p in (self.root / "PROJECTS").glob("*"):
            if (p / "PROJECT.json").exists():
                manifest = read_manifest(p)
                if manifest.get("project_id") == project_id:
                    return p
        if self.global_store is not None and (self.global_store / "PROJECT.json").exists():
            manifest = read_manifest(self.global_store)
            if manifest.get("project_id") == project_id:
                return self.global_store
        return None

    def _find_by_topic_key(self, project_id: str, topic_key: str) -> Optional["MemoryRecord"]:
        """Find the most recent active record with the given topic_key in a project."""
        project_dir = self._find_project_dir(project_id)
        if not project_dir:
            return None
        matches = []
        for _dir, record in self._iter_records(project_id):
            if record.topic_key == topic_key and record.state != "deprecated":
                matches.append(record)
        if not matches:
            return None
        matches.sort(key=lambda r: r.updated_at, reverse=True)
        return matches[0]

    def _generate_memory_id(self, project_id: str) -> str:
        """Generate MEM-XXXX ID."""
        project_dir = self._find_project_dir(project_id)
        if not project_dir:
            # Cross-project, use global counter
            return f"MEM-{random.randint(1000, 9999):04d}"

        # Find existing memories in project
        mem_dir = project_dir / "memories"
        if not mem_dir.exists():
            return f"MEM-{1:04d}"

        highest = 0
        for f in mem_dir.glob("*.json"):
            try:
                num = int(f.stem.split("-")[1])
                highest = max(highest, num)
            except (IndexError, ValueError):
                pass

        # Find next free slot (handles concurrent writes)
        candidate = highest + 1
        while (mem_dir / f"MEM-{candidate:04d}.json").exists():
            candidate += 1
        return f"MEM-{candidate:04d}"

    def _record_path(self, project_dir: Path, memory_id: str) -> Path:
        """Canonical on-disk location of a memory record (ADR-0003)."""
        return Path(project_dir) / "memories" / f"{memory_id}.json"

    def _read_record(self, path: Path) -> "MemoryRecord":
        return MemoryRecord.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def _write_record(self, project_dir: Path, record: "MemoryRecord") -> None:
        """Validate and persist a record atomically (LF, no half-written file)."""
        errors = validate(record.to_dict(), self._get_schema("memory_record"))
        if errors:
            raise ValueError(f"Memory validation failed: {errors}")
        write_json_atomic(self._record_path(project_dir, record.memory_id), record.to_dict())

    @staticmethod
    def _prepare_for_write(record: "MemoryRecord") -> None:
        """Stamp timestamps before a write; identity fields are never touched."""
        now = now_utc()
        if not record.created_at:
            record.created_at = now
        record.updated_at = now

    def _load_record(self, memory_id: str, project_id: Optional[str] = None):
        """Return ``(project_dir, record)`` for an existing memory, or ``(None, None)``.

        Memory IDs are project-scoped (``MEM-0001`` exists in more than one
        project), so a lookup without a project scope is ambiguous. It resolves to
        nothing instead of guessing a project and reading — or worse, writing — the
        wrong record.
        """
        if not project_id:
            return None, None
        project_dir = self._find_project_dir(project_id)
        if project_dir is None:
            return None, None
        path = self._record_path(project_dir, memory_id)
        if path.exists():
            return project_dir, self._read_record(path)
        return None, None

    def _require_record(self, memory_id: str, project_id: Optional[str] = None):
        """Resolve a record for writing; an unambiguous project scope is required."""
        if not project_id:
            raise ValueError(f"project scope is required to resolve memory {memory_id}")
        project_dir, record = self._load_record(memory_id, project_id)
        if record is None:
            raise ValueError(f"memory {memory_id} not found")
        return project_dir, record

    def _project_dirs(self, project_id: Optional[str] = None) -> List[Path]:
        """Project directories in scope for this engine root.

        A project ID resolves to at most one directory; without one, every
        discoverable project is in scope (the cross-project listing path).
        """
        if project_id:
            found = self._find_project_dir(project_id)
            return [found] if found else []
        dirs = sorted(
            p for p in (self.root / "PROJECTS").glob("*")
            if (p / "PROJECT.json").exists()
        )
        if self.global_store is not None and (self.global_store / "PROJECT.json").exists():
            dirs = dirs + [self.global_store]
        return dirs

    @staticmethod
    def _project_id_of(project_dir: Path) -> Optional[str]:
        """The project_id a directory belongs to, taken from its manifest."""
        return read_manifest(project_dir).get("project_id")

    @staticmethod
    def _file_revision(path: Path) -> str:
        """A cheap revision marker: ``stat`` only, never the file contents."""
        st = Path(path).stat()
        return f"{st.st_mtime_ns}:{st.st_size}"

    def _iter_records(self, project_id: Optional[str] = None):
        """Yield ``(project_dir, record)`` for every readable record in scope.

        A malformed file is skipped rather than fatal: one bad record must not
        hide every other record.
        """
        for project_dir in self._project_dirs(project_id):
            mem_dir = project_dir / "memories"
            if not mem_dir.exists():
                continue
            for mem_file in sorted(mem_dir.glob("*.json")):
                try:
                    record = MemoryRecord.from_dict(
                        json.loads(mem_file.read_text(encoding="utf-8"))
                    )
                except Exception as exc:
                    import sys as _sys
                    print(
                        f"WARN: skipped corrupt memory file {mem_file}: {exc}",
                        file=_sys.stderr,
                    )
                    continue
                yield project_dir, record

    def _scan_local_memories(
        self,
        project_id: Optional[str],
        types: Optional[List[str]],
        tags: Optional[List[str]],
        author: Optional[str],
        since: Optional[str],
        until: Optional[str],
        tags_mode: str,
        state: Optional[str] = None,
    ) -> List:
        """Scan local memory files with filters."""
        memories = []

        for _project_dir, record in self._iter_records(project_id):
            if types and record.type not in types:
                continue
            if state:
                if record.state != state:
                    continue
            elif record.state == "deprecated":
                continue
            if author and record.author != author:
                continue
            if tags:
                record_tags = set(record.tags)
                filter_tags = set(tags)
                if tags_mode == "all" and not filter_tags.issubset(record_tags):
                    continue
                if tags_mode == "any" and not filter_tags.intersection(record_tags):
                    continue
            if since and record.created_at < since:
                continue
            if until and record.created_at > until:
                continue

            memories.append(record)

        # Sort by created_at descending
        memories.sort(key=lambda m: m.created_at, reverse=True)
        return memories

    # -- derived search index (ADR-0027) -----------------------------------

    def _index_scope(
        self, project_id: Optional[str] = None
    ) -> Tuple[Dict[Tuple[str, str], str], Dict[Tuple[str, str], Path]]:
        """Inventory of indexable records: ``(revisions, paths)`` by identity.

        Both maps come from directory listings and ``stat`` calls alone, so
        deciding whether the index is current never parses a record.
        """
        revisions: Dict[Tuple[str, str], str] = {}
        paths: Dict[Tuple[str, str], Path] = {}

        for project_dir in self._project_dirs(project_id):
            mem_dir = project_dir / "memories"
            if not mem_dir.exists():
                continue
            pid = self._project_id_of(project_dir)
            if not pid:
                continue
            for mem_file in sorted(mem_dir.glob("*.json")):
                key = (pid, mem_file.stem)
                try:
                    revisions[key] = self._file_revision(mem_file)
                except OSError:
                    continue
                paths[key] = mem_file

        return revisions, paths

    def _index_entry(
        self, project_id: str, path: Path, revision: str
    ) -> Optional[IndexEntry]:
        """Build an index entry from one record file, or ``None`` if unreadable."""
        try:
            record = MemoryRecord.from_dict(
                json.loads(Path(path).read_text(encoding="utf-8"))
            )
        except Exception:
            return None
        return IndexEntry.from_record(record, revision, project_id=project_id)

    def _entry_loader(
        self,
        revisions: Dict[Tuple[str, str], str],
        paths: Dict[Tuple[str, str], Path],
    ):
        """A ``load(project_id, memory_id)`` callable for :meth:`MemoryIndex.sync`."""

        def load(project_id: str, memory_id: str) -> Optional[IndexEntry]:
            key = (project_id, memory_id)
            path = paths.get(key)
            revision = revisions.get(key)
            if path is None or revision is None:
                return None
            return self._index_entry(project_id, path, revision)

        return load

    def index_stats(self) -> Dict[str, Any]:
        """State of the derived search index (never reads a record)."""
        return MemoryIndex(self.root).stats()

    def refresh_index(self, rebuild: bool = False) -> Dict[str, Any]:
        """Bring the derived index up to date, or rebuild it from scratch.

        The index is disposable, so ``rebuild`` simply deletes it first; that is
        also the remedy for any doubt about its contents.
        """
        index = MemoryIndex(self.root)
        if not index.available:
            return {
                "status": "unavailable",
                "reason": "SQLite FTS5 is not available; searches fall back to a scan",
                "path": str(index.path),
                "dropped": False,
                "inserted": 0,
                "updated": 0,
                "deleted": 0,
                "total": 0,
            }

        revisions, paths = self._index_scope()
        dropped = index.drop() if rebuild else False
        report = index.sync(revisions, self._entry_loader(revisions, paths))

        return {
            "status": "rebuilt" if rebuild else "synced",
            "path": str(index.path),
            "dropped": dropped,
            **report,
        }

    def gc(
        self,
        project_id: Optional[str] = None,
        older_than_days: Optional[int] = None,
        tag_filter: Optional[List[str]] = None,
        state_filter: Optional[List[str]] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Garbage collect expired/eligible memories.

        A memory is eligible for GC if:
        - It has `expires_at` in the past (ttl_days expired), OR
        - It matches `older_than_days` from created_at, OR
        - It matches `tag_filter` (all tags must match), AND
        - It is NOT `gc_protected`, AND
        - It is NOT in a protected state (active by default unless state_filter overrides)

        Args:
            project_id: Specific project, or None for all projects
            older_than_days: Consider memories older than this many days from created_at
            tag_filter: Only consider memories with ALL these tags
            state_filter: Only consider memories in these states (default: ["archived", "deprecated"])
            dry_run: If True, only report what would be deleted

        Returns:
            Dict with deleted_count, deleted_ids, skipped_protected, scanned_count
        """
        from datetime import datetime, timezone

        # Determine projects to scan
        if project_id:
            projects = [project_id]
        else:
            # Scan all projects under repo_root
            projects = []
            for p in (self.root / "PROJECTS").iterdir():
                if p.is_dir() and (p / "PROJECT.json").exists():
                    projects.append(p.name)

        deleted_count = 0
        deleted_ids = []
        skipped_protected = 0
        scanned_count = 0
        now = datetime.now(timezone.utc)

        for pid in projects:
            try:
                project_dir = self._find_project_dir(pid)
                if not project_dir:
                    continue
            except Exception:
                continue

            mem_dir = project_dir / "memories"
            if not mem_dir.exists():
                continue

            for mem_file in mem_dir.glob("*.json"):
                scanned_count += 1
                try:
                    # Extract memory_id from filename (MEM-XXXX.json -> MEM-XXXX)
                    memory_id = mem_file.stem
                    project_dir, record = self._load_record(memory_id, pid)
                    if not record:
                        continue

                    # Check gc_protected
                    if record.gc_protected:
                        skipped_protected += 1
                        continue

                    # Check state filter
                    target_states = state_filter or ["archived", "deprecated"]
                    if record.state not in target_states:
                        continue

                    # Check tag filter
                    if tag_filter:
                        if not all(tag in record.tags for tag in tag_filter):
                            continue

                    # Check expiration
                    should_delete = False
                    if record.expires_at:
                        try:
                            expires_dt = datetime.fromisoformat(record.expires_at.replace('Z', '+00:00'))
                            if expires_dt < now:
                                should_delete = True
                        except Exception:
                            pass

                    if older_than_days and not should_delete:
                        try:
                            created_dt = datetime.fromisoformat(record.created_at.replace('Z', '+00:00'))
                            if (now - created_dt).days > older_than_days:
                                should_delete = True
                        except Exception:
                            pass

                    if should_delete:
                        deleted_count += 1
                        deleted_ids.append(record.memory_id)
                        if not dry_run:
                            mem_file.unlink()
                            # Also remove from index if available
                            try:
                                index = MemoryIndex(self.root)
                                if index.available:
                                    index.delete(record.memory_id)
                            except Exception:
                                pass
                except Exception:
                    # Skip corrupt records
                    continue

        return {
            "deleted_count": deleted_count,
            "deleted_ids": deleted_ids,
            "skipped_protected": skipped_protected,
            "scanned_count": scanned_count,
            "dry_run": dry_run,
        }

    def _get_schema(self, name: str) -> Dict[str, Any]:
        """Get schema by name."""
        schemas = load_schemas(repo_root())
        return schemas.get(name, {})
