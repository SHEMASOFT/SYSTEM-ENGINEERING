"""State persistence layer for HARs and project state.

Provides an abstract StateStore interface with SQLite (default) and
PostgreSQL (future) implementations. The state is the source of truth;
the conversation is not authority.

The store lives per-project at ``<project>/.se/state.db`` so a project is
self-contained and portable. The backend is chosen with the
``SE_STATE_BACKEND`` environment variable (``sqlite`` by default).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import os
import sqlite3


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StateStore(ABC):
    """Abstract state store for HARs and project state.

    The state is the source of truth; the conversation is not authority.
    All implementations must provide durable, ACID-compliant persistence.
    """

    @abstractmethod
    def save_har(self, har: dict[str, Any]) -> None:
        """Save or update a HAR."""
        ...

    @abstractmethod
    def load_har(self, har_id: str) -> dict[str, Any] | None:
        """Load a HAR by its ID."""
        ...

    @abstractmethod
    def list_hars(
        self,
        project_id: str,
        state: str | None = None,
    ) -> list[dict[str, Any]]:
        """List HARs for a project, optionally filtered by state."""
        ...

    @abstractmethod
    def update_har(self, har_id: str, updates: dict[str, Any]) -> bool:
        """Merge ``updates`` into a HAR. Returns True if a row changed."""
        ...

    @abstractmethod
    def close(self) -> None:
        """Close the store and release resources."""
        ...

    def __enter__(self) -> "StateStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class SQLiteStore(StateStore):
    """SQLite implementation with WAL mode for concurrent reads.

    Default implementation for local-first, portable operation.
    Works on WSL/DrvFs without metadata issues.
    """

    # Fields that live in their own column and are indexable.
    _COLUMNS = ("state", "expires_at", "answered_at", "answered_by")

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")  # concurrent readers
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS hars (
                har_id       TEXT PRIMARY KEY,
                project_id   TEXT NOT NULL,
                payload      TEXT NOT NULL,
                state        TEXT NOT NULL,
                created_at   TEXT NOT NULL,
                updated_at   TEXT NOT NULL,
                expires_at   TEXT,
                answered_at  TEXT,
                answered_by  TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_hars_project ON hars(project_id);
            CREATE INDEX IF NOT EXISTS idx_hars_state ON hars(state);
            CREATE INDEX IF NOT EXISTS idx_hars_expires ON hars(expires_at);
            """
        )

    def save_har(self, har: dict[str, Any]) -> None:
        now = _utc_now()
        self.conn.execute(
            """
            INSERT INTO hars
                (har_id, project_id, payload, state, created_at, updated_at,
                 expires_at, answered_at, answered_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(har_id) DO UPDATE SET
                payload     = excluded.payload,
                state       = excluded.state,
                updated_at  = excluded.updated_at,
                expires_at  = excluded.expires_at,
                answered_at = excluded.answered_at,
                answered_by = excluded.answered_by
            """,
            (
                har["har_id"],
                har["project_id"],
                json.dumps(har, ensure_ascii=False),
                har["state"],
                har.get("created_at", now),
                now,
                har.get("expires_at"),
                har.get("answered_at"),
                har.get("answered_by"),
            ),
        )
        self.conn.commit()

    def _row_to_har(self, row: sqlite3.Row) -> dict[str, Any]:
        har = json.loads(row["payload"])
        har["state"] = row["state"]
        har["updated_at"] = row["updated_at"]
        if har.get("state") == "OPEN" and har.get("expires_at"):
            try:
                if datetime.fromisoformat(har["expires_at"]) <= datetime.now(timezone.utc):
                    har["state"] = "STALE"
            except (ValueError, TypeError):
                pass
        return har

    def load_har(self, har_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM hars WHERE har_id = ?", (har_id,)
        ).fetchone()
        return self._row_to_har(row) if row else None

    def list_hars(self, project_id: str, state: str | None = None) -> list[dict[str, Any]]:
        if state:
            rows = self.conn.execute(
                "SELECT * FROM hars WHERE project_id = ? AND state = ? ORDER BY created_at DESC",
                (project_id, state),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM hars WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,),
            ).fetchall()
        hars = [self._row_to_har(r) for r in rows]
        if state:
            hars = [h for h in hars if h["state"] == state]
        return hars

    def update_har(self, har_id: str, updates: dict[str, Any]) -> bool:
        row = self.conn.execute(
            "SELECT * FROM hars WHERE har_id = ?", (har_id,)
        ).fetchone()
        if row is None:
            return False

        har = json.loads(row["payload"])
        for key, value in updates.items():
            har[key] = value
        har["updated_at"] = _utc_now()

        self.conn.execute(
            """
            UPDATE hars SET
                payload = ?, state = ?, updated_at = ?,
                expires_at = ?, answered_at = ?, answered_by = ?
            WHERE har_id = ?
            """,
            (
                json.dumps(har, ensure_ascii=False),
                har.get("state", row["state"]),
                har["updated_at"],
                har.get("expires_at"),
                har.get("answered_at"),
                har.get("answered_by"),
                har_id,
            ),
        )
        self.conn.commit()
        return True

    def close(self) -> None:
        self.conn.close()


class PostgresStore(StateStore):
    """PostgreSQL implementation placeholder.

    Activated when ``SE_STATE_BACKEND=postgres`` and ``SE_PG_DSN`` is set.
    Not implemented yet; reserved for the multi-user deployment path.
    """

    def __init__(self, dsn: str) -> None:
        raise NotImplementedError(
            "PostgreSQL store not yet implemented. "
            "Use SE_STATE_BACKEND=sqlite or implement when multi-user is required."
        )


def get_state_store(project_dir: Path | str) -> StateStore:
    """Factory: return the StateStore for a project.

    SQLite by default, at ``<project>/.se/state.db``. Set
    ``SE_STATE_BACKEND=postgres`` plus ``SE_PG_DSN`` for the future
    multi-user backend.
    """
    backend = os.environ.get("SE_STATE_BACKEND", "sqlite").lower()
    if backend == "postgres":
        dsn = os.environ.get("SE_PG_DSN")
        if not dsn:
            raise ValueError("SE_PG_DSN is required when SE_STATE_BACKEND=postgres")
        return PostgresStore(dsn)
    return SQLiteStore(Path(project_dir) / ".se" / "state.db")
