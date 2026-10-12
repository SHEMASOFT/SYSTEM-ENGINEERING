"""``se sync`` - reconcile declared vs registered vs actual MCP servers.

Three sources of truth are compared:

* **DECLARED** - ``TEMPLATES/mcp/*.json.tmpl`` (the canonical source), resolved
  with the same placeholder/interpreter rules ``se install`` uses;
* **REGISTERED** - the lifecycle state at ``<target>/.se/lifecycle-state.json``;
* **ACTUAL** - the runtime config on disk (``mcp.servers`` V2 and legacy
  ``mcpServers``, both checked for every name).

Rules (v1):

* declared but missing from actual -> register (through install's registration
  spec + runner) and record state;
* present in actual but NOT in state -> FOREIGN/pre-existing: report only, never
  touched, never duplicated;
* in state but actual differs from the declared spec -> SE-owned: re-register
  and refresh the state hash;
* in state but no longer declared -> orphan: report only (no auto-unregister);
* servers present in legacy ``mcpServers`` are never duplicated into
  ``mcp.servers``;
* idempotent: a second run reports no diff and changes nothing.

Flags: ``--project`` (default cwd), ``--dry-run``, ``--json``.
Exit codes: 0 success/safe, 1 failure, 2 usage.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from . import install, mcpconfig
from . import lifecycle_state as lc
from .paths import repo_root
from .reporting import build_envelope, render_json, wants_json

#: Sync always registers at project scope in v1 (global is install-only).
SCOPE = "project"


def declared_view(templates, *, se_root, project, project_id, interpreter, path_mapper=None) -> dict:
    """Map registered server name -> declared info.

    Each entry is ``{"template", "spec" (resolved config entry), "hash"}``;
    the hash is the canonical declared spec hash lifecycle state records.
    ``path_mapper`` must be the one the recorded state used, or the hashes
    diverge on a translate-target install (see ``install.resolved_server_spec``).
    """
    view = {}
    for template in templates:
        spec = install.resolved_server_spec(
            template,
            se_root=se_root,
            project=project,
            project_id=project_id,
            interpreter=interpreter,
            path_mapper=path_mapper,
        )
        view[spec["name"]] = {
            "template": template,
            "spec": spec,
            "hash": lc.spec_hash(spec),
        }
    return view


def entry_matches(actual_value, spec, *, legacy: bool) -> bool:
    """Whether an ACTUAL config entry equals the DECLARED spec.

    Handles both the V2 shape (``command`` list + ``environment``) and the legacy
    shape (``command`` string + ``args`` + ``env``).
    """
    if not isinstance(actual_value, dict) or not isinstance(spec, dict):
        return False
    if legacy:
        command = actual_value.get("command")
        args = list(actual_value.get("args") or [])
        if isinstance(command, str):
            parts = command.split()
            cmd, cmd_args = (parts[0], parts[1:]) if parts else ("", [])
        elif isinstance(command, list):
            cmd, cmd_args = (command[0] if command else ""), list(command[1:])
        else:
            return False
        env = actual_value.get("env") or actual_value.get("environment") or {}
        return [cmd, *cmd_args] == spec["command"] and dict(env) == spec["environment"]
    command = actual_value.get("command")
    if isinstance(command, str):
        cmd_parts = command.split()
    elif isinstance(command, list):
        cmd_parts = list(command)
    else:
        return False
    env = actual_value.get("environment") or actual_value.get("env") or {}
    return cmd_parts == spec["command"] and dict(env) == spec["environment"]


def reconcile(*, declared: dict, state: dict | None, cfg: dict) -> dict:
    """Classify every server name across declared / state / actual (pure).

    Returns ``{"register": [], "update": [], "foreign": [], "orphan": [],
    "up_to_date": []}`` where every entry carries ``name``, ``action`` and
    ``reason``. Never mutates anything.
    """
    state_servers = (state or {}).get("servers") or {}
    by_scope = {"v2": {}, "legacy": {}}
    for item in mcpconfig.list_servers(cfg):
        by_scope[item["scope"]][item["name"]] = item["value"]

    report = {"register": [], "update": [], "foreign": [], "orphan": [], "up_to_date": []}
    for name in sorted(set(declared) | set(state_servers)):
        is_declared = name in declared
        in_state = name in state_servers
        in_v2 = name in by_scope["v2"]
        in_legacy = name in by_scope["legacy"]
        in_actual = in_v2 or in_legacy

        if is_declared and not in_actual:
            report["register"].append({
                "name": name,
                "action": "register",
                "reason": "declared but missing from the runtime config",
            })
            continue
        if is_declared and not in_state:
            report["foreign"].append({
                "name": name,
                "action": "report_only",
                "reason": "present in the runtime config but not recorded by SE; "
                          "pre-existing entry left untouched",
                "scopes": [scope for scope, present in (("v2", in_v2), ("legacy", in_legacy)) if present],
            })
            continue
        if is_declared and in_state:
            spec = declared[name]["spec"]
            matches = (in_v2 and entry_matches(by_scope["v2"][name], spec, legacy=False)) or (
                in_legacy and entry_matches(by_scope["legacy"][name], spec, legacy=True)
            )
            if matches:
                report["up_to_date"].append({"name": name, "action": "none", "reason": "matches the declared spec"})
                continue
            if in_legacy and not in_v2:
                report["update"].append({
                    "name": name,
                    "action": "report_only",
                    "reason": "SE-owned server present only in legacy mcpServers; "
                              "re-registering would duplicate it into mcp.servers - "
                              "migrate manually",
                })
                continue
            report["update"].append({
                "name": name,
                "action": "re-register",
                "reason": "runtime entry differs from the declared spec",
            })
            continue
        if not is_declared and in_state:
            report["orphan"].append({
                "name": name,
                "action": "report_only",
                "reason": "recorded in lifecycle state but no longer declared by "
                          "TEMPLATES/mcp; reported only (no auto-unregister in v1)",
            })
    return report


def render_sync(report: dict) -> str:
    """Render the sync report as deterministic human-readable text (no ANSI)."""
    lines = ["se sync" + (" (dry-run)" if report["dry_run"] else "")]
    lines.append(f"Target: {report['target']}")
    lines.append(f"Declared ({len(report['declared'])}): " + (", ".join(report["declared"]) or "none"))
    actions = report["actions"]
    labels = (
        ("register", "Missing (will register)"),
        ("update", "SE-owned changed (will re-register)"),
        ("foreign", "Foreign/pre-existing (never touched)"),
        ("orphan", "Orphans in state (reported only)"),
        ("up_to_date", "Up to date"),
    )
    for key, label in labels:
        entries = actions[key]
        if not entries:
            continue
        lines.append(f"{label} ({len(entries)}):")
        for entry in entries:
            lines.append(f"  {entry['name']}: {entry['reason']}")
    if report["applied"]["register"] or report["applied"]["update"]:
        lines.append(
            "Applied: registered "
            + ", ".join(sorted(set(report["applied"]["register"] + report["applied"]["update"])))
        )
    elif not report["dry_run"]:
        lines.append("Applied: nothing (no diff)")
    else:
        lines.append("Applied: nothing (dry-run)")
    for entry in report.get("skipped") or []:
        lines.append(f"WARN: skipped {entry['name']}: {entry['reason']}")
    for failure in report["failures"]:
        lines.append(f"FAIL: {failure}")
    lines.append(f"Status: {report['status']}")
    return "\n".join(lines)


def cmd_sync(args, *, platform_name=None, runner=None, which=None) -> int:
    """Execute the ``se sync`` pipeline (injectable seams: platform, runner, which)."""
    se_root = repo_root()
    project = Path(getattr(args, "project", None) or ".").resolve()
    os_name = install.detect_os(platform_name)
    which = which or shutil.which
    dry_run = bool(getattr(args, "dry_run", False))

    state_path = lc.state_path(project)
    state = lc.load_state(project)
    if state_path.exists() and state is None:
        return _finish(
            args, "sync", "BLOCKED", report=None,
            blockers=[f"lifecycle state is corrupt: {state_path}; restore or delete it manually"],
            project=project, dry_run=dry_run,
        )

    templates = install.load_mcp_templates(se_root)
    host_env = install.detect_env_target(platform_name)
    recorded_target = str((state or {}).get("env_target") or host_env)
    path_mapper = install.path_mapper_for(host_env, recorded_target)
    interpreter = install.resolve_python_interpreter(which, env_target=recorded_target)
    project_id = install.read_project_id(project)
    config_path = mcpconfig.config_path(project)
    cfg = mcpconfig.read_config(config_path) if config_path.exists() else {}

    declared = declared_view(
        templates, se_root=se_root, project=project, project_id=project_id,
        interpreter=interpreter, path_mapper=path_mapper,
    )
    actions = reconcile(declared=declared, state=state, cfg=cfg)
    register_names = {entry["name"] for entry in actions["register"]}
    update_names = {entry["name"] for entry in actions["update"]}

    apply_names = [
        entry["name"]
        for entry in actions["register"] + actions["update"]
        if entry["action"] in ("register", "re-register")
    ]
    report = {
        "target": str(project),
        "os": os_name,
        "declared": sorted(declared),
        "state_file": str(state_path),
        "config": str(config_path),
        "actions": actions,
        "applied": {"register": [], "update": []},
        "skipped": [],
        "changed": list(apply_names),
        "failures": [],
        "dry_run": dry_run,
        "status": "PASS",
    }

    if apply_names and not dry_run:
        preflight = install.preflight_dependencies(os_name, which=which)
        selected = [t for t in templates if t["name"] in set(apply_names)]
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
        install.execute_registrations(registrations, runner or install.default_runner)
        if state is None:
            state = lc.new_state(
                se_version=lc.read_se_version(se_root),
                os_name=os_name,
                target=str(project),
                scope=SCOPE,
            )
        state["se_version"] = lc.read_se_version(se_root)
        state["os"] = os_name
        state["target"] = str(project)
        for registration in registrations:
            name = registration["name"]
            if registration["status"] == "registered":
                declared_entry = declared[name]
                lc.record_server(
                    state,
                    name,
                    declared=declared_entry["hash"],
                    source=declared_entry["template"]["template"],
                    scope=SCOPE,
                )
                if name in register_names:
                    report["applied"]["register"].append(name)
                else:
                    report["applied"]["update"].append(name)
            elif str(registration.get("reason") or "").startswith("registration failed"):
                report["failures"].append(f"{name}: {registration['reason']}")
            else:
                report["skipped"].append({"name": name, "reason": registration.get("reason")})
        lc.save_state(state, project)

    if report["failures"]:
        report["status"] = "FAIL"
    return _finish(args, "sync", report["status"], report=report)


def _finish(args, operation, status, *, report=None, blockers=None, project=None, dry_run=None) -> int:
    """Emit the command result (JSON envelope or human text) and the exit code."""
    details = report
    if details is None:
        details = {
            "target": str(project) if project is not None else None,
            "dry_run": dry_run,
            "blockers": list(blockers or []),
        }
    elif blockers:
        details["blockers"] = list(blockers)
    if wants_json(args):
        print(render_json(build_envelope(operation, status, details=details)))
    elif report is not None:
        print(render_sync(report))
    else:
        prefix = "BLOCKED" if status == "BLOCKED" else "FAIL"
        print(f"{prefix}: {(blockers or [''])[0]}")
    return 0 if status in ("PASS", "INFO") else 1