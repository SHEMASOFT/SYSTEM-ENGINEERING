"""Agent list screen for the model picker."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Static, DataTable, Label, Button
from textual.binding import Binding

from ..rows import AGENT_ROWS, get_agents_by_category


class AgentListScreen(Screen):
    """Screen for viewing and editing agent overrides."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("enter", "edit", "Edit Override"),
    ]

    def __init__(self, agents: list, overrides: dict, global_model: str):
        super().__init__()
        self.agents = agents
        self.overrides = overrides
        self.global_model = global_model

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Agent Overrides", id="screen-title"),
            Label(f"Global default: {self.global_model}"),
            DataTable(id="agents-table", zebra_stripes=True),
            Label(""),
            Button("Back (Esc)", id="btn-back", variant="default"),
            id="screen-container",
        )

    def on_mount(self) -> None:
        table = self.query_one("#agents-table", DataTable)
        table.add_columns("Agent", "Current Model", "Status", "Action")

        for row in self.agents:
            override = self.overrides.get(row.agent_id)
            if override and override.provider and override.model:
                model_display = f"{override.provider}/{override.model}"
                if override.variant:
                    model_display += f" [{override.variant}]"
                status = "Overridden"
            else:
                model_display = f"(inherits: {self.global_model})"
                status = "Inherited"
            table.add_row(row.display_name, model_display, status, "Change" if override else "Set Override", key=row.agent_id)

        table.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.dismiss(event.row_key.value)

    def action_back(self) -> None:
        self.dismiss(None)