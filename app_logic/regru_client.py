"""
Reg.ru CloudVPS API Client for Liberal IP Roller.

Design based on deep analysis of reference scripts in need_to_integrate/:
- VM creation takes ~90 seconds before first poll (hard initial_wait)
- Deletion must be confirmed via polling until status == 'archive' or 404
- API is prone to 500 errors on delete and ConnectionReset (WinError 10054)
- Stability validation: N consecutive 'active + IP' checks before considering done

This client treats each VM (reglet) as an IP address entity — the Roller
doesn't need to know about VMs; it only sees a CloudAddress with an IP.
"""

import asyncio
import socket
from typing import List, Optional

import httpx
from .models import CloudAddress
from .service_base import CloudService


class RegruApiException(Exception):
    """Raised on unrecoverable Reg.ru API errors."""
    pass


class RegruClient(CloudService):
    """
    Industrial async client for the Reg.ru CloudVPS API.
    Implements the CloudService interface so it plugs directly into
    the existing Roller engine without modification.

    Key contractual differences from YandexClient:
      - create_address()    → creates a VM (reglet), returns reglet_id
      - wait_for_operation()→ polls until VM is active + stable (up to 240s)
      - delete_address()    → deletes VM + polls until archived
      - list_addresses()    → returns active VMs as CloudAddress objects
    """

    def __init__(
        self,
        api_token: str,
        api_base_url: str,
        region_slug: str,
        server_size: str,
        server_image: str,
        initial_wait: float = 0.0,
        check_interval: float = 10.0,
        stability_checks: int = 1,
        delete_wait: float = 10.0,
        vm_active_timeout: float = 240.0,
        vm_delete_timeout: float = 180.0,
    ):
        self.api_base_url = api_base_url.rstrip("/")
        self.region_slug = region_slug
        self.server_size = server_size
        self.server_image = server_image
        self.initial_wait = initial_wait
        self.check_interval = check_interval
        self.stability_checks = stability_checks
        self.delete_wait = delete_wait
        self.vm_active_timeout = vm_active_timeout
        self.vm_delete_timeout = vm_delete_timeout

        self.http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=15.0),
            headers={
                "accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_token}",
            },
        )

    async def close(self):
        """Cleanly closes the HTTP connection pool."""
        await self.http_client.aclose()

    # ──────────────────────────────────────────────
    #  INTERNAL HELPERS
    # ──────────────────────────────────────────────

    async def _request(
        self,
        method: str,
        url: str,
        max_retries: int = 5,
        retry_delay: float = 15.0,
        **kwargs,
    ) -> httpx.Response:
        """
        Robust request helper with retry logic.

        Reg.ru API is known to:
          - Drop connections (WinError 10054 / ConnectionReset)
          - Return HTTP 500 intermittently (especially on DELETE)
          - Hang on slow operations

        Strategy: retry on network errors and 500s, raise on other HTTP errors.
        """
        last_exc: Optional[Exception] = None

        for attempt in range(max_retries):
            try:
                resp = await self.http_client.request(method, url, **kwargs)

                # 500 on DELETE is a known Reg.ru quirk — retry
                # 400 on DELETE usually means VM is locked/building — retry to allow unlocking
                if method == "DELETE" and resp.status_code in (400, 500) and attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue

                # 404 on DELETE/GET is valid (already deleted) — return as-is
                if resp.status_code == 404:
                    return resp

                resp.raise_for_status()
                return resp

            except (httpx.NetworkError, httpx.RemoteProtocolError) as e:
                # Handles ConnectionReset (WinError 10054) and similar
                last_exc = e
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue
                raise RegruApiException(
                    f"Network error after {max_retries} retries: {e}"
                ) from e

            except httpx.TimeoutException as e:
                last_exc = e
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue
                raise RegruApiException(
                    f"Request timeout after {max_retries} retries: {e}"
                ) from e

        raise RegruApiException(
            f"All {max_retries} retries exhausted"
        ) from last_exc

    @staticmethod
    def _extract_public_ip(reglet: dict) -> str:
        """
        Safely extracts the public IPv4 from a reglet object.

        Reg.ru API returns IP in two possible structures:
          1. reglet.ip (direct field in some responses)
          2. reglet.networks.v4[type=public].ip_address
        """
        # Try direct IP field first (some API versions)
        direct_ip = reglet.get("ip")
        if direct_ip:
            return str(direct_ip)

        # Fall back to nested networks structure
        try:
            networks = reglet.get("networks", {}).get("v4", [])
            for net in networks:
                if net.get("type") == "public":
                    ip = net.get("ip_address", "")
                    if ip:
                        return str(ip)
        except (TypeError, AttributeError):
            pass

        return ""

    def _reglet_to_cloud_address(self, reglet: dict) -> CloudAddress:
        """Converts a raw reglet dict to a standardized CloudAddress."""
        return CloudAddress(
            id=str(reglet.get("id", "")),
            address=self._extract_public_ip(reglet),
            status=reglet.get("status", "unknown"),
            zone_id=reglet.get("region_slug", self.region_slug),
            folder_id="regru",
        )



    # ──────────────────────────────────────────────
    #  CloudService CONTRACT IMPLEMENTATION
    # ──────────────────────────────────────────────

    async def list_addresses(self) -> List[CloudAddress]:
        """
        Returns all active/non-archived VMs as CloudAddress objects.

        PHANTOM IP FIX: Filters out VMs that are 'archive', 'deleted',
        or 'locked' — only truly active/provisioning VMs are returned.
        """
        resp = await self._request("GET", self.api_base_url)
        data = resp.json()
        reglets = data.get("reglets", [])

        result = []
        excluded_statuses = {"archive", "deleted", "error"}
        for reglet in reglets:
            status = reglet.get("status", "").lower()
            if status in excluded_statuses:
                continue
            addr = self._reglet_to_cloud_address(reglet)
            # Only include if we have a valid ID
            if addr.id:
                result.append(addr)

        return result

    async def create_address(self, zone_id: str) -> str:
        """
        Creates a new VM (reglet) on Reg.ru.

        Args:
            zone_id: Ignored for Reg.ru (uses configured region_slug).
                     Kept for CloudService interface compatibility.

        Returns:
            The reglet ID (used as operation ID for wait_for_operation).
        """
        payload = {
            "backups": False,
            "floating_ip": True,
            "image": self.server_image,
            "name": "vm",
            "region_slug": self.region_slug,
            "size": self.server_size,
        }
        resp = await self._request("POST", self.api_base_url, json=payload)
        data = resp.json()
        reglet_id = data.get("reglet", {}).get("id")

        if not reglet_id:
            raise RegruApiException(
                f"Failed to get reglet ID from response: {data}"
            )

        return str(reglet_id)

    async def wait_for_operation(self, op_id: str, timeout: int = 300) -> str:
        """
        Waits for the VM to become stable and assigns a public IP.

        This is the core of Reg.ru's industrial-grade timing strategy:

        Phase 1: Hard initial wait (90s by default).
            Reg.ru VMs are NOT immediately available after creation.
            Polling too early results in 'new' or 'building' status loops
            that waste API calls and can trigger rate limits.

        Phase 2: Stability check polling.
            Poll every check_interval seconds. Require stability_checks
            consecutive 'active + has_IP' responses before declaring success.
            This guards against transient 'active' blips with no IP yet.

        Args:
            op_id: The reglet ID returned by create_address().
            timeout: Unused (internal timeout used instead). Kept for interface.

        Returns:
            The reglet ID (used by Roller to call get_address_info()).
        """
        url = f"{self.api_base_url}/{op_id}"

        # ── Phase 1: Hard initial wait ──────────────────────────────────
        if self.initial_wait > 0:
            await asyncio.sleep(self.initial_wait)

        # ── Phase 2: Stability polling ──────────────────────────────────
        deadline = asyncio.get_event_loop().time() + self.vm_active_timeout
        stability_counter = 0

        while asyncio.get_event_loop().time() < deadline:
            try:
                resp = await self._request("GET", url)

                if resp.status_code == 404:
                    raise RegruApiException(
                        f"VM {op_id} disappeared during activation (404)."
                    )

                reglet = resp.json().get("reglet", {})
                status = reglet.get("status", "").lower()
                ip = self._extract_public_ip(reglet)

                if status == "error":
                    raise RegruApiException(
                        f"VM {op_id} entered error state on provider side."
                    )

                if status == "active" and ip:
                    # VM is active and has an IP address assigned — SUCCESS
                    # source/regru.py logic: return immediately on first find
                    return op_id

            except RegruApiException:
                raise
            except Exception:
                # Network hiccup during polling — reset and retry
                stability_counter = 0

            await asyncio.sleep(self.check_interval)

        raise TimeoutError(
            f"VM {op_id} did not become active within "
            f"{self.vm_active_timeout}s (initial_wait={self.initial_wait}s)."
        )

    async def delete_address(self, addr_id: str) -> Optional[str]:
        """
        Deletes a VM and waits until it is archived or 404.

        Reg.ru specific behavior:
          - DELETE can return 500 intermittently → handled by _request retry.
          - VM may briefly remain in 'locked' state before transitioning.
          - 'archive' status = safe to create new VM.
          - If VM is already gone (404) = success.

        Returns:
            addr_id (for caller reference) or None if already deleted.
        """
        url = f"{self.api_base_url}/{addr_id}"

        # Send deletion request (retries on 500)
        resp = await self._request(
            "DELETE", url, max_retries=5, retry_delay=5.0
        )

        if resp.status_code == 404:
            # Already deleted — clean state, no further action needed
            return None

        # Poll until archived or gone
        deadline = asyncio.get_event_loop().time() + self.vm_delete_timeout

        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(self.check_interval)

            try:
                check_resp = await self._request("GET", url)

                if check_resp.status_code == 404:
                    # Confirmed deleted
                    return addr_id

                reglet = check_resp.json().get("reglet", {})
                status = reglet.get("status", "").lower()
                locked = reglet.get("locked", False)

                # 'archive' and not locked = safe to proceed
                if status == "archive" and not locked:
                    return addr_id

            except Exception:
                # If we can't reach the VM during deletion, assume it's gone
                pass

        # Timeout — log warning internally, but don't crash the roller
        # The cooldown (delete_wait) will provide additional safety margin
        return addr_id

    async def get_address_info(self, addr_id: str) -> CloudAddress:
        """
        Fetches current state of a VM and returns it as a CloudAddress.
        Called by the Roller after wait_for_operation() completes.
        """
        url = f"{self.api_base_url}/{addr_id}"
        resp = await self._request("GET", url)

        if resp.status_code == 404:
            raise RegruApiException(f"VM {addr_id} not found.")

        reglet = resp.json().get("reglet", {})
        return self._reglet_to_cloud_address(reglet)
