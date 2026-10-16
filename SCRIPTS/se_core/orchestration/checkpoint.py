"""Checkpoint Manager for Workflow Recovery.

Persists workflow execution state (completed nodes, node results, gate results and
accumulated context) so an interrupted run can be resumed instead of restarted.

Storage is one JSON document per checkpoint under
``<project>/.workflows/checkpoints/CP-NNNN.json``, written atomically so a crash
never leaves a half-written checkpoint behind.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..paths import repo_root, now_utc, write_json_atomic
from ..schemas import load_schemas, validate


CHECKPOINT_DIR = ".workflows/checkpoints"
CHECKPOINT_PREFIX = "CP-"
SCHEMA_VERSION = "1"


def _checkpoint_number(checkpoint_id: str) -> int:
    """Numeric part of a checkpoint id, or -1 when it does not parse."""
    try:
        return int(str(checkpoint_id).split("-")[1])
    except (IndexError, ValueError):
        return -1


class CheckpointManager:
    """Manages workflow execution checkpoints for recovery/resume."""

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)
        self.checkpoint_dir = self.project_root / CHECKPOINT_DIR
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self._schemas = load_schemas(repo_root())

    def _checkpoint_path(self, checkpoint_id: str) -> Path:
        return self.checkpoint_dir / f"{checkpoint_id}.json"

    def _next_checkpoint_id(self) -> str:
        """Next monotonic checkpoint id (CP-0001, CP-0002, ...)."""
        highest = 0
        for f in self.checkpoint_dir.glob(f"{CHECKPOINT_PREFIX}*.json"):
            number = _checkpoint_number(f.stem)
            if number > highest:
                highest = number
        return f"{CHECKPOINT_PREFIX}{highest + 1:04d}"

    def save(
        self,
        workflow_id: str,
        execution_id: str,
        completed_nodes: List[str],
        node_results: Dict[str, Any],
        gate_results: Dict[str, Any],
        context: Dict[str, Any],
        status: str = "IN_PROGRESS",
    ) -> str:
        """Save a new checkpoint."""
        checkpoint_id = self._next_checkpoint_id()

        checkpoint = {
            "schema_version": SCHEMA_VERSION,
            "checkpoint_id": checkpoint_id,
            "workflow_id": workflow_id,
            "execution_id": execution_id,
            "completed_nodes": completed_nodes,
            "node_results": node_results,
            "gate_results": gate_results,
            "context": context,
            "created_at": now_utc(),
            "status": status,
        }

        # Validate against schema
        errors = validate(checkpoint, self._schemas.get("checkpoint", {}))
        if errors:
            raise ValueError(f"Checkpoint validation failed: {errors}")

        path = self._checkpoint_path(checkpoint_id)
        write_json_atomic(path, checkpoint)
        return checkpoint_id

    def load(self, checkpoint_id: str) -> Optional[Dict[str, Any]]:
        """Load a checkpoint by ID."""
        path = self._checkpoint_path(checkpoint_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def list_checkpoints(self, workflow_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List checkpoints, newest first, optionally filtered by workflow.

        Sorting is by ``created_at`` and then by checkpoint number, because
        ``now_utc()`` has second resolution: without the tiebreaker several
        checkpoints written in the same second would order arbitrarily and
        ``cleanup_old`` could keep the oldest instead of the newest.
        """
        checkpoints = []
        for f in sorted(self.checkpoint_dir.glob("CP-*.json")):
            try:
                cp = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if workflow_id is not None and cp.get("workflow_id") != workflow_id:
                continue
            try:
                checkpoints.append({
                    "checkpoint_id": cp["checkpoint_id"],
                    "workflow_id": cp["workflow_id"],
                    "execution_id": cp["execution_id"],
                    "completed_nodes": cp["completed_nodes"],
                    "created_at": cp["created_at"],
                    "status": cp["status"],
                })
            except KeyError:
                continue
        return sorted(
            checkpoints,
            key=lambda x: (x["created_at"], _checkpoint_number(x["checkpoint_id"])),
            reverse=True,
        )

    def delete(self, checkpoint_id: str) -> bool:
        """Delete a checkpoint. Returns True only when a file was removed."""
        path = self._checkpoint_path(checkpoint_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def cleanup_old(self, keep: int = 10, workflow_id: Optional[str] = None) -> int:
        """Delete every checkpoint except the newest ``keep`` ones.

        Scoped to ``workflow_id`` when given, otherwise across all workflows in the
        project. Returns the number of checkpoints removed.
        """
        checkpoints = self.list_checkpoints(workflow_id)
        if len(checkpoints) <= keep:
            return 0
        to_delete = checkpoints[keep:]
        for cp in to_delete:
            self.delete(cp["checkpoint_id"])
        return len(to_delete)


def create_checkpoint_manager(project_root: Path) -> CheckpointManager:
    """Factory function to create a CheckpointManager."""
    return CheckpointManager(project_root)