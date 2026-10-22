"""``se update`` - apply declared changes to SE-owned MCP servers with rollback.

Pipeline (fail-closed, never leaves half-applied state):

1. BLOCKED (exit 1) when there is no lifecycle state - ``nothing installed  - 
   run se install``;
2. preflight: report an SE version mismatch against the recorded ``se_version``
   non-fatally (advise ``se adapter opencode`` / ``se init`` when it changed);
3. diff DECLARED (``TEMPLATES/mcp``) vs REGISTERED (state) per server; nothing
   changed -> no-op report;
4. otherwise: backup the config file AND the state into ``.se/backups/``, apply
   the changed registrations through install's runner (state checkpointed per
   server), then VERIFY (config re-reads cleanly, state consistent, the internal
   install plan re-runs without error);
5. on ANY failure: restore both backups and report BLOCKED with rollback
   evidence (restored files + hashes).

Flags: ``--project`` (default cwd), ``--dry-run``, ``--json``.
Exit codes: 0 success/no-op, 1 BLOCKED/failure, 2 usage.
"""

from __future__ import annotations

import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path

from . import install, mcpconfig
from . import lifecycle_state as lc
from .paths import repo_root
from .reporting import build_envelope, render_json, wants_json

SCOPE = "project"


def _file_timestamp() -> str:
    """Filesystem-safe UTC timestamp for backup file names (no colons)."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _backup_bytes(source: Path, target_dir: Path, name: str) -> Path:
    """Copy ``source`` bytes to ``target_dir/<name>`` and return the backup path."""
    target_dir.mkdir(parents=True, exist_ok=True)
    backup = target_dir / name
    shutil.copy2(source, backup)
    return backup


def plan_diff(declared: dict, state: dict) -> dict:
    """Diff DECLARED vs REGISTERED per server (pure).

    Returns ``{"changed": [...], "orphaned": [...], "unmanaged": [...]}`` where
    ``changed`` carries ``{"name", "old", "new"}`` hash pairs for state servers
    whose declared spec hash no longer matches.
    """
    state_servers = (state or {}).get("servers") or {}
    changed = []
    orphaned = []
    for name in sorted(state_servers):
        if name not in declared:
            orphaned.append(name)
            continue
        old = state_servers[name].get("declared")
        new = declared[name]["hash"]
        if old != new:
            changed.append({"name": name, "old": old, "new": new})
    unmanaged = [name for name in sorted(declared) if name not in state_servers]
    return {"changed": changed, "orphaned": orphaned, "unmanaged": unmanaged}


def verify_update(
    *, se_root, project, os_name, templates, preflight, interpreter, changed_names, path_mapper=None,
    portable=False,
) -> list[str]:
    """Post-apply verification; returns a list of error strings (empty = PASS).

    Checks: the config re-reads cleanly, the state is consistent (every changed
    server recorded with its current declared hash) and the internal install plan
    re-runs without error.
    """
    errors = []
    config_path = mcpconfig.config_path(project)
    try:
        mcpconfig.read_config(config_path)
    except Exception as exc:  # noqa: BLE001 - reported as verification evidence
        errors.append(f"config re-read failed ({config_path}): {exc}")
    state = lc.load_state(project)
    if state is None:
        errors.append(f"state unreadable after apply: {lc.state_path(project)}")
    else:
        declared = declared_view(
            templates,
            se_root=se_root,
            project=project,
            project_id=install.read_project_id(project),
            interpreter=interpreter,
            path_mapper=path_mapper,
            portable=portable,
        )
        for name in changed_names:
            record = (state.get("servers") or {}).get(name)
            if record is None:
                errors.append(f"state missing {name!r} after apply")
            elif record.get("declared") != declared[name]["hash"]:
                errors.append(f"state hash for {name!r} not refreshed after apply")
    try:
        plan = install.build_plan(
            os_name=os_name,
            se_root=se_root,
            project=project,
            dry_run=True,
            templates=templates,
            preflight=preflight,
        )
        if plan.get("status") != "PASS":
            errors.append(f"install plan re-run is {plan.get('status')}: {plan.get('blockers')}")
    except Exception as exc:  # noqa: BLE001 - reported as verification evidence
        errors.append(f"install plan re-run raised: {exc}")
    return errors


def declared_view(templates, *, se_root, project, project_id, interpreter, path_mapper=None, portable=False) -> dict:
    """Map registered server name -> {"template", "spec", "hash"} (same as sync)."""
    view = {}
    for template in templates:
        spec = install.resolved_server_spec(
            template,
            se_root=se_root,
            project=project,
            project_id=project_id,
            interpreter=interpreter,
            path_mapper=path_mapper,
            portable=portable,
        )
        view[spec["name"]] = {
            "template": template,
            "spec": spec,
            "hash": lc.spec_hash(spec),
        }
    return view


def render_update(report: dict) -> str:
    """Render the update report as deterministic human-readable text (no ANSI)."""
    lines = ["se update" + (" (dry-run)" if report["dry_run"] else "")]
    lines.append(f"Target: {report['target']}")
    versions = report["se_version"]
    version_line = f"SE version: {versions['current']}"
    if versions["recorded"] is not None:
        version_line += f" (recorded: {versions['recorded']})"
    lines.append(version_line)
    for warning in report["warnings"]:
        lines.append(f"WARN: {warning}")
    for change in report["changed"]:
        lines.append(f"CHANGED: {change['name']}")
    if report["orphaned"]:
        lines.append(
            "Orphans (reported only, no unregister in v1): " + ", ".join(report["orphaned"])
        )
    if report["unmanaged"]:
        lines.append(
            "Not managed yet (run `se sync`): " + ", ".join(report["unmanaged"])
        )
    if report["dry_run"]:
        if report["changed"]:
            lines.append(
                "Would update: " + ", ".join(c["name"] for c in report["changed"])
            )
        else:
            lines.append("No changes: declared matches registered state")
    elif report["applied"]:
        lines.append("Applied: " + ", ".join(report["applied"]))
        lines.append(f"Backups: config={report['backups']['config']} state={report['backups']['state']}")
    elif not report["blockers"]:
        lines.append("No changes: declared matches registered state (no-op)")
    verify = report.get("verify")
    if verify is not None:
        lines.append(f"Verify: {verify['status']}")
        for error in verify["errors"]:
            lines.append(f"  - {error}")
    rollback = report.get("rollback")
    if rollback:
        lines.append("ROLLBACK: " + rollback["reason"])
        lines.append(f"  config restored: {rollback['config_restored']} (sha256 {rollback['config_restored_hash']})")
        lines.append(f"  state restored:  {rollback['state_restored']} (sha256 {rollback['state_restored_hash']})")
        lines.append(f"  original hashes: config {rollback['config_before_hash']} state {rollback['state_before_hash']}")
    for blocker in report["blockers"]:
        lines.append(f"BLOCKED: {blocker}")
    lines.append(f"Status: {report['status']}")
    return "\n".join(lines)


def cmd_update(args, *, platform_name=None, runner=None, which=None) -> int:
    """Execute the ``se update`` pipeline (injectable seams: platform, runner, which)."""
    se_root = repo_root()
    project = Path(getattr(args, "project", None) or ".").resolve()
    os_name = install.detect_os(platform_name)
    which = which or shutil.which
    dry_run = bool(getattr(args, "dry_run", False))

    state_path = lc.state_path(project)
    state = lc.load_state(project)
    if state is None:
        message = (
            f"lifecycle state is corrupt: {state_path}; restore or delete it manually"
            if state_path.exists()
            else "nothing installed - run se install"
        )
        return _finish(args, "update", "BLOCKED", report=None, blockers=[message])

    templates = install.load_mcp_templates(se_root)
    host_env = install.detect_env_target(platform_name)
    recorded_target = str(state.get("env_target") or host_env)
    path_mapper = install.path_mapper_for(host_env, recorded_target)
    interpreter = install.resolve_python_interpreter(which, env_target=recorded_target)
    project_id = install.read_project_id(project)
    declared = declared_view(
        templates, se_root=se_root, project=project, project_id=project_id,
        interpreter=interpreter, path_mapper=path_mapper,
        portable=install.is_master_repo(project),
    )
    diff = plan_diff(declared, state)

    warnings = []
    current_version = lc.read_se_version(se_root)
    recorded_version = state.get("se_version")
    if recorded_version is not None and recorded_version != current_version:
        warnings.append(
            f"SE version changed since registration: recorded {recorded_version}, "
            f"current {current_version}; run `se adapter opencode` / `se init` to "
            "refresh generated adapters"
        )

    report = {
        "target": str(project),
        "os": os_name,
        "se_version": {"current": current_version, "recorded": recorded_version},
        "declared": sorted(declared),
        "state_servers": sorted((state.get("servers") or {})),
        "changed": diff["changed"],
        "orphaned": diff["orphaned"],
        "unmanaged": diff["unmanaged"],
        "applied": [],
        "backups": {"config": None, "state": None},
        "verify": None,
        "rollback": None,
        "warnings": warnings,
        "dry_run": dry_run,
        "status": "PASS",
        "blockers": [],
    }

    if not diff["changed"]:
        return _finish(args, "update", "PASS", report=report)

    if dry_run:
        return _finish(args, "update", "PASS", report=report)

    config_path = mcpconfig.config_path(project)
    if not config_path.exists():
        report["status"] = "BLOCKED"
        report["blockers"].append(
            f"runtime config not found: {config_path}; register servers with `se install` or `se sync`"
        )
        return _finish(args, "update", "BLOCKED", report=report)

    stamp = _file_timestamp()
    backups = lc.backup_dir(project)
    config_backup = _backup_bytes(config_path, backups, f"config-{stamp}.jsonc")
    state_backup = _backup_bytes(state_path, backups, f"state-{stamp}.json")
    report["backups"] = {"config": str(config_backup), "state": str(state_backup)}
    config_bytes_before = config_path.read_bytes()
    state_bytes_before = state_path.read_bytes()

    changed_names = [entry["name"] for entry in diff["changed"]]
    selected = [t for t in templates if t["name"] in set(changed_names)]
    preflight = install.preflight_dependencies(
        os_name, which=which, selected_servers=[t["key"] for t in selected]
    )
    registrations = install.build_registrations(
        selected,
        se_root=se_root,
        project=project,
        project_id=project_id,
        interpreter=interpreter,
        scope=SCOPE,
        register=True,
        preflight=preflight,
    )

    # Apply with a state checkpoint per successfully registered server so a later
    # failure has an observable rollback (state bytes differ until restored).
    failed = None
    applied = []
    for registration in registrations:
        install.execute_registrations([registration], runner or install.default_runner)
        if registration["status"] != "registered":
            failed = f"{registration['name']}: {registration.get('reason') or 'registration failed'}"
            break
        name = registration["name"]
        lc.record_server(
            state,
            name,
            declared=declared[name]["hash"],
            source=declared[name]["template"]["template"],
            scope=SCOPE,
        )
        lc.save_state(state, project)
        applied.append(name)
    report["applied"] = applied

    verify_errors = []
    if failed is None:
        state["se_version"] = current_version
        state["os"] = os_name
        lc.save_state(state, project)
        verify_errors = verify_update(
            se_root=se_root,
            project=project,
            os_name=os_name,
            templates=templates,
            preflight=preflight,
            interpreter=interpreter,
            changed_names=changed_names,
            path_mapper=path_mapper,
            portable=install.is_master_repo(project),
        )

    if failed is None and not verify_errors:
        report["verify"] = {"status": "PASS", "errors": []}
        return _finish(args, "update", "PASS", report=report)

    # Rollback: restore BOTH backups and report the evidence.
    reason = failed or "verification failed"
    config_restored = False
    state_restored = False
    try:
        config_path.write_bytes(config_bytes_before)
        config_restored = config_path.read_bytes() == config_bytes_before
    except OSError:
        config_restored = False
    try:
        state_path.write_bytes(state_bytes_before)
        state_restored = state_path.read_bytes() == state_bytes_before
    except OSError:
        state_restored = False
    report["verify"] = {"status": "FAIL" if failed is None else "NOT RUN", "errors": verify_errors}
    report["rollback"] = {
        "reason": reason,
        "config_backup": str(config_backup),
        "state_backup": str(state_backup),
        "config_before_hash": _sha256_bytes(config_bytes_before),
        "config_restored_hash": _sha256_bytes(config_path.read_bytes()) if config_path.exists() else "",
        "state_before_hash": _sha256_bytes(state_bytes_before),
        "state_restored_hash": _sha256_bytes(state_path.read_bytes()) if state_path.exists() else "",
        "config_restored": config_restored,
        "state_restored": state_restored,
    }
    report["status"] = "BLOCKED"
    report["blockers"].append(f"update failed: {reason}; rolled back to the pre-update state")
    if not (config_restored and state_restored):
        report["blockers"].append(
            "rollback incomplete; restore manually from .se/backups/"
        )
    return _finish(args, "update", "BLOCKED", report=report)


def _finish(args, operation, status, *, report=None, blockers=None) -> int:
    """Emit the command result (JSON envelope or human text) and the exit code."""
    details = report if report is not None else {"blockers": list(blockers or [])}
    if report is not None and blockers:
        details["blockers"] = list(blockers)
    if wants_json(args):
        print(render_json(build_envelope(operation, status, details=details)))
    elif report is not None:
        print(render_update(report))
    else:
        prefix = "BLOCKED" if status == "BLOCKED" else "FAIL"
        print(f"{prefix}: {(blockers or [''])[0]}")
    return 0 if status in ("PASS", "INFO") else 1