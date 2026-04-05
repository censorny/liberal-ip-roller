"""
Central Application Controller for Liberal IP Roller.
Orchestrates business logic, service lifecycles, and task management.

Bug Fixes Applied:
  - PHANTOM IP: manage_ips() now awaits deletion operations rather than
    fire-and-forgetting them, preventing stale IPs from appearing in the
    modal on repeated opens.
  - HARDCODED LIMIT: ip_limit is now read from the provider's api config
    (api.ip_limit) instead of being hardcoded as 2.
"""

import asyncio
from typing import Optional, Callable, Dict, Any, List
import logging

from .service_base import CloudService
from .roller import Roller
from .telegram_client import TelegramClient
from .logger import logger  # Industrial logger instance
from storage.provider import ConfigProvider


class AppController:
    """
    Stateful controller that manages the application's core functionality.
    Acts as a bridge between the service layer and the TUI.
    """

    def __init__(self, config_provider: ConfigProvider):
        """Initializes the controller with configuration and clients."""
        self.config_provider = config_provider
        self.client: Optional[CloudService] = None
        self.roller: Optional[Roller] = None
        self.tg_client = TelegramClient()
        self.rolling_task: Optional[asyncio.Task] = None

        # UI Communication Callbacks
        self._on_log: Optional[Callable[[str], None]] = None
        self._on_stats: Optional[Callable[[Dict[str, Any]], None]] = None
        self._on_notify: Optional[Callable[[str, str], None]] = None
        self._request_quota_resolution: Optional[Callable[[List[Dict[str, Any]]], Any]] = None

    def set_ui_handlers(
        self,
        on_log: Callable[[str], None],
        on_stats: Callable[[Dict[str, Any]], None],
        on_notify: Callable[[str, str], None],
        request_quota_resolution: Callable[[List[Dict[str, Any]]], Any]
    ):
        """Connects UI event handlers to the controller and wires the industrial logger."""
        # Wrap on_log to also write to the persistent file log
        def _on_log_wrapper(msg: str):
            # Strip Rich markup before writing to plain text log file
            import re
            clean_msg = re.sub(r'\[.*?\]', '', msg)
            logger.info(clean_msg)
            if on_log:
                on_log(msg)

        self._on_log = _on_log_wrapper
        self._on_stats = on_stats
        self._on_notify = on_notify
        self._request_quota_resolution = request_quota_resolution

    async def update_clients(self) -> bool:
        """
        Synchronizes API clients with the current configuration.
        Uses a Factory pattern to instantiate the correct provider client.
        """
        try:
            config = self.config_provider.config
            active_service = config.active_service
            svc_config = config.get_service_config()

            if self.client:
                await self.client.close()
                self.client = None
                self.roller = None

            if active_service == "yandex":
                api = svc_config.api
                # Configuration is complete if we have Folder ID 
                # AND (Manual Token OR SA Key Path)
                has_auth = bool(api.iam_token or api.sa_key_path)
                if has_auth and api.folder_id:
                    from .yandex_client import YandexClient
                    self.client = YandexClient(
                        iam_token=api.iam_token,
                        folder_id=api.folder_id,
                        sa_key_path=api.sa_key_path,
                        polling_delay=svc_config.process.polling_delay
                    )
                else:
                    return False

            elif active_service == "regru":
                api = svc_config.api
                process = svc_config.process
                if api.api_token:
                    from .regru_client import RegruClient
                    self.client = RegruClient(
                        api_token=api.api_token,
                        api_base_url=api.api_base_url,
                        region_slug=api.region_slug,
                        server_size=api.server_size,
                        server_image=api.server_image,
                        initial_wait=process.initial_wait,
                        check_interval=process.check_interval,
                        stability_checks=process.stability_checks,
                        delete_wait=process.delete_wait,
                        vm_active_timeout=process.vm_active_timeout,
                        vm_delete_timeout=process.vm_delete_timeout,
                    )
                else:
                    return False
            else:
                return False

            # Wire up the Roller engine
            self.roller = Roller(self.client, svc_config)
            self.roller.set_callbacks(
                on_log=self._on_log,
                on_stats=self._on_stats,
                on_match=self._handle_match,
                on_error=self._handle_error
            )

            # Update Telegram client
            await self.tg_client.update_config(
                config.telegram.token,
                config.telegram.chat_ids
            )
            return True

        except Exception as e:
            if self._on_notify:
                self._on_notify(f"Controller Init Error: {e}", "error")
            return False

    def _get_ip_limit(self) -> int:
        """
        Reads the IP/VM limit from the active provider's API config.
        Eliminates the hardcoded '2' that was previously in the code.
        """
        try:
            svc_config = self.config_provider.config.get_service_config()
            return svc_config.api.ip_limit
        except AttributeError:
            return 2  # Safe fallback

    def _handle_match(self, ip: str):
        """Internal handler for IP match events."""
        config = self.config_provider.config
        svc_config = config.get_service_config()

        if config.telegram.enabled and svc_config.process.report_matches_to_tg:
            asyncio.create_task(self.tg_client.send_message(f"🌟 IP Match Found: {ip}"))

    def _handle_error(self, error: str):
        """Internal handler for engine errors."""
        config = self.config_provider.config
        svc_config = config.get_service_config()

        if config.telegram.enabled and svc_config.process.report_errors_to_tg:
            asyncio.create_task(self.tg_client.send_message(f"🛑 Error: {error}"))

    async def start_rotation(self):
        """Starts the background rotation process."""
        if self.rolling_task and not self.rolling_task.done():
            return

        if not self.client or not self.roller:
            if self._on_notify:
                self._on_notify("Client not initialized", "error")
            return

        async def _run():
            try:
                ip_limit = self._get_ip_limit()

                # BUG FIX: Uses dynamic ip_limit instead of hardcoded 2
                addresses = await self.client.list_addresses()
                if len(addresses) >= ip_limit:
                    if self._on_log:
                        self._on_log(
                            f"[bold yellow]Cloud IP/VM limit reached "
                            f"({len(addresses)}/{ip_limit}). Requesting resolution...[/bold yellow]"
                        )

                    if self._request_quota_resolution:
                        addr_to_del = await self._request_quota_resolution(
                            [a.model_dump() for a in addresses],
                            current_count=len(addresses),
                            ip_limit=ip_limit
                        )

                        if addr_to_del == "all":
                            for addr in addresses:
                                op_id = await self.client.delete_address(addr.id)
                                if op_id:
                                    try:
                                        await self.client.wait_for_operation(op_id)
                                    except Exception:
                                        pass  # Best-effort wait on bulk delete
                        elif addr_to_del:
                            op_id = await self.client.delete_address(addr_to_del)
                            if op_id:
                                await self.client.wait_for_operation(op_id)
                        else:
                            if self._on_log:
                                self._on_log("Sequence cancelled by user.")
                            return

                await self.roller.roll_one()
            except Exception as e:
                if self._on_log:
                    self._on_log(f"[red]Controller Failure: {e}[/red]")

        self.rolling_task = asyncio.create_task(_run())

    async def stop_rotation(self):
        """Stops the background rotation process."""
        if self.roller:
            await self.roller.stop()
        if self.rolling_task:
            self.rolling_task.cancel()
            self.rolling_task = None

    async def manage_ips(self, request_resolution_via_ui_fn: Callable):
        """
        Orchestrates manual IP management via the service layer.

        BUG FIX (Phantom IPs):
        Previously used asyncio.create_task() (fire-and-forget) which caused
        the modal to close before the cloud actually confirmed deletion.
        On subsequent opens, the old IP would still appear.

        Fix: await the delete call so the UI reflects the true cloud state.
        """
        if not self.client:
            return

        try:
            # Fresh read from cloud — only returns non-archived IPs
            addresses = await self.client.list_addresses()
            if self._on_log:
                self._on_log(
                    f"[bold blue]ℹ[/bold blue] Synchronizing cloud state... "
                    f"({len(addresses)} active {'VM' if self.config_provider.config.active_service == 'regru' else 'IP'}(s) found)"
                )

            addr_to_del = await request_resolution_via_ui_fn(
                [a.model_dump() for a in addresses]
            )

            if not addr_to_del:
                return

            if addr_to_del == "all":
                # BUG FIX: await each deletion instead of fire-and-forget
                for addr in addresses:
                    try:
                        op_id = await self.client.delete_address(addr.id)
                        if op_id:
                            await self.client.wait_for_operation(op_id)
                        if self._on_log:
                            self._on_log(
                                f"Manual Clean: {addr.address:<15} [bold red]🛑 REMOVED[/bold red]"
                            )
                    except Exception as e:
                        if self._on_log:
                            self._on_log(f"[yellow]Warning: could not delete {addr.address}: {e}[/yellow]")

                if self._on_log:
                    self._on_log("[bold green]Success: All IPs/VMs deleted.[/bold green]")

            elif addr_to_del:
                target_addr = next((a for a in addresses if a.id == addr_to_del), None)
                ip_str = target_addr.address if target_addr else addr_to_del

                # BUG FIX: await deletion instead of fire-and-forget
                try:
                    op_id = await self.client.delete_address(addr_to_del)
                    if op_id:
                        await self.client.wait_for_operation(op_id)
                    if self._on_log:
                        self._on_log(
                            f"Manual Clean: {ip_str:<15} [bold red]🛑 REMOVED[/bold red]"
                        )
                except Exception as e:
                    if self._on_log:
                        self._on_log(f"[yellow]Warning: could not delete {ip_str}: {e}[/yellow]")

        except Exception as e:
            if self._on_log:
                self._on_log(f"[bold red]Management Error: {e}[/bold red]")
            if self._on_notify:
                self._on_notify(f"Management Error: {e}", "error")
