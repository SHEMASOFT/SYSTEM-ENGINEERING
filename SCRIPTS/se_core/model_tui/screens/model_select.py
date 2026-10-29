"""Model selection screen for the model picker."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Static, DataTable, Label, Button, Input
from textual.binding import Binding

from ..providers import ProviderInfo, ModelInfo


class ModelSelectScreen(Screen):
    """Screen for selecting a model from a provider."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("enter", "select", "Select"),
        Binding("/", "search", "Search"),
    ]

    def __init__(self, provider: ProviderInfo, current_model: Optional[str] = None):
        super().__init__()
        self.provider = provider
        self.current_model = current_model
        self.filtered_models = list(provider.models)
        self.search_query = ""

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(f"Select Model ({self.provider.name})", id="screen-title"),
            Label("Type / to search"),
            Input(placeholder="Search models...", id="search-input"),
            DataTable(id="models-table", zebra_stripes=True),
            Label(""),
            Button("Back (Esc)", id="btn-back", variant="default"),
            id="screen-container",
        )

    def on_mount(self) -> None:
        table = self.query_one("#models-table", DataTable)
        table.add_columns("Model", "Family", "Input $", "Output $", "Capabilities")

        for m in self.filtered_models:
            caps = []
            if m.tool_call: caps.append("tool_call")
            if m.reasoning: caps.append("reasoning")
            if m.vision: caps.append("vision")
            current = " ← current" if m.id == self.current_model else ""
            table.add_row(f"{m.name}{current}", m.family or "", f"${m.input_cost:.4f}", f"${m.output_cost:.4f}", ", ".join(caps), key=m.id)

        table.focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        self.search_query = event.value.lower()
        self._filter_models()

    def _filter_models(self) -> None:
        table = self.query_one("#models-table", DataTable)
        table.clear()

        if not self.search_query:
            self.filtered_models = list(self.provider.models)
        else:
            self.filtered_models = [
                m for m in self.provider.models
                if self.search_query in m.name.lower() or self.search_query in m.id.lower()
            ]

        for m in self.filtered_models:
            caps = []
            if m.tool_call: caps.append("tool_call")
            if m.reasoning: caps.append("reasoning")
            if m.vision: caps.append("vision")
            current = " ← current" if m.id == self.current_model else ""
            table.add_row(f"{m.name}{current}", m.family or "", f"${m.input_cost:.4f}", f"${m.output_cost:.4f}", ", ".join(caps), key=m.id)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        model_id = event.row_key.value
        self.dismiss({"model_id": model_id})

    def action_back(self) -> None:
        self.dismiss(None)

    def action_search(self) -> None:
        self.query_one("#search-input", Input).focus()


from typing import Optional