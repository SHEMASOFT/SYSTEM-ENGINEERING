"""``se upgrade`` - thin, fail-closed upgrade orchestrator (skeleton phase).

This module implements the *read-only* half of the upgrade contract approved in
``DOCS/internal/upgrade-readiness-audit-2026-10-22.md`` (section 6):

* version discovery (strict SemVer tags from the remote or local refs);
* a read-only preflight that BLOCKS before any write;
* a verifiable snapshot of the runtime config and lifecycle state (explicitly
  invoked only - ``--check`` / ``--dry-run`` never create ``.se/``);
* snapshot verification and hash-guarded restoration.

The execution half (fetch/ff-only advance, migrations, adapter regeneration,
sync, rollback) is intentionally **not** implemented in this phase: a bare
``se upgrade`` reports ``BLOCKED`` with reason
``upgrade execution not implemented in this phase`` and performs zero writes.

Design constraints (inherited from the audit):

* orchestrator, not a second engine - reconciliation/adapters/health stay in
  ``sync`` / ``opencode.generator`` / ``doctor``;
* every failure is fail-closed and reported, never guessed;
* no network beyond ``git ls-remote`` when the caller asks for it, and never in
  ``--offline`` mode;
* the git runner is injectable so the module is unit-testable without git and
  without touching a real repository.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import lifecycle_state as lc
from . import mcpconfig
from .paths import write_json_atomic
from .reporting import build_envelope, render_json, wants_json

#: Lifecycle state schema this build understands. Anything else must be
#: migrated before the state is trusted (``load_state`` returns ``None``).
SUPPORTED_STATE_SCHEMA = "1"

#: Marker written by a future execution phase before the first mutation; its
#: presence means a previous upgrade was interrupted.
UPGRADE_MARKER = "upgrade-in-progress.json"

_SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_PRERELEASE_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)-([0-9A-Za-z.-]+)$")

#: Statuses that mean "nothing is wrong, just nothing to do".
_OK_STATUSES = ("PASS", "INFO", "UNKNOWN")


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
    """Normalize a ``git ls-remote``/``git tag`` result into the tag contract."""
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
        if name.startswith("v") and name not in tags:
            tags.append(name)
    return {"tags": sorted(tags), "error": None}


def list_remote_tags(runner, *, remote: str = "origin", timeout: int = 30) -> dict:
    """List published ``v*`` tags from ``remote`` via ``git ls-remote``.

    Returns ``{"tags": [...], "error": None|str}``. An empty remote, a git
    failure and a raised exception all produce ``tags: []`` plus either
    ``error: None`` (genuinely no tags) or a diagnostic string.
    """
    argv = ["git", "ls-remote", "--tags", "--refs", remote, "v*"]
    try:
        completed = _invoke(runner, argv, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - reported, never fatal
        return {"tags": [], "error": f"git ls-remote failed: {exc}"}
    return _tag_result(completed)


def list_local_tags(runner, *, timeout: int = 30) -> dict:
    """List local ``v*`` tags (used by ``--offline``; never touches the network)."""
    argv = ["git", "tag", "--list", "v*"]
    try:
        completed = _invoke(runner, argv, timeout=timeout)
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
                ["git", "status", "--porcelain", "--untracked-files=no"],
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


def _snapshot_sources(target: Path, include_projects: bool) -> list[Path]:
    """Files captured by default: runtime config + lifecycle state (if present)."""
    sources: list[Path] = []
    config = mcpconfig.config_path(target)
    if config.is_file():
        sources.append(config)
    state = lc.state_path(target)
    if state.is_file():
        sources.append(state)
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
    ``manifest.json`` (hashes per file) plus byte copies of the runtime config
    and lifecycle state. ``PROJECTS/`` is copied only when explicitly requested.
    The sequence suffix makes two snapshots in the same second distinct.
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
    }
    manifest_path = snapshot_dir / "manifest.json"
    write_json_atomic(manifest_path, manifest)
    return {
        "snapshot_dir": str(snapshot_dir),
        "manifest_path": str(manifest_path),
        "manifest": manifest,
        "files": files,
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
    if details.get("tag_error"):
        lines.append(f"WARN: {details['tag_error']}")
    for blocker in details.get("blockers") or []:
        lines.append(f"BLOCKED: {blocker}")
    if not details.get("blockers"):
        lines.append("No changes applied (read-only).")
    lines.append(f"Status: {status}")
    return "\n".join(lines)


def _finish(args, status: str, details: dict) -> int:
    """Emit JSON or text and return the documented exit code."""
    if wants_json(args):
        print(render_json(build_envelope("upgrade", status, details=details)))
    else:
        print(render_upgrade(status, details))
    return 0 if status in _OK_STATUSES else 1


def cmd_upgrade(args, *, git_runner=None, which=None) -> int:
    """``se upgrade`` - read-only planning today, BLOCKED execution.

    ``--check`` and ``--dry-run`` resolve the target version and run the
    read-only preflight; they never create ``.se/`` or write any file. Without
    either flag the command is a deliberate ``BLOCKED`` (execution is not part
    of this phase) and still performs zero writes.
    """
    target = Path(getattr(args, "project", None) or ".").resolve()
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

    check = bool(getattr(args, "check", False))
    dry_run = bool(getattr(args, "dry_run", False))
    offline = bool(getattr(args, "offline", False))
    include_projects = bool(getattr(args, "include_projects", False))
    allow_downgrade = bool(getattr(args, "allow_downgrade", False))
    allow_prerelease = bool(getattr(args, "allow_prerelease", False))
    no_sync = bool(getattr(args, "no_sync", False))

    mode = "check" if check else ("dry-run" if dry_run else "execute")
    details = {
        "mode": mode,
        "target": str(target),
        "offline": offline,
        "include_projects": include_projects,
        "current_version": None,
        "tags": [],
        "selection": None,
        "preflight": None,
        "snapshot": None,
        "writes": [],
        "blockers": [],
    }

    # Execution is out of scope in this phase: refuse before touching anything.
    if not check and not dry_run:
        details["blockers"] = ["upgrade execution not implemented in this phase"]
        return _finish(args, "BLOCKED", details)

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
        details["blockers"] = list(preflight_result["blockers"])
        return _finish(args, "BLOCKED", details)

    tag_result = (
        list_local_tags(runner) if offline else list_remote_tags(runner)
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
        return _finish(args, "UNKNOWN", details)

    try:
        selection = select_target_version(
            tag_result["tags"],
            current_version,
            allow_prerelease=allow_prerelease,
            allow_downgrade=allow_downgrade,
        )
    except ValueError as exc:
        details["blockers"] = [str(exc)]
        return _finish(args, "BLOCKED", details)
    details["selection"] = selection

    if selection["status"] == "DOWNGRADE_BLOCKED":
        details["blockers"] = [selection["reason"]]
        return _finish(args, "BLOCKED", details)
    if selection["status"] == "NO_TAGS":
        return _finish(args, "UNKNOWN", details)
    if selection["status"] == "UP_TO_DATE":
        return _finish(args, "INFO", details)
    return _finish(args, "PASS", details)
