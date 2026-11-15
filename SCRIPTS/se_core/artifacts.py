"""Artifact collection helpers for managed project workspaces."""

from __future__ import annotations

from pathlib import Path

from .paths import load_json, write_json
from .schemas import HAVE_JSONSCHEMA, load_schemas, validate

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
    "rdd": {"dir": "rdds", "prefix": "RDD"},
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
    "rdds",
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
    "rdd": "rdd_id",
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


_SCHEMA_BY_KIND: dict = {}


def schema_for_kind(kind: str):
    """The schema a collection kind is validated against (cached per process)."""
    if kind not in _SCHEMA_BY_KIND:
        _SCHEMA_BY_KIND[kind] = load_schemas().get(kind)
    return _SCHEMA_BY_KIND[kind]


def resolve_project_dir(project_dir, project_id=None) -> Path:
    """Resolve an explicit project directory and check it against ``project_id``.

    The directory is the authority: the caller already resolved it, so this
    only verifies that it *is* a project and that it is the project the caller
    expects. A manifest that declares another project is an explicit error,
    never a silent fallback to a different workspace.
    """
    path = Path(project_dir)
    if not (path / PROJECT_MANIFEST).exists():
        raise ValueError(f"no {PROJECT_MANIFEST} in {path}")
    manifest = read_manifest(path)
    declared = manifest.get("project_id")
    if project_id and declared and declared != project_id:
        raise ValueError(
            f"project_id mismatch: path says {declared}, expected {project_id}"
        )
    return path


def collection(project_dir, kind: str):
    """Return (items, errors) where items is [(path, data), ...].

    Only a record that parses *and* validates against its schema is returned.
    A record the workspace cannot prove is not evidence of anything: counting
    it would let a gate report a fact the workspace does not contain (an empty
    wrapper file used to make G4 pass without evaluating a single task).

    Every rejected record is reported in ``errors`` as ``(path, reason)`` with
    exactly one entry per record, so a caller can state how many records are
    invalid and why.
    """
    meta = COLLECTIONS[kind]
    directory = Path(project_dir) / meta["dir"]
    items, errors = [], []
    # Without jsonschema the environment cannot validate anything; `se doctor`
    # already fails it, so the collection stays readable instead of raising.
    schema = schema_for_kind(kind) if HAVE_JSONSCHEMA else None
    if directory.is_dir():
        for path in sorted(directory.glob("*.json")):
            try:
                data = load_json(path)
            except Exception as exc:  # pragma: no cover - reported by callers
                errors.append((path, f"unreadable JSON: {exc}"))
                continue
            if schema is not None:
                problems = validate(data, schema)
                if problems:
                    errors.append(
                        (path, "schema validation failed: " + "; ".join(problems))
                    )
                    continue
            items.append((path, data))
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
