import asyncio
import ipaddress
from typing import List, Optional, Dict, Any, Tuple
import httpx

from .http_client import BaseServiceClient
from ..core.models import IPAddress, CloudStatus
from ..core.protocol import CloudProvider

class RegruClient(BaseServiceClient, CloudProvider):
    """Reg.ru CloudVPS client with recursive public-IP extraction."""

    def __init__(
        self, 
        api_token: str, 
        region_slug: str, 
        server_size: str, 
        server_image: str,
        base_url: str = "https://api.cloudvps.reg.ru/v1/reglets",
        initial_wait: float = 90.0,
        stability_checks: int = 3,
        check_interval: float = 5.0,
        vm_active_timeout: float = 240.0,
        vm_delete_timeout: float = 180.0,
    ):
        headers = {
            "accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_token}"
        }
        super().__init__(base_url=base_url, headers=headers)
        self.region_slug = region_slug
        self.server_size = server_size
        self.server_image = server_image
        self.initial_wait = max(initial_wait, 0.0)
        self.stability_checks = stability_checks
        self.check_interval = check_interval
        self.vm_active_timeout = vm_active_timeout
        self.vm_delete_timeout = vm_delete_timeout

    def _normalize_ip(self, value: Any) -> Optional[str]:
        if not isinstance(value, str): return None
        candidate = value.strip().split("/", 1)[0].strip()
        try:
            ip_obj = ipaddress.ip_address(candidate)
            if ip_obj.version == 4 and not ip_obj.is_private:
                return candidate
        except ValueError:
            pass
        return None

    def _collect_ip_candidates(self, node: Any, is_preferred: bool = False) -> Tuple[List[str], List[str]]:
        preferred, fallback = [], []
        
        def walk(val, preferred_ctx):
            if isinstance(val, dict):
                # Detect markers for "Public" status in various API versions
                markers = {str(val.get(k, "")).lower() for k in ("type", "scope", "kind")}
                is_pub = preferred_ctx or any(m in ("public", "external", "internet") for m in markers)
                is_pub = is_pub or val.get("public") is True
                
                for key in ("ip_address", "ip", "address", "public_ip", "ipv4"):
                    ip = self._normalize_ip(val.get(key))
                    if ip:
                        (preferred if is_pub else fallback).append(ip)
                
                for k, v in val.items():
                    if isinstance(v, (dict, list)): walk(v, is_pub)
            elif isinstance(val, (list, tuple)):
                for item in val: walk(item, preferred_ctx)
                
        walk(node, is_preferred)
        return preferred, fallback

    def extract_public_ip(self, data: Dict[str, Any]) -> str:
        """Deep recursive scan to find the elusive public IPv4 among diverse API payloads."""
        preferred, fallback = self._collect_ip_candidates(data)
        for ip in preferred + fallback:
            if ip: return ip
        return ""

    # ──────────────────────────────────────────────
    #  CloudProvider Implementation
    # ──────────────────────────────────────────────

    async def list_addresses(self) -> List[IPAddress]:
        resp = await self._request("GET", "")
        reglets = resp.json().get("reglets", [])
        excluded = {"archive", "deleted", "error"}
        return [self._to_model(r) for r in reglets if str(r.get("status", "")).lower() not in excluded]

    async def create_address(self, zone_id: str) -> str:
        payload = {
            "backups": False,
            "floating_ip": True,
            "image": self.server_image,
            "name": "ip-roller-worker",
            "region_slug": self.region_slug,
            "size": self.server_size,
        }
        resp = await self._request("POST", "", json=payload)
        return str(resp.json().get("reglet", {}).get("id", ""))

    async def wait_for_operation(self, op_id: str, timeout: int = 300) -> str:
        """Sequential stability check: require N consecutive successful polls."""
        loop = asyncio.get_running_loop()
        effective_timeout = self.vm_active_timeout if timeout == 300 else timeout
        deadline = loop.time() + effective_timeout
        stability_count = 0

        if self.initial_wait > 0:
            await asyncio.sleep(self.initial_wait)
        
        while loop.time() < deadline:
            try:
                addr = await self.get_address_info(op_id)
                if addr.is_active:
                    stability_count += 1
                    if stability_count >= self.stability_checks:
                        return op_id
                else:
                    stability_count = 0 # Reset on blips
            except Exception:
                stability_count = 0
            
            await asyncio.sleep(self.check_interval)
            
        raise TimeoutError(f"VM {op_id} stability check failed within {effective_timeout}s")

    async def delete_address(self, resource_id: str) -> bool:
        for attempt in range(5):
            try:
                await self._request("DELETE", resource_id, max_retries=1)
                break
            except httpx.HTTPStatusError as error:
                if error.response.status_code == 404:
                    return True
                if error.response.status_code in {400, 500, 503} and attempt < 4:
                    await asyncio.sleep(5.0 * (attempt + 1))
                    continue
                raise

        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.vm_delete_timeout
        while loop.time() < deadline:
            await asyncio.sleep(self.check_interval)
            try:
                resp = await self._request("GET", resource_id, max_retries=1)
                status = str(resp.json().get("reglet", {}).get("status", "")).lower()
                if status == "archive":
                    return True
            except httpx.HTTPStatusError as error:
                if error.response.status_code == 404:
                    return True
            except Exception:
                pass

        return True

    async def get_address_info(self, resource_id: str) -> IPAddress:
        resp = await self._request("GET", resource_id)
        return self._to_model(resp.json().get("reglet", {}))

    def _to_model(self, data: Dict[str, Any]) -> IPAddress:
        status_map = {
            "active": CloudStatus.ACTIVE,
            "new": CloudStatus.BUILDING,
            "building": CloudStatus.BUILDING,
            "archive": CloudStatus.ARCHIVED,
            "error": CloudStatus.ERROR
        }
        raw_status = data.get("status", "unknown").lower()
        return IPAddress(
            id=str(data.get("id", "")),
            address=self.extract_public_ip(data),
            status=status_map.get(raw_status, CloudStatus.UNKNOWN),
            zone_id=data.get("region_slug"),
            reserved=True,
        )
