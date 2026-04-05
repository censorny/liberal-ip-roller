"""
Custom UI widgets for Liberal IP Roller.
Includes the synchronized application header with version display.
"""

from textual.app import ComposeResult
from textual.widgets import Static, Label
from textual.containers import Horizontal


class CustomHeader(Static):
    """
    Application branding header. 
    Displays the software name and the dynamic version from the App instance.
    """
    def compose(self) -> ComposeResult:
        """ Renders the header layout. """
        with Horizontal():
            yield Label("Liberal IP Roller by censorny", id="header-brand")
            yield Label(f"v{self.app.APP_VERSION}", id="header-version")
