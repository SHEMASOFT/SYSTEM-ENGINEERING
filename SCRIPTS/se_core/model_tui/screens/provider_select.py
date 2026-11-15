"""Provider selection screen for the model picker."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Static, DataTable, Label, Button
from textual.binding import Binding

from ..providers import ProviderInfo


class ProviderSelectScreen(Screen):
    """Screen for selecting a provider."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("enter", "select", "Select"),
    ]

    def __init__(self, providers: list[ProviderInfo], current_override: Optional[dict] = None):
        super().__init__()
        self.providers = providers
        self.current_override = current_override

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Select Provider", id="screen-title"),
            DataTable(id="providers-table", zebra_stripes=True),
            Label(""),
            Button("Back (Esc)", id="btn-back", variant="default"),
            id="screen-container",
        )

    def on_mount(self) -> None:
        table = self.query_one("#providers-table", DataTable)
        table.add_columns("Provider", "Status", "Models")

        for p in self.providers:
            status = "✓ Connected" if p.connected else "✗ Not configured"
            current = " ← current" if (self.current_override and self.current_override.get("provider") == p.id) else ""
            table.add_row(p.name, f"{status}{current}", str(len(p.models)), key=p.id)

        table.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        provider_id = event.row_key.value
        self.dismiss({"provider_id": provider_id})

    def action_back(self) -> None:
        self.dismiss(None)


# Need Optional import
from typing import Optional