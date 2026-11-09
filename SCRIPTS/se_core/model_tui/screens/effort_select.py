"""Effort/variant selection screen for the model picker."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Static, DataTable, Label, Button
from textual.binding import Binding


class EffortSelectScreen(Screen):
    """Screen for selecting reasoning effort level."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("enter", "select", "Select"),
    ]

    def __init__(self, effort_levels: list[str], current_effort: str = ""):
        super().__init__()
        self.effort_levels = effort_levels
        self.current_effort = current_effort

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Select Reasoning Effort", id="screen-title"),
            DataTable(id="effort-table", zebra_stripes=True),
            Label(""),
            Button("Back (Esc)", id="btn-back", variant="default"),
            id="screen-container",
        )

    def on_mount(self) -> None:
        table = self.query_one("#effort-table", DataTable)
        table.add_columns("Effort Level", "Description")

        # "default" maps to empty string (provider default)
        options = [("default", "Provider default")] + [(e, e.capitalize()) for e in self.effort_levels if e != "default"]

        for effort, desc in options:
            current = " ← current" if effort == self.current_effort else ""
            table.add_row(f"{effort}{current}", desc, key=effort)

        table.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        effort = event.row_key.value
        # "default" maps to empty string
        result = "" if effort == "default" else effort
        self.dismiss(result)

    def action_back(self) -> None:
        self.dismiss(None)