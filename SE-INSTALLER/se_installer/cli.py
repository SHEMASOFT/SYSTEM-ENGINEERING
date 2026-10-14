"""CLI entry point for SE Installer."""

from __future__ import annotations

import sys
import argparse

from .orchestrator import InstallerOrchestrator
from .components import get_all_components, get_recommended_components
from .models import InstallationPlan, OSType, InstallStatus


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="se-installer",
        description="SE Installer - Unified installer for System Engineering Master System"
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # install command
    install_parser = subparsers.add_parser("install", help="Install selected components")
    install_parser.add_argument(
        "--components", "-c", nargs="+",
        help="Component IDs to install (default: all recommended)"
    )
    install_parser.add_argument(
        "--all", "-a", action="store_true",
        help="Install all components"
    )
    install_parser.add_argument(
        "--recommended", "-r", action="store_true",
        help="Install only recommended components (default)"
    )
    install_parser.add_argument(
        "--dry-run", action="store_true",
        help="Validate and plan only, don't install"
    )
    install_parser.add_argument(
        "--runtimes", nargs="+", default=["opencode"],
        help="Target runtimes to configure (opencode, codex, claude_code)"
    )
    install_parser.add_argument(
        "--force", action="store_true",
        help="Force reinstall even if already installed"
    )
    install_parser.add_argument(
        "--skip-verification", action="store_true",
        help="Skip post-install verification"
    )
    # Opt-in, and mutually exclusive so the intent is never ambiguous. Default is
    # off: the shortcut writes to the operator's Desktop.
    shortcut_group = install_parser.add_mutually_exclusive_group()
    shortcut_group.add_argument(
        "--shortcuts", dest="shortcuts", action="store_true",
        help="Create a desktop shortcut for the SE Console (one shortcut; it starts the console)"
    )
    shortcut_group.add_argument(
        "--no-shortcuts", dest="shortcuts", action="store_false",
        help="Do not create any desktop shortcut (default)"
    )
    install_parser.set_defaults(shortcuts=False)
    install_parser.add_argument(
        "--json", action="store_true",
        help="Output JSON result"
    )

    # list command
    list_parser = subparsers.add_parser("list", help="List available components")
    list_parser.add_argument(
        "--category", help="Filter by category"
    )
    list_parser.add_argument(
        "--installed", action="store_true",
        help="Show only installed components"
    )
    list_parser.add_argument(
        "--json", action="store_true",
        help="Output JSON"
    )

    # status command
    status_parser = subparsers.add_parser("status", help="Check installation status")
    status_parser.add_argument(
        "--json", action="store_true",
        help="Output JSON"
    )

    # tui command
    tui_parser = subparsers.add_parser("tui", help="Launch interactive TUI")

    # doctor command
    doctor_parser = subparsers.add_parser("doctor", help="Run health checks")
    doctor_parser.add_argument(
        "--json", action="store_true",
        help="Output JSON"
    )

    return parser


def print_components(components, show_status=True, json_output=False):
    """Print component list."""
    import json

    if json_output:
        data = []
        for c in components:
            data.append({
                "id": c.id,
                "name": c.name,
                "description": c.description,
                "category": c.category,
                "component_type": c.component_type.value,
                "status": c.status.value if show_status else "unknown",
                "installed_version": c.installed_version,
                "requires": c.requires,
                "recommended": c.recommended,
                "install_method": c.install_method,
            })
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return

    from collections import defaultdict
    by_cat = defaultdict(list)
    for c in components:
        by_cat[c.category].append(c)

    for cat, comps in sorted(by_cat.items()):
        print(f"\n[DIR] {cat}")
        for c in comps:
            status_str = ""
            if show_status:
                # Keys must match InstallStatus.value (lowercase), not the
                # upper-case member names, or every status renders as "[?]".
                icons = {
                    InstallStatus.SUCCESS.value: "[OK]",
                    InstallStatus.FAILED.value: "[FAIL]",
                    InstallStatus.PENDING.value: "[PENDING]",
                    InstallStatus.CHECKING.value: "[CHECK]",
                    InstallStatus.DOWNLOADING.value: "[DL]",
                    InstallStatus.INSTALLING.value: "[INSTALLING]",
                    InstallStatus.CONFIGURING.value: "[CONFIG]",
                    InstallStatus.VERIFYING.value: "[VERIFY]",
                    InstallStatus.SKIPPED.value: "[SKIPPED]",
                }
                icon = icons.get(c.status.value, "[?]")
                ver = f" {c.installed_version}" if c.installed_version else ""
                status_str = f" {icon}{ver}"

            rec = " *" if c.recommended else ""
            print(f"  {c.id:<20} {c.name:<25}{status_str}{rec}")
            print(f"    {c.description}")

    return 0


def cmd_list(args) -> int:
    from .components import get_all_components, get_components_by_category

    components = get_all_components()

    if args.category:
        components = [c for c in components if c.category.lower() == args.category.lower()]

    if args.installed:
        components = [c for c in components if c.status == InstallStatus.SUCCESS]

    print_components(components, show_status=True, json_output=args.json)
    return 0


def cmd_status(args) -> int:
    import json
    from .orchestrator import InstallerOrchestrator

    plan = InstallationPlan()
    orchestrator = InstallerOrchestrator(plan)

    # Check all components. Reuse the same list for probing AND reporting, so
    # the computed status is actually shown (a fresh get_all_components() call
    # returns unprobed components and always reports PENDING).
    components = get_all_components()
    for comp in components:
        if comp.component_type.value in ("mcp", "runtime"):
            try:
                if comp.component_type.value == "mcp":
                    from .installers.mcp import get_mcp_installer
                    installer = get_mcp_installer(comp.id, comp, dry_run=True)
                elif comp.component_type.value == "runtime":
                    from .installers.runtime import get_runtime_installer
                    installer = get_runtime_installer(comp.id, comp, dry_run=True)
                else:
                    continue

                installed, version = installer.check_installed()
                if installed:
                    comp.status = InstallStatus.SUCCESS
                    comp.installed_version = version
                else:
                    comp.status = InstallStatus.PENDING
            except Exception:
                pass

    if args.json:
        data = []
        for c in components:
            data.append({
                "id": c.id,
                "name": c.name,
                "status": c.status.value,
                "version": c.installed_version,
                "category": c.category,
            })
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print_components(components, show_status=True)

    return 0


def cmd_doctor(args) -> int:
    import json
    from .orchestrator import InstallerOrchestrator

    plan = InstallationPlan()
    orchestrator = InstallerOrchestrator(plan)

    # Run health checks
    issues = []
    warnings = []

    # Check Python
    import sys
    if sys.version_info < (3, 10):
        issues.append(f"Python {sys.version.split()[0]} < 3.10 (requerido 3.10+)")

    # Check required components
    components = get_all_components()
    for comp in components:
        if comp.component_type.value in ("mcp", "runtime") and comp.recommended:
            try:
                if comp.component_type.value == "mcp":
                    from .installers.mcp import get_mcp_installer
                    installer = get_mcp_installer(comp.id, comp, dry_run=True)
                elif comp.component_type.value == "runtime":
                    from .installers.runtime import get_runtime_installer
                    installer = get_runtime_installer(comp.id, comp, dry_run=True)
                else:
                    continue

                installed, version = installer.check_installed()
                if not installed:
                    if comp.id in ("se_core", "opencode", "engram"):
                        issues.append(f"{comp.name} ({comp.id}) no instalado (requerido)")
                    else:
                        warnings.append(f"{comp.name} ({comp.id}) no instalado (opcional)")
                else:
                    print(f"[OK] {comp.name} v{version}")
            except Exception as e:
                warnings.append(f"Error verificando {comp.name}: {e}")

    if args.json:
        print(json.dumps({
            "issues": issues,
            "warnings": warnings,
            "ok": len(issues) == 0
        }, indent=2))
    else:
        if issues:
            print("[ISSUES]:")
            for i in issues:
                print(f"  - {i}")
        if warnings:
            print("[WARNINGS]:")
            for w in warnings:
                print(f"  - {w}")
        if not issues and not warnings:
            print("[OK] Todo OK")

    return 0 if len(issues) == 0 else 1


def _print_shortcut(data, out) -> None:
    """Report the desktop shortcut, when the plan asked for one."""
    if data is None:
        return
    if data.get("created"):
        print(f"  [OK] Acceso directo: {data['path']}", file=out)
    elif data.get("skipped"):
        print(f"  [SKIP] Acceso directo: {data.get('reason', '')}", file=out)
    elif data.get("dry_run") and not data.get("error"):
        print(f"  [PLAN] Acceso directo: {data['path']} (dry run: no se crea)", file=out)
    else:
        print(f"  [FAIL] Acceso directo: {data.get('error') or 'no se pudo crear'}", file=out)


def cmd_install(args) -> int:
    from .orchestrator import InstallerOrchestrator
    from .models import InstallationPlan
    import json
    import sys

    plan = InstallationPlan()
    plan.dry_run = args.dry_run
    plan.force_reinstall = args.force
    plan.skip_verification = args.skip_verification
    # `is True`, not truthiness: an opt-in that writes to the operator's Desktop
    # has to be an explicit yes. Nothing else may switch it on by accident.
    plan.create_shortcuts = getattr(args, "shortcuts", False) is True

    orchestrator = InstallerOrchestrator(plan)

    # Determine components to install
    if args.all:
        selected = [c.id for c in get_all_components()]
    elif args.components:
        selected = args.components
    else:
        selected = [c.id for c in get_recommended_components()]

    orchestrator.prepare_plan(selected, args.runtimes)

    # When --json, send progress to stderr so stdout is clean JSON
    json_mode = args.json
    def progress_cb(event, data):
        icons = {"started": "[START]", "component_start": "[>>]", "status_change": "[..]",
                 "component_failed": "[FAIL]", "completed": "[DONE]"}
        icon = icons.get(event, "[INFO]")
        out = sys.stderr if json_mode else sys.stdout
        if event == "component_start":
            print(f"{icon} [{data['index']+1}/{data['total']}] {data['component']}", file=out)
        elif event == "status_change":
            comp = data["component"]
            status = data["status"]
            if "version" in data:
                print(f"  [OK] {comp} v{data['version']}", file=out)
            elif "error" in data:
                print(f"  [FAIL] {comp}: {data['error']}", file=out)
        elif event == "completed":
            if data["success"]:
                print("[DONE] Instalación completada exitosamente", file=out)
            else:
                print("[FAIL] Instalación completada con errores", file=out)
        elif event == "shortcut":
            _print_shortcut(data, out)

    orchestrator = InstallerOrchestrator(
        plan=plan,
        dry_run=args.dry_run,
        progress_callback=progress_cb
    )

    orchestrator.prepare_plan(selected, args.runtimes)
    success = orchestrator.run_installation()

    summary = orchestrator.get_summary()

    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print("\n[RESUMEN]")
        print(f"  Total (seleccionados): {summary['total']}")
        print(f"  [OK] Exitos: {summary['success']}")
        print(f"  [FAIL] Fallos: {summary['failed']}")
        print(f"  [SKIP] Omitidos (no seleccionados): {summary['skipped']}")
        _print_shortcut(summary.get("shortcut"), sys.stdout)

    return 0 if success else 1


def cmd_tui(args) -> int:
    from .tui import InstallerApp
    app = InstallerApp()
    app.run()
    return 0


def main() -> int:
    parser = create_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    commands = {
        "install": cmd_install,
        "list": cmd_list,
        "status": cmd_status,
        "doctor": cmd_doctor,
        "tui": cmd_tui,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
