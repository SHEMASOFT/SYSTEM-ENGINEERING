"""Workflow schemas for SYSTEM-ENGINEERING orchestration."""

from typing import Any, Dict

from ..schemas import load_schemas
from ..paths import repo_root


def load_workflow_schema() -> Dict[str, Any]:
    """Load workflow schema."""
    schemas = load_schemas(repo_root())
    return schemas.get("workflow", {})


def load_execution_schema() -> Dict[str, Any]:
    """Load workflow execution schema."""
    schemas = load_schemas(repo_root())
    return schemas.get("workflow_execution", {})
