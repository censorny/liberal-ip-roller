from __future__ import annotations

import asyncio

import httpx

class BaseServiceClient:
    """Shared async HTTP client with retry-aware request handling."""

    def __init__(
        self,
        base_url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.headers = self._sanitize_headers(headers or {})

        limits = httpx.Limits(max_connections=100, max_keepalive_connections=20)
        self.http_client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=self.headers,
            limits=limits,
            timeout=httpx.Timeout(timeout),
            follow_redirects=True,
        )

    @staticmethod
    def _sanitize_headers(headers: dict[str, str]) -> dict[str, str]:
        return {
            key: value
            for key, value in headers.items()
            if not (
                key.lower() == "authorization"
                and (not value or value in {"Bearer", "Bearer "})
            )
        }

    async def _request(
        self,
        method: str,
        path: str,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        **kwargs,
    ) -> httpx.Response:
        """Perform a request with retry handling for transient transport and 5xx failures."""
        path = f"/{path.lstrip('/')}"
        last_error: Exception | None = None

        for attempt in range(max_retries):
            try:
                response = await self.http_client.request(method, path, **kwargs)

                if response.status_code >= 500 and attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay * (attempt + 1))
                    continue

                response.raise_for_status()
                return response
            except (httpx.NetworkError, httpx.TimeoutException) as error:
                last_error = error
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay * (attempt + 1))
                    continue
                raise

        raise httpx.RequestError("Max retries exceeded") from last_error

    async def close(self) -> None:
        await self.http_client.aclose()
