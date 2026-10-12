"""``se uninstall`` - remove only SE-managed MCP servers, safely and reversibly.

Design contract (v1):

* **simulation by default** - with no ``--apply`` (or with an explicit
  ``--dry-run``) the command reports exactly what *would* be removed and mutates
  nothing (exit 0);
* **``--apply``** removes ONLY the servers recorded in the lifecycle state
  (``<target>/.se/lifecycle-state.json``), one at a time, via the byte-preserving
  :func:`mcpconfig.remove_server_text` (which backs the config up to
  ``.se/backups/`` first) and moves each removed server into the state's
  ``uninstalled`` audit trail;
* servers present in the runtime config but NOT recorded in state are FOREIGN and
  are never touched (reported only);
* a server recorded in state but absent from the config is cleaned up in state
  only (no config rewrite) - this also covers a missing config file;
* **never** removes projects, data, environment variables, binaries,
  ``.opencode/``, the ``.se/`` state directory, or foreign config entries;
* a missing state file means "nothing managed" (exit 0); a corrupt state file is
  BLOCKED (exit 1) - the two cases are reported differently.

Flags: ``--project`` (default cwd), ``--apply``, ``--dry-run`` (default), ``--json``.
Exit codes: 0 success/no-op, 1 BLOCKED/failure, 2 usage.
"""

from __future__ import annotations

from pathlib import Path

from . import install, mcpconfig
from . import lifecycle_state as lc
from .reporting import build_envelope, render_json, wants_json


def plan_uninstall(state: dict, cfg: dict | None) -> dict:
    """Classify every state-managed server against the runtime config (pure).

    Returns ``{"managed", "in_config", "state_only", "foreign"}`` where the first
    three are sorted name lists and ``foreign`` lists ``{"name", "scopes"}`` for
    entries present in the config but not recorded by SE (report only, never
    touched). Never mutates anything.
    """
    managed = sorted((state or {}).get("servers") or {})
    managed_set = set(managed)
    by_scope = {"v2": {}, "legacy": {}}
    for item in mcpconfig.list_servers(cfg or {}):
        by_scope[item["scope"]][item["name"]] = item["value"]

    in_config = [name for name in managed if name in by_scope["v2"] or name in by_scope["legacy"]]
    state_only = [name for name in managed if name not in by_scope["v2"] and name not in by_scope["legacy"]]
    foreign = [
        {
            "name": name,
            "scopes": [scope for scope in ("v2", "legacy") if name in by_scope[scope]],
        }
        for name in sorted(set(by_scope["v2"]) | set(by_scope["legacy"]))
        if name not in managed_set
    ]
    return {"managed": managed, "in_config": in_config, "state_only": state_only, "foreign": foreign}


def render_uninstall(report: dict) -> str:
    """Render the uninstall report as deterministic human-readable text (no ANSI)."""
    mode = " (dry-run)" if report["dry_run"] else " (apply)"
    lines = ["se uninstall" + mode]
    lines.append(f"Target: {report['target']}")
    managed = report["managed"]
    if not managed:
        lines.append("Managed servers: none (nothing managed)")
    else:
        lines.append(f"Managed servers ({len(managed)}): " + ", ".join(managed))
        if report["in_config"]:
            lines.append("In runtime config (SE-owned, removable): " + ", ".join(report["in_config"]))
        if report["state_only"]:
            lines.append("State-only (not in config, audit cleanup): " + ", ".join(report["state_only"]))
        if report["dry_run"]:
            if managed:
                lines.append("Would remove: " + ", ".join(managed))
            lines.append("Nothing removed (dry-run)")
        else:
            lines.append("Removed: " + (", ".join(report["removed"]) or "none"))
            for name, backup in sorted(report["backups"].items()):
                lines.append(f"  {name}: backup {backup}")
    if report["foreign"]:
        names = ", ".join(entry["name"] for entry in report["foreign"])
        lines.append(f"Foreign/pre-existing (never touched): {names}")
    for error in report["errors"]:
        lines.append(f"FAIL: {error}")
    for blocker in report["blockers"]:
        lines.append(f"BLOCKED: {blocker}")
    lines.append(f"Status: {report['status']}")
    return "\n".join(lines)


def cmd_uninstall(args, *, platform_name: str | None = None) -> int:
    """Execute the ``se uninstall`` pipeline.

    Uninstall is a pure filesystem operation (no registration runner is needed):
    it edits the runtime config via :mod:`mcpconfig` and the lifecycle state via
    :mod:`lifecycle_state`. ``platform_name`` is injectable for deterministic OS
    reporting in tests.
    """
    project = Path(getattr(args, "project", None) or ".").resolve()
    os_name = install.detect_os(platform_name)
    dry_run = not bool(getattr(args, "apply", False)) or bool(getattr(args, "dry_run", False))

    state_path = lc.state_path(project)
    state = lc.load_state(project)
    if state_path.exists() and state is None:
        return _finish(
            args,
            "uninstall",
            "BLOCKED",
            blockers=[f"lifecycle state is corrupt: {state_path}; restore or delete it manually"],
        )

    config_path = mcpconfig.config_path(project)
    has_config = config_path.exists()
    cfg: dict | None = None
    if has_config:
        try:
            cfg = mcpconfig.read_config(config_path)
        except Exception as exc:  # noqa: BLE001 - fail closed before any removal
            return _finish(
                args,
                "uninstall",
                "BLOCKED",
                blockers=[f"runtime config is unparseable ({config_path}): {exc}; refusing to plan removal"],
            )

    if state is None:
        report = _base_report(project, os_name, state_path, config_path, dry_run)
        report["status"] = "PASS"
        report["message"] = "nothing managed (no lifecycle state for this target)"
        return _finish(args, "uninstall", "PASS", report=report)

    plan = plan_uninstall(state, cfg)
    report = _base_report(project, os_name, state_path, config_path, dry_run)
    report.update(
        {
            "managed": plan["managed"],
            "in_config": plan["in_config"],
            "state_only": plan["state_only"],
            "foreign": plan["foreign"],
        }
    )

    if not plan["managed"]:
        report["message"] = "nothing managed (lifecycle state records no servers)"
        report["status"] = "PASS"
        return _finish(args, "uninstall", "PASS", report=report)

    if dry_run:
        report["status"] = "PASS"
        return _finish(args, "uninstall", "PASS", report=report)

    # ---- apply ----
    managed = set(plan["managed"])
    for name in plan["managed"]:
        if name in plan["in_config"]:
            result = mcpconfig.remove_server_text(config_path, name, target=project)
            for error in result["errors"]:
                report["errors"].append(f"{name}: {error}")
            if result["errors"] or not result["changed"]:
                # Keep the state entry so config and state never diverge.
                if not result["errors"]:
                    report["errors"].append(f"{name}: config entry not found for removal")
                continue
            report["removed"].append(name)
            if result["backup"]:
                report["backups"][name] = result["backup"]
        # else: state-only cleanup (server absent from the config)
        lc.remove_server(state, name)

    try:
        lc.save_state(state, project)
    except Exception as exc:  # noqa: BLE001 - reported as a failed uninstall
        report["errors"].append(f"failed to save lifecycle state: {exc}")

    # Guard: only state-recorded names are ever removed (defence in depth).
    unexpected = [name for name in report["removed"] if name not in managed]
    if unexpected:
        report["errors"].append(f"internal error: removed unmanaged servers {unexpected}")

    report["status"] = "FAIL" if report["errors"] else "PASS"
    return _finish(args, "uninstall", report["status"], report=report)


def _base_report(project: Path, os_name: str, state_path: Path, config_path: Path, dry_run: bool) -> dict:
    """Create the deterministic report skeleton shared by every uninstall path."""
    return {
        "target": str(project),
        "os": os_name,
        "state_file": str(state_path),
        "config": str(config_path),
        "dry_run": dry_run,
        "managed": [],
        "in_config": [],
        "state_only": [],
        "foreign": [],
        "removed": [],
        "backups": {},
        "errors": [],
        "blockers": [],
        "status": "PASS",
    }


def _finish(args, operation, status, *, report=None, blockers=None) -> int:
    """Emit the command result (JSON envelope or human text) and the exit code."""
    details = report if report is not None else {"blockers": list(blockers or [])}
    if report is not None and blockers:
        details["blockers"] = list(blockers)
    if wants_json(args):
        print(render_json(build_envelope(operation, status, details=details)))
    elif report is not None:
        print(render_uninstall(report))
    else:
        prefix = "BLOCKED" if status == "BLOCKED" else "FAIL"
        print(f"{prefix}: {(blockers or [''])[0]}")
    return 0 if status in ("PASS", "INFO") else 1
