"""Reusable UI widgets for the Textual interface."""

from textual.app import ComposeResult
from textual.widgets import Static, Label
from textual.containers import Horizontal


class CustomHeader(Static):
    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Label("Liberal IP Roller by censorny", id="header-brand")
            yield Label(f"v{self.app.app_version}", id="header-version")
