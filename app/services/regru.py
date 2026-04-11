import asyncio
import ipaddress
from typing import List, Dict, Any, Tuple
import httpx

from .http_client import BaseServiceClient
from ..core.models import IPAddress, CloudStatus
from ..core.protocol import CloudProvider

class RegruClient(BaseServiceClient, CloudProvider):
    """Reg.ru CloudVPS client with deep public-IP extraction."""

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

    def _normalize_public_ipv4(self, value: Any) -> str:
        if not isinstance(value, str):
            return ""
        candidate = value.strip()
        if not candidate:
            return ""
        if "/" in candidate:
            candidate = candidate.split("/", 1)[0].strip()
        try:
            ip_obj = ipaddress.ip_address(candidate)
        except ValueError:
            return ""
        if ip_obj.version != 4:
            return ""
        if any([
            ip_obj.is_private,
            ip_obj.is_loopback,
            ip_obj.is_link_local,
            ip_obj.is_multicast,
            ip_obj.is_unspecified,
            ip_obj.is_reserved,
        ]):
            return ""
        return candidate

    def _collect_public_ip_candidates(self, node: Any, preferred: bool = False) -> Tuple[List[str], List[str]]:
        preferred_list: List[str] = []
        fallback_list: List[str] = []

        def walk(val: Any, is_preferred: bool = False) -> None:
            if isinstance(val, dict):
                public_markers = {
                    str(val.get("type", "")).lower(),
                    str(val.get("scope", "")).lower(),
                    str(val.get("network_type", "")).lower(),
                    str(val.get("kind", "")).lower(),
                    str(val.get("name", "")).lower(),
                }
                nested_preferred = is_preferred or any(
                    m in {"public", "floating", "external", "internet"} for m in public_markers
                )
                nested_preferred = (
                    nested_preferred
                    or val.get("public") is True
                    or val.get("is_public") is True
                )
                for key in (
                    "ip_address", "ip", "address", "public_ip", "public_ipv4",
                    "floating_ip", "floating_ip_address", "main_ip", "ipv4",
                ):
                    ip = self._normalize_public_ipv4(val.get(key))
                    if ip:
                        (preferred_list if nested_preferred else fallback_list).append(ip)
                for child in val.values():
                    if isinstance(child, (dict, list, tuple)):
                        walk(child, nested_preferred)
            elif isinstance(val, (list, tuple)):
                for item in val:
                    walk(item, is_preferred)
            else:
                ip = self._normalize_public_ipv4(val)
                if ip:
                    (preferred_list if is_preferred else fallback_list).append(ip)

        walk(node, preferred)
        return preferred_list, fallback_list

    def extract_public_ip(self, data: Dict[str, Any]) -> str:
        """Priority-ordered deep scan matching the reg.ru reglet API structure."""
        if not isinstance(data, dict):
            return ""

        preferred_candidates: List[str] = []
        fallback_candidates: List[str] = []

        # 1. networks dict — scan public/floating/external keys first
        networks = data.get("networks")
        if isinstance(networks, dict):
            for key in ("public", "floating", "external", "v4", "ipv4", "v6", "ipv6"):
                if key in networks:
                    p, f = self._collect_public_ip_candidates(
                        networks[key],
                        preferred=key in {"public", "floating", "external"},
                    )
                    preferred_candidates.extend(p)
                    fallback_candidates.extend(f)
            p, f = self._collect_public_ip_candidates(networks)
            preferred_candidates.extend(p)
            fallback_candidates.extend(f)
        elif networks is not None:
            p, f = self._collect_public_ip_candidates(networks)
            preferred_candidates.extend(p)
            fallback_candidates.extend(f)

        # 2. interface attachments
        for key in ("interfaces", "network_interfaces"):
            if key in data:
                p, f = self._collect_public_ip_candidates(data[key])
                preferred_candidates.extend(p)
                fallback_candidates.extend(f)

        # 3. other IP collection fields
        for key in (
            "v4", "ipv4", "v6", "ipv6", "ips", "ip_addresses", "addresses",
            "floating_ips", "public_network", "public_interface", "public_interfaces",
        ):
            if key in data:
                p, f = self._collect_public_ip_candidates(
                    data[key],
                    preferred=key in {"floating_ips", "public_network", "public_interface", "public_interfaces"},
                )
                preferred_candidates.extend(p)
                fallback_candidates.extend(f)

        # 4. direct scalar fields (fast path)
        for key in (
            "public_ip", "public_ipv4", "floating_ip", "floating_ip_address",
            "main_ip", "access_ip_v4", "access_ip", "ip_address", "ipv4", "ip",
        ):
            ip = self._normalize_public_ipv4(data.get(key))
            if ip:
                return ip

        # 5. full recursive fallback
        p, f = self._collect_public_ip_candidates(data)
        preferred_candidates.extend(p)
        fallback_candidates.extend(f)

        for ip in preferred_candidates + fallback_candidates:
            if ip:
                return ip
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
