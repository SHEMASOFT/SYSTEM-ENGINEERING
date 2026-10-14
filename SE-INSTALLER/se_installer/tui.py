"""Textual TUI for SE Installer."""

from __future__ import annotations

from __future__ import annotations

from typing import Optional, Callable
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
    
    def compose(self) -> ComposeResult:
        yield Header()
        
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