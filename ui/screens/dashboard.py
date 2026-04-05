"""
Main Rolling Dashboard for Liberal IP Roller.
Provides real-time statistics, logging, and process control.
"""

import asyncio
from typing import Dict, Any, Optional

from textual.app import ComposeResult
from textual.widgets import Button, Footer, Label, RichLog
from textual.containers import Vertical, Horizontal
from textual.reactive import reactive

from ui.widgets import CustomHeader
from .base import BaseScreen


class Dashboard(BaseScreen):
    """
    Primary application view containing the rotation control panel, 
    statistics, and a real-time log.
    """

    # Reactive attributes for smooth UI animations/updates
    attempts = reactive(0)
    matches = reactive(0)
    status_text = reactive("READY")

    def compose(self) -> ComposeResult:
        """ Renders the dashboard layout with sidebar and main content areas. """
        yield CustomHeader()
        with Horizontal():
            # Navigation Sidebar
            with Vertical(id="sidebar"):
                yield Button(
                    self.app._t("dashboard_tab"),
                    id="view-dashboard",
                    variant="primary"
                )
                yield Button(
                    self.app._t("manage_ips_tab"),
                    id="view-addresses"
                )
                yield Button(
                    self.app._t("config_tab"),
                    id="view-config"
                )
                yield Button(
                    self.app._t("settings_tab"),
                    id="view-settings"
                )
                yield Button(
                    self.app._t("back"),
                    id="view-back",
                    variant="error"
                )

            # Main Operating Area
            with Vertical(id="main-content"):
                with Horizontal(id="stats-panel"):
                    with Vertical(classes="stat-item"):
                        yield Label(self.app._t("status"), classes="stat-label")
                        yield Label(
                            self.app._t("ready"),
                            id="app-status",
                            classes="stat-value"
                        )
                    with Vertical(classes="stat-item"):
                        yield Label(self.app._t("attempts"), classes="stat-label")
                        yield Label("0", id="app-attempts", classes="stat-value")
                    with Vertical(classes="stat-item"):
                        yield Label(self.app._t("matches"), classes="stat-label")
                        yield Label("0", id="app-matches", classes="stat-value")

                # The engine's log output
                yield RichLog(
                    markup=True,
                    highlight=True,
                    id="log-view",
                    max_lines=self.app.config_provider.config.get_service_config().process.log_limit
                )

                # Control Buttons
                with Horizontal(classes="action-row"):
                    yield Button(
                        self.app._t("start"),
                        id="btn-start",
                        variant="success"
                    )
                    yield Button(
                        self.app._t("stop"),
                        id="btn-stop",
                        variant="error",
                        disabled=True
                    )
        yield Footer()

    def on_mount(self) -> None:
        """ Initializes the dashboard and starts auto-rotation if enabled. """
        super().on_mount()
        self.status_text = self.app._t("ready")
        self.update_stats_display()

        # Hydrate log from cache
        log_view = self.query_one("#log-view", RichLog)
        for msg in self.app.logs_cache:
            log_view.write(msg)

        # Trigger auto-start if configured
        svc_config = self.app.config_provider.config.get_service_config()
        if svc_config.process.auto_start:
            self.start_rolling()

    def update_stats_display(self) -> None:
        """ Force-updates the labels in the statistics panel. """
        self.query_one("#app-status", Label).update(self.status_text)
        self.query_one("#app-attempts", Label).update(str(self.attempts))
        self.query_one("#app-matches", Label).update(str(self.matches))


    def on_button_pressed(self, event: Button.Pressed) -> None:
        """ Handles navigation and rotation control button clicks. """
        btn_id = event.button.id
        if not btn_id:
            return

        if btn_id == "btn-start":
            self.start_rolling()
        elif btn_id == "btn-stop":
            self.stop_rolling()
        elif btn_id == "view-back":
            self.app.switch_screen("service_selection")
        elif btn_id == "view-config":
            # Route to the correct config screen for the active provider
            active_svc = self.app.config_provider.config.active_service
            if active_svc == "regru":
                self.app.switch_screen("config_regru")
            else:
                self.app.switch_screen("config")
        elif btn_id == "view-settings":
            self.app.switch_screen("settings")
        elif btn_id == "view-addresses":
            if not getattr(self, "_is_pushing", False):
                self._is_pushing = True
                async def run_managed():
                    try:
                        await self.app.manage_addresses()
                    finally:
                        self._is_pushing = False
                asyncio.create_task(run_managed())

    def log_message(self, message: str) -> None:
        """ Writes a message to the real-time RichLog. """
        log_view = self.query_one("#log-view", RichLog)
        log_view.write(message)

    def start_rolling(self) -> None:
        """Validates config and initiates the rotation engine."""
        config = self.app.config_provider.config
        svc_config = config.get_service_config()
        active_svc = config.active_service

        # Provider-specific credential check
        creds_ok = False
        if active_svc == "regru":
            creds_ok = bool(getattr(svc_config.api, "api_token", ""))
        else:  # yandex and any future providers
            # Yandex: Must have (iam_token OR sa_key_path) AND folder_id
            api = svc_config.api
            has_auth = bool(getattr(api, "iam_token", "") or getattr(api, "sa_key_path", ""))
            has_folder = bool(getattr(api, "folder_id", ""))
            creds_ok = has_auth and has_folder

        if not creds_ok:
            if svc_config.process.enable_notifications:
                self.app.notify(self.app._t("config_incomplete"), severity="error")
            return

        self.status_text = self.app._t("rolling")
        self.query_one("#btn-start").disabled = True
        self.query_one("#btn-stop").disabled = False
        self.update_stats_display()
        self.log_message(self.app._t("starting_process"))

        self.app.start_rolling_task()

    def stop_rolling(self) -> None:
        """ Signals the rotation task to stop and updates UI state. """
        self.app.stop_rolling_task()
        self.status_text = self.app._t("stopped")
        self.query_one("#btn-start").disabled = False
        self.query_one("#btn-stop").disabled = True
        self.update_stats_display()
        self.log_message(self.app._t("stopping_process"))

    # Watchers for reactive attribute animation
    def watch_attempts(self, value: float) -> None:
        """ Updates the attempts label on reactive change. """
        try:
            self.query_one("#app-attempts", Label).update(str(int(round(value))))
        except Exception:
            pass

    def watch_matches(self, value: float) -> None:
        """ Updates the matches label on reactive change. """
        try:
            self.query_one("#app-matches", Label).update(str(int(round(value))))
        except Exception:
            pass

    def watch_status_text(self, value: str) -> None:
        """ Updates the status label on reactive change. """
        try:
            self.query_one("#app-status", Label).update(value)
        except Exception:
            pass
