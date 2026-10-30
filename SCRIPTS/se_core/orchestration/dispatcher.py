"""Reference Dispatcher — Automatic memory reference resolution for internal route.

Resolves memory references in agent inputs/context before LLM call.
Enables transparent reference passing without explicit memory.get() calls.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set
from pathlib import Path

from ..memory.engine import MemoryEngine
from ..paths import repo_root

logger = logging.getLogger(__name__)


class ReferenceDispatcher:
    """Resolves memory references in inputs/context automatically.

    Detects dicts with "memory_id" or "topic_key" and replaces them
    with actual memory content from the memory engine.
    """

    def __init__(
        self,
        memory_engine: MemoryEngine,
        project_id: str,
        auto_resolve: bool = True,
        max_depth: int = 3,
    ):
        self.memory_engine = memory_engine
        self.project_id = project_id
        self.auto_resolve = auto_resolve
        self.max_depth = max_depth
        self._resolved_in_call: Set[str] = set()  # Track memory_ids to avoid cycles

    def resolve_inputs(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve memory references in inputs dict."""
        if not self.auto_resolve:
            return inputs
        return self._resolve_dict(inputs, depth=0)

    def resolve_context(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve memory references in context dict."""
        if not self.auto_resolve:
            return context
        return self._resolve_dict(context, depth=0)

    def _resolve_dict(self, obj: Any, depth: int) -> Any:
        """Recursively resolve memory references in dict/list structures."""
        if depth >= self.max_depth:
            return obj

        if isinstance(obj, dict):
            # Check if this dict is a memory reference
            if self._is_memory_reference(obj):
                return self._resolve_memory_ref(obj)
            # Otherwise recurse into values
            return {k: self._resolve_dict(v, depth + 1) for k, v in obj.items()}

        elif isinstance(obj, list):
            return [self._resolve_dict(item, depth + 1) for item in obj]

        return obj

    def _is_memory_reference(self, obj: Dict[str, Any]) -> bool:
        """Check if dict represents a memory reference.

        Supported formats:
        - {"memory_id": "MEM-123", ...}
        - {"topic_key": "key", "project_id": "PRJ-1", ...}  (for upsert-style refs)
        """
        if not isinstance(obj, dict):
            return False

        # Must have memory_id or topic_key, and not be a regular content dict
        has_memory_id = "memory_id" in obj and isinstance(obj["memory_id"], str)
        has_topic_key = "topic_key" in obj and isinstance(obj["topic_key"], str)

        # Exclude dicts that look like actual content (have many keys)
        if has_memory_id or has_topic_key:
            # If it has content-like keys, it's probably not a reference
            content_keys = {"output", "result", "data", "content", "value", "status"}
            if len(obj.keys() & content_keys) > 1:
                return False
            return True

        return False

    def _resolve_memory_ref(self, ref: Dict[str, Any]) -> Any:
        """Resolve a single memory reference to its content."""
        memory_id = ref.get("memory_id")
        topic_key = ref.get("topic_key")

        # Track to avoid circular resolution
        resolve_key = memory_id or topic_key or "unknown"
        if resolve_key in self._resolved_in_call:
            logger.warning(f"Circular reference detected for {resolve_key}, returning ref as-is")
            return ref

        self._resolved_in_call.add(resolve_key)

        try:
            if memory_id:
                mem_record = self.memory_engine.get(memory_id, self.project_id)
                if mem_record is None:
                    logger.warning(f"Memory not found: {memory_id} (project: {self.project_id})")
                    return {"_unresolved": True, "memory_id": memory_id, "error": "not_found"}
                return mem_record.get("content", {})
            elif topic_key:
                # Search by topic_key (upsert pattern)
                search_result = self.memory_engine.search(
                    text=topic_key,
                    project_id=self.project_id,
                    limit=1
                )
                hits = search_result.get("hits", [])
                if not hits:
                    logger.warning(f"No memory found for topic_key: {topic_key}")
                    return {"_unresolved": True, "topic_key": topic_key, "error": "not_found"}
                mem_record = self.memory_engine.get(hits[0]["memory_id"], self.project_id)
                if mem_record is None:
                    return {"_unresolved": True, "topic_key": topic_key, "error": "not_found"}
                return mem_record.get("content", {})
        except Exception as e:
            logger.error(f"Failed to resolve memory reference {ref}: {e}")
            return {"_unresolved": True, **ref, "error": str(e)}
        finally:
            self._resolved_in_call.discard(resolve_key)

        return {"_unresolved": True, **ref, "error": "unknown"}


def create_dispatcher(
    memory_engine: MemoryEngine,
    project_id: str,
    node: Optional[Dict[str, Any]] = None,
) -> ReferenceDispatcher:
    """Factory function to create dispatcher from node/workflow config.

    Reads auto_resolve_refs from node.auto_resolve_refs (default: True).
    """
    auto_resolve = True
    if node:
        auto_resolve = node.get("auto_resolve_refs", True)
    return ReferenceDispatcher(memory_engine, project_id, auto_resolve=auto_resolve)