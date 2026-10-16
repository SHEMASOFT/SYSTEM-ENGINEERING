"""Memory Engine for SYSTEM-ENGINEERING.

Provides structured, queryable memory backed by canonical JSON records
(ADR-0003, ADR-0027). Supports project-scoped and cross-project operations.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

from ..paths import repo_root, now_utc, write_json_atomic
from ..schemas import load_schemas, validate
from ..artifacts import read_manifest


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
    schema_version: str = "1"

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
        )


class MemoryEngine:
    """Memory Engine over canonical JSON records (ADR-0003, ADR-0027).

    Provides CRUD operations for memory records with:
    - Project-scoped and cross-project queries
    - Relationship tracking (supersedes, related, compatible)
    - Tag-based filtering
    - Atomic, LF, schema-validated persistence
    """

    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root else repo_root()
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
    ) -> Dict[str, Any]:
        """Create a new memory record."""
        # Validate project exists
        project_dir = self._find_project_dir(project_id)
        if not project_dir:
            raise ValueError(f"Project {project_id} not found")

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
            author=author,  # Fixed: was source, should be author
            source=source,
            related_memories=related_memories or [],
            supersedes=None,
            superseded_by=None,
            metadata=metadata or {},
        )

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
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Query memories with filters."""
        # The project memory files are the deterministic, auditable source of
        # truth. Engram sync (when available) is a separate concern and must not
        # add latency or stderr noise to a plain query.
        memories = self._scan_local_memories(project_id, types, tags, author, since, until, tags_mode)

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
        return None

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
        return f"MEM-{highest + 1:04d}"

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

    def _scan_local_memories(
        self,
        project_id: Optional[str],
        types: Optional[List[str]],
        tags: Optional[List[str]],
        author: Optional[str],
        since: Optional[str],
        until: Optional[str],
        tags_mode: str,
    ) -> List:
        """Scan local memory files with filters."""
        memories = []

        if project_id:
            found = self._find_project_dir(project_id)
            project_dirs = [found] if found else []
        else:
            project_dirs = [
                p for p in (self.root / "PROJECTS").glob("*")
                if (p / "PROJECT.json").exists()
            ]

        for project_dir in project_dirs:
            if not project_dir:
                continue
            mem_dir = project_dir / "memories"
            if not mem_dir.exists():
                continue
            for mem_file in mem_dir.glob("*.json"):
                try:
                    data = json.loads(mem_file.read_text(encoding="utf-8"))
                    record = MemoryRecord.from_dict(data)

                    # Apply filters
                    if types and record.type not in types:
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
                except Exception:
                    continue

        # Sort by created_at descending
        memories.sort(key=lambda m: m.created_at, reverse=True)
        return memories

    def _get_schema(self, name: str) -> Dict[str, Any]:
        """Get schema by name."""
        schemas = load_schemas(repo_root())
        return schemas.get(name, {})
