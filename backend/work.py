"""Tracks real component work so models are not released mid-inference.

A wrapper Task (or the coroutine awaiting asyncio.to_thread) can be cancelled
while the worker thread keeps running. Components therefore own a WorkTracker
that is entered inside the worker thread and left in its finally block; the
tracker, not the Task state, is the source of truth.
"""

from __future__ import annotations

import functools
import threading
from collections.abc import Callable
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


class WorkTracker:
    """Thread-safe count of in-flight unit(s) of real work."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._active = 0

    def begin(self) -> None:
        with self._cond:
            self._active += 1

    def end(self) -> None:
        with self._cond:
            if self._active > 0:
                self._active -= 1
            self._cond.notify_all()

    def busy(self) -> bool:
        with self._cond:
            return self._active > 0

    def wait_idle(self, timeout: float | None = None) -> bool:
        """Wait until no work is active; True when idle, False on timeout."""
        with self._cond:
            return self._cond.wait_for(lambda: self._active == 0, timeout=timeout)


def tracked_async(method: F) -> F:
    """Track an async component method for its whole coroutine lifetime.

    Suitable for async I/O backends (httpx): cancelling the coroutine aborts
    the request, so coroutine lifetime equals real work lifetime.
    """

    @functools.wraps(method)
    async def wrapper(self, *args, **kwargs):
        tracker = getattr(self, "_work_tracker", None)
        if tracker is not None:
            tracker.begin()
        try:
            return await method(self, *args, **kwargs)
        finally:
            if tracker is not None:
                tracker.end()

    return wrapper  # type: ignore[return-value]
