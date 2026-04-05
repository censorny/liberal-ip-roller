"""
Configuration screen for Reg.ru CloudVPS API credentials.
Handles validation of API token, server parameters, IP limits, and CIDR ranges.
"""

import ipaddress
from typing import List, Optional

from textual.app import ComposeResult
from textual.widgets import Button, Footer, Label, Input, TextArea
from textual.containers import Container, Horizontal, VerticalScroll, Vertical

from ui.widgets import CustomHeader
from .base import BaseScreen


class ConfigRegruScreen(BaseScreen):
    """
    Screen for editing Reg.ru service-specific settings.
    Covers: API token, server parameters, IP limit, and CIDR whitelist.
    """

    def compose(self) -> ComposeResult:
        """Renders the Reg.ru configuration form."""
        svc_config = self.app.config_provider.config.regru
        api = svc_config.api
        process = svc_config.process

        yield CustomHeader()
        with Container(id="main-content"):
            yield Label(self.app._t("config_title_regru"), classes="title")

            with VerticalScroll(classes="inputs-container"):
                # API Token
                with Horizontal():
                    yield Label(self.app._t("api_token"))
                    yield Input(
                        value=api.api_token,
                        placeholder=self.app._t("api_token") + "...",
                        id="cfg-regru-token",
                        password=True
                    )

                # API Base URL
                with Horizontal():
                    yield Label(self.app._t("api_base_url"))
                    yield Input(
                        value=api.api_base_url,
                        placeholder="https://api.cloudvps.reg.ru/v1/reglets",
                        id="cfg-regru-url"
                    )

                # Region Slug
                with Horizontal():
                    yield Label(self.app._t("region_slug"))
                    yield Input(
                        value=api.region_slug,
                        placeholder=self.app._t("region_slug") + "...",
                        id="cfg-regru-region"
                    )

                # Server Size
                with Horizontal():
                    yield Label(self.app._t("server_size"))
                    yield Input(
                        value=api.server_size,
                        placeholder="e.g. c2-m2-d10-base",
                        id="cfg-regru-size"
                    )

                # Server Image
                with Horizontal():
                    yield Label(self.app._t("server_image"))
                    yield Input(
                        value=api.server_image,
                        placeholder="e.g. ubuntu-18-04-amd64",
                        id="cfg-regru-image"
                    )

                # IP/VM Limit
                with Horizontal():
                    yield Label(self.app._t("ip_limit"))
                    yield Input(
                        value=str(api.ip_limit),
                        placeholder="2",
                        id="cfg-regru-limit"
                    )

                # Target Matches Input
                with Horizontal():
                    yield Label(self.app._t("target_match_count"))
                    yield Input(
                        value=str(getattr(api, "target_match_count", 1)),
                        placeholder="1",
                        id="cfg-regru-target-matches"
                    )

                # Timing Parameters
                yield Vertical(classes="separator")
                yield Label(self.app._t("regru_settings_title"), classes="cidr-label")

                with Horizontal():
                    yield Label(self.app._t("initial_wait"))
                    yield Input(
                        value=str(process.initial_wait),
                        placeholder="90",
                        id="cfg-regru-initial-wait"
                    )

                with Horizontal():
                    yield Label(self.app._t("check_interval"))
                    yield Input(
                        value=str(process.check_interval),
                        placeholder="5",
                        id="cfg-regru-check-interval"
                    )

                with Horizontal():
                    yield Label(self.app._t("stability_checks"))
                    yield Input(
                        value=str(process.stability_checks),
                        placeholder="3",
                        id="cfg-regru-stability"
                    )

                with Horizontal():
                    yield Label(self.app._t("delete_wait"))
                    yield Input(
                        value=str(process.delete_wait),
                        placeholder="10",
                        id="cfg-regru-delete-wait"
                    )

                # CIDR Whitelist
                with Vertical(classes="cidr-card"):
                    yield Label(self.app._t("cidr_ranges"), classes="cidr-label")
                    yield TextArea(
                        text="\n".join(process.allowed_ranges),
                        id="cfg-regru-cidrs"
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
        """Handles Save/Cancel button interactions."""
        btn_id = event.button.id
        if btn_id == "btn-save":
            if self.save_config():
                self.app.switch_screen("dashboard")
        elif btn_id == "btn-cancel":
            self.app.switch_screen("dashboard")

    def save_config(self) -> bool:
        """
        Validates all inputs and persists Reg.ru configuration.

        Returns:
            True if valid and saved, False on validation error.
        """
        try:
            # Collect string values
            new_token = self.query_one("#cfg-regru-token", Input).value.strip()
            new_url = self.query_one("#cfg-regru-url", Input).value.strip()
            new_region = self.query_one("#cfg-regru-region", Input).value.strip()
            new_size = self.query_one("#cfg-regru-size", Input).value.strip()
            new_image = self.query_one("#cfg-regru-image", Input).value.strip()

            # Numeric validation
            try:
                new_limit = int(self.query_one("#cfg-regru-limit", Input).value)
                new_target = int(self.query_one("#cfg-regru-target-matches", Input).value)
                new_initial_wait = float(self.query_one("#cfg-regru-initial-wait", Input).value)
                new_check_interval = float(self.query_one("#cfg-regru-check-interval", Input).value)
                new_stability_checks = int(self.query_one("#cfg-regru-stability", Input).value)
                new_delete_wait = float(self.query_one("#cfg-regru-delete-wait", Input).value)
            except ValueError:
                self.app.notify(self.app._t("invalid_delay"), severity="error")
                return False

            if new_limit < 1 or new_target < 1:
                self.app.notify("Limits and Target must be >= 1", severity="error")
                return False

            if new_initial_wait < 0 or new_check_interval <= 0 or new_stability_checks < 1:
                self.app.notify("Invalid timing values!", severity="error")
                return False

            # CIDR validation
            cidrs_raw = self.query_one("#cfg-regru-cidrs", TextArea).text.strip()
            new_cidrs = [c.strip() for c in cidrs_raw.split("\n") if c.strip()]
            for cidr in new_cidrs:
                try:
                    ipaddress.ip_network(cidr)
                except ValueError:
                    self.app.notify(f"Invalid CIDR: {cidr}", severity="error")
                    return False

            # Apply to configuration
            svc_config = self.app.config_provider.config.regru
            svc_config.api.api_token = new_token
            svc_config.api.api_base_url = new_url
            svc_config.api.region_slug = new_region
            svc_config.api.server_size = new_size
            svc_config.api.server_image = new_image
            svc_config.api.ip_limit = new_limit
            svc_config.api.target_match_count = new_target
            svc_config.process.initial_wait = new_initial_wait
            svc_config.process.check_interval = new_check_interval
            svc_config.process.stability_checks = new_stability_checks
            svc_config.process.delete_wait = new_delete_wait
            svc_config.process.allowed_ranges = new_cidrs

            # Save to disk and reinit client
            self.app.config_provider.save()
            self.app.notify(self.app._t("config_saved"), severity="information")
            self.app.run_worker(self.app.update_client())
            return True

        except Exception as e:
            self.app.notify(f"Config Save Error: {e}", severity="error")
            return False
