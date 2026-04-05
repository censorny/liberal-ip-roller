"""
Configuration screen for Yandex Cloud API credentials.
Handles validation of IAM tokens, Folder IDs, and CIDR ranges.
"""

import ipaddress
from typing import List, Optional

from textual.app import ComposeResult
from textual.widgets import Button, Footer, Label, Input, TextArea
from textual.containers import Container, Horizontal, VerticalScroll, Vertical

from ui.widgets import CustomHeader
from .base import BaseScreen


class ConfigScreen(BaseScreen):
    """
    Screen for editing service-specific API configurations (Tokens, Zones, CIDRs).
    Includes real-time validation of IP networks.
    """

    def compose(self) -> ComposeResult:
        """ Renders the configuration form with current provider settings. """
        svc_config = self.app.config_provider.config.get_service_config()
        config = svc_config.api
        
        yield CustomHeader()
        with Container(id="main-content"):
            yield Label(self.app._t("config_title"), classes="title")

            with VerticalScroll(classes="inputs-container"):
                # IAM Token Input
                with Horizontal():
                    yield Label(self.app._t("iam_token"))
                    yield Input(
                        value=config.iam_token,
                        placeholder=self.app._t("iam_token") + "...",
                        id="cfg-token"
                    )

                # SA Key Path Input
                with Horizontal():
                    yield Label(self.app._t("sa_key_label"))
                    yield Input(
                        value=config.sa_key_path,
                        placeholder=self.app._t("sa_key_placeholder"),
                        id="cfg-sa-key-path"
                    )

                # Folder ID Input
                with Horizontal():
                    yield Label(self.app._t("folder_id"))
                    yield Input(
                        value=config.folder_id,
                        placeholder=self.app._t("folder_id") + "...",
                        id="cfg-folder"
                    )

                # Zone ID Input
                with Horizontal():
                    yield Label(self.app._t("zone_id"))
                    yield Input(
                        value=config.zone_id,
                        placeholder="e.g. ru-central1-a",
                        id="cfg-zone"
                    )

                # IP Limit Input
                with Horizontal():
                    yield Label(self.app._t("ip_limit"))
                    yield Input(
                        value=str(config.ip_limit),
                        placeholder="2",
                        id="cfg-ip-limit"
                    )

                # Target Matches Input
                with Horizontal():
                    yield Label(self.app._t("target_match_count"))
                    yield Input(
                        value=str(getattr(config, "target_match_count", 1)),
                        placeholder="1",
                        id="cfg-target-matches"
                    )

                # CIDR Whitelist TextArea
                with Vertical(classes="cidr-card"):
                    yield Label(self.app._t("cidr_ranges"), classes="cidr-label")
                    yield TextArea(
                        text="\n".join(svc_config.process.allowed_ranges),
                        id="cfg-cidrs"
                    )

            # Footer Actions
            with Horizontal(classes="action-row"):
                yield Button(
                    self.app._t("save"),
                    id="btn-save",
                    variant="success"
                )
                yield Button(
                    self.app._t("cancel"),
                    id="btn-cancel",
                    variant="error"
                )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """ Handles Save/Cancel button interactions. """
        btn_id = event.button.id
        if btn_id == "btn-save":
            if self.save_config():
                self.app.switch_screen("dashboard")
        elif btn_id == "btn-cancel":
            self.app.switch_screen("dashboard")

    def save_config(self) -> bool:
        """
        Validates inputs and persists them to the configuration layer.
        
        Returns:
            True if settings are valid and saved, False on error.
        """
        try:
            # Collect values
            new_token = self.query_one("#cfg-token", Input).value.strip()
            new_sa_key = self.query_one("#cfg-sa-key-path", Input).value.strip()
            new_folder = self.query_one("#cfg-folder", Input).value.strip()
            new_zone = self.query_one("#cfg-zone", Input).value.strip()
            new_cidrs_block = self.query_one("#cfg-cidrs", TextArea).text.strip()

            # IP Limit validation
            try:
                new_ip_limit = int(self.query_one("#cfg-ip-limit", Input).value)
                if new_ip_limit < 1:
                    raise ValueError()
            except ValueError:
                self.app.notify("IP Limit must be a positive integer!", severity="error")
                return False

            # CIDR format validation
            new_cidrs = [c.strip() for c in new_cidrs_block.split("\n") if c.strip()]
            for cidr in new_cidrs:
                try:
                    ipaddress.ip_network(cidr)
                except ValueError:
                    self.app.notify(f"Invalid CIDR: {cidr}", severity="error")
                    return False

            # Target Matches validation
            try:
                new_target = int(self.query_one("#cfg-target-matches", Input).value)
                if new_target < 1:
                    raise ValueError()
            except ValueError:
                self.app.notify("Target Matches must be a positive integer!", severity="error")
                return False

            # Apply to configuration model
            svc_config = self.app.config_provider.config.get_service_config()
            svc_config.api.iam_token = new_token
            svc_config.api.sa_key_path = new_sa_key
            svc_config.api.folder_id = new_folder
            svc_config.api.zone_id = new_zone
            svc_config.api.ip_limit = new_ip_limit
            svc_config.api.target_match_count = new_target
            svc_config.process.allowed_ranges = new_cidrs

            # Save to disk
            self.app.config_provider.save()
            self.app.notify(self.app._t("config_saved"), severity="information")
            
            # Trigger client re-init in the background
            self.app.run_worker(self.app.update_client())
            return True

        except Exception as e:
            self.app.notify(f"Config Save Error: {e}", severity="error")
            return False
