"""Backend utility functions — shared logic."""

import logging

import httpx

logger = logging.getLogger(__name__)


def normalize_api_url(base: str) -> str:
    """规范化 API 根地址。

    只有路径为空时才补 /v1；已经带有路径（/v1、/compatible-mode/v1、
    /api/paas/v4 等）的地址原样保留，避免把智谱 v4、DashScope 兼容模式
    这类厂商路径改坏。
    """
    base = (base or "").strip().rstrip("/")
    if not base:
        return base
    from urllib.parse import urlsplit

    if not urlsplit(base).path.strip("/"):
        return base + "/v1"
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
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers[auth_header] = f"{auth_prefix}{api_key}"
    if async_client:
        return httpx.AsyncClient(base_url=base_url, headers=headers, timeout=timeout)
    return httpx.Client(base_url=base_url, headers=headers, timeout=timeout)
