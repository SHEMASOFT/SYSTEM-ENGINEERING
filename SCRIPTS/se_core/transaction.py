"""Byte-level transactions for lifecycle writes (config + lifecycle state).

``se install`` and ``se sync`` mutate two coupled artifacts: the runtime config
(``opencode.jsonc``) and the lifecycle state (``.se/lifecycle-state.json``). A
failure halfway through used to leave one written without the other: servers
present in the config but unknown to SE (``foreign`` on the next sync), or a
state record for a server that was never written.

This module provides a small, dependency-free journal:

* :func:`begin` copies every file (or records its absence) into
  ``<target>/.se/backups/<operation>-<utc>-<seq>/`` together with a
  ``manifest.json`` (status ``open``) that holds the sha256 of each original;
* :func:`commit` marks the journal ``committed`` (kept as an audit record);
* :func:`rollback` restores the exact bytes, deletes files that did not exist
  at ``begin``, and verifies every restored hash;
* :func:`recover_open` rolls back journals left ``open`` by an interrupted run.

Design limits (documented, not hidden): no locks and no processes, so two
concurrent writers of the same target are out of scope; adapter generation is
*not* journaled (it happens before the config write and is owned by the
generator); journals are never deleted.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from . import lifecycle_state as lc
from .paths import write_json_atomic

#: Manifest schema this module writes/reads.
SCHEMA_VERSION = "1"

#: Keys persisted in ``manifest.json`` (the in-memory journal also carries
#: ``journal_dir`` / ``manifest_path``, which are derived, not persisted).
_MANIFEST_KEYS = (
    "schema_version",
    "operation",
    "created_at",
    "status",
    "target",
    "files",
)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _coerce_now(now) -> datetime:
    """Accept ``None``, a ``datetime`` or an ISO-8601 string (UTC-normalized)."""
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, datetime):
        moment = now
    else:
        moment = datetime.fromisoformat(str(now).replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _resolve_source(target: Path, path) -> Path:
    source = Path(path)
    if not source.is_absolute():
        source = target / source
    return source.resolve()


def _relative_to_target(target: Path, source: Path) -> str:
    try:
        return source.resolve().relative_to(target.resolve()).as_posix()
    except ValueError:
        return str(source.resolve())


def _manifest_payload(journal: dict) -> dict:
    return {key: journal.get(key) for key in _MANIFEST_KEYS if key in journal}


def _journal_dir(journal: dict) -> Path:
    directory = journal.get("journal_dir")
    if directory:
        return Path(directory)
    manifest_path = journal.get("manifest_path")
    if manifest_path:
        return Path(manifest_path).parent
    raise ValueError("journal has neither journal_dir nor manifest_path")


def _write_manifest(journal: dict) -> None:
    manifest_path = Path(
        journal.get("manifest_path") or (_journal_dir(journal) / "manifest.json")
    )
    write_json_atomic(manifest_path, _manifest_payload(journal))


def begin(target, operation: str, paths: list[Path], *, now=None) -> dict:
    """Start a transaction journaling ``paths`` before any mutation.

    Creates ``<target>/.se/backups/<operation>-<utc>-<seq>/`` with ``files/``
    and a ``manifest.json`` (``status: "open"``). Existing files are copied
    byte-for-byte with :func:`shutil.copy2`; absent files are recorded with
    ``existed: false`` so a rollback removes them if the operation creates them.

    ``seq`` is two digits (``-01``, ``-02``) so two transactions started in the
    same second never collide. The manifest is written atomically (LF).
    """
    target = Path(target)
    moment = _coerce_now(now)
    stamp = moment.strftime("%Y%m%dT%H%M%SZ")
    created_at = moment.strftime("%Y-%m-%dT%H:%M:%SZ")

    backups = lc.backup_dir(target)
    backups.mkdir(parents=True, exist_ok=True)
    prefix = f"{operation}-{stamp}"
    sequence = 1
    while (backups / f"{prefix}-{sequence:02d}").exists():
        sequence += 1
    journal_dir = backups / f"{prefix}-{sequence:02d}"
    journal_dir.mkdir(parents=True, exist_ok=False)
    files_dir = journal_dir / "files"

    entries: list[dict] = []
    for index, path in enumerate(paths):
        source = _resolve_source(target, path)
        relative = _relative_to_target(target, source)
        existed = source.is_file()
        entry = {
            "path": relative,
            "absolute": str(source),
            "existed": existed,
            "sha256": "",
            "bytes": 0,
            "copy": None,
        }
        if existed:
            payload = source.read_bytes()
            files_dir.mkdir(parents=True, exist_ok=True)
            destination = files_dir / f"{index:02d}-{source.name}"
            shutil.copy2(source, destination)
            entry["sha256"] = _sha256_bytes(payload)
            entry["bytes"] = len(payload)
            entry["copy"] = destination.relative_to(journal_dir).as_posix()
        entries.append(entry)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "operation": str(operation),
        "created_at": created_at,
        "status": "open",
        "target": str(target),
        "files": entries,
    }
    journal = dict(manifest)
    journal["journal_dir"] = str(journal_dir)
    journal["manifest_path"] = str(journal_dir / "manifest.json")
    _write_manifest(journal)
    return journal


def commit(journal: dict) -> dict:
    """Mark ``journal`` as ``committed`` (atomic rewrite; kept as audit)."""
    committed = dict(journal)
    committed["status"] = "committed"
    _write_manifest(committed)
    return committed


def rollback(journal: dict) -> dict:
    """Restore every file in ``journal`` to its ``begin`` bytes.

    Existing files are restored from their copy and verified against the
    recorded sha256; files recorded as absent are removed when the operation
    created them. The objective is always "return to the previous state", so a
    destination whose current hash differs from the recorded one is still
    restored, but it is reported in ``changed_since_begin``.

    Returns ``{"ok", "restored", "removed", "errors", "hashes",
    "changed_since_begin"}``. On a fully successful rollback the manifest is
    marked ``rolled_back`` so :func:`recover_open` never applies it twice.
    """
    result = {
        "ok": True,
        "restored": [],
        "removed": [],
        "errors": [],
        "hashes": {},
        "changed_since_begin": [],
    }
    try:
        journal_dir = _journal_dir(journal)
    except ValueError as exc:
        result["ok"] = False
        result["errors"].append(str(exc))
        return result

    for entry in journal.get("files") or []:
        if not isinstance(entry, dict):
            result["errors"].append("journal entry is not an object")
            continue
        relative = str(entry.get("path") or "")
        absolute = str(entry.get("absolute") or "")
        label = relative or absolute or "<unknown>"
        if not absolute:
            result["errors"].append(f"journal entry without absolute path: {label}")
            continue
        destination = Path(absolute)

        if not entry.get("existed"):
            if destination.exists():
                try:
                    destination.unlink()
                except OSError as exc:
                    result["errors"].append(f"cannot remove {label}: {exc}")
                else:
                    result["removed"].append(relative or absolute)
            continue

        copy_relative = entry.get("copy")
        if not copy_relative:
            result["errors"].append(f"journal entry without backup copy: {label}")
            continue
        copy_path = journal_dir / str(copy_relative)
        expected = str(entry.get("sha256") or "")
        try:
            payload = copy_path.read_bytes()
        except OSError as exc:
            result["errors"].append(f"cannot read backup copy for {label}: {exc}")
            continue
        copy_hash = _sha256_bytes(payload)
        if expected and copy_hash != expected:
            result["errors"].append(
                f"backup copy for {label} is corrupt: expected {expected}, got {copy_hash}"
            )
            continue

        current_hash = ""
        if destination.exists():
            try:
                current_hash = _sha256_bytes(destination.read_bytes())
            except OSError as exc:
                result["errors"].append(f"cannot read current {label}: {exc}")
                continue
            if current_hash != expected:
                result["changed_since_begin"].append(relative or absolute)

        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
        except OSError as exc:
            result["errors"].append(f"cannot restore {label}: {exc}")
            continue
        try:
            actual = _sha256_bytes(destination.read_bytes())
        except OSError as exc:
            result["errors"].append(f"cannot verify restored {label}: {exc}")
            continue
        result["hashes"][relative or absolute] = actual
        if expected and actual != expected:
            result["errors"].append(
                f"restored hash mismatch for {label}: expected {expected}, got {actual}"
            )
            continue
        result["restored"].append(relative or absolute)

    result["ok"] = not result["errors"]
    if result["ok"] and journal.get("status") == "open":
        rolled_back = dict(journal)
        rolled_back["status"] = "rolled_back"
        _write_manifest(rolled_back)
    return result


def list_open(target, *, operation: str | None = None) -> list[dict]:
    """Return the ``open`` journals under ``<target>/.se/backups`` (read-only).

    Each item is the manifest plus ``journal_dir`` / ``manifest_path``. Nothing
    is written, created or deleted: callers that only need to *detect* pending
    work (e.g. ``se sync --dry-run``) use this instead of :func:`recover_open`.
    Unreadable manifests are ignored (they are not a journal this module wrote).
    """
    backups = lc.backup_dir(target)
    journals: list[dict] = []
    if not backups.is_dir():
        return journals
    for manifest_path in sorted(backups.glob("*/manifest.json")):
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - read-only discovery, ignore garbage
            continue
        if not isinstance(data, dict):
            continue
        if data.get("status") != "open":
            continue
        if operation is not None and data.get("operation") != operation:
            continue
        journal = dict(data)
        journal["journal_dir"] = str(manifest_path.parent)
        journal["manifest_path"] = str(manifest_path)
        journals.append(journal)
    return journals


def recover_open(target, *, operation: str | None = None) -> dict:
    """Roll back every ``open`` journal under ``<target>/.se/backups``.

    Journals are never deleted; ``committed``/``rolled_back`` ones are left
    untouched. Returns ``{"recovered": [journal_dir, ...], "errors": [...],
    "results": [...]}``; ``errors`` are human-readable strings, ``results``
    carries the per-journal rollback detail.
    """
    backups = lc.backup_dir(target)
    outcome = {"recovered": [], "errors": [], "results": []}
    if not backups.is_dir():
        return outcome

    for manifest_path in sorted(backups.glob("*/manifest.json")):
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - fail closed, report it
            outcome["errors"].append(f"{manifest_path}: unreadable manifest ({exc})")
            continue
        if not isinstance(data, dict):
            continue
        if data.get("status") != "open":
            continue
        if operation is not None and data.get("operation") != operation:
            continue
        journal = dict(data)
        journal["journal_dir"] = str(manifest_path.parent)
        journal["manifest_path"] = str(manifest_path)
        rolled = rollback(journal)
        outcome["results"].append({"journal": str(manifest_path.parent), **rolled})
        if rolled["ok"]:
            outcome["recovered"].append(str(manifest_path.parent))
        else:
            outcome["errors"].extend(
                f"{manifest_path.parent}: {error}" for error in rolled["errors"]
            )
    return outcome
