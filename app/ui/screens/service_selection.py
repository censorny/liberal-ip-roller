"""
Service Provider Selection Screen for Liberal IP Roller.
Allows the user to select the cloud backend for IP rotation.
"""

from textual.app import ComposeResult
from textual.widgets import Button, Footer, Label
from textual.containers import Vertical, Center

from ..widgets import CustomHeader
from .screen_base import BaseScreen


class ServiceSelection(BaseScreen):
    """
    Onboarding screen for choosing between cloud providers.
    Supports Yandex Cloud, Reg.ru CloudVPS, and Selectel.
    """

    def compose(self) -> ComposeResult:
        """Renders the service selection dialog center-screen."""
        yield CustomHeader()
        with Center():
            with Vertical(id="service-selection-box"):
                yield Label(self.app._t("select_provider"), classes="title")
                btn_yandex = Button(
                    self.app._t("yandex_cloud"),
                    id="btn-yandex",
                    variant="primary"
                )
                btn_yandex.can_focus = False
                yield btn_yandex

                btn_regru = Button(
                    self.app._t("regru_cloud"),
                    id="btn-regru",
                    variant="primary"
                )
                btn_regru.can_focus = False
                yield btn_regru

                btn_selectel = Button(
                    self.app._t("selectel_cloud"),
                    id="btn-selectel",
                    variant="primary"
                )
                btn_selectel.can_focus = False
                yield btn_selectel

                btn_exit = Button(
                    self.app._t("exit"),
                    id="btn-exit",
                    variant="error"
                )
                btn_exit.can_focus = False
                yield btn_exit
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handles navigation to the dashboard or app exit."""
        btn_id = event.button.id
        if not btn_id:
            return

        if btn_id == "btn-yandex":
            self.app.config_provider.config.active_service = "yandex"
            self.app.config_provider.save()
            self.app.run_worker(self.app.update_client())
            self.app.switch_screen("dashboard")
        elif btn_id == "btn-regru":
            self.app.config_provider.config.active_service = "regru"
            self.app.config_provider.save()
            self.app.run_worker(self.app.update_client())
            self.app.switch_screen("dashboard")
        elif btn_id == "btn-selectel":
            self.app.config_provider.config.active_service = "selectel"
            self.app.config_provider.save()
            self.app.run_worker(self.app.update_client())
            self.app.switch_screen("dashboard")
        elif btn_id == "btn-exit":
            self.app.exit()
