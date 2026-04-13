import asyncio
from collections import deque

from textual.app import App
from textual.binding import Binding

from .i18n import I18N
from .screens.dashboard import Dashboard
from .screens.settings import SettingsScreen
from .screens.providers import ConfigRegruScreen, ConfigScreen, ConfigSelectelScreen
from .screens.service_selection import ServiceSelection
from .screens.language_selection import LanguageSelection
from .screens.modals import IpLimitModal

from .event_bridge import bridge_events, UILogMessage, UIStatsUpdate
from ..controller import AppController
from ..paths import load_version
from storage import ConfigProvider

class LiberallyApp(App):
    """Main Textual application shell."""
    
    TITLE = "Liberal IP Roller"
    CSS_PATH = "styles.tcss"
    
    SCREENS = {
        "language_selection": LanguageSelection,
        "service_selection": ServiceSelection,
        "dashboard": Dashboard,
        "config": ConfigScreen,
        "config_regru": ConfigRegruScreen,
        "config_selectel": ConfigSelectelScreen,
        "settings": SettingsScreen,
    }
    
    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
    ]

    def __init__(self):
        super().__init__()
        self.config_provider = ConfigProvider()
        self.i18n = I18N(self.config_provider.config.language)
        self.controller = AppController(self.config_provider)
        self.app_version = load_version()
        self.title = self._t("app_title")

        log_limit = self.config_provider.config.get_service_config().process.log_limit
        self.logs_cache = deque(maxlen=log_limit)

        bridge_events(self)

    def _t(self, key: str, **kwargs) -> str:
        """ Shortcut for i18n translation. """
        return self.i18n.translate(key, **kwargs)

    async def on_mount(self):
        if self.config_provider.config.skip_language_selection:
            self.push_screen("service_selection")
        else:
            self.push_screen("language_selection")

    def _dashboard(self) -> Dashboard | None:
        try:
            return self.get_screen("dashboard")
        except Exception:
            return None

    def start_rolling_task(self):
        async def runner():
            try:
                await self.controller.start_rotation()
            except Exception as exc:
                self._reset_dashboard_after_failed_start()
                self.notify(f"Startup Failed: {exc}", severity="error")

        asyncio.create_task(runner())

    def _reset_dashboard_after_failed_start(self) -> None:
        dashboard = self._dashboard()
        if dashboard is None:
            return

        dashboard.status_text = self._t("stopped")
        dashboard.query_one("#btn-start").disabled = False
        dashboard.query_one("#btn-stop").disabled = True
        dashboard.update_stats_display()

    def stop_rolling_task(self):
        asyncio.create_task(self.controller.stop_rotation())

    async def manage_addresses(self):
        if self.controller.rotation_task and not self.controller.rotation_task.done():
            self.notify(self._t("stop_before_manage"), severity="warning")
            return

        async def request_resolution(addresses, current_count=0, ip_limit=0):
            return await self.push_screen_wait(
                IpLimitModal(addresses=addresses, current_count=current_count, ip_limit=ip_limit)
            )

        try:
            await self.controller.manage_ips(request_resolution)
        except Exception as exc:
            self.notify(f"Address management failed: {exc}", severity="error")

    async def action_start(self):
        """Action handler for starting the rotation engine."""
        try:
            await self.controller.start_rotation()
        except Exception as e:
            self.notify(f"Startup Failed: {e}", severity="error")

    async def action_stop(self):
        """Action handler for stopping the engine."""
        await self.controller.stop_rotation()

    async def update_client(self):
        svc_config = self.config_provider.config.get_service_config()
        self.logs_cache = deque(self.logs_cache, maxlen=svc_config.process.log_limit)

        if self.controller.rotation_task and not self.controller.rotation_task.done():
            self.notify(self._t("changes_apply_after_stop"), severity="warning")
            return

        if self.controller.provider:
            await self.controller.provider.close()
            self.controller.provider = None

    def on_uilog_message(self, message: UILogMessage):
        self.logs_cache.append(message.message)
        dashboard = self._dashboard()
        if dashboard is not None:
            dashboard.log_message(message.message)

    def on_uistats_update(self, message: UIStatsUpdate):
        dashboard = self._dashboard()
        if dashboard is not None:
            dashboard.apply_stats(message.stats)

    async def action_quit(self):
        await self.controller.stop_rotation()
        self.exit()
