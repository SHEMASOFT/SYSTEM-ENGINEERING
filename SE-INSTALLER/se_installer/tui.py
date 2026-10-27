"""Textual TUI for SE Installer."""

from __future__ import annotations

from __future__ import annotations

import subprocess
import sys
from typing import Callable, Iterable, Optional
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import (
    Header, Footer, Static, Button, Checkbox, Label, 
    ProgressBar, Log, TabbedContent, TabPane, Select
)
from textual.widgets import Tree, Collapsible
from textual.reactive import reactive
from textual.message import Message
from textual.screen import Screen
from textual.binding import Binding

from .components import get_all_components, get_components_by_category
from .models import InstallableComponent, InstallStatus, OSType, ComponentType
from .orchestrator import InstallerOrchestrator
from .state import InstallationState


def register_mcps(
    selected_ids: Iterable[str],
    *,
    repo_root: Path | str | None = None,
    project: Path | str | None = None,
    runner: Callable[..., subprocess.CompletedProcess] | None = None,
) -> int:
    """Register the selected MCP servers with the repository's ``se install``.

    The TUI can install MCPs that do not have a registration template yet, so
    only the selected IDs present in ``TEMPLATES/mcp`` are passed to ``--with``.
    """
    repo = Path(repo_root).resolve() if repo_root else Path(__file__).resolve().parents[2]
    target = Path(project).resolve() if project else repo
    se_cli = repo / "SCRIPTS" / "se.py"
    templates_dir = repo / "TEMPLATES" / "mcp"

    if not se_cli.is_file():
        print(
            "MCP registration skipped: SCRIPTS/se.py was not found.",
            file=sys.stderr,
        )
        return 0

    available = {
        path.name[: -len(".json.tmpl")]
        for path in templates_dir.glob("*.json.tmpl")
    }
    keys = sorted(set(selected_ids) & available)
    if not keys:
        print("MCP registration skipped: no selected MCP has a registration template.")
        return 0

    command = [
        sys.executable,
        str(se_cli),
        "install",
        "--project",
        str(target),
        "--with",
        ",".join(keys),
    ]
    print(f"Registering MCP servers: {', '.join(keys)}")

    run = runner or subprocess.run
    try:
        completed = run(
            command,
            cwd=str(target),
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        print("MCP registration timed out after 300 seconds.", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"MCP registration failed: {exc}", file=sys.stderr)
        return 1

    stdout = getattr(completed, "stdout", "") or ""
    stderr = getattr(completed, "stderr", "") or ""
    if stdout:
        print(stdout, end="" if stdout.endswith("\n") else "\n")
    if stderr:
        print(stderr, file=sys.stderr, end="" if stderr.endswith("\n") else "\n")

    if completed.returncode != 0:
        print(
            f"MCP registration failed (exit {completed.returncode}).",
            file=sys.stderr,
        )
        return 1
    return 0


def run_uninstall(
    *,
    repo_root: Path | str | None = None,
    project: Path | str | None = None,
    interactive: bool = False,
    all_flag: bool = False,
    include_untracked: bool = False,
    remove_opencode: bool = False,
    purge_adapter: bool = False,
    keep_jsonc: bool = False,
    force: bool = False,
    apply: bool = False,
    dry_run: bool = True,
    json_output: bool = False,
) -> int:
    """Run the ``se uninstall`` command with the given options."""
    repo = Path(repo_root).resolve() if repo_root else Path(__file__).resolve().parents[2]
    target = Path(project).resolve() if project else repo
    se_cli = repo / "SCRIPTS" / "se.py"

    if not se_cli.is_file():
        print("Error: SCRIPTS/se.py not found.", file=sys.stderr)
        return 1

    cmd = [
        sys.executable,
        str(se_cli),
        "uninstall",
        "--project",
        str(target),
    ]

    if interactive:
        cmd += ["-i"]
    if all_flag:
        cmd += ["--all"]
    if include_untracked:
        cmd += ["--include-untracked-se-mcps"]
    if remove_opencode:
        cmd += ["--remove-opencode-dir"]
    if purge_adapter:
        cmd += ["--purge-adapter"]
    if keep_jsonc:
        cmd += ["--keep-opencode-jsonc"]
    if force:
        cmd += ["--force"]
    if apply:
        cmd += ["--apply"]
    if dry_run:
        cmd += ["--dry-run"]
    if json_output:
        cmd += ["--json"]

    print(f"Running: {' '.join(cmd)}")

    try:
        completed = subprocess.run(
            cmd,
            cwd=str(target),
            capture_output=False,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        print("Uninstall timed out after 300 seconds.", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Uninstall failed: {exc}", file=sys.stderr)
        return 1

    return completed.returncode


class ComponentTree(Tree):
    """Tree widget for component selection."""
    
    def __init__(self, components_by_cat: dict, *args, **kwargs):
        super().__init__("Components", *args, **kwargs)
        self.components_by_cat = components_by_cat
        self.selected_ids = set()
        self.show_root = False
        self.root.expand()
        
        # Build tree
        for cat, comps in components_by_cat.items():
            cat_node = self.root.add(cat, expand=True)
            for comp in comps:
                node = cat_node.add_leaf(f"{comp.name} — {comp.description[:60]}", data=comp.id)
                node.allow_expand = False
    
    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        if event.node.data:
            self.toggle_selection(event.node.data)
    
    def toggle_selection(self, comp_id: str) -> None:
        if comp_id in self.selected_ids:
            self.selected_ids.remove(comp_id)
        else:
            self.selected_ids.add(comp_id)
        
        # Update node label
        for node in self.nodes.values():
            if node.data == comp_id:
                comp = next(c for c in self.app.all_components if c.id == comp_id)
                prefix = "☑ " if comp_id in self.selected_ids else "☐ "
                suffix = f" ({comp.category})"
                node.set_label(f"{prefix}{comp.name} — {comp.description[:60]}{suffix}")
                break
    
    def get_selected(self) -> set:
        return self.selected_ids.copy()


class ProgressWidget(Static):
    """Progress display widget."""
    
    progress = reactive(0.0)
    current_component = reactive("")
    status_text = reactive("")
    
    def compose(self) -> ComposeResult:
        yield ProgressBar(total=100, show_eta=False, id="progress-bar")
        yield Static("", id="status-text")
    
    def watch_progress(self, value: float) -> None:
        self.query_one("#progress-bar", ProgressBar).update(progress=value)
    
    def watch_current_component(self, value: str) -> None:
        self.query_one("#status-text", Static).update(f"[{value}] {self.status_text}")
    
    def watch_status_text(self, value: str) -> None:
        self.query_one("#status-text", Static).update(f"[{self.current_component}] {value}")
    
    def update_progress(self, current: int, total: int, component: str, status: str) -> None:
        self.progress = (current / max(total, 1)) * 100
        self.current_component = component
        self.status_text = status


class LogWidget(Log):
    """Installation log widget."""
    
    def add_entry(self, level: str, message: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        self.write_line(f"[{timestamp}] {level}: {message}")


class ComponentDetailPanel(Static):
    """Detail panel for selected component."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_component = None
    
    def show_component(self, comp: Optional) -> None:
        self.current_component = comp
        if comp is None:
            self.update("Selecciona un componente para ver detalles")
            return
        
        status_icon = {
            InstallStatus.PENDING: "⏳",
            InstallStatus.INSTALLING: "🔄",
            InstallStatus.SUCCESS: "✅",
            InstallStatus.FAILED: "❌",
            InstallStatus.SKIPPED: "⏭️",
        }.get(comp.status, "❓")
        
        reqs = ", ".join(comp.requires) if comp.requires else "Ninguno"
        
        content = f"""# {comp.name} {status_icon}
**Categoría:** {comp.category}
**Estado:** {comp.status.value}
**Versión instalada:** {comp.installed_version or "No instalado"}
**Tipo:** {comp.component_type.value}

**Descripción:**
{comp.long_description}

**Requiere:** {reqs}
**OS soportados:** {", ".join(o.value for c in comp.supported_os)}
**Método:** {comp.install_method}

**Homepage:** {comp.homepage}
**Docs:** {comp.docs_url}
**Licencia:** {comp.license or "N/A"}

**Recomendado:** {"Sí" if comp.recommended else "No"}
"""
        self.update(content)


class InstallerApp(App):
    """Main SE Installer TUI Application."""
    
    TITLE = "SE Installer"
    SUB_TITLE = "System Engineering Master System - Unified Installer"
    
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("space", "toggle_select", "Select/Unselect"),
        Binding("enter", "install", "Install Selected"),
        Binding("r", "refresh", "Refresh Status"),
        Binding("d", "dry_run", "Toggle Dry Run"),
        Binding("a", "select_all_recommended", "Select Recommended"),
    ]
    
    CSS = """
    Screen {
        layout: horizontal;
    }
    
    #sidebar {
        width: 45%;
        border-right: solid $primary;
        padding: 1;
    }
    
    #main {
        width: 55%;
        padding: 1;
    }
    
    #component-tree {
        height: 1fr;
        border: solid $secondary;
        padding: 1;
    }
    
    #progress-container {
        height: auto;
        margin: 1 0;
        padding: 1;
        border: solid $primary;
    }
    
    #detail-panel {
        height: 1fr;
        border: solid $secondary;
        padding: 1;
        overflow-y: auto;
    }
    
    #log-container {
        height: 20;
        border: solid $secondary;
        padding: 1;
        margin-top: 1;
    }
    
    #buttons {
        height: auto;
        padding: 1;
        dock: bottom;
    }
    
    Button {
        margin: 0 1;
    }
    
    .success { color: green; }
    .failed { color: red; }
    .pending { color: yellow; }
    .installing { color: cyan; }
    .skipped { color: gray; }
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.orchestrator = None
        self.dry_run = False
        self.selected_ids = set()
        self.installation_running = False
        # The CLI needs to know whether the last run succeeded before it can
        # decide the exit code and register the selected MCPs.
        self.installation_attempted = False
        self.install_succeeded = False
        self.install_was_dry_run = False
        self.installed_mcp_ids: list[str] = []
    
    def compose(self) -> ComposeResult:
        yield Header()
        
        with TabbedContent():
            # Tab 1: Instalar
            with TabPane("Instalar", id="tab-install"):
                with Horizontal():
                    # Sidebar - Component Selection
                    with Vertical(id="sidebar"):
                        yield Static("## Componentes a Instalar", id="sidebar-title")
                        yield Static("SPACE=select | ENTER=install | A=recommended", id="hint")
                        yield ComponentTree(self.get_components_by_cat(), id="component-tree")
                        yield Checkbox(
                            "Crear acceso directo en el Escritorio (SE Console)",
                            id="chk-shortcuts",
                        )
                        
                        with Horizontal(id="buttons"):
                            yield Button("Instalar Seleccionados", id="btn-install", variant="primary")
                            yield Button("Solo Recomendados", id="btn-recommended")
                            yield Button("Refrescar", id="btn-refresh")
                            yield Button("Dry Run: OFF", id="btn-dryrun")
                    
                    # Main - Progress + Detail + Log
                    with Vertical(id="main"):
                        yield Static("## Detalle del Componente", id="detail-title")
                        yield ComponentDetailPanel(id="detail-panel")
                        
                        with Container(id="progress-container"):
                            yield ProgressWidget(id="progress-widget")
                        
                        yield Static("## Log de Instalación", id="log-title")
                        yield LogWidget(id="log-widget")
            
            # Tab 2: Desinstalar
            with TabPane("Desinstalar", id="tab-uninstall"):
                with Vertical(id="uninstall-container"):
                    yield Static("## Desinstalar System Engineering de OpenCode", id="uninstall-title")
                    yield Static(
                        "Esta herramienta elimina artefactos generados por SE en OpenCode:\n"
                        "• MCPs gestionados por SE (lifecycle-state)\n"
                        "• MCPs SE no rastreados (se-memory-server, se-skill-server, etc.)\n"
                        "• Capa generada de OpenCode (.opencode/ con agentes, comandos, skills)\n\n"
                        "Los MCPs ajenos (context7, filesystem, etc.) NUNCA se tocan.",
                        id="uninstall-description"
                    )
                    
                    with Horizontal(id="uninstall-options"):
                        with Vertical(id="uninstall-left"):
                            yield Checkbox("Interactivo (selección por elemento)", id="chk-uninstall-interactive", value=True)
                            yield Checkbox("Todo (--all): MCPs gestionados + no rastreados + .opencode/", id="chk-uninstall-all")
                            yield Checkbox("Incluir MCPs SE no rastreados (se-memory-server, etc.)", id="chk-uninstall-untracked")
                            yield Checkbox("Eliminar .opencode/ generado (con backup)", id="chk-uninstall-opencode")
                        
                        with Vertical(id="uninstall-right"):
                            yield Checkbox("Alias --purge-adapter (igual que --remove-opencode-dir)", id="chk-uninstall-purge")
                            yield Checkbox("No tocar opencode.jsonc (--keep-opencode-jsonc)", id="chk-uninstall-keep-jsonc")
                            yield Checkbox("Forzar sin confirmaciones extra (--force)", id="chk-uninstall-force")
                            yield Checkbox("Aplicar cambios (--apply) - por defecto es dry-run", id="chk-uninstall-apply")
                    
                    with Horizontal(id="uninstall-buttons"):
                        yield Button("Ejecutar Desinstalación (Dry-Run)", id="btn-uninstall-dryrun", variant="default")
                        yield Button("Ejecutar Desinstalación (Aplicar)", id="btn-uninstall-apply", variant="primary")
                        yield Button("Refrescar Estado", id="btn-uninstall-refresh")
                    
                    yield Static("## Log de Desinstalación", id="uninstall-log-title")
                    yield LogWidget(id="uninstall-log-widget")
        
        yield Footer()
    
    def on_mount(self) -> None:
        self._load_state()
    
    @property
    def all_components(self):
        from .components import get_all_components
        return get_all_components()
    
    def on_tree_node_selected(self, event) -> None:
        if event.node.data:
            comp_id = event.node.data
            comp = next((c for c in self.all_components if c.id == comp_id), None)
            if comp:
                self.query_one("#detail-panel", ComponentDetailPanel).show_component(comp)
    
    def action_toggle_select(self) -> None:
        tree = self.query_one("#component-tree", Tree)
        if tree.cursor_node and tree.cursor_node.data:
            comp_id = tree.cursor_node.data
            self.toggle_selection(comp_id)
    
    def toggle_selection(self, comp_id: str) -> None:
        if comp_id in self.selected_ids:
            self.selected_ids.remove(comp_id)
        else:
            self.selected_ids.add(comp_id)
        self._refresh_tree_labels()
    
    def _refresh_tree_labels(self) -> None:
        tree = self.query_one("#component-tree", Tree)
        for node in tree.nodes.values():
            if node.data:
                comp = next(c for c in self.all_components if c.id == node.data)
                prefix = "☑ " if node.data in self.selected_ids else "☐ "
                suffix = f" ({comp.category})"
                node.set_label(f"{prefix}{comp.name} — {comp.description[:60]}{suffix}")
    
    def get_components_by_cat(self):
        from .components import get_components_by_category
        return get_components_by_category()
    
    def action_select_all_recommended(self) -> None:
        self.selected_ids = {c.id for c in self.all_components if c.recommended}
        self._refresh_tree_labels()
    
    def action_refresh(self) -> None:
        self._refresh_status()
    
    def action_dry_run(self) -> None:
        self.dry_run = not self.dry_run
        btn = self.query_one("#btn-dryrun", Button)
        btn.label = f"Dry Run: {'ON' if self.dry_run else 'OFF'}"
        btn.variant = "primary" if self.dry_run else "default"
    
    def action_install(self) -> None:
        if not self.selected_ids:
            self.notify("No hay componentes seleccionados", severity="warning")
            return
        
        if self.installation_running:
            return
        
        self.installation_running = True
        self._start_installation()
    
    def _start_installation(self) -> None:
        from .orchestrator import InstallerOrchestrator

        self.installation_attempted = True
        self.install_succeeded = False
        self.install_was_dry_run = self.dry_run
        self.installed_mcp_ids = []

        self.orchestrator = InstallerOrchestrator(
            dry_run=self.dry_run,
            progress_callback=self._on_progress
        )
        
        # The operator answered the shortcut question with this checkbox. It is
        # read here, at install time, so what gets created matches what the box
        # said when Install was pressed.
        self.orchestrator.plan.create_shortcuts = bool(
            self.query_one("#chk-shortcuts", Checkbox).value
        )
        
        self.orchestrator.prepare_plan(
            selected_ids=list(self.selected_ids),
            target_runtimes=["opencode"]  # default
        )
        
        # Disable buttons during installation
        self.query_one("#btn-install", Button).disabled = True
        self.query_one("#btn-recommended", Button).disabled = True
        self.query_one("#btn-refresh", Button).disabled = True
        self.query_one("#btn-dryrun", Button).disabled = True
        self.query_one("#chk-shortcuts", Checkbox).disabled = True
        
        # Run installation in background
        self.run_worker(self._run_installation, exclusive=True)
    
    async def _run_installation(self) -> None:
        success = self.orchestrator.run_installation()
        self.installation_running = False
        self.install_succeeded = success
        if success:
            self.installed_mcp_ids = [
                comp.id
                for comp in self.orchestrator.plan.components
                if comp.component_type == ComponentType.MCP
                and comp.status == InstallStatus.SUCCESS
            ]
        
        # Re-enable buttons
        self.query_one("#btn-install", Button).disabled = False
        self.query_one("#btn-recommended", Button).disabled = False
        self.query_one("#btn-refresh", Button).disabled = False
        self.query_one("#btn-dryrun", Button).disabled = False
        self.query_one("#chk-shortcuts", Checkbox).disabled = False
        
        summary = self.orchestrator.get_summary()
        if success:
            self.notify(f"Instalación completada: {summary['success']}/{summary['total']} OK", severity="success")
        else:
            self.notify(f"Instalación completada con errores: {summary['failed']} fallaron", severity="error")
        
        self._refresh_tree_labels()
    
    def _on_progress(self, event: str, data: dict) -> None:
        self.call_from_thread(self._handle_progress, event, data)
    
    def _handle_progress(self, event: str, data: dict) -> None:
        log = self.query_one("#log-widget", LogWidget)
        progress = self.query_one("#progress-widget", ProgressWidget)
        
        if event == "started":
            log.add_entry("INFO", f"Iniciando instalación de {data['total']} componentes")
        elif event == "component_start":
            comp_id = data["component"]
            comp = next((c for c in self.all_components if c.id == comp_id), None)
            name = comp.name if comp else comp_id
            progress.update_progress(
                data["index"], data["total"], name, "Iniciando..."
            )
            log.add_entry("INFO", f"Iniciando {name}")
        elif event == "status_change":
            comp_id = data["component"]
            status = data["status"]
            comp = next((c for c in self.all_components if c.id == comp_id), None)
            if comp:
                comp.status = type(comp.status)(status)
            self._refresh_tree_labels()
            
            if "version" in data:
                log.add_entry("SUCCESS", f"{comp_id} v{data['version']} instalado")
            if "error" in data:
                log.add_entry("ERROR", f"{comp_id}: {data['error']}")
        elif event == "component_failed":
            log.add_entry("ERROR", f"{data['component']} falló: {data['error']}")
        elif event == "shortcut":
            if data.get("created"):
                log.add_entry("SUCCESS", f"Acceso directo creado: {data['path']}")
            elif data.get("skipped"):
                log.add_entry("INFO", f"Acceso directo omitido: {data.get('reason', '')}")
            elif data.get("dry_run") and not data.get("error"):
                log.add_entry("INFO", f"Acceso directo (dry run): {data['path']}")
            else:
                log.add_entry("ERROR", f"Acceso directo: {data.get('error') or 'no se pudo crear'}")
        elif event == "completed":
            log.add_entry("INFO" if data["success"] else "ERROR", 
                         f"Instalación {'completada' if data['success'] else 'fallida'}")
    
    def _refresh_status(self) -> None:
        """Refresh component statuses by checking what's installed."""
        for comp in self.all_components:
            if comp.component_type.value in ("mcp", "runtime"):
                # Quick check
                from .installers.mcp import get_mcp_installer
                from .installers.runtime import get_runtime_installer
                from .models import ComponentType
                
                try:
                    if comp.component_type == ComponentType.MCP:
                        installer = get_mcp_installer(comp.id, comp, dry_run=True)
                    elif comp.component_type == ComponentType.RUNTIME:
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
        
        self._refresh_tree_labels()
        self.notify("Estado actualizado", severity="information")
    
    def _load_state(self) -> None:
        state = InstallationState()
        plan = self.orchestrator.plan if self.orchestrator else None
        if plan and state.load_plan(plan):
            self.selected_ids = {c.id for c in plan.components if c.status != InstallStatus.SKIPPED}
            self._refresh_tree_labels()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses for uninstall tab."""
        button_id = event.button.id
        
        if button_id == "btn-uninstall-dryrun":
            self._run_uninstall(apply=False)
        elif button_id == "btn-uninstall-apply":
            self._run_uninstall(apply=True)
        elif button_id == "btn-uninstall-refresh":
            self._refresh_uninstall_status()

    def _refresh_uninstall_status(self) -> None:
        """Show current status of SE artifacts in OpenCode."""
        log = self.query_one("#uninstall-log-widget", LogWidget)
        log.add_entry("INFO", "Refrescando estado de artefactos SE en OpenCode...")
        # We can run a quick dry-run to show what would be removed
        self._run_uninstall(apply=False, dry_run=True, capture_output=True)

    def _run_uninstall(self, apply: bool = False, dry_run: bool = True, capture_output: bool = False) -> None:
        """Run the uninstall command with current checkbox selections."""
        log = self.query_one("#uninstall-log-widget", LogWidget)
        
        # Read checkbox values
        interactive = self.query_one("#chk-uninstall-interactive", Checkbox).value
        all_flag = self.query_one("#chk-uninstall-all", Checkbox).value
        include_untracked = self.query_one("#chk-uninstall-untracked", Checkbox).value
        remove_opencode = self.query_one("#chk-uninstall-opencode", Checkbox).value
        purge_adapter = self.query_one("#chk-uninstall-purge", Checkbox).value
        keep_jsonc = self.query_one("#chk-uninstall-keep-jsonc", Checkbox).value
        force = self.query_one("#chk-uninstall-force", Checkbox).value
        
        # If apply checkbox is checked, override the dry_run parameter
        if self.query_one("#chk-uninstall-apply", Checkbox).value:
            apply = True
            dry_run = False
        
        log.add_entry("INFO", f"Ejecutando desinstalación (apply={apply}, dry_run={dry_run})...")
        
        # Disable buttons during execution
        self.query_one("#btn-uninstall-dryrun", Button).disabled = True
        self.query_one("#btn-uninstall-apply", Button).disabled = True
        self.query_one("#btn-uninstall-refresh", Button).disabled = True
        
        # Run in background worker
        self.run_worker(
            self._run_uninstall_worker,
            interactive=interactive,
            all_flag=all_flag,
            include_untracked=include_untracked,
            remove_opencode=remove_opencode,
            purge_adapter=purge_adapter,
            keep_jsonc=keep_jsonc,
            force=force,
            apply=apply,
            dry_run=dry_run,
            exclusive=True
        )

    async def _run_uninstall_worker(
        self,
        interactive: bool,
        all_flag: bool,
        include_untracked: bool,
        remove_opencode: bool,
        purge_adapter: bool,
        keep_jsonc: bool,
        force: bool,
        apply: bool,
        dry_run: bool,
    ) -> None:
        """Worker to run uninstall command."""
        log = self.query_one("#uninstall-log-widget", LogWidget)
        
        try:
            exit_code = run_uninstall(
                interactive=interactive,
                all_flag=all_flag,
                include_untracked=include_untracked,
                remove_opencode=remove_opencode,
                purge_adapter=purge_adapter,
                keep_jsonc=keep_jsonc,
                force=force,
                apply=apply,
                dry_run=dry_run,
            )
            
            if exit_code == 0:
                log.add_entry("SUCCESS", "Desinstalación completada exitosamente")
                self.notify("Desinstalación completada", severity="success")
            else:
                log.add_entry("ERROR", f"Desinstalación falló (exit {exit_code})")
                self.notify("Desinstalación falló", severity="error")
        except Exception as exc:
            log.add_entry("ERROR", f"Error ejecutando desinstalación: {exc}")
            self.notify(f"Error: {exc}", severity="error")
        finally:
            # Re-enable buttons
            self.query_one("#btn-uninstall-dryrun", Button).disabled = False
            self.query_one("#btn-uninstall-apply", Button).disabled = False
            self.query_one("#btn-uninstall-refresh", Button).disabled = False