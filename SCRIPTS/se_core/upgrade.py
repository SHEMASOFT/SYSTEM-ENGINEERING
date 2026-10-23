"""``se upgrade`` - thin, fail-closed upgrade orchestrator.

This module implements the upgrade contract approved in
``DOCS/internal/upgrade-readiness-audit-2026-10-22.md`` (section 6):

* version discovery (SemVer tags, with or without a ``v`` prefix, from the
  remote or local refs);
* a read-only preflight that BLOCKS before any write;
* a verifiable snapshot of the runtime config, lifecycle state and migration
  ledger (explicitly invoked only - ``--check`` / ``--dry-run`` never create
  ``.se/``);
* snapshot verification and hash-guarded restoration;
* an execution phase: marker -> fetch -> ff-only advance -> migrations ->
  adapters -> sync -> doctor, with a byte-level rollback on any failure;
* ``--recover`` for an upgrade interrupted between steps.

Design constraints (inherited from the audit):

* orchestrator, not a second engine - reconciliation/adapters/health stay in
  ``sync`` / ``opencode.generator`` / ``doctor``;
* every failure is fail-closed and reported, never guessed;
* no network beyond ``git ls-remote``/``git fetch`` when the caller asks for
  it, and never in ``--offline`` mode;
* the git runner and the step runner are injectable so the module is
  unit-testable without git and without touching a real repository;
* ``git reset --hard <git_head_before>`` is the only destructive git operation
  and it happens only inside :func:`rollback_upgrade`, only when the marker
  proves a code advance.
"""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import lifecycle_state as lc
from . import mcpconfig
from .paths import write_json_atomic
from .reporting import build_envelope, render_json, wants_json

#: Lifecycle state schema this build understands. Anything else must be
#: migrated before the state is trusted (``load_state`` returns ``None``).
SUPPORTED_STATE_SCHEMA = "1"

#: Marker written by the execution phase before the first mutation; its
#: presence means a previous upgrade was interrupted.
UPGRADE_MARKER = "upgrade-in-progress.json"

#: Migration directory (repository root) and its ledger (inside ``.se/``).
MIGRATIONS_DIRNAME = "MIGRATIONS"
MIGRATIONS_LEDGER = "migrations.json"

#: Append-only audit trail for upgrade attempts (one JSON object per line, LF).
UPGRADE_HISTORY = "upgrade-history.jsonl"

_SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_PRERELEASE_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)-([0-9A-Za-z.-]+)$")

#: Statuses that mean "nothing is wrong, just nothing to do".
_OK_STATUSES = ("PASS", "INFO", "UNKNOWN")


class MigrationError(RuntimeError):
    """A migration failed while running; the orchestrator must roll back."""


class UpgradeError(RuntimeError):
    """An upgrade step failed for a reason that is not a subprocess exit code."""


# --------------------------------------------------------------------------- #
# Version parsing and selection
# --------------------------------------------------------------------------- #


def parse_semver(text) -> tuple[int, int, int] | None:
    """Parse ``X.Y.Z`` / ``vX.Y.Z``; return ``None`` for anything else.

    Pre-releases (``-rc1``, ``-beta``) and build metadata are deliberately
    rejected: they are not a published upgrade target unless the caller opts in
    through :func:`select_target_version` (``allow_prerelease``).
    """
    if not isinstance(text, str):
        return None
    match = _SEMVER_RE.match(text.strip())
    if match is None:
        return None
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _format_version(version: tuple[int, int, int]) -> str:
    return f"{version[0]}.{version[1]}.{version[2]}"


def _normalize_tag(tag) -> str:
    text = str(tag).strip()
    if text.startswith("refs/tags/"):
        text = text[len("refs/tags/") :]
    return text


def select_target_version(
    tags,
    current,
    *,
    allow_prerelease: bool = False,
    allow_downgrade: bool = False,
) -> dict:
    """Select the newest published tag that is strictly newer than ``current``.

    Returns ``{"target": "X.Y.Z"|None, "status": ..., "reason": str}`` with one
    of the documented statuses:

    * ``OK`` - a strictly newer tag exists (or a downgrade was explicitly
      allowed), ``target`` is set;
    * ``UP_TO_DATE`` - the newest candidate equals ``current``; no target;
    * ``NO_TAGS`` - no usable tag at all (empty, garbage, or only pre-releases
      while they are disabled);
    * ``DOWNGRADE_BLOCKED`` - every candidate is older than ``current`` and
      ``allow_downgrade`` is false.

    ``current`` must be a valid SemVer string; a malformed current version is a
    caller error (``ValueError``), not a silent guess.
    """
    current_version = parse_semver(current)
    if current_version is None:
        raise ValueError(f"invalid current version: {current!r}")

    candidates: list[tuple[tuple, str]] = []
    for tag in tags or []:
        name = _normalize_tag(tag)
        parsed = parse_semver(name)
        if parsed is not None:
            # (core, 1) sorts a release above any pre-release of the same core.
            candidates.append(((parsed, 1, ""), _format_version(parsed)))
            continue
        pre = _PRERELEASE_RE.match(name)
        if pre is not None and allow_prerelease:
            core = tuple(int(part) for part in pre.groups()[:3])
            label = pre.group(4)
            candidates.append(
                ((core, 0, label), f"{_format_version(core)}-{label}")
            )

    if not candidates:
        return {
            "target": None,
            "status": "NO_TAGS",
            "reason": "no published versions found",
        }

    candidates.sort(key=lambda item: item[0])
    best_key, best_display = candidates[-1]
    best_core = best_key[0]

    if best_core > current_version:
        return {
            "target": best_display,
            "status": "OK",
            "reason": (
                f"{best_display} is newer than current "
                f"{_format_version(current_version)}"
            ),
        }
    if best_core == current_version:
        return {
            "target": None,
            "status": "UP_TO_DATE",
            "reason": (
                f"current {_format_version(current_version)} is already the "
                "newest published version"
            ),
        }
    if allow_downgrade:
        return {
            "target": best_display,
            "status": "OK",
            "reason": (
                f"downgrade allowed: {best_display} is older than current "
                f"{_format_version(current_version)}"
            ),
        }
    return {
        "target": None,
        "status": "DOWNGRADE_BLOCKED",
        "reason": (
            f"newest published version {best_display} is older than current "
            f"{_format_version(current_version)}; pass --allow-downgrade to "
            "downgrade explicitly"
        ),
    }


# --------------------------------------------------------------------------- #
# Git runner (injectable; read-only)
# --------------------------------------------------------------------------- #


def _invoke(runner, argv, *, cwd=None, timeout=30):
    """Call ``runner`` with only the keyword arguments it actually accepts.

    The production runner takes ``cwd``/``timeout``; test fakes usually take
    just the argv list. Inspecting the signature keeps both shapes working
    without swallowing errors raised *inside* the runner.
    """
    try:
        parameters = inspect.signature(runner).parameters
    except (TypeError, ValueError):  # builtins / callables without a signature
        parameters = {}
    accepts_kwargs = any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )
    kwargs = {}
    if accepts_kwargs or "cwd" in parameters:
        kwargs["cwd"] = cwd
    if accepts_kwargs or "timeout" in parameters:
        kwargs["timeout"] = timeout
    return runner(argv, **kwargs)


def default_git_runner(git_path=None):
    """Return a read-only git runner bound to ``git_path`` (or ``git``).

    The runner executes the argv list it receives; ``git_path`` only replaces
    ``argv[0]`` so a host without git on ``PATH`` can still use ``--git-path``.
    It captures output and never writes to the repository.
    """

    def runner(argv, *, cwd=None, timeout=30):
        command = [str(part) for part in argv]
        if git_path:
            command[0] = str(git_path)
        return subprocess.run(
            command,
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    return runner


def _tag_result(completed) -> dict:
    """Normalize a ``git ls-remote``/``git tag`` result into the tag contract.

    A usable tag is a release (``X.Y.Z``) or a pre-release (``X.Y.Z-label``),
    with or without the historical ``v`` prefix. Anything else (branch refs,
    ``latest``, malformed versions) is ignored. Names are deduplicated and
    sorted so callers never depend on git's output order.
    """
    returncode = int(getattr(completed, "returncode", 1) or 0)
    stdout = getattr(completed, "stdout", "") or ""
    stderr = getattr(completed, "stderr", "") or ""
    if returncode != 0:
        return {
            "tags": [],
            "error": stderr.strip() or f"git exited with code {returncode}",
        }
    tags: list[str] = []
    for line in stdout.splitlines():
        parts = line.split()
        if not parts:
            continue
        name = _normalize_tag(parts[-1])
        if _SEMVER_RE.match(name) is None and _PRERELEASE_RE.match(name) is None:
            continue
        if name not in tags:
            tags.append(name)
    return {"tags": sorted(tags), "error": None}


def find_tag_for_version(tags, version) -> str | None:
    """Return the tag that publishes ``version`` (preferring ``v<version>``).

    ``tags`` may mix prefixed and unprefixed names; ``None`` means no tag
    publishes that exact version.
    """
    if version is None:
        return None
    version = str(version).strip()
    if not version:
        return None
    normalized = [_normalize_tag(tag) for tag in tags or []]
    for candidate in (f"v{version}", version):
        if candidate in normalized:
            return candidate
    return None


def list_remote_tags(
    runner, *, remote: str = "origin", timeout: int = 30, cwd=None
) -> dict:
    """List published tags from ``remote`` via ``git ls-remote``.

    Returns ``{"tags": [...], "error": None|str}``. An empty remote, a git
    failure and a raised exception all produce ``tags: []`` plus either
    ``error: None`` (genuinely no tags) or a diagnostic string.
    """
    argv = ["git", "ls-remote", "--tags", "--refs", remote]
    try:
        completed = _invoke(runner, argv, cwd=cwd, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - reported, never fatal
        return {"tags": [], "error": f"git ls-remote failed: {exc}"}
    return _tag_result(completed)


def list_local_tags(runner, *, timeout: int = 30, cwd=None) -> dict:
    """List local tags (used by ``--offline``; never touches the network)."""
    argv = ["git", "tag", "--list"]
    try:
        completed = _invoke(runner, argv, cwd=cwd, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - reported, never fatal
        return {"tags": [], "error": f"git tag failed: {exc}"}
    return _tag_result(completed)


# --------------------------------------------------------------------------- #
# Preflight (read-only)
# --------------------------------------------------------------------------- #


def _read_version(target: Path) -> str:
    try:
        return (target / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def preflight(
    target,
    *,
    git_runner=None,
    current_version,
    which=shutil.which,
    require_opencode: bool = True,
) -> dict:
    """Read-only readiness gate; any failed check becomes a blocker.

    Checks (in order): git availability, clean tracked work tree, readable
    ``VERSION`` consistent with ``current_version``, ``SYSTEM.json``
    ``master_system_version`` equal to ``VERSION``, parseable runtime config (if
    present), usable lifecycle state with a supported schema (if present),
    ``opencode`` on ``PATH`` (unless ``require_opencode`` is false), and the
    absence of an interrupted-upgrade marker.

    Returns ``{"status": "PASS"|"BLOCKED", "blockers": [...], "checks": [...]}``.
    It creates nothing: no ``.se/`` directory is ever written here.
    """
    target = Path(target)
    runner = git_runner or default_git_runner()
    which = which or shutil.which
    checks: list[dict] = []
    blockers: list[str] = []

    def record(name: str, ok: bool, detail: str, blocker: str | None = None) -> None:
        checks.append({"name": name, "status": "PASS" if ok else "BLOCKED", "detail": detail})
        if not ok:
            blockers.append(blocker or detail)

    # 1. git binary -----------------------------------------------------------
    git_bin = which("git") if which else None
    if git_bin:
        record("git", True, f"git available: {git_bin}")
    else:
        record(
            "git",
            False,
            "git not found on PATH (use --git-path)",
            "git not found on PATH (use --git-path)",
        )

    # 2. clean tracked work tree ---------------------------------------------
    if git_bin:
        try:
            completed = _invoke(
                runner,
                [
                    "git",
                    "--no-optional-locks",
                    "status",
                    "--porcelain",
                    "--untracked-files=no",
                ],
                cwd=target,
                timeout=30,
            )
        except Exception as exc:  # noqa: BLE001 - reported as a blocker
            record("work_tree", False, f"git status failed: {exc}")
        else:
            returncode = int(getattr(completed, "returncode", 1) or 0)
            stdout = (getattr(completed, "stdout", "") or "").strip()
            stderr = (getattr(completed, "stderr", "") or "").strip()
            if returncode != 0:
                record(
                    "work_tree",
                    False,
                    f"git status exited with code {returncode}: "
                    f"{stderr or 'not a git repository'}",
                )
            elif stdout:
                changed = [line.strip() for line in stdout.splitlines() if line.strip()]
                record(
                    "work_tree",
                    False,
                    "working tree has uncommitted tracked changes: " + ", ".join(changed),
                )
            else:
                record("work_tree", True, "working tree clean (tracked files)")
    else:
        record(
            "work_tree",
            False,
            "cannot verify the working tree without git",
        )

    # 3. VERSION --------------------------------------------------------------
    version_path = target / "VERSION"
    try:
        version = version_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        version = ""
        record("version", False, f"VERSION unreadable: {version_path} ({exc})")
    else:
        if not version:
            record("version", False, f"VERSION is empty: {version_path}")
        elif current_version and version != str(current_version).strip():
            record(
                "version",
                False,
                f"VERSION ({version}) != expected current version "
                f"({current_version})",
            )
        else:
            record("version", True, f"VERSION = {version}")

    # 4. SYSTEM.json coherence ------------------------------------------------
    system_path = target / "SYSTEM.json"
    try:
        system = json.loads(system_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - reported as a blocker
        record("system_json", False, f"SYSTEM.json unreadable: {system_path} ({exc})")
    else:
        master = system.get("master_system_version") if isinstance(system, dict) else None
        if master != version:
            record(
                "system_json",
                False,
                f"SYSTEM.json master_system_version ({master}) != VERSION ({version})",
            )
        else:
            record("system_json", True, f"SYSTEM.json master_system_version = {master}")

    # 5. runtime config -------------------------------------------------------
    config_path = mcpconfig.config_path(target)
    if config_path.exists():
        try:
            mcpconfig.read_config(config_path)
        except Exception as exc:  # noqa: BLE001 - reported as a blocker
            record(
                "config",
                False,
                f"runtime config unparseable ({config_path}): {exc}",
            )
        else:
            record("config", True, f"runtime config parseable: {config_path}")
    else:
        record("config", True, f"no runtime config at {config_path} (nothing to validate)")

    # 6. lifecycle state ------------------------------------------------------
    state_file = lc.state_path(target)
    if not state_file.exists():
        record("state", True, "no lifecycle state (nothing to validate)")
    else:
        state = lc.load_state(target)
        if state is None:
            raw_schema = None
            try:
                raw = json.loads(state_file.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    raw_schema = raw.get("schema_version")
            except Exception:  # noqa: BLE001 - only used to improve the message
                raw_schema = None
            if raw_schema is not None and str(raw_schema) != SUPPORTED_STATE_SCHEMA:
                record(
                    "state",
                    False,
                    f"unsupported lifecycle state schema_version {raw_schema!r} "
                    f"(supported: {SUPPORTED_STATE_SCHEMA})",
                )
            else:
                record(
                    "state",
                    False,
                    f"lifecycle state corrupt or unusable: {state_file}",
                )
        else:
            schema = state.get("schema_version")
            if str(schema) != SUPPORTED_STATE_SCHEMA:
                record(
                    "state",
                    False,
                    f"unsupported lifecycle state schema_version {schema!r} "
                    f"(supported: {SUPPORTED_STATE_SCHEMA})",
                )
            else:
                record("state", True, f"lifecycle state usable (schema {schema})")

    # 7. opencode dependency --------------------------------------------------
    if require_opencode:
        opencode = which("opencode") if which else None
        if opencode:
            record("opencode", True, f"opencode available: {opencode}")
        else:
            record(
                "opencode",
                False,
                "opencode not found on PATH (required for sync; pass --no-sync "
                "to skip the dependency)",
            )
    else:
        record("opencode", True, "opencode check skipped (--no-sync)")

    # 8. interrupted upgrade marker ------------------------------------------
    marker = lc.state_dir(target) / UPGRADE_MARKER
    if marker.exists():
        record(
            "upgrade_marker",
            False,
            f"an interrupted upgrade marker exists: {marker} (resume or roll "
            "back before upgrading)",
        )
    else:
        record("upgrade_marker", True, "no interrupted upgrade marker")

    return {
        "status": "BLOCKED" if blockers else "PASS",
        "blockers": blockers,
        "checks": checks,
    }


# --------------------------------------------------------------------------- #
# Snapshot / verify / restore
# --------------------------------------------------------------------------- #


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_snapshot_paths(target: Path) -> list[Path]:
    """Paths the snapshot tracks as present-or-absent (config, state, ledger)."""
    return [
        mcpconfig.config_path(target),
        lc.state_path(target),
        lc.state_dir(target) / MIGRATIONS_LEDGER,
    ]


def _snapshot_sources(target: Path, include_projects: bool) -> list[Path]:
    """Files captured by default: runtime config, state and migration ledger."""
    sources = [path for path in _canonical_snapshot_paths(target) if path.is_file()]
    if include_projects:
        projects = target / "PROJECTS"
        if projects.is_dir():
            sources.extend(
                sorted(path for path in projects.rglob("*") if path.is_file())
            )
    return sources


def _coerce_now(now) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, datetime):
        moment = now
    else:
        moment = datetime.fromisoformat(str(now).replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def create_snapshot(
    target,
    *,
    from_version: str,
    to_version: str,
    git_head: str,
    include_projects: bool = False,
    now=None,
) -> dict:
    """Create a verified, collision-free snapshot under ``.se/backups/``.

    Layout: ``.se/backups/upgrade-<from>-to-<to>-<utc>-<seq>/`` with a
    ``manifest.json`` (hashes per file, plus the canonical config/state/ledger
    paths that did not exist and must stay absent after a rollback) plus byte
    copies of the runtime config and lifecycle state. ``PROJECTS/`` is copied
    only when explicitly requested. The sequence suffix makes two snapshots in
    the same second distinct.
    """
    target = Path(target)
    moment = _coerce_now(now)
    stamp = moment.strftime("%Y%m%dT%H%M%SZ")
    created_at = moment.strftime("%Y-%m-%dT%H:%M:%SZ")

    backups = lc.backup_dir(target)
    prefix = f"upgrade-{from_version}-to-{to_version}-{stamp}"
    sequence = 1
    while (backups / f"{prefix}-{sequence:02d}").exists():
        sequence += 1
    snapshot_dir = backups / f"{prefix}-{sequence:02d}"
    snapshot_dir.mkdir(parents=True, exist_ok=False)

    files: list[dict] = []
    for source in _snapshot_sources(target, include_projects):
        relative = source.relative_to(target).as_posix()
        destination = snapshot_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = source.read_bytes()
        destination.write_bytes(payload)
        files.append(
            {
                "path": relative,
                "sha256": _sha256_bytes(payload),
                "bytes": len(payload),
            }
        )

    # Files that must not exist after a rollback: if they were absent before the
    # upgrade, anything the upgrade creates at these canonical paths is undone.
    absent = [
        path.relative_to(target).as_posix()
        for path in _canonical_snapshot_paths(target)
        if not path.is_file()
    ]

    manifest = {
        "schema_version": "1",
        "operation": "upgrade",
        "from_version": from_version,
        "to_version": to_version,
        "created_at": created_at,
        "git_head_before": git_head,
        "state_schema": SUPPORTED_STATE_SCHEMA,
        "include_projects": bool(include_projects),
        "files": files,
        "absent": absent,
    }
    manifest_path = snapshot_dir / "manifest.json"
    write_json_atomic(manifest_path, manifest)
    return {
        "snapshot_dir": str(snapshot_dir),
        "manifest_path": str(manifest_path),
        "manifest": manifest,
        "files": files,
        "absent": absent,
    }


def _load_manifest(snapshot_dir: Path) -> dict:
    return json.loads((snapshot_dir / "manifest.json").read_text(encoding="utf-8"))


def verify_snapshot(snapshot_dir) -> dict:
    """Verify every file in ``manifest.json`` against its recorded sha256."""
    snapshot_dir = Path(snapshot_dir)
    manifest_path = snapshot_dir / "manifest.json"
    if not manifest_path.exists():
        return {"ok": False, "errors": [f"manifest not found: {manifest_path}"]}
    try:
        manifest = _load_manifest(snapshot_dir)
    except Exception as exc:  # noqa: BLE001 - reported, never trusted
        return {"ok": False, "errors": [f"manifest unreadable ({manifest_path}): {exc}"]}

    entries = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(entries, list):
        return {"ok": False, "errors": ["manifest has no files list"]}

    errors: list[str] = []
    root = snapshot_dir.resolve()
    for entry in entries:
        entry = entry if isinstance(entry, dict) else {}
        relative = str(entry.get("path") or "")
        expected = str(entry.get("sha256") or "")
        if not relative:
            errors.append("manifest entry without path")
            continue
        candidate = (snapshot_dir / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            errors.append(f"manifest path escapes the snapshot: {relative}")
            continue
        if not candidate.is_file():
            errors.append(f"snapshot file missing: {relative}")
            continue
        payload = candidate.read_bytes()
        actual = _sha256_bytes(payload)
        if actual != expected:
            errors.append(
                f"sha256 mismatch for {relative}: expected {expected}, got {actual}"
            )
        recorded_bytes = entry.get("bytes")
        if isinstance(recorded_bytes, int) and recorded_bytes != len(payload):
            errors.append(
                f"size mismatch for {relative}: expected {recorded_bytes}, "
                f"got {len(payload)}"
            )
    return {"ok": not errors, "errors": errors}


def restore_snapshot(snapshot_dir, *, force: bool = False) -> dict:
    """Restore a verified snapshot, refusing to overwrite unrecorded changes.

    Verification runs first. A destination file is restored when it is absent,
    when its current sha256 equals the snapshot's, or when ``force`` is true;
    otherwise it is skipped and reported. Files that are not in the manifest are
    never deleted.
    """
    snapshot_dir = Path(snapshot_dir)
    verification = verify_snapshot(snapshot_dir)
    if not verification["ok"]:
        return {
            "ok": False,
            "restored": [],
            "skipped": [],
            "hashes": {},
            "errors": list(verification["errors"]),
        }

    try:
        manifest = _load_manifest(snapshot_dir)
    except Exception as exc:  # noqa: BLE001 - reported, never trusted
        return {
            "ok": False,
            "restored": [],
            "skipped": [],
            "hashes": {},
            "errors": [f"manifest unreadable: {exc}"],
        }

    resolved = snapshot_dir.resolve()
    try:
        target = resolved.parents[2]  # <target>/.se/backups/<snapshot>
    except IndexError:
        return {
            "ok": False,
            "restored": [],
            "skipped": [],
            "hashes": {},
            "errors": [
                "cannot derive the target root from the snapshot path: "
                f"{snapshot_dir}"
            ],
        }

    restored: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []
    hashes: dict[str, str] = {}
    for entry in manifest.get("files") or []:
        entry = entry if isinstance(entry, dict) else {}
        relative = str(entry.get("path") or "")
        expected = str(entry.get("sha256") or "")
        if not relative:
            errors.append("manifest entry without path")
            continue
        source = snapshot_dir / relative
        destination = target / relative
        try:
            payload = source.read_bytes()
        except OSError as exc:
            errors.append(f"cannot read snapshot file {relative}: {exc}")
            continue
        if destination.exists():
            try:
                current_hash = _sha256_bytes(destination.read_bytes())
            except OSError as exc:
                errors.append(f"cannot read current {relative}: {exc}")
                continue
            if current_hash != expected and not force:
                skipped.append(relative)
                errors.append(
                    f"refusing to overwrite {relative}: current sha256 "
                    f"{current_hash} != snapshot {expected} (pass force to "
                    "overwrite)"
                )
                continue
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
        except OSError as exc:
            errors.append(f"cannot restore {relative}: {exc}")
            continue
        restored.append(relative)
        hashes[relative] = _sha256_bytes(destination.read_bytes())

    return {
        "ok": not errors and not skipped,
        "restored": restored,
        "skipped": skipped,
        "hashes": hashes,
        "errors": errors,
    }


def _remove_absent_paths(target, snapshot_dir) -> dict:
    """Delete the canonical paths the manifest recorded as absent.

    Only ``manifest["absent"]`` is considered; paths outside ``target`` (absolute
    paths, ``..`` traversal or symlinks resolving elsewhere) are rejected and
    never removed. Directories are refused: the tracked entries are files.
    Returns ``{"removed": [relative...], "errors": [str...]}``.
    """
    target = Path(target)
    snapshot_dir = Path(snapshot_dir)
    result: dict = {"removed": [], "errors": []}
    try:
        manifest = _load_manifest(snapshot_dir)
    except Exception as exc:  # noqa: BLE001 - reported, never trusted
        result["errors"].append(f"manifest unreadable: {exc}")
        return result
    entries = manifest.get("absent") if isinstance(manifest, dict) else None
    if not isinstance(entries, list):
        # Manifests written before absence tracking have nothing to undo.
        return result

    root = target.resolve()
    for raw in entries:
        relative = str(raw or "").strip()
        if not relative:
            result["errors"].append("manifest absent entry without path")
            continue
        candidate = Path(relative)
        if candidate.is_absolute():
            result["errors"].append(
                f"refusing to remove an absolute absent path: {relative}"
            )
            continue
        destination = (target / candidate).resolve()
        try:
            destination.relative_to(root)
        except ValueError:
            result["errors"].append(
                f"absent path escapes the target: {relative}"
            )
            continue
        if destination.is_dir() and not destination.is_symlink():
            result["errors"].append(
                f"refusing to remove a directory recorded as absent: {relative}"
            )
            continue
        if destination.is_symlink() or destination.exists():
            try:
                destination.unlink()
            except OSError as exc:
                result["errors"].append(f"cannot remove {relative}: {exc}")
                continue
            result["removed"].append(candidate.as_posix())
    return result


# --------------------------------------------------------------------------- #
# Migrations
# --------------------------------------------------------------------------- #


def _ledger_path(target: Path) -> Path:
    return lc.state_dir(target) / MIGRATIONS_LEDGER


def _read_migrations_ledger(target: Path) -> tuple[dict | None, str | None]:
    """Read ``.se/migrations.json``; ``(ledger, error)`` with fail-closed errors."""
    path = _ledger_path(target)
    if not path.is_file():
        return {"schema_version": "1", "applied": []}, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - reported, never trusted
        return None, f"migrations ledger unreadable ({path}): {exc}"
    if not isinstance(data, dict):
        return None, f"migrations ledger is not an object: {path}"
    if str(data.get("schema_version")) != "1":
        return (
            None,
            f"unsupported migrations ledger schema_version "
            f"{data.get('schema_version')!r} (supported: 1)",
        )
    applied = data.get("applied")
    if not isinstance(applied, list):
        return None, f"migrations ledger has no applied list: {path}"
    for entry in applied:
        if not isinstance(entry, dict) or not str(entry.get("id") or "").strip():
            return None, f"migrations ledger has an invalid applied entry: {path}"
    return {"schema_version": "1", "applied": list(applied)}, None


def _discover_migrations(directory: Path) -> tuple[list[dict], list[str]]:
    """Load ``*.py`` migrations (ignoring ``_*.py``) in filename order.

    Returns ``(modules, errors)``. A module is usable only when it exposes a
    non-empty string ``ID`` and a callable ``migrate(root, context)``; anything
    else is an error (fail-closed) and no migration runs.
    """
    modules: list[dict] = []
    errors: list[str] = []
    paths = sorted(directory.glob("*.py"), key=lambda path: path.name)
    for index, path in enumerate(paths):
        if path.name.startswith("_"):
            continue
        safe_stem = re.sub(r"[^0-9A-Za-z_]", "_", path.stem)
        module_name = f"se_migration_{index}_{safe_stem}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                errors.append(f"{path.name}: cannot create an import spec")
                continue
            module = importlib.util.module_from_spec(spec)
            # Importing a migration must not leave ``MIGRATIONS/__pycache__``
            # behind in the target: the upgrade has to be side-effect free
            # outside the snapshot and its own bookkeeping.
            previous_bytecode = sys.dont_write_bytecode
            sys.dont_write_bytecode = True
            try:
                spec.loader.exec_module(module)
            finally:
                sys.dont_write_bytecode = previous_bytecode
        except Exception as exc:  # noqa: BLE001 - reported, never guessed
            errors.append(f"{path.name}: import failed ({exc})")
            continue
        identifier = getattr(module, "ID", None)
        migrate = getattr(module, "migrate", None)
        if not isinstance(identifier, str) or not identifier.strip():
            errors.append(f"{path.name}: missing a non-empty string ID")
            continue
        if not callable(migrate):
            errors.append(f"{path.name}: migrate(root, context) is not callable")
            continue
        modules.append(
            {"path": path, "id": identifier.strip(), "migrate": migrate}
        )

    seen: dict[str, str] = {}
    for item in modules:
        if item["id"] in seen:
            errors.append(
                f"duplicate migration ID {item['id']!r}: "
                f"{seen[item['id']]} and {item['path'].name}"
            )
        else:
            seen[item["id"]] = item["path"].name
    return modules, errors


def run_migrations(
    target,
    *,
    from_version: str,
    to_version: str,
    migrations_dir=None,
    now=None,
    git_head_before=None,
) -> dict:
    """Apply pending migrations in filename order, recording a durable ledger.

    * directory defaults to ``<target>/MIGRATIONS``; absent means a no-op;
    * every module needs a non-empty string ``ID`` and ``migrate(root, context)``;
    * IDs already recorded in ``.se/migrations.json`` are skipped (idempotence);
    * the ledger is rewritten atomically after **each** successful migration, so
      a crash never loses an applied step;
    * a raising migration propagates :class:`MigrationError` (the orchestrator
      rolls the upgrade back).

    Returns ``{"applied": [id...], "skipped": [id...], "errors": [str...]}``.
    ``errors`` is non-empty only for discovery/ledger problems; the caller must
    treat it as a failure and roll back.
    """
    target = Path(target)
    directory = (
        Path(migrations_dir) if migrations_dir is not None else target / MIGRATIONS_DIRNAME
    )
    result: dict = {"applied": [], "skipped": [], "errors": []}
    if not directory.is_dir():
        return result

    ledger, ledger_error = _read_migrations_ledger(target)
    if ledger_error:
        result["errors"].append(ledger_error)
        return result

    modules, errors = _discover_migrations(directory)
    if errors:
        result["errors"].extend(errors)
        return result

    if git_head_before is None:
        marker = read_marker(target)
        if marker is not None:
            git_head_before = marker.get("git_head_before")

    context = {
        "from_version": from_version,
        "to_version": to_version,
        "target": str(target),
        "git_head_before": git_head_before,
    }
    applied_ids = {str(entry.get("id")) for entry in ledger["applied"]}
    timestamp = _coerce_now(now).strftime("%Y-%m-%dT%H:%M:%SZ")

    for module in modules:
        identifier = module["id"]
        if identifier in applied_ids:
            result["skipped"].append(identifier)
            continue
        try:
            module["migrate"](target, context)
        except Exception as exc:  # noqa: BLE001 - propagate with the ID attached
            raise MigrationError(
                f"migration {identifier} failed: {exc}"
            ) from exc
        ledger["applied"].append(
            {
                "id": identifier,
                "version": to_version,
                "applied_at": timestamp,
            }
        )
        try:
            write_json_atomic(_ledger_path(target), ledger)
        except Exception as exc:  # noqa: BLE001 - a lost ledger is fatal
            raise MigrationError(
                f"migration {identifier} applied but the ledger could not be "
                f"written: {exc}"
            ) from exc
        applied_ids.add(identifier)
        result["applied"].append(identifier)
    return result


# --------------------------------------------------------------------------- #
# Marker / history / git helpers
# --------------------------------------------------------------------------- #


def marker_path(target) -> Path:
    """Return ``<target>/.se/upgrade-in-progress.json``."""
    return lc.state_dir(target) / UPGRADE_MARKER


def write_marker(target, marker: dict) -> None:
    """Persist the in-progress marker atomically (LF JSON)."""
    write_json_atomic(marker_path(target), marker)


def read_marker(target) -> dict | None:
    """Read the marker; ``None`` when absent or unreadable."""
    path = marker_path(target)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - treated as "unreadable"
        return None
    return data if isinstance(data, dict) else None


def delete_marker(target) -> bool:
    """Delete the marker; ``True`` when it is gone afterwards."""
    path = marker_path(target)
    try:
        if path.exists():
            path.unlink()
    except OSError:
        return False
    return not path.exists()


def history_path(target) -> Path:
    """Return ``<target>/.se/upgrade-history.jsonl``."""
    return lc.state_dir(target) / UPGRADE_HISTORY


def _append_history(target, record: dict) -> str:
    path = history_path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
    return str(path)


def read_history(target) -> list[dict]:
    """Read the append-only upgrade history (unreadable lines are skipped)."""
    path = history_path(target)
    if not path.is_file():
        return []
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except Exception:  # noqa: BLE001 - audit trail is best-effort on read
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _git(runner, argv, *, cwd, timeout=30):
    return _invoke(runner, argv, cwd=cwd, timeout=timeout)


def _git_rev_parse(runner, target, ref: str) -> str:
    completed = _git(runner, ["git", "rev-parse", ref], cwd=target)
    returncode = int(getattr(completed, "returncode", 1) or 0)
    if returncode != 0:
        stderr = (getattr(completed, "stderr", "") or "").strip()
        raise UpgradeError(
            f"git rev-parse {ref} failed: {stderr or f'exit code {returncode}'}"
        )
    value = (getattr(completed, "stdout", "") or "").strip()
    if not value:
        raise UpgradeError(f"git rev-parse {ref} returned no commit")
    return value


def _safe_rev_parse(runner, target, ref: str) -> str | None:
    try:
        return _git_rev_parse(runner, target, ref)
    except UpgradeError:
        return None


def _tail(text, limit: int = 20) -> list[str]:
    return str(text or "").splitlines()[-limit:]


def _last_line(step: dict) -> str:
    tail = step.get("tail") or []
    return tail[-1] if tail else f"exit code {step.get('rc')}"


def _parse_doctor_payload(step: dict) -> tuple[str | None, dict | None, list[dict]]:
    """Extract ``status``, ``details.summary`` and ``details.checks``.

    Anything unparseable is reported as ``(None, None, [])`` so the caller fails
    closed instead of trusting a partial payload.
    """
    try:
        payload = json.loads(step.get("stdout") or "")
    except Exception:  # noqa: BLE001 - reported as a failed verification
        return None, None, []
    if not isinstance(payload, dict):
        return None, None, []

    status = payload.get("status")
    summary = None
    checks: list[dict] = []
    raw_details = payload.get("details")
    if isinstance(raw_details, dict):
        candidate = raw_details.get("summary")
        if isinstance(candidate, dict):
            summary = candidate
        raw_checks = raw_details.get("checks")
        if isinstance(raw_checks, list):
            checks = [item for item in raw_checks if isinstance(item, dict)]
    if not checks:
        # The envelope also exposes one ``"<id>: <detail>"`` line per WARN at the
        # top level; use it when the detailed check list is absent.
        raw_warnings = payload.get("warnings")
        if isinstance(raw_warnings, list):
            checks = [
                {"status": "WARN", "detail": str(item)} for item in raw_warnings
            ]
    return status, summary, checks


def _doctor_warn_text(
    status, summary, checks, *, limit: int = 3
) -> str:
    """Deterministic one-line warning naming at most ``limit`` WARN checks."""
    parts: list[str] = []
    for check in checks or []:
        if not isinstance(check, dict) or check.get("status") != "WARN":
            continue
        identifier = str(check.get("id") or "").strip()
        detail = str(check.get("detail") or "").strip()
        if identifier and detail:
            parts.append(f"{identifier}: {detail}")
        elif detail:
            parts.append(detail)
        elif identifier:
            parts.append(identifier)
        if len(parts) == limit:
            break
    if parts:
        return "doctor reported WARN: " + "; ".join(parts)
    if isinstance(summary, dict):
        return (
            "doctor reported WARN: "
            f"PASS={summary.get('PASS')} WARN={summary.get('WARN')} "
            f"FAIL={summary.get('FAIL')}"
        )
    return f"doctor reported status {status!r}"


def _step_record(step: dict) -> dict:
    return {"name": step["name"], "rc": step["rc"], "tail": list(step["tail"])}


def default_step_runner(argv, *, cwd=None):
    """Run one orchestrated step (``se adapter`` / ``se sync`` / ``se doctor``)."""
    return subprocess.run(
        [str(part) for part in argv],
        cwd=str(cwd) if cwd is not None else None,
        text=True,
        capture_output=True,
        timeout=600,
    )


def _execute_step(step_runner, name: str, argv, *, cwd) -> dict:
    completed = step_runner([str(part) for part in argv], cwd=cwd)
    returncode = int(getattr(completed, "returncode", 1) or 0)
    stdout = getattr(completed, "stdout", "") or ""
    stderr = getattr(completed, "stderr", "") or ""
    separator = "\n" if stdout and stderr else ""
    return {
        "name": name,
        "argv": [str(part) for part in argv],
        "rc": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "tail": _tail(stdout + separator + stderr),
    }


def _untracked_files(runner, target) -> list[str]:
    """Read-only list of untracked files (never deleted by a rollback)."""
    try:
        completed = _git(
            runner,
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=target,
        )
    except Exception:  # noqa: BLE001 - read-only audit, best effort
        return []
    returncode = int(getattr(completed, "returncode", 1) or 0)
    if returncode != 0:
        return []
    files = []
    for line in (getattr(completed, "stdout", "") or "").splitlines():
        if line.startswith("?? "):
            files.append(line[3:].strip())
    return sorted(files)


def _verify_restored_hashes(snapshot_dir) -> tuple[bool, list[str]]:
    """Re-hash every manifest file after a restore."""
    snapshot_dir = Path(snapshot_dir)
    try:
        manifest = _load_manifest(snapshot_dir)
    except Exception as exc:  # noqa: BLE001 - reported, never trusted
        return False, [f"manifest unreadable: {exc}"]
    try:
        target = snapshot_dir.resolve().parents[2]
    except IndexError:
        return False, [f"cannot derive the target root from {snapshot_dir}"]
    errors: list[str] = []
    for entry in manifest.get("files") or []:
        entry = entry if isinstance(entry, dict) else {}
        relative = str(entry.get("path") or "")
        expected = str(entry.get("sha256") or "")
        if not relative:
            errors.append("manifest entry without path")
            continue
        destination = target / relative
        try:
            actual = _sha256_bytes(destination.read_bytes())
        except OSError as exc:
            errors.append(f"cannot verify restored {relative}: {exc}")
            continue
        if expected and actual != expected:
            errors.append(
                f"restored hash mismatch for {relative}: expected {expected}, "
                f"got {actual}"
            )
    return not errors, errors


# --------------------------------------------------------------------------- #
# Rollback (the only place that may reset --hard)
# --------------------------------------------------------------------------- #


def rollback_upgrade(target, marker, *, git_runner, step_runner=None) -> dict:
    """Undo an in-progress upgrade, fail-closed and hash-verified.

    Order:

    1. verify the snapshot (a corrupt snapshot aborts **before** any reset);
    2. ``git reset --hard <git_head_before>`` only when ``HEAD`` actually moved;
    3. restore the snapshot with ``force=True`` and verify every sha256;
    4. verify ``HEAD == git_head_before``;
    5. delete the marker and append a ``rolled_back`` history record.

    Untracked files are never deleted; they are reported in
    ``residual_untracked``. Paths the snapshot recorded as absent (config, state
    or ledger) are removed after the restore, so the pre-upgrade state is intact
    even when the upgrade created them. Returns
    ``{"ok","git_reset","snapshot_restore","removed_absent","errors",
    "head_before","head_after","residual_untracked"}``.
    """
    target = Path(target)
    if not isinstance(marker, dict):
        try:
            marker = json.loads(Path(marker).read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - reported, never trusted
            return {
                "ok": False,
                "git_reset": False,
                "snapshot_restore": None,
                "removed_absent": [],
                "errors": [f"upgrade marker unreadable: {exc}"],
                "head_before": None,
                "head_after": None,
                "residual_untracked": [],
            }

    snapshot = marker.get("snapshot")
    head_before = marker.get("git_head_before")
    result: dict = {
        "ok": False,
        "git_reset": False,
        "snapshot_restore": None,
        "removed_absent": [],
        "errors": [],
        "head_before": head_before,
        "head_after": None,
        "residual_untracked": [],
    }

    verification = (
        verify_snapshot(snapshot)
        if snapshot
        else {"ok": False, "errors": ["upgrade marker has no snapshot"]}
    )
    if not verification["ok"]:
        result["errors"].extend(verification["errors"])
        result["snapshot_restore"] = {
            "ok": False,
            "restored": [],
            "skipped": [],
            "hashes": {},
            "errors": list(verification["errors"]),
        }
        result["head_after"] = _safe_rev_parse(git_runner, target, "HEAD")
        result["residual_untracked"] = _untracked_files(git_runner, target)
        return result

    head_now = _safe_rev_parse(git_runner, target, "HEAD")
    if not head_before:
        result["errors"].append("upgrade marker has no git_head_before")
    if head_now is None:
        result["errors"].append("cannot read HEAD before rollback")
    elif head_before and head_now != head_before:
        completed = _git(
            git_runner,
            ["git", "reset", "--hard", str(head_before)],
            cwd=target,
            timeout=120,
        )
        returncode = int(getattr(completed, "returncode", 1) or 0)
        if returncode != 0:
            stderr = (getattr(completed, "stderr", "") or "").strip()
            result["errors"].append(
                f"git reset --hard {head_before} failed: "
                f"{stderr or f'exit code {returncode}'}"
            )
        else:
            result["git_reset"] = True

    restore = restore_snapshot(snapshot, force=True)
    result["snapshot_restore"] = restore
    if not restore["ok"]:
        result["errors"].extend(restore["errors"])

    hashes_ok, hash_errors = _verify_restored_hashes(snapshot)
    if not hashes_ok:
        result["errors"].extend(hash_errors)

    absent = _remove_absent_paths(target, snapshot)
    result["removed_absent"] = absent["removed"]
    result["errors"].extend(absent["errors"])

    head_after = _safe_rev_parse(git_runner, target, "HEAD")
    result["head_after"] = head_after
    if head_before and head_after != head_before:
        result["errors"].append(
            f"HEAD after rollback ({head_after}) != git_head_before "
            f"({head_before})"
        )

    result["residual_untracked"] = _untracked_files(git_runner, target)

    if not result["errors"]:
        if not delete_marker(target):
            result["errors"].append("could not delete the upgrade marker")

    record = {
        "schema_version": "1",
        "operation": "upgrade",
        "status": "rolled_back",
        "from": marker.get("from"),
        "to": marker.get("to"),
        "tag": marker.get("tag"),
        "git_head_before": head_before,
        "git_head_after": head_after,
        "snapshot": snapshot,
        "phase": marker.get("phase"),
        "rollback": {
            "ok": not result["errors"],
            "git_reset": result["git_reset"],
            "errors": list(result["errors"]),
        },
    }
    try:
        _append_history(target, record)
    except OSError as exc:
        result["errors"].append(f"could not append upgrade history: {exc}")

    result["ok"] = not result["errors"]
    return result


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


def _new_details(target, *, mode, offline, include_projects) -> dict:
    return {
        "mode": mode,
        "target": str(target),
        "offline": offline,
        "include_projects": include_projects,
        "current_version": None,
        "tags": [],
        "selection": None,
        "preflight": None,
        "snapshot": None,
        "snapshot_restore": None,
        "git_head_before": None,
        "git_head_after": None,
        "phases": [],
        "migrations": None,
        "doctor": None,
        "steps": [],
        "rollback": None,
        "warnings": [],
        "writes": [],
        "blockers": [],
        "marker": None,
        "history": None,
        "message": None,
    }


def _resolve_selection(
    target,
    details,
    *,
    runner,
    offline,
    current_version,
    allow_prerelease,
    allow_downgrade,
):
    """Fill ``details`` with tags + selection; return the selection or ``None``."""
    tag_result = (
        list_local_tags(runner, cwd=target)
        if offline
        else list_remote_tags(runner, cwd=target)
    )
    details["tags"] = tag_result["tags"]
    if tag_result["error"]:
        details["tag_error"] = tag_result["error"]

    if not tag_result["tags"]:
        details["selection"] = {
            "target": None,
            "status": "NO_TAGS",
            "reason": (
                "no local tags found (offline)"
                if offline
                else "no published versions found"
            ),
        }
        return details["selection"]

    try:
        selection = select_target_version(
            tag_result["tags"],
            current_version,
            allow_prerelease=allow_prerelease,
            allow_downgrade=allow_downgrade,
        )
    except ValueError as exc:
        details["blockers"].append(str(exc))
        return None
    details["selection"] = selection
    return selection


def _run_check(
    target,
    details,
    *,
    runner,
    which,
    offline,
    allow_downgrade,
    allow_prerelease,
    no_sync,
):
    """``--check`` / ``--dry-run``: resolve and report, never write."""
    current_version = _read_version(target)
    details["current_version"] = current_version or None

    preflight_result = preflight(
        target,
        git_runner=runner,
        current_version=current_version,
        which=which,
        require_opencode=not no_sync,
    )
    details["preflight"] = preflight_result
    if preflight_result["status"] != "PASS":
        details["blockers"].extend(preflight_result["blockers"])
        details["status"] = "BLOCKED"
        return details

    selection = _resolve_selection(
        target,
        details,
        runner=runner,
        offline=offline,
        current_version=current_version,
        allow_prerelease=allow_prerelease,
        allow_downgrade=allow_downgrade,
    )
    if selection is None:
        details["status"] = "BLOCKED"
        return details

    if selection["status"] == "DOWNGRADE_BLOCKED":
        details["blockers"].append(selection["reason"])
        details["status"] = "BLOCKED"
    elif selection["status"] == "NO_TAGS":
        details["status"] = "UNKNOWN"
    elif selection["status"] == "UP_TO_DATE":
        details["status"] = "INFO"
    else:
        details["status"] = "PASS"
    return details


def _run_recover(target, details, *, git_runner, step_runner=None, now=None) -> dict:
    """``--recover``: restore a marker left by an interrupted upgrade.

    Runs **before** the preflight (which would otherwise block on the marker).
    """
    path = marker_path(target)
    details["marker"] = str(path)
    marker = read_marker(target)
    if marker is None:
        if not path.exists():
            details["message"] = "nothing to recover"
            details["status"] = "INFO"
            return details
        details["blockers"].append(
            f"interrupted upgrade marker is unreadable: {path}"
        )
        details["status"] = "BLOCKED"
        return details

    snapshot = marker.get("snapshot")
    head_before = marker.get("git_head_before")
    details["git_head_before"] = head_before
    details["snapshot"] = {"snapshot_dir": str(snapshot)} if snapshot else None

    if not head_before:
        details["blockers"].append(
            "interrupted upgrade marker has no git_head_before; refusing to "
            "reset HEAD, restore the snapshot or delete the marker"
        )
        details["status"] = "BLOCKED"
        return details

    if not snapshot:
        details["blockers"].append("interrupted upgrade marker has no snapshot")
        details["status"] = "BLOCKED"
        return details

    verification = verify_snapshot(snapshot)
    if not verification["ok"]:
        details["blockers"].extend(verification["errors"])
        details["status"] = "BLOCKED"
        return details

    head_now = _safe_rev_parse(git_runner, target, "HEAD")
    if head_now is None:
        details["blockers"].append("cannot read HEAD before recovery")
        details["status"] = "BLOCKED"
        return details
    if head_before and head_now != head_before:
        completed = _git(
            git_runner,
            ["git", "reset", "--hard", str(head_before)],
            cwd=target,
            timeout=120,
        )
        returncode = int(getattr(completed, "returncode", 1) or 0)
        if returncode != 0:
            stderr = (getattr(completed, "stderr", "") or "").strip()
            details["blockers"].append(
                f"git reset --hard {head_before} failed: "
                f"{stderr or f'exit code {returncode}'}"
            )
            details["status"] = "BLOCKED"
            return details

    restore = restore_snapshot(snapshot, force=True)
    details["snapshot_restore"] = restore
    if not restore["ok"]:
        details["blockers"].extend(restore["errors"])
        details["status"] = "BLOCKED"
        return details

    hashes_ok, hash_errors = _verify_restored_hashes(snapshot)
    if not hashes_ok:
        details["blockers"].extend(hash_errors)
        details["status"] = "BLOCKED"
        return details

    absent = _remove_absent_paths(target, snapshot)
    details["removed_absent"] = absent["removed"]
    if absent["errors"]:
        details["blockers"].extend(absent["errors"])
        details["status"] = "BLOCKED"
        return details

    head_after = _safe_rev_parse(git_runner, target, "HEAD")
    details["git_head_after"] = head_after
    if head_before and head_after != head_before:
        details["blockers"].append(
            f"HEAD after recovery ({head_after}) != git_head_before "
            f"({head_before})"
        )
        details["status"] = "BLOCKED"
        return details

    if not delete_marker(target):
        details["warnings"].append(
            f"could not delete the upgrade marker: {path}"
        )

    record = {
        "schema_version": "1",
        "operation": "upgrade",
        "status": "recovered",
        "from": marker.get("from"),
        "to": marker.get("to"),
        "tag": marker.get("tag"),
        "git_head_before": head_before,
        "git_head_after": head_after,
        "snapshot": snapshot,
        "phase": marker.get("phase"),
        "finished_at": _coerce_now(now).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    try:
        details["history"] = _append_history(target, record)
    except OSError as exc:
        details["warnings"].append(f"could not append upgrade history: {exc}")

    details["status"] = "PASS"
    return details


def _run_execute(
    target,
    details,
    *,
    git_runner,
    step_runner,
    which,
    migrations_dir,
    now,
    offline,
    include_projects,
    allow_downgrade,
    allow_prerelease,
    no_sync,
) -> dict:
    """Perform the upgrade: marker -> fetch -> ff -> migrations -> adapters ->
    sync -> doctor, rolling back on any failure."""
    path = marker_path(target)
    details["marker"] = str(path)
    if path.exists():
        details["blockers"].append(
            f"interrupted upgrade detected: {path}; run se upgrade --recover"
        )
        details["status"] = "BLOCKED"
        return details

    current_version = _read_version(target)
    details["current_version"] = current_version or None
    preflight_result = preflight(
        target,
        git_runner=git_runner,
        current_version=current_version,
        which=which,
        require_opencode=not no_sync,
    )
    details["preflight"] = preflight_result
    if preflight_result["status"] != "PASS":
        details["blockers"].extend(preflight_result["blockers"])
        details["status"] = "BLOCKED"
        return details

    selection = _resolve_selection(
        target,
        details,
        runner=git_runner,
        offline=offline,
        current_version=current_version,
        allow_prerelease=allow_prerelease,
        allow_downgrade=allow_downgrade,
    )
    if selection is None:
        details["status"] = "BLOCKED"
        return details
    if selection["status"] == "DOWNGRADE_BLOCKED":
        details["blockers"].append(selection["reason"])
        details["status"] = "BLOCKED"
        return details
    if selection["status"] == "NO_TAGS":
        details["status"] = "UNKNOWN"
        return details
    if selection["status"] == "UP_TO_DATE":
        details["status"] = "INFO"
        return details

    to_version = selection["target"]
    tag = find_tag_for_version(details["tags"], to_version)
    if tag is None:
        details["blockers"].append(f"no tag publishes version {to_version}")
        details["status"] = "BLOCKED"
        return details

    try:
        head_before = _git_rev_parse(git_runner, target, "HEAD")
    except UpgradeError as exc:
        details["blockers"].append(str(exc))
        details["status"] = "BLOCKED"
        return details
    details["git_head_before"] = head_before

    snapshot = create_snapshot(
        target,
        from_version=current_version,
        to_version=to_version,
        git_head=head_before,
        include_projects=include_projects,
        now=now,
    )
    details["snapshot"] = snapshot
    details["writes"].append(snapshot["snapshot_dir"])

    started_at = _coerce_now(now).strftime("%Y-%m-%dT%H:%M:%SZ")
    marker = {
        "schema_version": "1",
        "from": current_version,
        "to": to_version,
        "tag": tag,
        "git_head_before": head_before,
        "snapshot": snapshot["snapshot_dir"],
        "started_at": started_at,
        "phase": "fetch",
    }
    try:
        write_marker(target, marker)
    except Exception as exc:  # noqa: BLE001 - reported; nothing mutated yet
        details["blockers"].append(f"cannot write the upgrade marker: {exc}")
        details["status"] = "FAIL"
        return details
    details["writes"].append(str(path))

    steps: list[dict] = []
    migrations = None
    runner_step = step_runner if step_runner is not None else default_step_runner
    se_py = target / "SCRIPTS" / "se.py"

    def phase(name: str) -> None:
        marker["phase"] = name
        try:
            write_marker(target, marker)
        except Exception as exc:  # noqa: BLE001 - abort through the rollback
            raise UpgradeError(
                f"cannot update the upgrade marker phase {name!r}: {exc}"
            ) from exc

    def fail(message: str) -> dict:
        details["blockers"].append(message)
        rolled = rollback_upgrade(
            target, marker, git_runner=git_runner, step_runner=step_runner
        )
        details["rollback"] = rolled
        details["git_head_after"] = rolled.get("head_after")
        for error in rolled.get("errors") or []:
            details["blockers"].append(f"rollback: {error}")
        details["status"] = "FAIL"
        return details

    def run_step(name: str, argv) -> dict:
        step = _execute_step(runner_step, name, argv, cwd=target)
        steps.append(_step_record(step))
        details["steps"].append(_step_record(step))
        return step

    def run_git_step(name: str, argv, *, timeout: int = 120) -> dict:
        completed = _git(git_runner, argv, cwd=target, timeout=timeout)
        returncode = int(getattr(completed, "returncode", 1) or 0)
        stdout = getattr(completed, "stdout", "") or ""
        stderr = getattr(completed, "stderr", "") or ""
        separator = "\n" if stdout and stderr else ""
        step = {
            "name": name,
            "argv": [str(part) for part in argv],
            "rc": returncode,
            "stdout": stdout,
            "stderr": stderr,
            "tail": _tail(stdout + separator + stderr),
        }
        steps.append(_step_record(step))
        details["steps"].append(_step_record(step))
        return step

    # 1. fetch -------------------------------------------------------------
    try:
        phase("fetch")
    except UpgradeError as exc:
        return fail(str(exc))
    if offline:
        details["phases"].append({"name": "fetch", "status": "SKIPPED"})
    else:
        step = run_git_step(
            "fetch", ["git", "fetch", "--tags", "--prune", "origin"]
        )
        if step["rc"] != 0:
            return fail(f"git fetch failed: {_last_line(step)}")
        details["phases"].append({"name": "fetch", "status": "PASS"})

    # 2. ff-only advance ---------------------------------------------------
    try:
        phase("advance")
    except UpgradeError as exc:
        return fail(str(exc))
    step = run_git_step("advance", ["git", "merge", "--ff-only", tag])
    if step["rc"] != 0:
        return fail(
            f"git merge --ff-only {tag} failed (divergent history); no merge "
            f"commit was created: {_last_line(step)}"
        )
    details["phases"].append({"name": "advance", "status": "PASS"})

    # 3. verify the code landed on the tag --------------------------------
    try:
        tag_commit = _git_rev_parse(git_runner, target, f"{tag}^{{commit}}")
        head_now = _git_rev_parse(git_runner, target, "HEAD")
    except UpgradeError as exc:
        return fail(str(exc))
    if head_now != tag_commit:
        return fail(
            f"HEAD ({head_now}) != {tag} commit ({tag_commit}) after the "
            "fast-forward"
        )
    details["git_head_after"] = head_now

    # 4. migrations --------------------------------------------------------
    try:
        phase("migrations")
    except UpgradeError as exc:
        return fail(str(exc))
    try:
        migrations = run_migrations(
            target,
            from_version=current_version,
            to_version=to_version,
            migrations_dir=migrations_dir,
            now=now,
            git_head_before=head_before,
        )
    except MigrationError as exc:
        details["migrations"] = {
            "applied": [],
            "skipped": [],
            "errors": [str(exc)],
        }
        return fail(str(exc))
    details["migrations"] = migrations
    if migrations.get("errors"):
        return fail("migrations failed: " + "; ".join(migrations["errors"]))
    details["phases"].append({"name": "migrations", "status": "PASS"})

    # 5. adapters ----------------------------------------------------------
    try:
        phase("adapters")
    except UpgradeError as exc:
        return fail(str(exc))
    if step_runner is None and not se_py.is_file():
        steps.append(
            {
                "name": "adapters",
                "rc": 1,
                "tail": [f"SCRIPTS/se.py not found in {target}"],
            }
        )
        details["steps"].append(steps[-1])
        return fail(f"adapter step failed: SCRIPTS/se.py not found in {target}")
    step = run_step(
        "adapters", [sys.executable, str(se_py), "adapter", "all"]
    )
    if step["rc"] != 0:
        return fail(
            f"adapter step failed with exit code {step['rc']}: "
            f"{_last_line(step)}"
        )
    details["phases"].append({"name": "adapters", "status": "PASS"})

    # 6. sync --------------------------------------------------------------
    if no_sync:
        details["phases"].append({"name": "sync", "status": "SKIPPED"})
    else:
        try:
            phase("sync")
        except UpgradeError as exc:
            return fail(str(exc))
        step = run_step(
            "sync",
            [sys.executable, str(se_py), "sync", "--project", str(target)],
        )
        if step["rc"] != 0:
            return fail(
                f"sync step failed with exit code {step['rc']}: "
                f"{_last_line(step)}"
            )
        details["phases"].append({"name": "sync", "status": "PASS"})

    # 7. doctor ------------------------------------------------------------
    try:
        phase("doctor")
    except UpgradeError as exc:
        return fail(str(exc))
    step = run_step("doctor", [sys.executable, str(se_py), "doctor", "--json"])
    doctor_status, doctor_summary, doctor_checks = _parse_doctor_payload(step)
    details["doctor"] = {"status": doctor_status, "summary": doctor_summary}
    if step["rc"] != 0:
        return fail(
            f"doctor step failed with exit code {step['rc']}: "
            f"{_last_line(step)}"
        )
    if doctor_status not in ("PASS", "WARN"):
        return fail(
            f"doctor reported status {doctor_status!r} (expected PASS or WARN): "
            f"{_last_line(step)}"
        )
    fail_count = (
        doctor_summary.get("FAIL") if isinstance(doctor_summary, dict) else None
    )
    if isinstance(fail_count, int) and fail_count != 0:
        return fail(
            f"doctor reported {fail_count} FAIL check(s): {_last_line(step)}"
        )
    if doctor_status == "WARN":
        details["warnings"].append(
            _doctor_warn_text(doctor_status, doctor_summary, doctor_checks)
        )
    details["phases"].append({"name": "doctor", "status": "PASS"})

    # 8. success -----------------------------------------------------------
    details["git_head_after"] = _safe_rev_parse(git_runner, target, "HEAD")
    if not delete_marker(target):
        details["warnings"].append(f"could not delete the upgrade marker: {path}")

    record = {
        "schema_version": "1",
        "operation": "upgrade",
        "status": "success",
        "from": current_version,
        "to": to_version,
        "tag": tag,
        "git_head_before": head_before,
        "git_head_after": details["git_head_after"],
        "snapshot": snapshot["snapshot_dir"],
        "migrations": migrations,
        "steps": steps,
        "started_at": started_at,
        "finished_at": _coerce_now(now).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    try:
        details["history"] = _append_history(target, record)
    except OSError as exc:
        details["warnings"].append(f"could not append upgrade history: {exc}")

    details["status"] = "PASS"
    return details


def run_upgrade(
    args,
    *,
    git_runner,
    step_runner,
    which,
    migrations_dir=None,
    now=None,
) -> dict:
    """Resolve ``args`` into the documented check/dry-run/execute/recover flow.

    Returns the ``details`` mapping including a ``status`` key. ``--check`` and
    ``--dry-run`` never create ``.se/`` or write any file.
    """
    target = Path(getattr(args, "project", None) or ".").resolve()
    which = which or shutil.which
    check = bool(getattr(args, "check", False))
    dry_run = bool(getattr(args, "dry_run", False))
    recover = bool(getattr(args, "recover", False))
    offline = bool(getattr(args, "offline", False))
    include_projects = bool(getattr(args, "include_projects", False))
    allow_downgrade = bool(getattr(args, "allow_downgrade", False))
    allow_prerelease = bool(getattr(args, "allow_prerelease", False))
    no_sync = bool(getattr(args, "no_sync", False))

    if recover:
        mode = "recover"
    elif check:
        mode = "check"
    elif dry_run:
        mode = "dry-run"
    else:
        mode = "execute"

    details = _new_details(
        target,
        mode=mode,
        offline=offline,
        include_projects=include_projects,
    )

    if recover:
        return _run_recover(
            target, details, git_runner=git_runner, step_runner=step_runner, now=now
        )
    if check or dry_run:
        return _run_check(
            target,
            details,
            runner=git_runner,
            which=which,
            offline=offline,
            allow_downgrade=allow_downgrade,
            allow_prerelease=allow_prerelease,
            no_sync=no_sync,
        )
    return _run_execute(
        target,
        details,
        git_runner=git_runner,
        step_runner=step_runner,
        which=which,
        migrations_dir=migrations_dir,
        now=now,
        offline=offline,
        include_projects=include_projects,
        allow_downgrade=allow_downgrade,
        allow_prerelease=allow_prerelease,
        no_sync=no_sync,
    )


# --------------------------------------------------------------------------- #
# Command
# --------------------------------------------------------------------------- #


def render_upgrade(status: str, details: dict) -> str:
    """Deterministic human-readable report (no ANSI, no decoration)."""
    lines = [f"se upgrade ({details.get('mode', 'check')})"]
    lines.append(f"Target: {details.get('target')}")
    if details.get("current_version"):
        lines.append(f"Current version: {details['current_version']}")
    lines.append(
        "Version source: local tags (offline)"
        if details.get("offline")
        else "Version source: origin tags"
    )
    if details.get("tags"):
        lines.append("Published tags: " + ", ".join(details["tags"]))
    selection = details.get("selection")
    if selection:
        lines.append(f"Target version: {selection.get('target') or 'none'}")
        lines.append(
            f"Selection: {selection.get('status')} - {selection.get('reason')}"
        )
    preflight_result = details.get("preflight")
    if preflight_result:
        lines.append(f"Preflight: {preflight_result['status']}")
        for check in preflight_result["checks"]:
            lines.append(
                f"  [{check['status']}] {check['name']}: {check['detail']}"
            )
    if details.get("git_head_before"):
        lines.append(f"HEAD before: {details['git_head_before']}")
    if details.get("git_head_after"):
        lines.append(f"HEAD after: {details['git_head_after']}")
    phases = details.get("phases") or []
    if phases:
        lines.append("Phases:")
        for phase in phases:
            lines.append(f"  [{phase.get('status')}] {phase.get('name')}")
    migrations = details.get("migrations")
    if migrations is not None:
        applied = ", ".join(migrations.get("applied") or []) or "none"
        skipped = ", ".join(migrations.get("skipped") or []) or "none"
        lines.append(f"Migrations applied: {applied}")
        lines.append(f"Migrations skipped: {skipped}")
        for error in migrations.get("errors") or []:
            lines.append(f"  MIGRATION ERROR: {error}")
    steps = details.get("steps") or []
    if steps:
        lines.append("Steps:")
        for step in steps:
            lines.append(f"  [{step.get('rc')}] {step.get('name')}")
            for line in step.get("tail") or []:
                lines.append(f"    {line}")
    rollback = details.get("rollback")
    if rollback:
        lines.append(
            "Rollback: "
            + ("ok" if rollback.get("ok") else "FAILED")
            + f" (git_reset={bool(rollback.get('git_reset'))})"
        )
        for error in rollback.get("errors") or []:
            lines.append(f"  ROLLBACK ERROR: {error}")
    if details.get("snapshot_restore"):
        restore = details["snapshot_restore"]
        lines.append(
            "Snapshot restore: "
            + ("ok" if restore.get("ok") else "FAILED")
            + f" (restored={len(restore.get('restored') or [])})"
        )
    if details.get("message"):
        lines.append(str(details["message"]))
    if details.get("history"):
        lines.append(f"History: {details['history']}")
    if details.get("tag_error"):
        lines.append(f"WARN: {details['tag_error']}")
    for warning in details.get("warnings") or []:
        lines.append(f"WARN: {warning}")
    for blocker in details.get("blockers") or []:
        lines.append(f"BLOCKED: {blocker}")
    if not details.get("blockers") and details.get("mode") in ("check", "dry-run"):
        lines.append("No changes applied (read-only).")
    lines.append(f"Status: {status}")
    return "\n".join(lines)


def _finish(args, status: str, details: dict) -> int:
    """Emit JSON or text and return the documented exit code."""
    if wants_json(args):
        print(
            render_json(
                build_envelope(
                    "upgrade",
                    status,
                    blockers=list(details.get("blockers") or []),
                    warnings=list(details.get("warnings") or []),
                    details=details,
                )
            )
        )
    else:
        print(render_upgrade(status, details))
    return 0 if status in _OK_STATUSES else 1


def cmd_upgrade(
    args,
    *,
    git_runner=None,
    which=None,
    step_runner=None,
    migrations_dir=None,
    now=None,
) -> int:
    """``se upgrade`` - plan (``--check``/``--dry-run``), execute, or ``--recover``.

    ``--check`` and ``--dry-run`` resolve the target version and run the
    read-only preflight; they never create ``.se/`` or write any file. Without
    either flag the upgrade runs (fetch -> ff-only -> migrations -> adapters ->
    sync -> doctor) and rolls back on any failure. ``--recover`` restores an
    interrupted upgrade even though the preflight would block on its marker.
    """
    which = which or shutil.which
    git_path = getattr(args, "git_path", None)

    if git_runner is not None:
        runner = git_runner
    else:
        runner = default_git_runner(git_path)
    if git_path:
        base_which = which

        def which_with_git(name):
            if name == "git":
                return git_path
            return base_which(name)

        which = which_with_git

    details = run_upgrade(
        args,
        git_runner=runner,
        step_runner=step_runner,
        which=which,
        migrations_dir=migrations_dir,
        now=now,
    )
    status = str(details.pop("status", "FAIL"))
    return _finish(args, status, details)
