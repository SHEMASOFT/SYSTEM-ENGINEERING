"""``se uninstall`` - remove SE-managed MCP servers and optionally purge
SE-related artifacts from OpenCode safely and reversibly.

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
  are never touched by default (reported only);
* a server recorded in state but absent from the config is cleaned up in state
  only (no config rewrite) - this also covers a missing config file;
* **never** removes projects, data, environment variables, binaries by default;
* ``.opencode/`` is only removed with explicit ``--remove-opencode-dir``/``--purge-adapter``
  and is always backed up first;
* SE-related MCPs not tracked in lifecycle state can be removed with
  ``--include-untracked-se-mcps`` (conservative detection);
* a missing state file means "nothing managed" (exit 0); a corrupt state file is
  BLOCKED (exit 1) - the two cases are reported differently.

Flags: ``--project`` (default cwd), ``--apply``, ``--dry-run`` (default), ``--json``,
``--interactive/-i``, ``--all``, ``--include-untracked-se-mcps``, ``--remove-opencode-dir``,
``--purge-adapter``, ``--keep-opencode-jsonc``, ``--force``.
Exit codes: 0 success/no-op, 1 BLOCKED/failure, 2 usage.
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
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


def detect_untracked_se_mcps(cfg: dict | None, managed_set: set[str]) -> list[dict]:
    """Detect SE-related MCP servers in config not tracked by lifecycle state."""
    results = []
    if not cfg:
        return results
    by_scope = {"v2": {}, "legacy": {}}
    for item in mcpconfig.list_servers(cfg):
        by_scope[item["scope"]][item["name"]] = item["value"]

    seen = set()
    for scope in ("v2", "legacy"):
        for name, entry in by_scope[scope].items():
            if name in managed_set or name in seen:
                continue
            is_se, reason = mcpconfig.is_se_related_server(name, entry)
            if not is_se:
                continue
            seen.add(name)
            results.append({
                "name": name,
                "scopes": [scope],
                "reason": reason,
                "entry": entry,
            })
    return sorted(results, key=lambda x: x["name"])


def _backup_path(base: Path, name: str) -> Path:
    ts = datetime.now().strftime("%Y%m%dT%H%M%SZ")
    backup_dir = base / ".se" / "uninstall-backups" / ts
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir / name


def remove_opencode_dir(project: Path) -> dict:
    """Remove .opencode/ directory with backup. Returns result dict."""
    opencode_dir = project / ".opencode"
    result = {"exists": opencode_dir.exists(), "removed": False, "backup": None, "errors": []}
    if not opencode_dir.exists():
        return result
    try:
        backup = _backup_path(project, ".opencode")
        shutil.copytree(opencode_dir, backup)
        result["backup"] = str(backup)
        shutil.rmtree(opencode_dir)
        result["removed"] = True
    except Exception as exc:
        result["errors"].append(str(exc))
    return result


def _interactive_purge_menu(report: dict) -> dict:
    """Interactive menu for purge selection. Returns selections dict."""
    selections = {
        "remove_managed": True,
        "remove_untracked_se": False,
        "remove_opencode": False,
    }
    if not sys.stdin.isatty():
        return selections

    print("\n=== SE UNINSTALL - Interactive Purge ===")
    print(f"Target: {report['target']}")
    print("\nSelect items to remove:")

    managed = report.get("managed") or []
    untracked = report.get("untracked_se_mcp") or []
    has_opencode = report.get("has_opencode_dir", False)

    print(f"  1) [ ] SE-managed MCPs ({len(managed)}) - {', '.join(managed) if managed else 'none'}")
    print(f"  2) [ ] SE-related MCPs not tracked ({len(untracked)}) - {', '.join([u['name'] for u in untracked]) if untracked else 'none'}")
    print(f"  3) [ ] Generated OpenCode layer (.opencode/) - {'exists' if has_opencode else 'not found'}")

    print("\nOptions: (a)ll, (1,2,3) toggle/select, ENTER to review plan with current defaults, or (q)uit")
    try:
        choice = input("Select: ").strip().lower()
    except Exception:
        return selections

    if choice == "q":
        selections["_quit"] = True
        return selections
    if choice == "a":
        selections["remove_managed"] = bool(managed)
        selections["remove_untracked_se"] = bool(untracked)
        selections["remove_opencode"] = has_opencode
        return selections
    if choice:
        # simple toggle
        for ch in choice.replace(" ", "").split(","):
            if ch == "1":
                selections["remove_managed"] = not selections["remove_managed"] and bool(managed) or (selections["remove_managed"] and managed and False)
                # easier: just set true if present
                if managed:
                    selections["remove_managed"] = True
            elif ch == "2":
                if untracked:
                    selections["remove_untracked_se"] = True
            elif ch == "3":
                if has_opencode:
                    selections["remove_opencode"] = True
    else:
        # Enter pressed - use defaults but suggest untracked
        if untracked:
            try:
                c2 = input("Include SE-related untracked MCPs (se-memory-server etc.)? [y/N]: ").strip().lower()
                selections["remove_untracked_se"] = c2 in ("y", "yes")
            except Exception:
                pass
        if has_opencode:
            try:
                c3 = input("Remove generated .opencode/ directory? [y/N]: ").strip().lower()
                selections["remove_opencode"] = c3 in ("y", "yes")
            except Exception:
                pass

    return selections


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
    
    # Show untracked SE-related MCPs (detected but not in lifecycle state)
    untracked = report.get("untracked_se_mcp") or []
    if untracked:
        names = ", ".join(u["name"] for u in untracked)
        lines.append(f"SE-related MCPs not tracked ({len(untracked)}): {names}")
        if report["dry_run"]:
            lines.append("Would remove with --include-untracked-se-mcps: " + names)
    
    # Foreign/pre-existing are those that are NOT managed AND NOT detected as SE-related
    foreign = report.get("foreign") or []
    if foreign:
        names = ", ".join(entry["name"] for entry in foreign)
        lines.append(f"Foreign/pre-existing (never touched): {names}")
    
    # Show .opencode/ directory status
    if report.get("has_opencode_dir"):
        lines.append("Generated OpenCode layer (.opencode/): exists")
        if report["dry_run"]:
            lines.append("Would remove with --remove-opencode-dir")
    
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

    interactive = bool(getattr(args, "interactive", False)) or bool(getattr(args, "i", False))
    include_untracked = bool(getattr(args, "include_untracked_se_mcps", False))
    remove_opencode = bool(getattr(args, "remove_opencode_dir", False)) or bool(getattr(args, "purge_adapter", False))
    all_flag = bool(getattr(args, "all", False))
    keep_opencode_jsonc = bool(getattr(args, "keep_opencode_jsonc", False))
    force = bool(getattr(args, "force", False))

    if all_flag:
        include_untracked = True
        remove_opencode = True

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

    managed_set = set((state or {}).get("servers") or {})
    plan = plan_uninstall(state, cfg) if state is not None else {"managed": [], "in_config": [], "state_only": [], "foreign": []}
    untracked_se = detect_untracked_se_mcps(cfg, managed_set) if cfg is not None else []
    has_opencode_dir = (project / ".opencode").exists()

    # Filter foreign to exclude untracked SE MCPs (they'll be shown separately)
    untracked_names = {u["name"] for u in untracked_se}
    foreign_filtered = [f for f in plan["foreign"] if f["name"] not in untracked_names]

    report = _base_report(project, os_name, state_path, config_path, dry_run)
    report.update(
        {
            "managed": plan["managed"],
            "in_config": plan["in_config"],
            "state_only": plan["state_only"],
            "foreign": foreign_filtered,
            "untracked_se_mcp": untracked_se,
            "has_opencode_dir": has_opencode_dir,
            "keep_opencode_jsonc": keep_opencode_jsonc,
        }
    )

    if state is None and not untracked_se and not has_opencode_dir:
        report["status"] = "PASS"
        report["message"] = "nothing managed (no lifecycle state for this target)"
        return _finish(args, "uninstall", "PASS", report=report)

    if not plan["managed"] and not untracked_se and not has_opencode_dir:
        report["message"] = "nothing to uninstall/purge"
        report["status"] = "PASS"
        return _finish(args, "uninstall", "PASS", report=report)

    selections = {
        "remove_managed": bool(plan["managed"]),
        "remove_untracked_se": include_untracked and bool(untracked_se),
        "remove_opencode": remove_opencode and has_opencode_dir,
    }

    if interactive and dry_run and sys.stdin.isatty():
        selections = _interactive_purge_menu(report)
        if selections.get("_quit"):
            report["status"] = "PASS"
            report["message"] = "aborted by user"
            return _finish(args, "uninstall", "PASS", report=report)
        # After interactive selection, if user wants to apply, we need --apply
        # but we stay in plan mode here; user will re-run with --apply or we proceed carefully
        if selections.get("remove_managed") or selections.get("remove_untracked_se") or selections.get("remove_opencode"):
            if not force:
                try:
                    c = input("\nProceed to apply these selections? [y/N]: ").strip().lower()
                    if c not in ("y", "yes"):
                        report["status"] = "PASS"
                        report["message"] = "selections made but not applied (use --apply)"
                        return _finish(args, "uninstall", "PASS", report=report)
                    dry_run = False
                except Exception:
                    pass

    report["selections"] = selections

    if dry_run:
        report["status"] = "PASS"
        return _finish(args, "uninstall", "PASS", report=report)

    # ---- apply ----
    managed_to_remove = set(plan["managed"]) if selections.get("remove_managed") else set()
    for name in plan["managed"]:
        if name not in managed_to_remove:
            continue
        if name in plan["in_config"]:
            result = mcpconfig.remove_server_text(config_path, name, target=project)
            for error in result["errors"]:
                report["errors"].append(f"{name}: {error}")
            if result["errors"] or not result["changed"]:
                if not result["errors"]:
                    report["errors"].append(f"{name}: config entry not found for removal")
                continue
            report["removed"].append(name)
            if result["backup"]:
                report["backups"][name] = result["backup"]
        if state is not None:
            lc.remove_server(state, name)

    # Remove untracked SE-related MCPs
    if selections.get("remove_untracked_se") and untracked_se and cfg is not None:
        for item in untracked_se:
            name = item["name"]
            try:
                result = mcpconfig.remove_server_text(config_path, name, target=project)
                for error in result["errors"]:
                    report["errors"].append(f"{name} (untracked-se): {error}")
                if result["errors"] or not result["changed"]:
                    if not result["errors"]:
                        report["errors"].append(f"{name} (untracked-se): config entry not found for removal")
                    continue
                report["removed"].append(name)
                if result["backup"]:
                    report["backups"][name] = result["backup"]
            except Exception as exc:
                report["errors"].append(f"{name} (untracked-se): {exc}")

    # Remove .opencode/ directory
    if selections.get("remove_opencode"):
        op_res = remove_opencode_dir(project)
        report["opencode_dir"] = op_res
        if op_res["errors"]:
            for err in op_res["errors"]:
                report["errors"].append(f".opencode: {err}")

    if state is not None:
        try:
            lc.save_state(state, project)
        except Exception as exc:  # noqa: BLE001 - reported as a failed uninstall
            report["errors"].append(f"failed to save lifecycle state: {exc}")

    # Guard: only state-recorded names are ever removed (defence in depth).
    unexpected = [name for name in report["removed"] if name not in managed_set and name not in {u["name"] for u in untracked_se}]
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
