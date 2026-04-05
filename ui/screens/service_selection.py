"""
Service Provider Selection Screen for Liberal IP Roller.
Allows the user to select the cloud backend for IP rotation.
"""

from textual.app import ComposeResult
from textual.widgets import Button, Footer, Label
from textual.containers import Vertical, Center

from ui.widgets import CustomHeader
from .base import BaseScreen


class ServiceSelection(BaseScreen):
    """
    Onboarding screen for choosing between cloud providers.
    Supports Yandex Cloud and Reg.ru CloudVPS.
    """

    def compose(self) -> ComposeResult:
        """Renders the service selection dialog center-screen."""
        yield CustomHeader()
        with Center():
            with Vertical(id="service-selection-box"):
                yield Label(self.app._t("select_provider"), classes="title")
                yield Button(
                    self.app._t("yandex_cloud"),
                    id="btn-yandex",
                    variant="primary"
                )
                yield Button(
                    self.app._t("regru_cloud"),
                    id="btn-regru",
                    variant="primary"
                )
                yield Button(
                    self.app._t("exit"),
                    id="btn-exit",
                    variant="error"
                )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handles navigation to the dashboard or app exit."""
        btn_id = event.button.id
        if not btn_id:
            return

        if btn_id == "btn-yandex":
            self.app.config_provider.config.active_service = "yandex"
            self.app.run_worker(self.app.update_client())
            self.app.switch_screen("dashboard")
        elif btn_id == "btn-regru":
            self.app.config_provider.config.active_service = "regru"
            self.app.run_worker(self.app.update_client())
            self.app.switch_screen("dashboard")
        elif btn_id == "btn-exit":
            self.app.exit()
