"""Check GitHub releases for updates."""

import logging
import threading
from collections.abc import Callable

import httpx

logger = logging.getLogger(__name__)

REPO = "Mineocean/Vocis"
GITHUB_API = f"https://api.github.com/repos/{REPO}/releases/latest"


def _parse_version(tag: str) -> tuple[int, ...]:
    """Parse 'v0.2.1' into (0, 2, 1)."""
    tag = tag.lstrip("v")
    try:
        return tuple(int(x) for x in tag.split("."))
    except (ValueError, AttributeError):
        return ()


def check_update(current_version: str) -> str | None:
    """Return newer tag name if available, else None."""
    try:
        resp = httpx.get(GITHUB_API, timeout=10, follow_redirects=True)
        resp.raise_for_status()
        latest_tag = resp.json().get("tag_name", "")
        if _parse_version(latest_tag) > _parse_version(current_version):
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
