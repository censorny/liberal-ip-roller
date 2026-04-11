import asyncio
import ipaddress
import random
from typing import List, Optional, Set
from datetime import datetime

from .events import bus, LogEvent, IpMatchEvent, StatsUpdateEvent, WorkerErrorEvent
from .network_analytics import ObservedSubnetAnalytics
from .models import RollerStats
from .protocol import CloudProvider

class IPNetworkMatcher:
    def __init__(self, networks: List[str]):
        self.networks = []
        for n in networks:
            try:
                self.networks.append(ipaddress.ip_network(n.strip(), strict=False))
            except ValueError:
                pass

    @property
    def has_networks(self) -> bool:
        return bool(self.networks)
    
    def matches(self, ip_str: str) -> bool:
        if not ip_str: return False
        try:
            ip_obj = ipaddress.ip_address(ip_str)
            return any(ip_obj in net for net in self.networks)
        except ValueError:
            return False

    def random_matching_ip(self) -> str:
        if not self.networks:
            return "1.2.3.1"

        network = random.choice(self.networks)
        if network.num_addresses <= 2:
            return str(network.network_address)

        first_host = int(network.network_address) + 1
        last_host = int(network.broadcast_address) - 1
        if last_host < first_host:
            return str(network.network_address)

        return str(ipaddress.ip_address(random.randint(first_host, last_host)))

    def random_non_matching_ip(self) -> str:
        for _ in range(128):
            candidate = str(
                ipaddress.ip_address(
                    random.randint(int(ipaddress.IPv4Address("1.0.0.1")), int(ipaddress.IPv4Address("223.255.255.254")))
                )
            )
            if not self.matches(candidate):
                return candidate
        return "203.0.113.10"

class Roller:
    """Coordinate concurrent address creation, matching, and cleanup."""

    def __init__(
        self, 
        provider: Optional[CloudProvider], 
        allowed_networks: List[str],
        target_count: int = 1,
        max_concurrent: int = 2,
        zone_id: str = "ru-central1-a",
        min_delay: float = 0.0,
        max_delay: float = 0.0,
        randomize_delay: bool = False,
        dry_run: bool = False,
        polling_delay: float = 1.0,
        error_wait_period: float = 30.0,
        auto_restart_on_error: bool = True,
    ):
        self.provider = provider
        self.matcher = IPNetworkMatcher(allowed_networks)
        self.target_count = target_count
        self.max_concurrent = max(1, max_concurrent)
        self.zone_id = zone_id
        self.min_delay = max(min_delay, 0.0)
        self.max_delay = max(max_delay, self.min_delay)
        self.randomize_delay = randomize_delay
        self.dry_run = dry_run
        self.polling_delay = max(polling_delay, 0.2)
        self.error_wait_period = max(error_wait_period, 0.0)
        self.auto_restart_on_error = auto_restart_on_error
        
        self.stats = RollerStats()
        self.is_running = False
        self._pending_tasks: Set[asyncio.Task] = set()
        self._start_time: Optional[datetime] = None
        self._stop_event = asyncio.Event()
        self._match_lock = asyncio.Lock()
        self._subnet_analytics = ObservedSubnetAnalytics(allowed_networks)

    async def run(self):
        """Main orchestrator loop."""
        self.is_running = True
        self._stop_event.clear()
        self._start_time = datetime.now()
        await bus.emit(LogEvent(">> Rotation Engine Started", "success"))
        
        try:
            while self.is_running and self.stats.matches < self.target_count:
                while self.is_running and len(self._pending_tasks) < self.max_concurrent:
                    worker_number = len(self._pending_tasks) + 1
                    await bus.emit(LogEvent(f"++ Spawning worker {worker_number}/{self.max_concurrent}..."))
                    task = asyncio.create_task(self._worker_loop())
                    self._pending_tasks.add(task)
                    task.add_done_callback(self._on_worker_done)

                await self._emit_stats()

                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self.polling_delay)
                except asyncio.TimeoutError:
                    continue
        except Exception as e:
            await bus.emit(WorkerErrorEvent(f"Critical Engine Failure: {e}"))
        finally:
            self.is_running = False
            self.stats.is_running = False
            self._stop_event.set()
            if self._pending_tasks:
                await asyncio.gather(*tuple(self._pending_tasks), return_exceptions=True)
            await self._emit_stats()
            await bus.emit(LogEvent("Rotation Engine Stopped", "warning"))

    def _on_worker_done(self, task: asyncio.Task) -> None:
        self._pending_tasks.discard(task)
        if not task.cancelled():
            try:
                task.result()
            except Exception:
                pass

    async def _emit_stats(self) -> None:
        self.stats.active_workers = len(self._pending_tasks)
        self.stats.is_running = self.is_running
        if self._start_time:
            elapsed_seconds = (datetime.now() - self._start_time).total_seconds()
            self.stats.uptime_seconds = int(elapsed_seconds)
            self.stats.attempts_per_minute = self.stats.attempts / (max(elapsed_seconds, 1.0) / 60)
        if self.stats.attempts:
            self.stats.success_rate_percent = (self.stats.matches / self.stats.attempts) * 100
        self.stats.unique_ip_count = self._subnet_analytics.unique_ip_count
        self.stats.unique_subnet_count = self._subnet_analytics.unique_subnet_count
        self.stats.top_subnets = self._subnet_analytics.top_subnets()
        await bus.emit(StatsUpdateEvent(self.stats))

    async def _sleep(self, delay: float) -> None:
        if delay <= 0:
            await asyncio.sleep(0)
            return
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
        except asyncio.TimeoutError:
            return

    def _next_delay(self) -> float:
        if not self.randomize_delay:
            return self.min_delay
        return random.uniform(self.min_delay, self.max_delay)

    def _next_dry_run_ip(self) -> str:
        if self.matcher.has_networks and self.stats.attempts % 4 == 0:
            return self.matcher.random_matching_ip()
        return self.matcher.random_non_matching_ip()

    async def _delete_resource(self, resource_id: str) -> bool:
        if self.dry_run or self.provider is None or not resource_id:
            return False

        deleted = await self.provider.delete_address(resource_id)
        if deleted:
            self.stats.deleted_resources += 1
            await self._emit_stats()
        return deleted

    def _record_ip_observation(self, ip_address: str) -> None:
        self.stats.last_ip = ip_address
        subnet_bucket = self._subnet_analytics.register_ip(ip_address)
        if subnet_bucket:
            self.stats.last_subnet = subnet_bucket

    async def _worker_loop(self):
        """Individual worker that attempts to find one match."""
        while self.is_running and self.stats.matches < self.target_count:
            operation_id = ""
            resource_id = ""
            try:
                self.stats.attempts += 1
                await self._emit_stats()

                if self.dry_run:
                    resource_id = f"dry-run-{self.stats.attempts}"
                    ip_address = self._next_dry_run_ip()
                    await self._sleep(0.1)
                else:
                    if self.provider is None:
                        raise RuntimeError("Provider is not initialized")

                    operation_id = await self.provider.create_address(self.zone_id)
                    await bus.emit(LogEvent(f"++ Resource {operation_id[:8]} creation initiated"))
                    resource_id = await self.provider.wait_for_operation(operation_id)
                    if not resource_id:
                        resource_id = operation_id
                    address = await self.provider.get_address_info(resource_id)
                    ip_address = address.address

                self._record_ip_observation(ip_address)

                if self.matcher.matches(ip_address):
                    async with self._match_lock:
                        if self.stats.matches >= self.target_count:
                            break
                        self.stats.matches += 1
                        self.stats.last_match_ip = ip_address
                    await self._emit_stats()
                    await bus.emit(IpMatchEvent(ip_address))
                    await bus.emit(LogEvent(f"*** MATCH FOUND: [bold green]{ip_address}[/bold green]", "success"))

                    if self.stats.matches >= self.target_count:
                        self.stop()
                        break
                else:
                    self.stats.non_matches += 1
                    await self._emit_stats()
                    await bus.emit(LogEvent(f"No match: {ip_address}. Deleting..."))
                    if resource_id:
                        await self._delete_resource(resource_id)

                await self._sleep(self._next_delay())
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.stats.errors += 1
                self.stats.last_error = str(e)
                await self._emit_stats()
                await bus.emit(LogEvent(f"!! Worker loop failure: {e}", "error"))
                if resource_id:
                    try:
                        await self._delete_resource(resource_id)
                    except Exception:
                        pass
                elif operation_id:
                    await bus.emit(
                        LogEvent(
                            f"Cleanup skipped for operation {operation_id[:8]} because the resource ID was never resolved.",
                            "warning",
                        )
                    )

                if not self.auto_restart_on_error:
                    await bus.emit(WorkerErrorEvent(str(e)))
                    self.stop()
                    break

                await self._sleep(self.error_wait_period or 5.0)

    def stop(self):
        self.is_running = False
        self._stop_event.set()
