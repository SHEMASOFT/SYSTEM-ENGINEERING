"""SE lifecycle state at ``<target>/.se/lifecycle-state.json`` (schema v1).

The lifecycle commands (``se install`` / ``se sync`` / ``se update`` /
``se uninstall``) share one audit state so every command is part of a single
integrated system rather than four independent mechanisms. The state records:

* the authoritative SE version and host OS at the time of registration;
* every MCP server SE owns (name -> declared spec hash, registration time,
  template source, scope);
* an optional adapter record;
* the ``uninstalled`` audit trail (removals are never silently forgotten).

The module is pure and path-based so it is unit-testable without touching any
real configuration: writing/deleting happens only inside ``<target>/.se/``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .paths import load_json, write_json_atomic

SCHEMA_VERSION = "1"
STATE_DIRNAME = ".se"
STATE_FILENAME = "lifecycle-state.json"
BACKUP_DIRNAME = "backups"


def state_dir(target: Path | str) -> Path:
    """Return ``<target>/.se`` (the lifecycle state directory)."""
    return Path(target) / STATE_DIRNAME


def backup_dir(target: Path | str) -> Path:
    """Return ``<target>/.se/backups`` (created on demand by writers)."""
    return state_dir(target) / BACKUP_DIRNAME


def state_path(target: Path | str) -> Path:
    """Return the lifecycle state file path for ``target``."""
    return state_dir(target) / STATE_FILENAME


def read_se_version(se_root: Path | str) -> str:
    """Read the authoritative SE version the same way existing code does.

    ``doctor.check_configuration`` reads ``<root>/VERSION`` and asserts it equals
    ``SYSTEM.json`` ``master_system_version``; ``VERSION`` is the canonical source.
    """
    return (Path(se_root) / "VERSION").read_text(encoding="utf-8").strip()


def now_iso() -> str:
    """UTC ISO-8601 timestamp (second precision, stable for audits)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_state(
    *,
    se_version: str,
    os_name: str,
    target: Path | str,
    scope: str = "project",
    runtime: str = "opencode",
) -> dict:
    """Create an empty schema-v1 lifecycle state."""
    return {
        "schema_version": SCHEMA_VERSION,
        "se_version": se_version,
        "runtime": runtime,
        "os": os_name,
        "target": str(target),
        "scope": scope,
        "servers": {},
        "adapter": None,
        "uninstalled": [],
    }


def load_state(target: Path | str) -> dict | None:
    """Load the lifecycle state for ``target``; ``None`` when absent or corrupt.

    A missing file and a corrupt file are both reported as "no usable state" by
    callers (the command reports rather than guessing), so the distinction is not
    surfaced here.
    """
    path = state_path(target)
    if not path.exists():
        return None
    try:
        data = load_json(path)
    except Exception:
        return None
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        return None
    if not isinstance(data.get("servers"), dict):
        return None
    return data


def save_state(state: dict, target: Path | str) -> None:
    """Persist ``state`` atomically at ``<target>/.se/lifecycle-state.json``."""
    write_json_atomic(state_path(target), state)


def spec_hash(spec: dict) -> str:
    """Canonical sha256 of a resolved server spec.

    ``spec`` is a plain dict (``name``, ``command``, ``environment``); keys are
    sorted so equivalent specs always hash identically regardless of insertion
    order.
    """
    canonical = json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def record_server(
    state: dict,
    name: str,
    *,
    declared: str,
    source: str,
    scope: str = "project",
    registered_at: str | None = None,
) -> None:
    """Record (or refresh) an SE-owned server in ``state.servers``."""
    state.setdefault("servers", {})[name] = {
        "declared": declared,
        "registered_at": registered_at or now_iso(),
        "source": source,
        "scope": scope,
    }


def remove_server(state: dict, name: str, *, removed_at: str | None = None) -> dict | None:
    """Move ``name`` from ``state.servers`` into the ``uninstalled`` audit trail.

    Returns the removed record (with ``removed_at``) or ``None`` when the server
    was not recorded. The audit trail is kept in v1 (``clear_state`` is a
    future decision).
    """
    servers = state.get("servers") or {}
    if name not in servers:
        return None
    record = servers.pop(name)
    audit_entry = {
        "name": name,
        "removed_at": removed_at or now_iso(),
        "source": record.get("source"),
        "declared": record.get("declared"),
        "scope": record.get("scope"),
    }
    state.setdefault("uninstalled", []).append(audit_entry)
    return audit_entry