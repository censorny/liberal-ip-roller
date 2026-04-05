"""
Core Rotation Engine for Liberal IP Roller.
Handles the sequential creation and deletion of IP addresses to find a target CIDR match.
"""

import asyncio
import ipaddress
import random
from typing import List, Optional, Callable, Dict, Any

from .service_base import CloudService
from storage.provider import ServiceConfig


class Roller:
    """
    Stateful engine that manages the IP rotation lifecycle.
    Implements the Sequential Champion Loop architecture.
    """

    def __init__(self, client: CloudService, config: ServiceConfig):
        """
        Initializes the Roller with a cloud service and configuration.
        
        Args:
            client: Implementation of CloudService.
            config: Generic service configuration.
        """
        self.client = client
        self.config = config
        self.is_running = False
        
        # Callbacks for UI updates
        self._on_log: Optional[Callable[[str], None]] = None
        self._on_stats: Optional[Callable[[Dict[str, Any]], None]] = None
        self._on_match: Optional[Callable[[str], None]] = None
        self._on_error: Optional[Callable[[str], None]] = None
        
        # UI interaction for quota resolution (New)
        self._request_quota_resolution: Optional[Callable] = None
        
        # Metrics
        self.attempts = 0
        self.matches = 0
        
        # Optimization: Pre-parse CIDR networks
        self._parsed_ranges: List[ipaddress.IPv4Network] = []
        self._pre_parse_ranges()

    def _pre_parse_ranges(self):
        """
        Optimizes CIDR matching by pre-parsing string networks into ipaddress objects.
        This provides O(1) matching vs O(N) string processing.
        """
        for network_str in self.config.process.allowed_ranges:
            try:
                net = ipaddress.ip_network(network_str.strip())
                self._parsed_ranges.append(net)
            except ValueError:
                self.log(f"[red]Invalid CIDR range skipped: {network_str}[/red]")

    def set_callbacks(
        self,
        on_log: Callable[[str], None],
        on_stats: Optional[Callable] = None,
        on_match: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
        request_quota_resolution: Optional[Callable] = None
    ):
        """ Configures the notification pipeline. """
        self._on_log = on_log
        self._on_stats = on_stats
        self._on_match = on_match
        self._on_error = on_error
        self._request_quota_resolution = request_quota_resolution

    def log(self, message: str):
        """ Dispatches a log message to the UI. """
        if self._on_log:
            self._on_log(message)

    def update_stats(self):
        """ Dispatches cumulative metrics to the UI. """
        if self._on_stats:
            self._on_stats({
                "attempts": self.attempts,
                "matches": self.matches,
                "is_running": self.is_running
            })

    def is_ip_matched(self, ip: str) -> bool:
        """
        Checks if the given IP address falls within any of the allowed CIDR ranges.
        """
        if not ip or not ip.strip():
            return False

        try:
            ip_obj = ipaddress.ip_address(ip.strip())
            for network in self._parsed_ranges:
                if ip_obj in network:
                    return True
        except ValueError:
            pass
        return False

    async def _safe_create_address(self) -> str:
        """
        Robust creation logic with automatic backoff for Rate-Limiting.
        Compatible with both Yandex (zone_id required) and Reg.ru (zone_id ignored).
        """
        # Safe read: Yandex has zone_id, Reg.ru does not — pass empty string fallback
        zone_id = getattr(self.config.api, "zone_id", "")

        max_retries = 10
        for attempt in range(max_retries):
            op_id = None
            try:
                op_id = await self.client.create_address(zone_id)
                return await self.client.wait_for_operation(op_id)
            except Exception as e:
                # [BUG FIX]: Clean up the hung operation/IP if creation started but failed to stabilize
                if op_id:
                    try:
                        asyncio.create_task(self.client.delete_address(op_id))
                    except Exception:
                        pass

                # Handle Quota/Limit errors interactively or via backoff
                from .yandex_client import YandexQuotaException
                error_str = str(e).lower()
                is_quota = isinstance(e, YandexQuotaException) or "limit" in error_str or "quota" in error_str or "429" in error_str
                
                if is_quota:
                    if self._request_quota_resolution:
                        self.log("[yellow]Quota hit. Launching manual resolution...[/yellow]")
                        all_addr = await self.client.list_addresses()
                        ip_limit = getattr(self.config.api, "ip_limit", 2)
                        addr_to_del = await self._request_quota_resolution(
                            [a.model_dump() for a in all_addr],
                            current_count=len(all_addr),
                            ip_limit=ip_limit
                        )
                        if addr_to_del == "all":
                            for r in [a for a in all_addr if a.reserved]: await self.client.delete_address(r.id)
                            continue
                        elif addr_to_del:
                            await self.client.delete_address(addr_to_del)
                            continue
                    
                    await asyncio.sleep(2.0)
                    continue
                raise e
        raise RuntimeError("Failed to create IP/VM after 10 retries.")

    async def roll_one(self):
        """
        Main Sequential Champion Loop.
        
        Algorithm:
        1. Create IP address.
        2. Wait for Cloud Operation (Minimum 1.0s delay).
        3. Check against CIDR whitelist.
        4. If matched -> STOP.
        5. If not matched -> DELETE -> REPEAT.
        """
        self.is_running = True
        self.update_stats()
        
        self.log("[bold green]Success: Sequence started.[/bold green]")
        
        try:
            while self.is_running:
                self.update_stats()

                # Pre-Flight Quota Check: Prevent API 400s by requesting resolution upfront
                try:
                    all_addr = await self.client.list_addresses()
                    managed_addr = [a for a in all_addr if a.reserved]
                    ip_limit = getattr(self.config.api, "ip_limit", 2)
                    
                    if len(managed_addr) >= ip_limit and self._request_quota_resolution:
                        self.log(f"[yellow]Managed limit reached ({len(managed_addr)}/{ip_limit}). Preparing for next match...[/yellow]")
                        addr_to_del = await self._request_quota_resolution(
                            [a.model_dump() for a in all_addr],
                            current_count=len(all_addr),
                            ip_limit=ip_limit
                        )
                        if addr_to_del == "all":
                             for r in [a for a in all_addr if a.reserved]: await self.client.delete_address(r.id)
                        elif addr_to_del:
                             await self.client.delete_address(addr_to_del)
                        elif not addr_to_del:
                             self.log("[yellow]Rotation stopped: Managed limit reached and cleanup skipped.[/yellow]")
                             self.is_running = False
                             break
                except Exception:
                    pass # Best effort pre-flight check

                try:
                    if self.config.process.dry_run:
                        # Simulation mode for testing TUI performance
                        self.attempts += 1
                        ip = f"1.2.3.{random.randint(1, 254)}"
                        addr_id = "dry-run-id"
                        await asyncio.sleep(0.5)
                    else:
                        # Real Cloud interaction
                        self.attempts += 1
                        addr_id = await self._safe_create_address()
                        addr_info = await self.client.get_address_info(addr_id)
                        ip = addr_info.address

                    if self.is_ip_matched(ip):
                        self.matches += 1
                        self.update_stats()
                        self.log(
                            f"FOUND: {ip:<15} [bold green]🌟 MATCH[/bold green]"
                        )
                        
                        if self._on_match:
                            self._on_match(ip)
                            
                        # Stop ONLY if we reached the target match count
                        target = getattr(self.config.api, "target_match_count", 1)
                        if self.matches >= target:
                            self.is_running = False
                            break
                    else:
                        if not self.config.process.dry_run:
                            await self.client.delete_address(addr_id)
                        self.log(
                            f"Check {self.attempts:04d}: {ip:<15} [bold red]🛑 REMOVED[/bold red]"
                        )
                        
                        # Apply specialized Reg.ru delete cooldown (90s)
                        regru_delete_wait = getattr(self.config.process, "delete_wait_time", 0.0)
                        if regru_delete_wait > 0:
                            self.log(f"[yellow]Cooldown: Waiting {regru_delete_wait:.0f}s after deletion...[/yellow]")
                            await asyncio.sleep(regru_delete_wait)
                        
                except Exception as e:
                    # Apply specialized Reg.ru timeout cooldown (120s) if applicable
                    if "timeout" in str(e).lower() or "did not become active" in str(e).lower():
                        regru_timeout_wait = getattr(self.config.process, "timeout_wait_time", 0.0)
                        if regru_timeout_wait > 0:
                            self.log(f"[red]TIMEOUT: Waiting {regru_timeout_wait:.0f}s before retry...[/red]")
                            await asyncio.sleep(regru_timeout_wait)

                    if self.is_running:
                        self.log(f"[red]Error in loop: {e}[/red]")
                        
                        # Respect Industrial Recovery Policy
                        if not self.config.process.auto_restart_on_error:
                            self.log("[bold yellow]Auto-restart is disabled. Sequence terminated on error.[/bold yellow]")
                            self.is_running = False
                            break
                            
                        await asyncio.sleep(self.config.process.error_wait_period)

                if self.is_running:
                    # Respect user-defined delays
                    delay = self.config.process.min_delay
                    if self.config.process.randomize_delay:
                        delay = random.uniform(
                            self.config.process.min_delay, 
                            self.config.process.max_delay
                        )
                    await asyncio.sleep(delay)
                    
        finally:
            self.is_running = False
            self.update_stats()

    async def stop(self):
        """ Signals the current loop to terminate gracefully. """
        self.is_running = False
        self.log("Stopping sequence...")
        self.update_stats()
