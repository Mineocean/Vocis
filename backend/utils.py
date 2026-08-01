"""Backend utility functions — shared logic."""

import logging

import httpx

logger = logging.getLogger(__name__)


def normalize_api_url(base: str) -> str:
    """Normalize API URL to end with /v1."""
    base = base.rstrip("/")
    if not base.endswith("/v1"):
        if "/v1/" in base or "/v1" in base:
            idx = base.index("/v1")
            base = base[:idx + 3]
        else:
            base += "/v1"
    return base


def create_http_client(
    base_url: str,
    api_key: str,
    auth_header: str = "Authorization",
    auth_prefix: str = "Bearer ",
    timeout: float = 10.0,
    async_client: bool = False,
) -> httpx.Client | httpx.AsyncClient:
    """Create httpx client instance (sync or async)."""
    headers = {
        auth_header: f"{auth_prefix}{api_key}",
        "Content-Type": "application/json",
    }
    if async_client:
        return httpx.AsyncClient(
            base_url=base_url,
            headers=headers,
            timeout=timeout,
        )
    return httpx.Client(
        base_url=base_url,
        headers=headers,
        timeout=timeout,
    )
