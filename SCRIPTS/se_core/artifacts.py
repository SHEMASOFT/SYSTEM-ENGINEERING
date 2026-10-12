"""Artifact collection helpers for managed project workspaces."""

from __future__ import annotations

from pathlib import Path

from .paths import load_json, write_json

PROJECT_MANIFEST = "PROJECT.json"
DISCOVERY_FILE = "discovery.json"

COLLECTIONS = {
    "objective": {"dir": "objectives", "prefix": "OBJ"},
    "requirement": {"dir": "requirements", "prefix": "REQ"},
    "task": {"dir": "tasks", "prefix": "TASK"},
    "artifact": {"dir": "artifacts", "prefix": "ART"},
    "evidence": {"dir": "evidence", "prefix": "EVD"},
    "acceptance": {"dir": "acceptances", "prefix": "ACC"},
    "decision": {"dir": "decisions", "prefix": "ADR"},
    "release": {"dir": "releases", "prefix": "REL"},
    "sdd": {"dir": "sdds", "prefix": "SDD"},
    "odd": {"dir": "odds", "prefix": "ODD"},
    "run": {"dir": "runs", "prefix": "RUN"},
}

WORKSPACE_DIRS = [
    "objectives",
    "requirements",
    "tasks",
    "artifacts",
    "evidence",
    "acceptances",
    "decisions",
    "releases",
    "sdds",
    "odds",
    "runs",
    "docs",
]

ID_FIELD = {
    "objective": "objective_id",
    "requirement": "id",
    "task": "id",
    "artifact": "artifact_id",
    "evidence": "id",
    "acceptance": "acceptance_id",
    "decision": "decision_id",
    "release": "id",
    "sdd": "sdd_id",
    "odd": "odd_id",
    "run": "run_id",
}


def manifest_path(project_dir) -> Path:
    return Path(project_dir) / PROJECT_MANIFEST


def read_manifest(project_dir) -> dict:
    return load_json(manifest_path(project_dir))


def write_manifest(project_dir, data: dict) -> None:
    write_json(manifest_path(project_dir), data)


def read_discovery(project_dir):
    path = Path(project_dir) / DISCOVERY_FILE
    if not path.exists():
        return None
    return load_json(path)


def write_discovery(project_dir, data: dict) -> None:
    write_json(Path(project_dir) / DISCOVERY_FILE, data)


def collection(project_dir, kind: str):
    """Return (items, errors) where items is [(path, data), ...]."""
    meta = COLLECTIONS[kind]
    directory = Path(project_dir) / meta["dir"]
    items, errors = [], []
    if directory.is_dir():
        for path in sorted(directory.glob("*.json")):
            try:
                items.append((path, load_json(path)))
            except Exception as exc:  # pragma: no cover - reported by callers
                errors.append((path, str(exc)))
    return items, errors


def all_collections(project_dir) -> dict:
    return {kind: collection(project_dir, kind) for kind in COLLECTIONS}


def artifact_id(kind: str, data: dict):
    return data.get(ID_FIELD[kind])


def next_id(kind: str, items) -> str:
    meta = COLLECTIONS[kind]
    field = ID_FIELD[kind]
    highest = 0
    for _, data in items:
        raw = str(data.get(field) or "")
        digits = "".join(ch for ch in raw if ch.isdigit())
        if digits:
            highest = max(highest, int(digits))
    return f"{meta['prefix']}-{highest + 1:04d}"


def write_artifact(project_dir, kind: str, data: dict) -> Path:
    field = ID_FIELD[kind]
    path = Path(project_dir) / COLLECTIONS[kind]["dir"] / f"{data[field]}.json"
    write_json(path, data)
    return path
