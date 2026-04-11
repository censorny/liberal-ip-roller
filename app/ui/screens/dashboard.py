"""
Main Rolling Dashboard for Liberal IP Roller.
Provides real-time statistics, logging, and process control.
"""

import asyncio

from textual.app import ComposeResult
from textual.widgets import Button, Footer, Label, RichLog, Static
from textual.containers import Vertical, Horizontal
from textual.reactive import reactive

from ...core.models import RollerStats
from ...core.stats_formatter import format_rate_summary, format_top_subnets, format_uptime
from ..widgets import CustomHeader
from .screen_base import BaseScreen


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
                btn_dashboard = Button(self.app._t("dashboard_tab"), id="view-dashboard", variant="primary")
                btn_dashboard.can_focus = False
                yield btn_dashboard

                btn_addr = Button(self.app._t("manage_ips_tab"), id="view-addresses")
                btn_addr.can_focus = False
                yield btn_addr

                btn_cfg = Button(self.app._t("config_tab"), id="view-config")
                btn_cfg.can_focus = False
                yield btn_cfg

                btn_set = Button(self.app._t("settings_tab"), id="view-settings")
                btn_set.can_focus = False
                yield btn_set

                btn_back = Button(self.app._t("back"), id="view-back", variant="error")
                btn_back.can_focus = False
                yield btn_back

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
                    with Vertical(classes="stat-item"):
                        yield Label(self.app._t("errors"), classes="stat-label")
                        yield Label("0", id="app-errors", classes="stat-value")
                    with Vertical(classes="stat-item"):
                        yield Label(self.app._t("workers"), classes="stat-label")
                        yield Label("0", id="app-workers", classes="stat-value")
                    with Vertical(classes="stat-item"):
                        yield Label(self.app._t("uptime"), classes="stat-label")
                        yield Label("00:00", id="app-uptime", classes="stat-value")

                with Horizontal(id="analytics-panel"):
                    with Vertical(classes="insight-card"):
                        yield Label(self.app._t("stats_summary"), classes="stat-label")
                        yield Static(self.app._t("stats_waiting"), id="app-rate-summary", classes="insight-value")
                    with Vertical(classes="insight-card"):
                        yield Label(self.app._t("top_subnets"), classes="stat-label")
                        yield Static(self.app._t("stats_waiting"), id="app-top-subnets", classes="insight-value")

                # The engine's log output
                log_view = RichLog(
                    markup=True,
                    highlight=True,
                    id="log-view",
                    max_lines=self.app.config_provider.config.get_service_config().process.log_limit
                )
                log_view.can_focus = False
                yield log_view

                # Control Buttons
                with Horizontal(classes="action-row"):
                    btn_clear = Button(self.app._t("clear_logs"), id="btn-clear-logs", variant="warning")
                    btn_clear.can_focus = False
                    yield btn_clear

                    btn_start = Button(self.app._t("start"), id="btn-start", variant="success")
                    btn_start.can_focus = False
                    yield btn_start

                    btn_stop = Button(self.app._t("stop"), id="btn-stop", variant="error", disabled=True)
                    btn_stop.can_focus = False
                    yield btn_stop
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
        self.query_one("#app-errors", Label).update("0")
        self.query_one("#app-workers", Label).update("0")
        self.query_one("#app-uptime", Label).update("00:00")
        self.query_one("#app-rate-summary", Static).update(self.app._t("stats_waiting"))
        self.query_one("#app-top-subnets", Static).update(self.app._t("stats_waiting"))

    def apply_stats(self, stats: RollerStats) -> None:
        self.attempts = stats.attempts
        self.matches = stats.matches

        if stats.is_running:
            self.status_text = self.app._t("rolling")
        elif stats.attempts > 0:
            self.status_text = self.app._t("stopped")
        else:
            self.status_text = self.app._t("ready")

        self.query_one("#app-errors", Label).update(str(stats.errors))
        self.query_one("#app-workers", Label).update(str(stats.active_workers))
        self.query_one("#app-uptime", Label).update(format_uptime(stats.uptime_seconds))
        self.query_one("#app-rate-summary", Static).update(format_rate_summary(stats))
        self.query_one("#app-top-subnets", Static).update(format_top_subnets(stats.top_subnets))

        start_button = self.query_one("#btn-start", Button)
        stop_button = self.query_one("#btn-stop", Button)
        start_button.disabled = stats.is_running
        stop_button.disabled = not stats.is_running


    def on_button_pressed(self, event: Button.Pressed) -> None:
        """ Handles navigation and rotation control button clicks. """
        btn_id = event.button.id
        if not btn_id:
            return

        if btn_id == "btn-start":
            self.start_rolling()
        elif btn_id == "btn-stop":
            self.stop_rolling()
        elif btn_id == "btn-clear-logs":
            self.app.logs_cache.clear()
            self.query_one("#log-view", RichLog).clear()
        elif btn_id == "view-back":
            self.app.switch_screen("service_selection")
        elif btn_id == "view-config":
            # Route to the correct config screen for the active provider
            active_svc = self.app.config_provider.config.active_service
            if active_svc == "regru":
                self.app.switch_screen("config_regru")
            elif active_svc == "selectel":
                self.app.switch_screen("config_selectel")
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
        validation_issues = self.app.controller.validate_active_service_config()
        if validation_issues:
            self.app.notify(validation_issues[0], severity="error")
            for issue in validation_issues:
                self.log_message(f"[bold red]{issue}[/bold red]")
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
