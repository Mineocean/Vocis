"""Translation cache — exact match + time window deduplication."""

import logging
import time

logger = logging.getLogger(__name__)


class TranslationCache:
    """Cache with time-based expiry and max-size eviction."""

    def __init__(self, window_seconds: int = 30, max_size: int = 500):
        self._cache: dict[str, tuple[float, str]] = {}
        self._window = window_seconds
        self._max_size = max_size

    def get(self, text: str) -> str | None:
        """Return cached translation if not expired."""
        key = text.strip()
        entry = self._cache.get(key)
        if entry is None:
            return None
        ts, translation = entry
        if time.time() - ts <= self._window:
            return translation
        del self._cache[key]
        return None

    def put(self, text: str, translation: str):
        """Store translation in cache."""
        if len(self._cache) >= self._max_size:
            self.cleanup()
        if len(self._cache) >= self._max_size:
            sorted_keys = sorted(self._cache, key=lambda k: self._cache[k][0])
            for k in sorted_keys[:len(sorted_keys) // 2]:
                del self._cache[k]
        key = text.strip()
        self._cache[key] = (time.time(), translation)

    def cleanup(self):
        """Remove expired entries."""
        now = time.time()
        expired = [k for k, (ts, _) in self._cache.items() if now - ts > self._window]
        for k in expired:
            del self._cache[k]

    def clear(self):
        """Clear all entries."""
        self._cache.clear()

    @property
    def size(self) -> int:
        return len(self._cache)
