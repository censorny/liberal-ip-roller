import asyncio
import itertools
import ssl
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from ..core.models import CloudStatus, IPAddress
from ..core.protocol import CloudProvider


def _build_ssl_context() -> ssl.SSLContext:
    """Keeps compatibility with Selectel's TLS stack across Python versions."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED

    try:
        context.set_ciphers("DEFAULT:@SECLEVEL=1")
    except ssl.SSLError:
        pass

    context.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0)
    return context


@dataclass
class SelectelRegionState:
    region: str
    server_id: str
    neutron_url: Optional[str] = None
    nova_url: Optional[str] = None
    external_network_id: Optional[str] = None
    vm_port_id: Optional[str] = None

    def ready(self) -> bool:
        return bool(self.neutron_url and self.nova_url)


class SelectelClient(CloudProvider):
    """Async Selectel Floating IP client integrated with the app provider contract."""

    AUTH_URL = "https://cloud.api.selcloud.ru/identity/v3/auth/tokens"

    def __init__(
        self,
        username: str,
        password: str,
        account_id: str,
        project_name: str,
        server_id_ru2: str = "",
        server_id_ru3: str = "",
        polling_delay: float = 1.0,
        association_timeout: float = 15.0,
    ):
        self.username = username.strip()
        self.password = password
        self.account_id = account_id.strip()
        self.project_name = project_name.strip()
        self.polling_delay = max(polling_delay, 0.5)
        self.association_timeout = max(association_timeout, 1.0)

        self._token: Optional[str] = None
        self._token_expires: Optional[datetime] = None
        self._resource_regions: Dict[str, str] = {}
        self._auth_lock = asyncio.Lock()

        self._regions: Dict[str, SelectelRegionState] = {}
        if server_id_ru2.strip():
            self._regions["ru-2"] = SelectelRegionState(region="ru-2", server_id=server_id_ru2.strip())
        if server_id_ru3.strip():
            self._regions["ru-3"] = SelectelRegionState(region="ru-3", server_id=server_id_ru3.strip())

        self._region_cycle = itertools.cycle(tuple(self._regions.keys())) if self._regions else None
        self._client = httpx.AsyncClient(
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=httpx.Timeout(30.0),
            verify=_build_ssl_context(),
            follow_redirects=True,
        )

    def _ensure_regions_configured(self) -> None:
        if not self._regions:
            raise ValueError("At least one Selectel VM server ID must be configured")

    def _token_valid(self) -> bool:
        if not self._token or not self._token_expires:
            return False
        return datetime.now(timezone.utc) < (self._token_expires - timedelta(minutes=5))

    async def ensure_authenticated(self) -> None:
        if self._token_valid():
            return

        async with self._auth_lock:
            if self._token_valid():
                return
            await self.authenticate()

    async def authenticate(self) -> None:
        last_error: Optional[Exception] = None
        response: Optional[httpx.Response] = None

        for domain_key in ("name", "id"):
            payload = {
                "auth": {
                    "identity": {
                        "methods": ["password"],
                        "password": {
                            "user": {
                                "name": self.username,
                                "password": self.password,
                                "domain": {domain_key: self.account_id},
                            }
                        },
                    },
                    "scope": {
                        "project": {
                            "name": self.project_name,
                            "domain": {"name": self.account_id},
                        }
                    },
                }
            }

            try:
                response = await self._client.post(self.AUTH_URL, json=payload)
                if response.status_code == 401:
                    last_error = httpx.HTTPStatusError(
                        "Selectel authentication failed",
                        request=response.request,
                        response=response,
                    )
                    continue

                response.raise_for_status()
                break
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code == 401:
                    continue
                raise
        else:
            raise ValueError(
                "Selectel authentication failed. Check username, password, account ID, and project name."
            ) from last_error

        if response is None:
            raise ValueError("Selectel authentication returned no response")

        token = response.headers.get("X-Subject-Token", "").strip()
        if not token:
            raise ValueError("Selectel authentication returned no X-Subject-Token header")

        self._token = token
        self._token_expires = self._parse_token_expiration(response.json())
        self._apply_service_catalog(response.json())

    def _parse_token_expiration(self, payload: Dict[str, Any]) -> Optional[datetime]:
        raw_value = str(payload.get("token", {}).get("expires_at", "")).strip()
        if not raw_value:
            return None

        normalized = raw_value[:-1] + "+00:00" if raw_value.endswith("Z") else raw_value
        try:
            dt = datetime.fromisoformat(normalized)
        except ValueError:
            return None

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def _apply_service_catalog(self, payload: Dict[str, Any]) -> None:
        for state in self._regions.values():
            state.neutron_url = None
            state.nova_url = None

        services = payload.get("token", {}).get("catalog", [])
        for service in services:
            service_type = str(service.get("type", "")).strip().lower()
            for endpoint in service.get("endpoints", []):
                region = endpoint.get("region_id") or endpoint.get("region")
                if endpoint.get("interface") != "public" or region not in self._regions:
                    continue

                url = str(endpoint.get("url", "")).rstrip("/")
                if not url:
                    continue

                state = self._regions[region]
                if service_type == "network":
                    state.neutron_url = url
                elif service_type == "compute":
                    state.nova_url = url

        missing = [state.region for state in self._regions.values() if not state.ready()]
        if missing:
            raise RuntimeError(
                "Selectel service catalog is missing public network/compute endpoints for: "
                + ", ".join(missing)
            )

    def _auth_headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self._token:
            headers["X-Auth-Token"] = self._token
        return headers

    async def _request(
        self,
        method: str,
        url: str,
        retry_on_unauthorized: bool = True,
        **kwargs,
    ) -> httpx.Response:
        extra_headers = kwargs.pop("headers", {})
        await self.ensure_authenticated()
        response = await self._client.request(
            method,
            url,
            headers={**self._auth_headers(), **extra_headers},
            **kwargs,
        )

        if response.status_code == 401 and retry_on_unauthorized:
            self._token = None
            self._token_expires = None
            await self.ensure_authenticated()
            response = await self._client.request(
                method,
                url,
                headers={**self._auth_headers(), **extra_headers},
                **kwargs,
            )

        if response.status_code == 403:
            raise PermissionError(
                "Selectel API access denied. Check service-user permissions and project scope."
            )

        response.raise_for_status()
        return response

    def _state_for(self, region: str) -> SelectelRegionState:
        self._ensure_regions_configured()
        if region not in self._regions:
            raise ValueError(f"Unsupported Selectel region: {region}")
        return self._regions[region]

    def _pick_region(self, preferred_region: str = "") -> str:
        self._ensure_regions_configured()
        if preferred_region in self._regions:
            return preferred_region
        return next(self._region_cycle)

    async def _get_external_network_id(self, region: str) -> str:
        state = self._state_for(region)
        if state.external_network_id:
            return state.external_network_id

        response = await self._request(
            "GET",
            f"{state.neutron_url}/v2.0/networks",
            params={"router:external": True, "status": "ACTIVE"},
        )
        networks = response.json().get("networks", [])
        if not networks:
            raise RuntimeError(f"Selectel region {region} has no active external networks")

        state.external_network_id = str(networks[0].get("id", ""))
        if not state.external_network_id:
            raise RuntimeError(f"Selectel region {region} returned an external network without ID")
        return state.external_network_id

    async def _get_vm_port_id(self, region: str, force_refresh: bool = False) -> str:
        state = self._state_for(region)
        if state.vm_port_id and not force_refresh:
            return state.vm_port_id

        response = await self._request(
            "GET",
            f"{state.nova_url}/servers/{state.server_id}/os-interface",
        )
        attachments = response.json().get("interfaceAttachments", [])
        if not attachments:
            raise RuntimeError(f"Selectel VM {state.server_id} in region {region} has no interfaces")

        port_id = str(attachments[0].get("port_id", "")).strip()
        if not port_id:
            raise RuntimeError(f"Selectel VM {state.server_id} in region {region} returned no port_id")

        state.vm_port_id = port_id
        return port_id

    async def _get_floating_ip_payload(self, region: str, resource_id: str) -> Dict[str, Any]:
        state = self._state_for(region)
        response = await self._request(
            "GET",
            f"{state.neutron_url}/v2.0/floatingips/{resource_id}",
        )
        payload = response.json().get("floatingip", {})
        if not payload:
            raise RuntimeError(f"Selectel floating IP {resource_id} returned an empty payload")

        self._resource_regions[str(payload.get("id", resource_id))] = region
        return payload

    async def _resolve_region(self, resource_id: str) -> str:
        self._ensure_regions_configured()
        known_region = self._resource_regions.get(resource_id)
        if known_region in self._regions:
            return known_region

        for region in self._regions:
            try:
                await self._get_floating_ip_payload(region, resource_id)
                return region
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    continue
                raise

        raise KeyError(resource_id)

    async def _associate_floating_ip(self, region: str, resource_id: str, port_id: str) -> None:
        state = self._state_for(region)
        payload = {"floatingip": {"port_id": port_id}}
        url = f"{state.neutron_url}/v2.0/floatingips/{resource_id}"

        try:
            await self._request("PUT", url, json=payload)
        except httpx.HTTPStatusError:
            refreshed_port_id = await self._get_vm_port_id(region, force_refresh=True)
            if refreshed_port_id == port_id:
                raise
            await self._request("PUT", url, json={"floatingip": {"port_id": refreshed_port_id}})

    async def _delete_floating_ip(self, region: str, resource_id: str) -> None:
        state = self._state_for(region)
        url = f"{state.neutron_url}/v2.0/floatingips/{resource_id}"

        try:
            await self._request("PUT", url, json={"floatingip": {"port_id": None}})
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in {400, 404, 409}:
                raise

        try:
            await self._request("DELETE", url)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise

        self._resource_regions.pop(resource_id, None)

    async def list_addresses(self) -> List[IPAddress]:
        if not self._regions:
            return []

        addresses: List[IPAddress] = []

        for region, state in self._regions.items():
            response = await self._request("GET", f"{state.neutron_url}/v2.0/floatingips")
            for item in response.json().get("floatingips", []):
                resource_id = str(item.get("id", "")).strip()
                if resource_id:
                    self._resource_regions[resource_id] = region
                addresses.append(self._to_model(item, region))

        return addresses

    async def create_address(self, zone_id: str) -> str:
        region = self._pick_region(zone_id)
        state = self._state_for(region)
        port_id = await self._get_vm_port_id(region)
        network_id = await self._get_external_network_id(region)

        response = await self._request(
            "POST",
            f"{state.neutron_url}/v2.0/floatingips",
            json={"floatingip": {"floating_network_id": network_id}},
        )
        payload = response.json().get("floatingip", {})
        resource_id = str(payload.get("id", "")).strip()
        if not resource_id:
            raise RuntimeError(f"Selectel region {region} returned no floating IP ID")

        self._resource_regions[resource_id] = region
        try:
            await self._associate_floating_ip(region, resource_id, port_id)
        except Exception:
            try:
                await self._delete_floating_ip(region, resource_id)
            except Exception:
                pass
            raise

        return resource_id

    async def wait_for_operation(self, op_id: str, timeout: int = 60) -> str:
        region = await self._resolve_region(op_id)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(float(timeout), self.association_timeout)

        while loop.time() < deadline:
            payload = await self._get_floating_ip_payload(region, op_id)
            if payload.get("port_id"):
                return op_id
            await asyncio.sleep(self.polling_delay)

        raise TimeoutError(f"Selectel floating IP {op_id} did not associate in time")

    async def delete_address(self, resource_id: str) -> bool:
        try:
            region = await self._resolve_region(resource_id)
        except KeyError:
            return True

        await self._delete_floating_ip(region, resource_id)
        return True

    async def get_address_info(self, resource_id: str) -> IPAddress:
        region = await self._resolve_region(resource_id)
        payload = await self._get_floating_ip_payload(region, resource_id)
        return self._to_model(payload, region)

    def _to_model(self, data: Dict[str, Any], region: str) -> IPAddress:
        status_raw = str(data.get("status", "")).upper()
        status_map = {
            "ACTIVE": CloudStatus.ACTIVE,
            "DOWN": CloudStatus.ACTIVE,
            "BUILD": CloudStatus.BUILDING,
            "ERROR": CloudStatus.ERROR,
        }
        return IPAddress(
            id=str(data.get("id", "")),
            address=str(data.get("floating_ip_address", "")),
            status=status_map.get(status_raw, CloudStatus.UNKNOWN),
            zone_id=region,
            reserved=True,
        )

    async def close(self):
        await self._client.aclose()