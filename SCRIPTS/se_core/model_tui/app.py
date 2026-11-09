"""Main Textual App for SE SHEMA-AI Model Picker."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import (
    Header, Footer, Static, Button, Label,
    DataTable, TabbedContent, TabPane, Select
)
from textual.reactive import reactive
from textual.screen import Screen
from textual.message import Message

from .providers import discover_providers, ProviderInfo
from .config import (
    load_model_config,
    save_model_config,
    ModelConfig,
    AgentModelOverride,
    reload_opencode_config,
)
from .rows import AGENT_ROWS, AgentRow
from .screens.agent_list import AgentListScreen
from .screens.provider_select import ProviderSelectScreen
from .screens.model_select import ModelSelectScreen
from .screens.effort_select import EffortSelectScreen


class ModelPickerApp(App):
    """SE SHEMA-AI Model Configuration TUI."""

    TITLE = "SE SHEMA-AI"
    SUB_TITLE = "Model Configuration per Agent"
    CSS_PATH = "app.tcss"
    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("s", "save", "Save & Reload", show=True),
        Binding("r", "reset", "Reset to Defaults", show=True),
        Binding("tab", "next_tab", "Next Section", show=False),
        Binding("shift+tab", "prev_tab", "Prev Section", show=False),
    ]

    # Reactive state
    global_model: reactive[str] = reactive("anthropic/claude-sonnet-5-5")
    providers: reactive[list[ProviderInfo]] = reactive([])
    agent_overrides: reactive[dict[str, AgentModelOverride]] = reactive({})
    selected_agent_index: reactive[int] = reactive(0)
    current_section: reactive[str] = reactive("agents")  # agents, providers, global

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.config: Optional[ModelConfig] = None
        self.project_root: Optional[Path] = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            # Sidebar - Navigation
            with Vertical(id="sidebar"):
                yield Static("SE SHEMA-AI", id="logo")
                yield Static("Model Configuration", id="subtitle")
                yield Button("Global Model", id="nav-global", variant="primary")
                yield Button("Agent Overrides", id="nav-agents", variant="default")
                yield Button("Providers", id="nav-providers", variant="default")
                yield Static("", id="spacer")
                yield Button("Save & Reload (s)", id="btn-save", variant="success")
                yield Button("Reset Defaults (r)", id="btn-reset", variant="warning")
                yield Button("Quit (q)", id="btn-quit", variant="error")
            # Main content area
            with Vertical(id="main-content"):
                yield Static(id="content-title")
                with ScrollableContainer(id="content-body"):
                    yield Static("Loading...", id="loading")

        yield Footer()

    async def on_mount(self) -> None:
        """Initialize app state."""
        self.project_root = self._find_project_root()
        await self._load_config()
        await self._discover_providers()
        self._update_nav_styles()
        await self._show_section("agents")

    def _find_project_root(self) -> Path:
        """Find the repository root (where opencode.jsonc lives)."""
        # Try current working directory first
        cwd = Path.cwd()
        if (cwd / "opencode.jsonc").exists():
            return cwd
        # Try parent directories
        for parent in cwd.parents:
            if (parent / "opencode.jsonc").exists():
                return parent
        # Fallback to repo root from paths module
        from se_core.paths import repo_root
        return repo_root()

    async def _load_config(self) -> None:
        """Load model configuration from opencode.jsonc."""
        self.config = load_model_config(self.project_root)
        self.global_model = self.config.global_model
        self.agent_overrides = self.config.agent_overrides.copy()

    async def _discover_providers(self) -> None:
        """Discover available providers and models from OpenCode runtime."""
        try:
            self.providers = await discover_providers(self.project_root)
        except Exception as e:
            self.notify(f"Provider discovery failed: {e}", severity="warning")
            self.providers = []

    def _update_nav_styles(self) -> None:
        """Update navigation button styles based on current section."""
        for btn_id, variant in [
            ("nav-global", "primary" if self.current_section == "global" else "default"),
            ("nav-agents", "primary" if self.current_section == "agents" else "default"),
            ("nav-providers", "primary" if self.current_section == "providers" else "default"),
        ]:
            btn = self.query_one(f"#{btn_id}", Button)
            btn.variant = variant

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        btn_id = event.button.id
        if btn_id in ("nav-global", "nav-agents", "nav-providers"):
            section = btn_id.replace("nav-", "")
            await self._show_section(section)
        elif btn_id == "btn-save":
            await self._save_and_reload()
        elif btn_id == "btn-reset":
            await self._reset_to_defaults()
        elif btn_id == "btn-quit":
            self.exit()

    async def _show_section(self, section: str) -> None:
        """Show the specified section."""
        self.current_section = section
        self._update_nav_styles()

        body = self.query_one("#content-body", ScrollableContainer)
        await body.remove_children()

        if section == "global":
            await self._render_global_section(body)
        elif section == "agents":
            await self._render_agents_section(body)
        elif section == "providers":
            await self._render_providers_section(body)

        self.query_one("#content-title", Static).update({
            "global": "Global Model",
            "agents": "Agent Overrides",
            "providers": "Providers & Models",
        }[section])

    async def _render_global_section(self, container: ScrollableContainer) -> None:
        """Render global model selection."""
        # Provider select
        provider_names = [f"{p.name} ({p.id})" for p in self.providers]
        current_provider = self.global_model.split("/")[0] if "/" in self.global_model else ""
        provider_idx = next((i for i, p in enumerate(self.providers) if p.id == current_provider), 0)

        await container.mount(
            Static("Global Model Configuration", classes="section-title"),
            Label("Select Provider:"),
            Select(
                [(name, i) for i, name in enumerate(provider_names)],
                value=provider_idx,
                id="global-provider-select",
                allow_blank=False,
            ),
            Label(""),
            Label("Model:"),
            Select(
                [(m.name, m.id) for m in self.providers[provider_idx].models] if self.providers else [("No models", "")],
                value=self.global_model.split("/")[1] if "/" in self.global_model else "",
                id="global-model-select",
                allow_blank=False,
            ),
            Label(""),
            Label("Variant/Effort:"),
            Select(
                [("default", ""), ("high", "high"), ("medium", "medium"), ("low", "low")],
                value="",
                id="global-variant-select",
                allow_blank=True,
            ),
        )

    async def _render_agents_section(self, container: ScrollableContainer) -> None:
        """Render agent overrides table."""
        table = DataTable(id="agents-table", zebra_stripes=True)
        table.add_columns("Agent", "Current Model", "Status", "Action")

        for row in AGENT_ROWS:
            override = self.agent_overrides.get(row.agent_id)
            if override and override.provider and override.model:
                model_display = f"{override.provider}/{override.model}"
                if override.variant:
                    model_display += f" [{override.variant}]"
                status = "Overridden"
            else:
                model_display = f"(inherits: {self.global_model})"
                status = "Inherited"
            table.add_row(row.display_name, model_display, status, "Change" if override else "Set Override", key=row.agent_id)

        await container.mount(
            Static("Agent Model Overrides", classes="section-title"),
            Label(f"Global default: {self.global_model}"),
            Label(""),
            table,
        )

        # Focus the table
        table.focus()

    async def _render_providers_section(self, container: ScrollableContainer) -> None:
        """Render providers and their models."""
        await container.mount(Static("Available Providers", classes="section-title"))

        for provider in self.providers:
            status = "✓ Connected" if provider.connected else "✗ Not configured"
            await container.mount(
                Static(f"{provider.name} ({provider.id}) — {status}", classes="provider-header"),
                DataTable(id=f"provider-{provider.id}", zebra_stripes=True),
            )
            table = self.query_one(f"#provider-{provider.id}", DataTable)
            table.add_columns("Model", "Family", "Input Cost", "Output Cost", "Capabilities")
            for model in provider.models:
                caps = []
                if model.tool_call: caps.append("tool_call")
                if model.reasoning: caps.append("reasoning")
                if model.vision: caps.append("vision")
                table.add_row(model.name, model.family or "", f"${model.input_cost:.4f}", f"${model.output_cost:.4f}", ", ".join(caps))

    async def on_select_changed(self, event: Select.Changed) -> None:
        """Handle select changes."""
        if event.select.id == "global-provider-select":
            # Update model select when provider changes
            provider_idx = event.value
            if provider_idx is not None and provider_idx < len(self.providers):
                provider = self.providers[provider_idx]
                model_select = self.query_one("#global-model-select", Select)
                model_select.set_options([(m.name, m.id) for m in provider.models])
                if provider.models:
                    model_select.value = provider.models[0].id

    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle agent row selection."""
        if event.data_table.id == "agents-table":
            agent_id = event.row_key.value
            await self._edit_agent_override(agent_id)

    async def _edit_agent_override(self, agent_id: str) -> None:
        """Open provider/model/effort selection for an agent."""
        row = next((r for r in AGENT_ROWS if r.agent_id == agent_id), None)
        if not row:
            return

        # Push provider selection screen
        await self.push_screen(
            ProviderSelectScreen(self.providers, self.agent_overrides.get(agent_id)),
            callback=lambda result: self._on_provider_selected(agent_id, result)
        )

    def _on_provider_selected(self, agent_id: str, result: Optional[dict]) -> None:
        """Callback when provider is selected."""
        if not result:
            return
        provider_id = result["provider_id"]
        provider = next((p for p in self.providers if p.id == provider_id), None)
        if not provider:
            return

        # Push model selection screen
        self.push_screen(
            ModelSelectScreen(provider, result.get("model_id")),
            callback=lambda result: self._on_model_selected(agent_id, provider_id, result)
        )

    def _on_model_selected(self, agent_id: str, provider_id: str, result: Optional[dict]) -> None:
        """Callback when model is selected."""
        if not result:
            return
        model_id = result["model_id"]
        model = next((m for m in self.providers[0].models if m.id == model_id), None)
        if not model:
            # Find model in correct provider
            for p in self.providers:
                if p.id == provider_id:
                    model = next((m for m in p.models if m.id == model_id), None)
                    if model:
                        break

        if model and model.effort_levels:
            # Push effort selection
            self.push_screen(
                EffortSelectScreen(model.effort_levels, result.get("variant", "")),
                callback=lambda result: self._on_effort_selected(agent_id, provider_id, model_id, result)
            )
        else:
            self._apply_agent_override(agent_id, provider_id, model_id, "")

    def _on_effort_selected(self, agent_id: str, provider_id: str, model_id: str, result: Optional[str]) -> None:
        """Callback when effort is selected."""
        if result is not None:
            self._apply_agent_override(agent_id, provider_id, model_id, result)

    def _apply_agent_override(self, agent_id: str, provider_id: str, model_id: str, variant: str) -> None:
        """Apply the agent override and refresh the table."""
        self.agent_overrides[agent_id] = AgentModelOverride(
            provider=provider_id,
            model=model_id,
            variant=variant if variant else None,
        )
        self.notify(f"Override set for {agent_id}: {provider_id}/{model_id}" + (f" [{variant}]" if variant else ""))
        # Refresh agents table
        self._refresh_agents_table()

    def _refresh_agents_table(self) -> None:
        """Refresh the agents table."""
        try:
            table = self.query_one("#agents-table", DataTable)
            table.clear()
            for row in AGENT_ROWS:
                override = self.agent_overrides.get(row.agent_id)
                if override and override.provider and override.model:
                    model_display = f"{override.provider}/{override.model}"
                    if override.variant:
                        model_display += f" [{override.variant}]"
                    status = "Overridden"
                else:
                    model_display = f"(inherits: {self.global_model})"
                    status = "Inherited"
                table.add_row(row.display_name, model_display, status, "Change" if override else "Set Override", key=row.agent_id)
        except Exception:
            pass  # Table might not exist yet

    async def _save_and_reload(self) -> None:
        """Save configuration and trigger OpenCode hot reload."""
        try:
            save_model_config(
                self.project_root,
                global_model=self.global_model,
                agent_overrides=self.agent_overrides,
            )
            # Trigger hot reload
            success = await reload_opencode_config(self.project_root)
            if success:
                self.notify("Configuration saved and OpenCode reloaded!", severity="success")
            else:
                self.notify("Configuration saved (reload manually: `opencode config reload`)", severity="warning")
        except Exception as e:
            self.notify(f"Save failed: {e}", severity="error")

    async def _reset_to_defaults(self) -> None:
        """Reset all configuration to defaults."""
        self.global_model = "anthropic/claude-sonnet-5-5"
        self.agent_overrides = {}
        self._refresh_agents_table()
        await self._show_section(self.current_section)
        self.notify("Reset to defaults", severity="information")

    async def action_save(self) -> None:
        await self._save_and_reload()

    async def action_reset(self) -> None:
        await self._reset_to_defaults()

    async def action_next_tab(self) -> None:
        sections = ["global", "agents", "providers"]
        idx = sections.index(self.current_section)
        await self._show_section(sections[(idx + 1) % len(sections)])

    async def action_prev_tab(self) -> None:
        sections = ["global", "agents", "providers"]
        idx = sections.index(self.current_section)
        await self._show_section(sections[(idx - 1) % len(sections)])


def run_model_tui() -> int:
    """Run the model picker TUI and return exit code."""
    app = ModelPickerApp()
    app.run()
    return 0