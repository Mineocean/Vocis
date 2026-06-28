"""Tests for TranslationCache."""

import time
from unittest.mock import patch

from backend.cache import TranslationCache


class TestTranslationCache:
    def test_get_put(self, cache):
        cache.put("hello", "你好")
        assert cache.get("hello") == "你好"

    def test_get_miss(self, cache):
        assert cache.get("nonexistent") is None

    def test_expiry(self, cache):
        cache.put("hello", "你好")
        with patch("backend.cache.time") as mock_time:
            mock_time.time.return_value = time.time() + 31
            assert cache.get("hello") is None

    def test_not_expired(self, cache):
        cache.put("hello", "你好")
        with patch("backend.cache.time") as mock_time:
            mock_time.time.return_value = time.time() + 10
            assert cache.get("hello") == "你好"

    def test_max_size_eviction(self):
        cache = TranslationCache(window_seconds=30, max_size=3)
        cache.put("a", "1")
        cache.put("b", "2")
        cache.put("c", "3")
        cache.put("d", "4")  # Should trigger eviction
        assert cache.size <= 3

    def test_clear(self, cache):
        cache.put("hello", "你好")
        cache.clear()
        assert cache.size == 0
        assert cache.get("hello") is None

    def test_whitespace_stripping(self, cache):
        cache.put("  hello  ", "你好")
        assert cache.get("hello") == "你好"
        assert cache.get("  hello  ") == "你好"

    def test_cleanup(self, cache):
        cache.put("old", "旧")
        cache.put("new", "新")
        with patch("backend.cache.time") as mock_time:
            mock_time.time.return_value = time.time() + 31
            cache.cleanup()
        assert cache.size == 0
