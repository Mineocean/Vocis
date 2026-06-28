"""Tests for configuration loading."""

import os
from unittest.mock import patch
from pathlib import Path

from backend.config import read_env_file, write_env_file


class TestConfig:
    def test_read_env_file_nonexistent(self, tmp_path):
        result = read_env_file(tmp_path / "nonexistent.env")
        assert result == {}

    def test_read_env_file_basic(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("KEY1=value1\nKEY2=value2\n", encoding="utf-8")
        result = read_env_file(env_file)
        assert result == {"KEY1": "value1", "KEY2": "value2"}

    def test_read_env_file_skips_comments(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("# comment\nKEY1=value1\n\nKEY2=value2\n", encoding="utf-8")
        result = read_env_file(env_file)
        assert result == {"KEY1": "value1", "KEY2": "value2"}

    def test_write_env_file_new(self, tmp_path):
        env_file = tmp_path / ".env"
        write_env_file({"KEY1": "value1", "KEY2": "value2"}, env_file)
        result = read_env_file(env_file)
        assert result == {"KEY1": "value1", "KEY2": "value2"}

    def test_write_env_file_preserves_comments(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("# comment\nKEY1=old\nKEY2=value2\n", encoding="utf-8")
        write_env_file({"KEY1": "new"}, env_file)
        content = env_file.read_text(encoding="utf-8")
        assert "# comment" in content
        assert "KEY1=new" in content
        assert "KEY2=value2" in content

    def test_write_env_file_strips_quotes(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text('KEY1="quoted"\n', encoding="utf-8")
        result = read_env_file(env_file)
        assert result == {"KEY1": "quoted"}
