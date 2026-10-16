"""Derived, rebuildable lexical index for SYSTEM-ENGINEERING memory (ADR-0027).

The canonical records are the JSON files under ``<project>/memories/`` (ADR-0003).
This module builds a disposable SQLite+FTS5 index over them so lexical retrieval
does not have to parse every JSON file on every query.

The design rules below are load-bearing:

* The index is **never** a source of truth. It can be deleted at any moment and
  rebuilt from the JSON; a missing or corrupt file is a rebuild, not data loss.
* The index is **optional**. When FTS5 is unavailable the engine falls back to a
  pure-Python scan, so the reference implementation keeps working on a bare
  Python without any extension.
* Staying current is **cheap**. The caller supplies an inventory of
  ``(project_id, memory_id) -> stat-based revision`` built from ``stat`` calls
  alone, plus a ``load`` callable. Only entries that are new or whose revision
  changed are ever parsed, so refresh cost is O(files) metadata calls instead of
  O(bytes) of JSON parsing.
* Search returns **compact hits** (id, type, score, snippet); full content is a
  separate lookup by id, so an agent can scan results before paying for bodies.

This module deliberately does not import the engine: the engine owns record
discovery and hands this module plain :class:`IndexEntry` values.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

INDEX_RELATIVE_PATH = Path(".se") / "memory" / "index.db"
# Bump whenever the stored columns change: the derived file is disposable, so a
# version mismatch is resolved by discarding it and reindexing, never by mixing
# two formats in one database.
INDEX_SCHEMA_VERSION = "2"

# Errors that mean "this derived file is unusable" rather than "the caller is
# wrong". The engine catches exactly these to fall back to a plain scan.
INDEX_ERRORS: Tuple[type, ...] = (sqlite3.Error,)

# Columns of the FTS5 table, in declaration order. Unindexed columns come first
# (FTS5 stores indexed columns separately, and keeping them last keeps rows
# small) and the searchable columns are last, so their indices are stable.
_FTS_UNINDEXED = (
    "project_id",
    "memory_id",
    "type",
    "scope",
    "author",
    "created_at",
    "updated_at",
    "confidence",
    "revision",
    "state",
    "tags_raw",
)
_FTS_INDEXED = ("tags", "content_text")
FTS_COLUMNS = _FTS_UNINDEXED + _FTS_INDEXED
CONTENT_COLUMN_INDEX = FTS_COLUMNS.index("content_text")

_TOKEN_RE = re.compile(r"[0-9a-z_]+")


def tokenize(text: Any) -> List[str]:
    """Lowercase alphanumeric terms; the single definition shared by both backends.

    The FTS5 query and the Python fallback must agree on what a term is, or the
    same search would answer differently depending on which backend ran.
    """
    if text is None:
        return []
    return _TOKEN_RE.findall(str(text).lower())


def flatten_content(content: Any) -> str:
    """Flatten a record's content into searchable text, deterministically.

    Values are kept, dict keys are not: keys such as ``title`` or ``reason`` are
    structural, while the text under them is what a query looks for. Dict keys
    are visited in sorted order so two runs produce identical text, which is what
    makes a rebuild reproducible.
    """
    parts: List[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, bool):
            parts.append(str(value))
        elif isinstance(value, str):
            parts.append(value)
        elif isinstance(value, (int, float)):
            parts.append(str(value))
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            for key in sorted(value):
                walk(value[key])

    walk(content)
    return " ".join(part for part in parts if part)


def fts5_available() -> bool:
    """Whether this interpreter's SQLite can build an FTS5 table."""
    try:
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute("CREATE VIRTUAL TABLE fts5_probe USING fts5(x)")
            return True
        finally:
            conn.close()
    except sqlite3.Error:
        return False


@dataclass(frozen=True)
class IndexEntry:
    """One canonical record, reduced to the fields the index stores."""

    project_id: str
    memory_id: str
    type: str
    scope: str
    author: str
    created_at: str
    updated_at: str
    confidence: float
    tags: List[str] = field(default_factory=list)
    content_text: str = ""
    revision: str = ""
    state: str = "active"

    @classmethod
    def from_record(
        cls,
        record: Any,
        revision: str,
        project_id: Optional[str] = None,
    ) -> "IndexEntry":
        """Reduce a ``MemoryRecord`` to an index entry.

        ``project_id`` defaults to the record's own field but can be overridden
        with the scope derived from the project directory: the record's location
        is what makes an ID unique, so indexing follows the location.
        """
        return cls(
            project_id=project_id or record.project_id,
            memory_id=record.memory_id,
            type=record.type,
            scope=getattr(record, "scope", "project"),
            author=record.author,
            created_at=record.created_at,
            updated_at=record.updated_at,
            confidence=float(record.confidence),
            tags=[str(tag) for tag in (record.tags or [])],
            content_text=flatten_content(record.content),
            revision=revision,
            state=getattr(record, "state", "active"),
        )


class MemoryIndex:
    """SQLite+FTS5 index over canonical memory records.

    Every method is safe to call when FTS5 is missing: :attr:`available` reports
    it and callers fall back. A corrupt database file is treated as "rebuild",
    never as an error the caller has to understand.
    """

    def __init__(self, root: Path):
        self.root = Path(root)
        self.path = self.root / INDEX_RELATIVE_PATH
        self._fts5 = fts5_available()

    # -- capability ---------------------------------------------------------

    @property
    def available(self) -> bool:
        """Whether an FTS5-backed index can be used at all."""
        return self._fts5

    @property
    def exists(self) -> bool:
        return self.path.exists()

    # -- connection / schema ------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """Open the index database, never leaking a handle on failure.

        If touching a damaged file fails during setup, the connection is closed
        before the error propagates: on Windows an open handle keeps the file
        locked, which would turn one bad file into an undroppable one.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.Error:
            conn.close()
            raise
        return conn

    def _create_schema(self, conn: sqlite3.Connection) -> None:
        if not self._fts5:
            raise sqlite3.OperationalError("FTS5 is not available")
        conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")

        # A format change invalidates the file rather than mixing two layouts.
        stamp = conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()
        if stamp is not None and stamp["value"] != INDEX_SCHEMA_VERSION:
            conn.execute("DROP TABLE IF EXISTS records_fts")
            conn.execute("DELETE FROM meta WHERE key='schema_version'")

        columns = ", ".join(
            column if column in _FTS_INDEXED else f"{column} UNINDEXED"
            for column in FTS_COLUMNS
        )
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS records_fts USING fts5({columns})"
        )
        conn.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)",
            (INDEX_SCHEMA_VERSION,),
        )

    # -- lifecycle ----------------------------------------------------------

    def drop(self) -> bool:
        """Delete the index file. Returns whether something was removed."""
        removed = False
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(self.path) + suffix)
            if candidate.exists():
                candidate.unlink()
                removed = True
        return removed

    def sync(
        self,
        inventory: Mapping[Tuple[str, str], str],
        load: Callable[[str, str], Optional[IndexEntry]],
    ) -> Dict[str, int]:
        """Reconcile the index with an inventory of canonical records.

        ``inventory`` maps ``(project_id, memory_id)`` to a revision and is the
        complete set of records that should be indexed; anything absent is
        deleted, anything with a different revision is reindexed. ``load`` is
        only called for those records, so unchanged files are never read.

        Returns ``{"inserted", "updated", "deleted", "total"}``.
        """
        if not self._fts5:
            return {"inserted": 0, "updated": 0, "deleted": 0, "total": 0}

        conn = self._connect()
        try:
            self._create_schema(conn)
            stored = {
                (row["project_id"], row["memory_id"]): row["revision"]
                for row in conn.execute(
                    "SELECT project_id, memory_id, revision FROM records_fts"
                )
            }

            removed = sorted(key for key in stored if key not in inventory)
            changed = sorted(
                key
                for key, revision in inventory.items()
                if stored.get(key) != revision
            )

            # A changed record is removed and rewritten; a removed one is gone.
            for key in removed:
                conn.execute(
                    "DELETE FROM records_fts WHERE project_id=? AND memory_id=?", key
                )

            inserted = updated = 0
            for key in changed:
                entry = load(*key)
                if entry is None:
                    # Unreadable or vanished mid-scan: never leave a stale row,
                    # and only report a deletion if a row was actually there.
                    if key in stored:
                        conn.execute(
                            "DELETE FROM records_fts WHERE project_id=? AND memory_id=?",
                            key,
                        )
                        removed.append(key)
                    continue
                if key in stored:
                    conn.execute(
                        "DELETE FROM records_fts WHERE project_id=? AND memory_id=?", key
                    )
                conn.execute(
                    "INSERT INTO records_fts ("
                    + ", ".join(FTS_COLUMNS)
                    + ") VALUES ("
                    + ", ".join("?" * len(FTS_COLUMNS))
                    + ")",
                    self._row(entry),
                )
                if key in stored:
                    updated += 1
                else:
                    inserted += 1

            total = int(conn.execute("SELECT COUNT(*) FROM records_fts").fetchone()[0])
            conn.execute(
                "INSERT INTO meta(key, value) VALUES('built_at', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (self._stamp(),),
            )
            conn.commit()
        finally:
            conn.close()

        return {
            "inserted": inserted,
            "updated": updated,
            "deleted": len(removed),
            "total": total,
        }

    @staticmethod
    def _row(entry: IndexEntry) -> tuple:
        return (
            entry.project_id,
            entry.memory_id,
            entry.type,
            entry.scope,
            entry.author,
            entry.created_at,
            entry.updated_at,
            entry.confidence,
            entry.revision,
            entry.state,
            json.dumps(entry.tags, ensure_ascii=False),
            " ".join(entry.tags),
            entry.content_text,
        )

    @staticmethod
    def _stamp() -> str:
        from ..paths import now_utc

        return now_utc()

    # -- read paths ---------------------------------------------------------

    def search(
        self,
        text: str,
        project_id: Optional[str] = None,
        types: Optional[Sequence[str]] = None,
        limit: int = 10,
        offset: int = 0,
        include_deprecated: bool = False,
    ) -> List[Dict[str, Any]]:
        """Lexical search returning compact hits, best match first.

        Every query term must be present (AND), which keeps snippets and ranking
        precise for the short queries an agent actually asks. ``bm25`` is
        negative (lower is better); it is negated here so a larger ``score``
        always means a better match. Scores are relative to the backend that
        answered, so compare them within one result set, never across backends.

        Deprecated records are soft-deleted and stay out of the results unless
        they are asked for explicitly.
        """
        terms = tokenize(text)
        if not terms:
            return []

        match = " AND ".join('"' + term + '"' for term in terms)
        sql = (
            "SELECT project_id, memory_id, type, created_at, tags_raw, state, "
            "bm25(records_fts) AS rank, "
            f"snippet(records_fts, {CONTENT_COLUMN_INDEX}, '[', ']', ' … ', 14) "
            "AS snippet "
            "FROM records_fts WHERE records_fts MATCH ?"
        )
        params: List[Any] = [match]
        if project_id:
            sql += " AND project_id = ?"
            params.append(project_id)
        if types:
            sql += " AND type IN (" + ",".join("?" * len(types)) + ")"
            params.extend(types)
        if not include_deprecated:
            sql += " AND state != 'deprecated'"
        sql += " ORDER BY rank, created_at DESC, memory_id LIMIT ? OFFSET ?"
        params.extend([max(int(limit), 0), max(int(offset), 0)])

        conn = self._connect()
        try:
            self._create_schema(conn)
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()

        return [
            {
                "memory_id": row["memory_id"],
                "project_id": row["project_id"],
                "type": row["type"],
                "created_at": row["created_at"],
                "state": row["state"],
                "tags": json.loads(row["tags_raw"] or "[]"),
                "score": -float(row["rank"]),
                "snippet": row["snippet"],
            }
            for row in rows
        ]

    def stats(self) -> Dict[str, Any]:
        """Index inventory: availability, location, size and per-project counts."""
        report: Dict[str, Any] = {
            "available": self._fts5,
            "path": str(self.path),
            "exists": self.path.exists(),
            "entries": 0,
            "by_project": {},
            "by_type": {},
            "built_at": None,
            "schema_version": None,
        }
        if not self._fts5 or not self.path.exists():
            return report

        conn = self._connect()
        try:
            self._create_schema(conn)
            report["entries"] = int(
                conn.execute("SELECT COUNT(*) FROM records_fts").fetchone()[0]
            )
            for row in conn.execute(
                "SELECT project_id, COUNT(*) AS n FROM records_fts GROUP BY project_id"
            ):
                report["by_project"][row["project_id"]] = int(row["n"])
            for row in conn.execute(
                "SELECT type, COUNT(*) AS n FROM records_fts GROUP BY type"
            ):
                report["by_type"][row["type"]] = int(row["n"])
            meta = {
                row["key"]: row["value"]
                for row in conn.execute("SELECT key, value FROM meta")
            }
            report["built_at"] = meta.get("built_at")
            report["schema_version"] = meta.get("schema_version")
        finally:
            conn.close()
        return report
