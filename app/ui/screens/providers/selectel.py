"""
Configuration screen for Selectel Floating IP credentials and server bindings.
Uses list-based IP/CIDR matching only and intentionally excludes device-side probing.
"""

import ipaddress

from textual.app import ComposeResult
from textual.widgets import Button, Footer, Label, Input, TextArea, Static
from textual.containers import Container, Horizontal, VerticalScroll, Vertical

from ...widgets import CustomHeader
from ..screen_base import BaseScreen


class ConfigSelectelScreen(BaseScreen):
    """Screen for editing Selectel credentials, VM bindings, and target IP lists."""

    def compose(self) -> ComposeResult:
        svc_config = self.app.config_provider.config.selectel
        api = svc_config.api
        process = svc_config.process

        yield CustomHeader()
        with Container(id="main-content"):
            yield Label(self.app._t("config_title_selectel"), classes="title")

            with VerticalScroll(classes="inputs-container"):
                with Horizontal():
                    yield Label(self.app._t("selectel_username"))
                    yield Input(value=api.username, id="cfg-selectel-username")

                with Horizontal():
                    yield Label(self.app._t("selectel_password"))
                    yield Input(value=api.password, id="cfg-selectel-password", password=True)

                with Horizontal():
                    yield Label(self.app._t("selectel_account_id"))
                    yield Input(value=api.account_id, id="cfg-selectel-account-id")

                with Horizontal():
                    yield Label(self.app._t("selectel_project_name"))
                    yield Input(value=api.project_name, id="cfg-selectel-project-name")

                yield Static(classes="separator")
                yield Label(self.app._t("selectel_regions_title"), classes="cidr-label")

                with Horizontal():
                    yield Label(self.app._t("selectel_server_id_ru2"))
                    yield Input(value=api.server_id_ru2, id="cfg-selectel-server-ru2")

                with Horizontal():
                    yield Label(self.app._t("selectel_server_id_ru3"))
                    yield Input(value=api.server_id_ru3, id="cfg-selectel-server-ru3")

                with Horizontal():
                    yield Label(self.app._t("ip_limit"))
                    yield Input(value=str(api.ip_limit), id="cfg-selectel-ip-limit")

                with Horizontal():
                    yield Label(self.app._t("target_match_count"))
                    yield Input(
                        value=str(getattr(api, "target_match_count", 1)),
                        id="cfg-selectel-target-matches"
                    )

                yield Static(classes="separator")
                yield Label(self.app._t("selectel_settings_title"), classes="cidr-label")

                with Horizontal():
                    yield Label(self.app._t("selectel_association_timeout"))
                    yield Input(
                        value=str(process.association_timeout),
                        id="cfg-selectel-association-timeout"
                    )

                with Vertical(classes="cidr-card"):
                    yield Label(self.app._t("target_ip_list"), classes="cidr-label")
                    yield TextArea(
                        text="\n".join(process.allowed_ranges),
                        id="cfg-selectel-targets"
                    )

            with Horizontal(classes="action-row"):
                yield Button(self.app._t("save"), id="btn-save", variant="success")
                yield Button(self.app._t("cancel"), id="btn-cancel", variant="error")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn-save":
            if self.save_config():
                self.app.switch_screen("dashboard")
        elif btn_id == "btn-cancel":
            self.app.switch_screen("dashboard")

    def save_config(self) -> bool:
        try:
            username = self.query_one("#cfg-selectel-username", Input).value.strip()
            password = self.query_one("#cfg-selectel-password", Input).value
            account_id = self.query_one("#cfg-selectel-account-id", Input).value.strip()
            project_name = self.query_one("#cfg-selectel-project-name", Input).value.strip()
            server_id_ru2 = self.query_one("#cfg-selectel-server-ru2", Input).value.strip()
            server_id_ru3 = self.query_one("#cfg-selectel-server-ru3", Input).value.strip()

            try:
                ip_limit = int(self.query_one("#cfg-selectel-ip-limit", Input).value)
                target_matches = int(self.query_one("#cfg-selectel-target-matches", Input).value)
                association_timeout = float(
                    self.query_one("#cfg-selectel-association-timeout", Input).value
                )
            except ValueError:
                self.app.notify(self.app._t("invalid_delay"), severity="error")
                return False

            if ip_limit < 1 or target_matches < 1 or association_timeout < 0:
                self.app.notify(self.app._t("invalid_delay"), severity="error")
                return False

            raw_targets = self.query_one("#cfg-selectel-targets", TextArea).text.strip()
            allowed_ranges = [line.strip() for line in raw_targets.split("\n") if line.strip()]
            for value in allowed_ranges:
                try:
                    ipaddress.ip_network(value, strict=False)
                except ValueError:
                    self.app.notify(f"Invalid IP/CIDR: {value}", severity="error")
                    return False

            svc_config = self.app.config_provider.config.selectel
            svc_config.api.username = username
            svc_config.api.password = password
            svc_config.api.account_id = account_id
            svc_config.api.project_name = project_name
            svc_config.api.server_id_ru2 = server_id_ru2
            svc_config.api.server_id_ru3 = server_id_ru3
            svc_config.api.ip_limit = ip_limit
            svc_config.api.target_match_count = target_matches
            svc_config.process.association_timeout = association_timeout
            svc_config.process.allowed_ranges = allowed_ranges

            self.app.config_provider.save()
            self.app.notify(self.app._t("config_saved"), severity="information")
            self.app.run_worker(self.app.update_client())
            return True
        except Exception as e:
            self.app.notify(f"Config Save Error: {e}", severity="error")
            return False