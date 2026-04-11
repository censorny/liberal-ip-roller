import asyncio
import json
import os
import time
from typing import List, Dict, Any
import httpx

try:
    import jwt
    HAS_JWT = True
except ImportError:
    HAS_JWT = False

from .http_client import BaseServiceClient
from ..core.models import IPAddress, CloudStatus
from ..core.protocol import CloudProvider


class YandexQuotaException(Exception):
    """Raised when the folder has reached its external IP limit."""


class YandexClient(BaseServiceClient, CloudProvider):
    """Refactored Yandex Cloud VPC client."""

    def __init__(self, iam_token: str, folder_id: str, sa_key_path: str = "", polling_delay: float = 1.0):
        self.iam_token = iam_token.strip()
        self.folder_id = folder_id.strip()
        self.sa_key_path = sa_key_path.strip()
        self.polling_delay = max(polling_delay, 0.5)

        headers = {"Content-Type": "application/json"}
        if self.iam_token:
            headers["Authorization"] = f"Bearer {self.iam_token}"

        super().__init__(base_url="https://vpc.api.cloud.yandex.net/vpc/v1/addresses", headers=headers, timeout=20.0)
        self.op_client = httpx.AsyncClient(
            base_url="https://operation.api.cloud.yandex.net/operations/",
            headers=self.http_client.headers.copy(),
            timeout=httpx.Timeout(20.0)
        )

    def _set_auth_header(self, token: str) -> None:
        self.iam_token = token.strip()
        auth_value = f"Bearer {self.iam_token}" if self.iam_token else None

        if auth_value:
            self.http_client.headers["Authorization"] = auth_value
            self.op_client.headers["Authorization"] = auth_value
        else:
            self.http_client.headers.pop("Authorization", None)
            self.op_client.headers.pop("Authorization", None)

    async def ensure_authenticated(self) -> None:
        if self.iam_token:
            return
        if not self.sa_key_path:
            raise ValueError("Yandex IAM token or service account key is required")
        if not await self._refresh_iam_token():
            raise ValueError("Failed to authenticate Yandex service account key")

    async def _refresh_iam_token(self) -> bool:
        if not HAS_JWT or not self.sa_key_path or not os.path.exists(self.sa_key_path):
            return False

        try:
            with open(self.sa_key_path, "r", encoding="utf-8") as file_handle:
                key_data = json.load(file_handle)

            required_fields = ("service_account_id", "id", "private_key")
            if any(field not in key_data for field in required_fields):
                return False

            now = int(time.time())
            payload = {
                "aud": "https://iam.api.cloud.yandex.net/iam/v1/tokens",
                "iss": key_data["service_account_id"],
                "iat": now,
                "exp": now + 3600,
            }

            encoded_token = jwt.encode(
                payload,
                key_data["private_key"],
                algorithm="PS256",
                headers={"kid": key_data["id"]},
            )

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    "https://iam.api.cloud.yandex.net/iam/v1/tokens",
                    json={"jwt": encoded_token},
                )
                response.raise_for_status()

            token = response.json().get("iamToken", "")
            if not token:
                return False

            self._set_auth_header(token)
            return True
        except Exception:
            return False

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        await self.ensure_authenticated()
        try:
            return await super()._request(method, path, **kwargs)
        except httpx.HTTPStatusError as error:
            if error.response.status_code == 401 and self.sa_key_path and await self._refresh_iam_token():
                return await super()._request(method, path, **kwargs)

            if error.response.status_code == 403:
                raise PermissionError("Yandex folder access denied. Check IAM permissions for the configured folder.") from error

            if error.response.status_code == 400 and "limit" in error.response.text.lower():
                raise YandexQuotaException(error.response.text) from error

            raise

    async def _get_operation(self, op_id: str) -> httpx.Response:
        await self.ensure_authenticated()
        response = await self.op_client.get(op_id)
        if response.status_code == 401 and self.sa_key_path and await self._refresh_iam_token():
            response = await self.op_client.get(op_id)
        if response.status_code == 403:
            raise PermissionError("Yandex operations API denied access. Check IAM permissions.")
        response.raise_for_status()
        return response

    async def list_addresses(self) -> List[IPAddress]:
        resp = await self._request("GET", f"?folderId={self.folder_id}&pageSize=1000")
        data = resp.json().get("addresses", [])
        return [self._to_model(a) for a in data]

    async def create_address(self, zone_id: str) -> str:
        payload = {
            "folderId": self.folder_id,
            "externalIpv4AddressSpec": {"zoneId": zone_id}
        }
        resp = await self._request("POST", "", json=payload)
        return str(resp.json().get("id", ""))

    async def wait_for_operation(self, op_id: str, timeout: int = 60) -> str:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            resp = await self._get_operation(op_id)
            data = resp.json()

            if data.get("done"):
                if "error" in data:
                    raise Exception(f"Yandex Op Failed: {data['error'].get('message')}")

                response_id = data.get("response", {}).get("id")
                metadata = data.get("metadata", {})
                resource_id = response_id or metadata.get("addressId") or metadata.get("resourceId") or ""
                return str(resource_id)

            await asyncio.sleep(self.polling_delay)
        raise TimeoutError("Yandex operation timed out")

    async def delete_address(self, resource_id: str) -> bool:
        try:
            resp = await self._request("DELETE", resource_id)
            op_id = str(resp.json().get("id", ""))
            if op_id:
                await self.wait_for_operation(op_id, timeout=60)
            return True
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return True
            raise e

    async def get_address_info(self, resource_id: str) -> IPAddress:
        resp = await self._request("GET", resource_id)
        return self._to_model(resp.json())

    async def close(self):
        await super().close()
        await self.op_client.aclose()

    def _to_model(self, data: Dict[str, Any]) -> IPAddress:
        ext = data.get("externalIpv4Address", {})
        status_map = {
            "ALLOCATING": CloudStatus.BUILDING,
            "RESERVING": CloudStatus.BUILDING,
            "READY": CloudStatus.ACTIVE,
            "DELETING": CloudStatus.ARCHIVED
        }
        return IPAddress(
            id=data.get("id", ""),
            address=ext.get("address", ""),
            status=status_map.get(data.get("status", ""), CloudStatus.UNKNOWN),
            zone_id=ext.get("zoneId"),
            reserved=data.get("reserved", False)
        )
