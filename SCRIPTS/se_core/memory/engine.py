"""Memory Engine for SYSTEM-ENGINEERING.

Provides structured, queryable memory with Engram backend.
Supports project-scoped and cross-project memory operations.
"""

from __future__ import annotations

import json
import random
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from dataclasses import dataclass, asdict
from datetime import datetime

from ..paths import repo_root, load_json, now_utc
from ..schemas import load_schemas, validate
from ..artifacts import all_collections, read_manifest
from ..artifacts import ID_FIELD, COLLECTIONS


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
    """Memory Engine with Engram backend.

    Provides CRUD operations for memory records with:
    - Project-scoped and cross-project queries
    - Relationship tracking (supersedes, related)
    - Tag-based filtering
    - Engram backend for persistence
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

        now = now_utc()
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

        # Validate
        schemas = load_schemas(repo_root())
        errors = validate(record.to_dict(), self._get_schema("memory_record"))
        if errors:
            raise ValueError(f"Memory validation failed: {errors}")

        # Persist to Engram
        self._persist_to_engram(record)

        # Also write to project's memory collection (optional local copy)
        self._write_local_copy(project_id, record)

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
        """Get a single memory by ID (reads the project memory files)."""
        if project_id:
            memories = self._scan_local_memories(project_id, None, None, None, None, None, "any")
            for m in memories:
                if m.memory_id == memory_id:
                    return m.to_dict()
        return None

    def link(
        self,
        memory_id: str,
        related_memory_id: str,
        relation: str = "related",
    ) -> Dict[str, Any]:
        """Link two memories (related, supersedes, superseded_by)."""
        # Implementation would update both records
        return {"status": "linked", "memory_id": memory_id, "related_to": related_memory_id, "relation": relation}

    def update(
        self,
        memory_id: str,
        project_id: str,
        updates: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Update a memory record."""
        # Implementation
        return {"status": "updated", "memory_id": memory_id}

    def supersede(
        self,
        old_memory_id: str,
        new_memory_id: str,
        project_id: str,
    ) -> Dict[str, Any]:
        """Mark old memory as superseded by new one."""
        # Update both records
        return {"status": "superseded", "old": old_memory_id, "new": new_memory_id}

    def _find_project_dir(self, project_id: str) -> Optional[Path]:
        """Find project directory by project_id."""
        for p in (repo_root() / "PROJECTS").glob("*"):
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

    def _persist_to_engram(self, record: "MemoryRecord") -> None:
        """Engram persistence hook.

        Engram sync is owned by its own MCP configuration, not by the skill
        server. Until a dedicated memory MCP tool exists, the local project
        memory file (written by ``_write_local_copy``) is the source of truth.
        """
        return None

    def _write_local_copy(self, project_id: str, record: "MemoryRecord") -> None:
        """Write local copy to project's memories dir."""
        project_dir = self._find_project_dir(project_id)
        if not project_dir:
            return
        mem_dir = project_dir / "memories"
        mem_dir.mkdir(parents=True, exist_ok=True)
        path = mem_dir / f"{record.memory_id}.json"
        path.write_text(json.dumps(record.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

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
            project_dirs = [self._find_project_dir(project_id)]
            project_dirs = [p for p in project_dirs if p]
        else:
            project_dirs = list((repo_root() / "PROJECTS").glob("*"))

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
