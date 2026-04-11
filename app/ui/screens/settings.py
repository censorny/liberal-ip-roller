"""
Global Settings Screen for Liberal IP Roller.
Manages localization, UI themes, Telegram notifications, and engine parameters.
"""

import asyncio
import os
import subprocess
import sys

from textual.app import ComposeResult
from textual.widgets import Button, Footer, Label, Input, Switch, Static
from textual.containers import Container, Horizontal, Vertical, VerticalScroll

from ...infrastructure.updater import UpdateManager
from ...paths import PROJECT_ROOT
from ..widgets import CustomHeader
from .modals import ConfirmationModal
from .screen_base import BaseScreen


class SettingsScreen(BaseScreen):
    """
    Comprehensive settings view allowing users to tune the app's behavior.
    Handles localization switching, theme selection, and Telegram bot setup.
    """

    def compose(self) -> ComposeResult:
        """ Renders the settings form with segmented sections. """
        self.config = self.app.config_provider.config
        self.selected_lang = self.config.language
        
        svc_config = self.config.get_service_config()
        process = svc_config.process
        tg = self.config.telegram

        yield CustomHeader()
        with Container(id="main-content"):
            yield Label(self.app._t("settings_title"), classes="title")

            with VerticalScroll(classes="inputs-container"):
                # Localization Section
                with Horizontal():
                    yield Label(self.app._t("language"))
                    with Vertical(classes="toggle-stack"):
                        yield Button(
                            "English", 
                            id="lang-en", 
                            classes="toggle-button " + ("-active" if self.selected_lang == "en" else "")
                        )
                        yield Button(
                            "Русский", 
                            id="lang-ru", 
                            classes="toggle-button " + ("-active" if self.selected_lang == "ru" else "")
                        )

                with Horizontal():
                    yield Label(self.app._t("skip_language"))
                    yield Switch(value=self.config.skip_language_selection, id="settings-skip-lang")

                with Horizontal():
                    yield Label(self.app._t("debug_mode"))
                    yield Switch(value=self.config.debug, id="settings-debug")

                # Theme Section
                yield Static(classes="separator")
                yield Label(self.app._t("telegram_title"), classes="title")
                with Horizontal():
                    yield Label(self.app._t("telegram_enabled"))
                    yield Switch(value=tg.enabled, id="settings-tg-enabled")
                
                with Horizontal():
                    yield Label(self.app._t("telegram_token_label"))
                    yield Input(value=tg.token, id="settings-tg-token", password=True)
                
                with Horizontal():
                    yield Label(self.app._t("telegram_chat_id_label"))
                    yield Input(value=",".join(tg.chat_ids), id="settings-tg-chats")

                with Horizontal():
                    yield Label(self.app._t("report_matches_to_tg"))
                    yield Switch(value=process.report_matches_to_tg, id="settings-report-matches")

                with Horizontal():
                    yield Label(self.app._t("report_errors_to_tg"))
                    yield Switch(value=process.report_errors_to_tg, id="settings-report-errors")

                yield Static(classes="separator")
                yield Label(self.app._t("rolling_settings_title"), classes="title")

                # Engine Parameters Section
                with Horizontal():
                    yield Label(self.app._t("auto_start"))
                    yield Switch(value=process.auto_start, id="settings-auto-start")

                with Horizontal():
                    yield Label(self.app._t("randomize"))
                    yield Switch(value=process.randomize_delay, id="settings-randomize")

                with Horizontal():
                    yield Label(self.app._t("min_delay"))
                    yield Input(value=str(process.min_delay), id="settings-min-delay")

                with Horizontal():
                    yield Label(self.app._t("max_delay"))
                    yield Input(value=str(process.max_delay), id="settings-max-delay")

                with Horizontal():
                    yield Label(self.app._t("log_limit"))
                    yield Input(value=str(process.log_limit), id="settings-log-limit")

                with Horizontal():
                    yield Label(self.app._t("polling_delay"))
                    yield Input(
                        value=str(process.polling_delay), 
                        id="settings-polling-delay"
                    )

                with Horizontal():
                    yield Label(self.app._t("error_wait_period"))
                    yield Input(
                        value=str(process.error_wait_period), 
                        id="settings-error-wait"
                    )

                with Horizontal():
                    yield Label(self.app._t("auto_restart_on_error"))
                    yield Switch(value=process.auto_restart_on_error, id="settings-auto-restart")

                with Horizontal():
                    yield Label(self.app._t("dry_run"))
                    yield Switch(value=process.dry_run, id="settings-dry-run")

                yield Static(classes="separator")
                yield Label(self.app._t("system_update_title"), classes="title")
                with Horizontal(classes="version-row"):
                    yield Label(self.app._t("version_label") + ": " + self.app.app_version)
                    yield Button(
                        self.app._t("check_updates"), 
                        id="btn-check-updates", 
                        variant="primary"
                    )

            # Footer Actions
            with Horizontal(classes="action-row"):
                yield Button(self.app._t("save"), id="btn-save", variant="success")
                yield Button(self.app._t("cancel"), id="btn-cancel", variant="error")
        yield Footer()

    def _update_toggle_group_ui(self) -> None:
        """ Syncs the '-active' CSS class for custom toggle buttons. """
        for btn in self.query("Button.toggle-button"):
            if btn.id and btn.id.startswith("lang-"):
                lang_val = btn.id.split("-")[1]
                if self.selected_lang == lang_val:
                    btn.add_class("-active")
                else:
                    btn.remove_class("-active")

    def on_mount(self) -> None:
        """ Initial UI state synchronization. """
        self._update_toggle_group_ui()
        self._is_closing = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """ Handles settings navigation and state updates. """
        btn_id = event.button.id
        if not btn_id:
            return

        # Handle custom toggle buttons (Lang only)
        if event.button.has_class("toggle-button"):
            if btn_id.startswith("lang-"):
                self.selected_lang = btn_id.split("-")[1]
                self._update_toggle_group_ui()
            self.refresh()
            return

        # Save/Cancel logic
        if btn_id == "btn-save":
            result = self.save_settings()
            if result == "saved":
                self.app.switch_screen("dashboard")
        elif btn_id == "btn-cancel":
            self.app.switch_screen("dashboard")
        elif btn_id == "btn-check-updates":
            self.run_worker(self.check_for_updates())

    def _restart_application(self) -> None:
        args = list(sys.argv)
        try:
            subprocess.Popen([sys.executable] + args, cwd=PROJECT_ROOT)
            self.app.exit()
        except Exception:
            os.execv(sys.executable, [sys.executable] + args)

    async def check_for_updates(self) -> None:
        """ Dispatches update check to the UpdateManager. """
        btn = self.query_one("#btn-check-updates", Button)
        original_label = btn.label
        btn.label = self.app._t("checking_updates")
        btn.disabled = True

        updater = UpdateManager(self.app.app_version)
        available, version = await updater.check_for_updates()

        btn.label = original_label
        btn.disabled = False

        if available:
            # Shift from notification to modal prompt
            should_update = await self.app.push_screen_wait(
                ConfirmationModal(
                    title_key="system_update_title",
                    subtitle_text=self.app._t("update_available", version=version) + " " + self.app._t("update_confirm_msg", version=version)
                )
            )
            
            if should_update:
                self.app.notify(self.app._t("downloading_update"), severity="information")
                success = await updater.download_update()
                
                if success:
                    self.app.notify(self.app._t("applying_settings"), severity="warning")
                    await asyncio.sleep(1.0)
                    if updater.trigger_bootstrap():
                        self.app.exit()
                else:
                    self.app.notify(self.app._t("update_failed"), severity="error")
        elif version == "error":
            self.app.notify(
                self.app._t("update_error"), 
                severity="error"
            )
        else:
            self.app.notify(
                self.app._t("update_not_available"), 
                severity="information"
            )

    def save_settings(self) -> str:
        """
        Validates all form fields and commits changes to the global config.
        Returns a status string: "saved", "restart", or "error".
        """
        try:
            # Validate technical values
            try:
                min_delay = float(self.query_one("#settings-min-delay", Input).value)
                max_delay = float(self.query_one("#settings-max-delay", Input).value)
                log_limit = int(self.query_one("#settings-log-limit", Input).value)
                error_wait = float(self.query_one("#settings-error-wait", Input).value)
                polling_delay = float(self.query_one("#settings-polling-delay", Input).value)
            except ValueError:
                self.app.notify(self.app._t("invalid_delay"), severity="error")
                return "error"

            if min_delay < 0 or max_delay < 0 or log_limit < 1 or polling_delay < 0:
                self.app.notify(self.app._t("positive_values_required"), severity="error")
                return "error"

            if max_delay < min_delay:
                self.app.notify(self.app._t("max_delay_must_exceed_min"), severity="error")
                return "error"

            # Gather state
            randomize = self.query_one("#settings-randomize", Switch).value
            dry_run = self.query_one("#settings-dry-run", Switch).value
            debug_mode = self.query_one("#settings-debug", Switch).value
            skip_lang = self.query_one("#settings-skip-lang", Switch).value
            auto_start = self.query_one("#settings-auto-start", Switch).value
            auto_restart = self.query_one("#settings-auto-restart", Switch).value
            report_matches = self.query_one("#settings-report-matches", Switch).value
            report_errors = self.query_one("#settings-report-errors", Switch).value

            # Telegram state
            tg_enabled = self.query_one("#settings-tg-enabled", Switch).value
            tg_token = self.query_one("#settings-tg-token", Input).value.strip()
            tg_chats_raw = self.query_one("#settings-tg-chats", Input).value.strip()
            tg_chats = [c.strip() for c in tg_chats_raw.split(",") if c.strip()]

            # Apply to configuration
            config = self.app.config_provider.config
            svc_config = config.get_service_config()

            # Track lang changes for potential restart
            old_lang = config.language

            config.language = self.selected_lang
            config.skip_language_selection = skip_lang
            config.debug = debug_mode

            svc_config.process.randomize_delay = randomize
            svc_config.process.min_delay = min_delay
            svc_config.process.max_delay = max_delay
            svc_config.process.dry_run = dry_run
            svc_config.process.auto_start = auto_start
            svc_config.process.log_limit = log_limit
            svc_config.process.polling_delay = polling_delay
            svc_config.process.error_wait_period = error_wait
            svc_config.process.auto_restart_on_error = auto_restart
            svc_config.process.report_matches_to_tg = report_matches
            svc_config.process.report_errors_to_tg = report_errors

            config.telegram.enabled = tg_enabled
            config.telegram.token = tg_token
            config.telegram.chat_ids = tg_chats

            # Commit to disk
            self.app.config_provider.save()
            self.app.notify(self.app._t("settings_saved"), severity="information")

            # If language changed, restart the app to apply full reload
            if old_lang != self.selected_lang:
                self.app.i18n.language = self.selected_lang
                self.app.title = self.app._t("app_title")
                self.app.notify(self.app._t("applying_settings"), severity="information")
                self._restart_application()
                return "restart"

            self.app.run_worker(self.app.update_client())
            return "saved"

        except Exception as e:
            self.app.notify(self.app._t("settings_save_error", error=str(e)), severity="error")
            return "error"
