"""Check GitHub releases for updates."""

import logging
import re
import threading
from collections.abc import Callable

import httpx

logger = logging.getLogger(__name__)

REPO = "Mineocean/Vocis"
GITHUB_API = f"https://api.github.com/repos/{REPO}/releases/latest"


def _parse_version(tag: str) -> tuple[int, ...]:
    """Parse 'v0.2.1' into (0, 2, 1); 'v0.4.0-alpha' into (0, 4, 0).

    忽略预发布/构建后缀（-alpha、-beta、-rc1、+build 等），只取数字段。
    解析失败（非版本格式）返回空元组，调用方比较时按"不更新"处理。
    """
    tag = tag.lstrip("v")
    # 去掉所有非数字/点字符及其之后的内容，仅保留形如 "0.4.0" 的前缀
    numeric = re.split(r"[^0-9.]+", tag, maxsplit=1)[0]
    try:
        return tuple(int(x) for x in numeric.split(".") if x)
    except ValueError:
        return ()


def _check_update_impl(current_version: str, latest_tag: str) -> bool:
    """比较版本：latest 严格大于 current 才为 True。"""
    latest = _parse_version(latest_tag)
    current = _parse_version(current_version)
    # 任一版本解析失败则不提示更新（避免误报）
    if not latest or not current:
        return False
    return latest > current


def check_update(current_version: str) -> str | None:
    """Return newer tag name if available, else None."""
    try:
        resp = httpx.get(GITHUB_API, timeout=10, follow_redirects=True)
        resp.raise_for_status()
        latest_tag = resp.json().get("tag_name", "")
        if _check_update_impl(current_version, latest_tag):
            return latest_tag
    except Exception as e:
        logger.debug("Update check failed: %s", e)
    return None


def check_update_async(
    current_version: str,
    callback: Callable[[str | None], None],
):
    """Check for updates in a background thread, call callback(latest_tag)."""

    def _worker():
        result = check_update(current_version)
        callback(result)

    threading.Thread(target=_worker, daemon=True).start()
