import asyncio
from typing import Any, Awaitable, Callable, Optional

from .core.roller import Roller
from .core.events import bus, LogEvent
from .infrastructure.task_manager import app_lifecycle
from .services.regru import RegruClient
from .services.selectel import SelectelClient
from .services.yandex import YandexClient
from storage import ConfigProvider


class AppController:
    """Coordinate provider lifecycle, rotation startup, and manual cleanup actions."""

    SUPPORTED_SERVICES = ("yandex", "regru", "selectel")
    
    def __init__(self, config_provider: ConfigProvider):
        self.config_provider = config_provider
        self.roller: Optional[Roller] = None
        self.provider = None
        self.rotation_task: Optional[asyncio.Task] = None
        self._start_lock = asyncio.Lock()

    async def initialize_provider(self):
        """Standardized provider initialization via Factory pattern."""
        config = self.config_provider.config
        svc = config.get_service_config()
        
        if self.provider:
            await self.provider.close()
            self.provider = None
        
        if config.active_service == "regru":
            self.provider = RegruClient(
                api_token=svc.api.api_token,
                base_url=svc.api.api_base_url,
                region_slug=svc.api.region_slug,
                server_size=svc.api.server_size,
                server_image=svc.api.server_image,
                initial_wait=svc.process.initial_wait,
                stability_checks=svc.process.stability_checks,
                check_interval=svc.process.check_interval,
                vm_active_timeout=svc.process.vm_active_timeout,
                vm_delete_timeout=svc.process.vm_delete_timeout,
            )
        elif config.active_service == "yandex":
            self.provider = YandexClient(
                iam_token=svc.api.iam_token,
                folder_id=svc.api.folder_id,
                sa_key_path=svc.api.sa_key_path,
                polling_delay=svc.process.polling_delay or 1.0,
            )
        elif config.active_service == "selectel":
            self.provider = SelectelClient(
                username=svc.api.username,
                password=svc.api.password,
                account_id=svc.api.account_id,
                project_name=svc.api.project_name,
                server_id_ru2=svc.api.server_id_ru2,
                server_id_ru3=svc.api.server_id_ru3,
                polling_delay=svc.process.polling_delay or 1.0,
                association_timeout=svc.process.association_timeout,
            )
        else:
            raise ValueError(f"Unsupported service: {config.active_service}")

    def validate_service_config(self, service_name: str | None = None) -> list[str]:
        """Return user-actionable configuration issues for the requested provider."""
        config = self.config_provider.config
        resolved_service = service_name or config.active_service
        svc = config.get_service_config(resolved_service)
        issues: list[str] = []

        if not svc.process.allowed_ranges:
            issues.append("No target IP/CIDR ranges are configured.")

        if svc.process.dry_run:
            return issues

        if resolved_service == "regru":
            if not svc.api.api_token:
                issues.append("Reg.ru API token is missing.")

        elif resolved_service == "yandex":
            has_auth = bool(svc.api.iam_token or svc.api.sa_key_path)
            if not has_auth:
                issues.append("Yandex IAM token or service-account key path is missing.")
            if not svc.api.folder_id:
                issues.append("Yandex folder ID is missing.")

        elif resolved_service == "selectel":
            if not svc.api.username:
                issues.append("Selectel service-user login is missing.")
            if not svc.api.password:
                issues.append("Selectel service-user password is missing.")
            if not svc.api.account_id:
                issues.append("Selectel account ID is missing.")
            if not svc.api.project_name:
                issues.append("Selectel project name is missing.")
            if not (svc.api.server_id_ru2 or svc.api.server_id_ru3):
                issues.append("At least one Selectel VM server ID must be configured.")

        return issues

    def validate_active_service_config(self) -> list[str]:
        return self.validate_service_config(self.config_provider.config.active_service)

    def find_first_ready_service(self) -> str | None:
        for service_name in self.SUPPORTED_SERVICES:
            if not self.validate_service_config(service_name):
                return service_name
        return None

    async def start_rotation(self):
        """Start the rotation engine if it is not already running."""
        async with self._start_lock:
            if self.rotation_task and not self.rotation_task.done():
                return False

            config = self.config_provider.config
            svc = config.get_service_config()
            validation_issues = self.validate_active_service_config()

            if validation_issues:
                raise ValueError(" ".join(validation_issues))

            if not svc.process.dry_run:
                await self.initialize_provider()
            else:
                self.provider = None

            self.roller = Roller(
                provider=self.provider,
                allowed_networks=svc.process.allowed_ranges,
                target_count=getattr(svc.api, "target_match_count", 1),
                max_concurrent=min(getattr(svc.api, "ip_limit", 2), getattr(svc.process, "max_concurrent", 2)),
                zone_id=getattr(svc.api, "zone_id", ""),
                min_delay=svc.process.min_delay,
                max_delay=svc.process.max_delay,
                randomize_delay=svc.process.randomize_delay,
                dry_run=svc.process.dry_run,
                polling_delay=svc.process.polling_delay,
                error_wait_period=svc.process.error_wait_period,
                auto_restart_on_error=svc.process.auto_restart_on_error,
            )

            self.rotation_task = app_lifecycle.run_task(self.roller.run())
            return True

    async def stop_rotation(self):
        """Gracefully terminates the rotation engine and cleans up cloud resources."""
        if self.roller:
            self.roller.stop()
        await app_lifecycle.shutdown()
        self.rotation_task = None
        if self.provider:
            await self.provider.close()
            self.provider = None

    async def manage_ips(self, request_resolution_via_ui_fn: Callable[..., Awaitable[Any]]):
        """Loads current provider resources and lets the UI resolve manual cleanup."""
        if self.provider is None:
            await self.initialize_provider()

        if self.provider is None:
            return

        all_addresses = await self.provider.list_addresses()
        if not all_addresses:
            await bus.emit(LogEvent("No active addresses found.", "info"))
            return

        config = self.config_provider.config
        ip_limit = getattr(config.get_service_config().api, "ip_limit", 0)
        choice = await request_resolution_via_ui_fn(
            [address.model_dump() for address in all_addresses],
            current_count=len(all_addresses),
            ip_limit=ip_limit,
        )

        if not choice:
            await bus.emit(LogEvent("Address management cancelled by user.", "warning"))
            return

        if choice == "all":
            deletable = [address for address in all_addresses if address.reserved]
            for address in deletable:
                await self.provider.delete_address(address.id)
                await bus.emit(LogEvent(f"Removed {address.address or address.id}", "success"))
            return

        target = next((address for address in all_addresses if address.id == choice), None)
        if target is None:
            return

        await self.provider.delete_address(target.id)
        await bus.emit(LogEvent(f"Removed {target.address or target.id}", "success"))
