"""
Yandex Cloud VPC API Client.
Handles IP address lifecycle (List, Create, Delete, Wait) for the Liberal IP Roller.
"""

import asyncio
import time
import json
import os
from typing import List, Dict, Optional, Any

import httpx
try:
    import jwt # PyJWT for signing SA key JWTs
    HAS_JWT = True
except ImportError:
    HAS_JWT = False

from .models import CloudAddress
from .service_base import CloudService
from .logger import logger # Industrial logger

class YandexQuotaException(Exception):
    """Raised when IP addresses limit for the folder is exceeded or rate-limited."""
    pass


class YandexClient(CloudService):
    """
    Industrial Yandex Cloud API Client with Connection Pooling and Retry logic.
    Implements the core CloudService interface.
    """
    VPC_BASE_URL = "https://vpc.api.cloud.yandex.net/vpc/v1/addresses"
    OP_BASE_URL = "https://operation.api.cloud.yandex.net/operations"

    def __init__(
        self,
        iam_token: str,
        folder_id: str,
        sa_key_path: str = "",
        polling_delay: float = 1.0
    ):
        """
        Initializes the client with IAM or Service Account authentication.
        """
        self.iam_token = iam_token
        self.folder_id = folder_id
        self.sa_key_path = sa_key_path
        self._set_headers(iam_token)
        self.polling_delay = polling_delay
        
        # Performance tuning for connection pool
        limits = httpx.Limits(
            max_connections=100,
            max_keepalive_connections=50
        )
        
        # Detect HTTP/2 support
        try:
            import h2
            has_http2 = True
        except ImportError:
            has_http2 = False

        self.http_client = httpx.AsyncClient(
            timeout=20.0,
            headers=self.headers,
            limits=limits,
            http2=has_http2
        )
        
        # If SA key path is provided, immediately try to get a fresh token
        if self.sa_key_path:
            asyncio.create_task(self._refresh_iam_token())

    def _set_headers(self, token: str):
        """Updates internal headers with a new IAM token."""
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        if hasattr(self, "http_client"):
            self.http_client.headers.update(self.headers)

    async def _refresh_iam_token(self) -> bool:
        """
        Industrial SA Auth: Generates a JWT signed with the Private Key (RS256)
        and exchanges it for a fresh IAM Token.
        """
        if not HAS_JWT:
            logger.error("[Yandex] Missing dependencies: please run 'pip install PyJWT cryptography'")
            return False

        if not self.sa_key_path:
            return False

        if not os.path.exists(self.sa_key_path):
            logger.error(f"[Yandex] SA Key file NOT FOUND at: {self.sa_key_path}")
            return False

        try:
            with open(self.sa_key_path, 'r', encoding='utf-8') as f:
                key_data = json.load(f)
            
            # Validation of JSON structure
            required = ['service_account_id', 'id', 'private_key']
            missing = [k for k in required if k not in key_data]
            if missing:
                logger.error(f"[Yandex] Invalid SA Key JSON. Missing fields: {', '.join(missing)}")
                return False

            service_account_id = key_data['service_account_id']
            key_id = key_data['id']
            private_key = key_data['private_key']

            now = int(time.time())
            payload = {
                'aud': 'https://iam.api.cloud.yandex.net/iam/v1/tokens',
                'iss': service_account_id,
                'iat': now,
                'exp': now + 3600
            }
            
            encoded_token = jwt.encode(
                payload, 
                private_key, 
                algorithm='PS256', 
                headers={'kid': key_id}
            )

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    'https://iam.api.cloud.yandex.net/iam/v1/tokens',
                    json={'jwt': encoded_token}
                )
                
                if resp.status_code != 200:
                    logger.error(f"[Yandex] IAM Exchange failed (HTTP {resp.status_code}): {resp.text}")
                    return False

                new_token = resp.json().get('iamToken')
                if new_token:
                    self.iam_token = new_token
                    self._set_headers(new_token)
                    logger.info("[Yandex] Successfully authenticated via SA Key (JSON)")
                    return True
        except Exception as e:
            logger.error(f"[Yandex] SA Auth Exception: {str(e)}")
        return False

    async def close(self):
        """Cleanly closes the underlying HTTP connection pool."""
        await self.http_client.aclose()

    async def _retry_request(
        self,
        method: str,
        url: str,
        **kwargs
    ) -> httpx.Response:
        """
        Industrial retry logic with automatic 401 (Auth) Refresh support.
        """
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                res = await self.http_client.request(method, url, **kwargs)
                
                # Handle 401 Unauthorized by refreshing token if SA key exists
                if res.status_code == 401 and self.sa_key_path:
                    logger.warning("[Yandex] 401 Unauthorized. Refreshing IAM token...")
                    if await self._refresh_iam_token():
                        # Retry the request with the new token
                        return await self.http_client.request(method, url, **kwargs)

                res.raise_for_status()
                return res
            except (httpx.NetworkError, httpx.TimeoutException) as e:
                if attempt == max_attempts - 1:
                    raise e
                await asyncio.sleep(0.5 * (attempt + 1))
        
        raise Exception("Request failed after max retries")

    async def list_addresses(self) -> List[CloudAddress]:
        """ Fetches all IP addresses (reserved and ephemeral) in the target folder. """
        url = f"{self.VPC_BASE_URL}?folderId={self.folder_id}&pageSize=1000"
        res = await self._retry_request("GET", url)
        data = res.json()
        
        addresses = []
        for addr in data.get("addresses", []):
            ext_ip = addr.get("externalIpv4Address", {})
            addresses.append(CloudAddress(
                id=addr.get("id", ""),
                folder_id=addr.get("folderId", ""),
                zone_id=ext_ip.get("zoneId", ""),
                address=ext_ip.get("address", ""),
                status=addr.get("status", "UNKNOWN"),
                reserved=addr.get("reserved", False) # Default to false for ephemeral IPs
            ))
        return addresses

    async def create_address(self, zone_id: str) -> str:
        """
        Initiates the creation of a new reserved IP address.
        
        Args:
            zone_id: Availability zone (e.g., 'ru-central1-a').
            
        Returns:
            Operation ID to be passed to wait_for_operation.
        """
        try:
            res = await self._retry_request(
                "POST",
                self.VPC_BASE_URL,
                json={
                    "folderId": self.folder_id,
                    "externalIpv4AddressSpec": {"zoneId": zone_id}
                }
            )
            return res.json().get("id", "")
        except httpx.HTTPStatusError as e:
            if e.response.status_code in [403, 409, 429]:
                raise YandexQuotaException(f"Cloud Limit Reached (HTTP {e.response.status_code})")
            
            # 400 is returned for both Quotas and Invalid Parameters
            if e.response.status_code == 400:
                err_text = e.response.text.upper()
                if any(k in err_text for k in ["QUOTA", "LIMIT", "OUT_OF_RESOURCE", "RESOURCE_EXHAUSTED"]):
                    raise YandexQuotaException(f"Cloud Quota Exceeded (400): {e.response.text}")
            
            raise e

    async def wait_for_operation(self, op_id: str, timeout: int = 60) -> str:
        """
        Resilient Operation Poller. 
        Enforces a minimum 1.0s delay to stay within Operations API limits.
        """
        start_time = asyncio.get_event_loop().time()
        safe_poll_delay = max(0.0, self.polling_delay)
        
        while asyncio.get_event_loop().time() - start_time < timeout:
            try:
                url = f"{self.OP_BASE_URL}/{op_id}"
                res = await self._retry_request("GET", url)
                data = res.json()
                
                if data.get("done"):
                    if "error" in data:
                        err_msg = data['error'].get('message', 'Unknown Error')
                        raise Exception(f"Operation failed: {err_msg}")
                    
                    response = data.get("response", {})
                    return response.get("id", "")
                    
            except httpx.HTTPStatusError as e:
                # If hit with 429 on operations api, wait longer (3s)
                if e.response.status_code == 429:
                    await asyncio.sleep(3.0)
                    continue
                raise e 
                
            await asyncio.sleep(safe_poll_delay)
            
        raise TimeoutError("Operation timed out")

    async def delete_address(self, addr_id: str) -> Optional[str]:
        """
        Requests the deletion of an IP address.
        
        Returns:
            Operation ID or None if address was already deleted (404).
        """
        try:
            url = f"{self.VPC_BASE_URL}/{addr_id}"
            res = await self._retry_request("DELETE", url)
            return res.json().get("id")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise e

    async def get_address_info(self, addr_id: str) -> CloudAddress:
        """ Fetches current state and IP for a specific address ID. """
        res = await self._retry_request("GET", f"{self.VPC_BASE_URL}/{addr_id}")
        addr = res.json()
        ext_ip = addr.get("externalIpv4Address", {})
        
        return CloudAddress(
            id=addr.get("id", ""),
            folder_id=addr.get("folderId", ""),
            zone_id=ext_ip.get("zoneId", ""),
            address=ext_ip.get("address", ""),
            status=addr.get("status", "UNKNOWN"),
            reserved=addr.get("reserved", True)
        )
