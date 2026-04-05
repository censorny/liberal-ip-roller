"""
Liberal IP Roller - The ultimate IP rotation tool for Yandex Cloud.
High-performance TUI application with real-time statistics and Telegram alerts.
"""

import asyncio
import os
import sys
import signal
from typing import Optional, List, Dict, Any
from collections import deque

from textual.app import App
from textual.widgets import Footer

from app_logic.controller import AppController
from storage.provider import ConfigProvider
from ui.screens.service_selection import ServiceSelection
from ui.screens.dashboard import Dashboard
from ui.screens.config import ConfigScreen
from ui.screens.config_regru import ConfigRegruScreen
from ui.screens.settings import SettingsScreen
from ui.screens.modals import IpLimitModal
from ui.screens.language_selection import LanguageSelection
from ui.i18n import I18N


class CloudRollerApp(App):
    """
    Main Application class for Liberal IP Roller.
    Manages the application lifecycle, screen routing, and UI state.
    """

    CSS_PATH = "ui/styles.tcss"
    SCREENS = {
        "service_selection": ServiceSelection,
        "dashboard": Dashboard,
        "config": ConfigScreen,
        "config_regru": ConfigRegruScreen,
        "settings": SettingsScreen,
        "language_selection": LanguageSelection,
    }

    def _load_version(self) -> str:
        """ Returns the current app version from version.json. """
        try:
            import json
            import os
            path = os.path.join(os.path.dirname(__file__), "version.json")
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f).get("version", "0.0.0")
        except Exception:
            return "0.0.0"

    def __init__(self, **kwargs):
        """ Initializes providers, localized strings, and connection pools. """
        super().__init__(**kwargs)
        self.APP_VERSION = self._load_version()
        self.config_provider = ConfigProvider()
        self.i18n = I18N(self.config_provider.config.language)
        self.title = self._t("app_title")
        
        # State management
        self.logs_cache = deque(maxlen=100)
        self.apply_theme()
        
        # Domain Controller (The Brain)
        self.controller = AppController(self.config_provider)
        self.controller.set_ui_handlers(
            on_log=self.on_roller_log,
            on_stats=self.on_roller_stats,
            on_notify=self.notify,
            request_quota_resolution=self.request_quota_resolution
        )

    def _setup_signals(self):
        """Standard industrial signal trap."""
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self.action_app_quit()))
            except (NotImplementedError, ValueError):
                # Signal handling can be restricted on Windows with specific event loops
                pass

    async def action_app_quit(self) -> None:
        """
        Gracefully shuts down the application.
        Ensures all cloud clients and background tasks are terminated.
        """
        try:
            # Stop the engine and all clients
            if self.controller:
                await self.controller.stop_rotation()
                if self.controller.client:
                    await self.controller.client.close()
        except Exception:
            pass
        self.exit()

    def _t(self, key: str, **kwargs) -> str:
        """ Shortcut for i18n translation. """
        return self.i18n.translate(key, **kwargs)

    async def update_client(self) -> None:
        """
        Synchronizes API clients via the domain controller.
        """
        await self.controller.update_clients()
        
        # Sync log cache limit
        svc_config = self.config_provider.config.get_service_config()
        self.logs_cache = deque(self.logs_cache, maxlen=svc_config.process.log_limit)

    def apply_theme(self) -> None:
        """ Applies the selected CSS theme globally. """
        theme = self.config_provider.config.theme
        theme_class = f"theme-{theme}"
        classes = ["theme-dark", "theme-light", "theme-high-contrast"]

        for t in classes:
            if t == theme_class:
                self.add_class(t)
            else:
                self.remove_class(t)
        
        self.refresh()

    async def on_mount(self) -> None:
        """ Startup logic: initializes clients, traps signals, and routes to the first screen. """
        self._cleanup_update_artifacts()
        self._setup_signals()
        await self.update_client()

        # Handle CLI flags for direct screen jumps
        if "--dashboard" in sys.argv:
            self.push_screen("dashboard")
        elif self.config_provider.config.skip_language_selection:
            self.push_screen("service_selection")
        else:
            self.push_screen("language_selection")

        if "--settings" in sys.argv:
            self.switch_screen("settings")

    def _cleanup_update_artifacts(self) -> None:
        """
        Industrial Self-Cleanup: Removes bootstrap scripts and temp files 
        left over from a previous update operation.
        """
        import shutil
        
        root = os.getcwd()
        # Clean bootstrap script
        bootstrap_path = os.path.join(root, "bootstrap_updater.py")
        if os.path.exists(bootstrap_path):
            try:
                os.remove(bootstrap_path)
            except Exception:
                pass
        
        # Clean temp directory
        temp_path = os.path.join(root, "temp")
        if os.path.exists(temp_path):
            try:
                shutil.rmtree(temp_path)
            except Exception:
                pass



    def on_roller_log(self, message: str) -> None:
        """ Dispatches engine logs to the UI cache and active dashboard. """
        self.logs_cache.append(message)
        try:
            dashboard = self.get_screen("dashboard")
            if hasattr(dashboard, "log_message"):
                dashboard.log_message(message)
        except Exception:
            pass

    def on_roller_stats(self, stats: dict) -> None:
        """ Updates UI statistics and triggers animations. """
        try:
            dashboard = self.get_screen("dashboard")
            poll_delay = self.config_provider.config.get_service_config().process.polling_delay
            
            # Smoothly animate only if polling is slow enough to avoid UI jitter
            if poll_delay < 0.3:
                dashboard.attempts = stats.get("attempts", 0)
                dashboard.matches = stats.get("matches", 0)
            else:
                dashboard.animate("attempts", stats.get("attempts", 0), duration=0.5)
                dashboard.animate("matches", stats.get("matches", 0), duration=0.5)
                
            if not stats.get("is_running") and dashboard.status_text == self._t("rolling"):
                dashboard.status_text = self._t("ready")
        except Exception:
            pass

    async def request_quota_resolution(
        self,
        addresses: List[Dict[str, Any]],
        current_count: int = 0,
        ip_limit: int = 0
    ) -> Optional[str]:
        """
        UI-driven callback to resolve IP/VM limits via a modal dialog.
        Called by the domain controller when cloud limits are reached.
        Passes dynamic count/limit info for a non-hardcoded modal title.
        """
        return await self.push_screen_wait(
            IpLimitModal(
                addresses=addresses,
                current_count=current_count,
                ip_limit=ip_limit
            )
        )

    def start_rolling_task(self) -> None:
        """ Delegates rotation initiation to the controller. """
        self.run_worker(self.controller.start_rotation())

    def stop_rolling_task(self) -> None:
        """ Delegates rotation termination to the controller. """
        self.run_worker(self.controller.stop_rotation())

    async def manage_addresses(self) -> None:
        """ Initiates manual IP management via the controller. """
        await self.controller.manage_ips(self.request_quota_resolution)

    async def push_screen_wait(self, screen):
        """ 
        Reliable result-awaiting wrapper. 
        Bridges Textual's callback-based dismissal to the Industrial Async/Await pattern.
        """
        loop = asyncio.get_event_loop()
        future = loop.create_future()

        def on_dismiss(result):
            if not future.done():
                future.set_result(result)

        self.push_screen(screen, callback=on_dismiss)
        return await future


if __name__ == "__main__":
    app = CloudRollerApp()
    app.run()
