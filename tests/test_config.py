"""Tests for configuration loading.

Note: the sandbox on this machine forbids creating files inside new temp
subdirectories from test processes, so env fixtures live directly in the
system temp directory with unique names.
"""

import tempfile
import uuid
from pathlib import Path

from backend.config import read_env_file, write_env_file


def _env_path() -> Path:
    return Path(tempfile.gettempdir()) / f"vocis_env_test_{uuid.uuid4().hex}.env"


class TestConfig:
    def test_read_env_file_nonexistent(self):
        result = read_env_file(_env_path())
        assert result == {}

    def test_read_env_file_basic(self):
        env_file = _env_path()
        env_file.write_text("KEY1=value1\nKEY2=value2\n", encoding="utf-8")
        result = read_env_file(env_file)
        assert result == {"KEY1": "value1", "KEY2": "value2"}

    def test_read_env_file_skips_comments(self):
        env_file = _env_path()
        env_file.write_text("# comment\nKEY1=value1\n\nKEY2=value2\n", encoding="utf-8")
        result = read_env_file(env_file)
        assert result == {"KEY1": "value1", "KEY2": "value2"}

    def test_write_env_file_new(self):
        env_file = _env_path()
        write_env_file({"KEY1": "value1", "KEY2": "value2"}, env_file)
        result = read_env_file(env_file)
        assert result == {"KEY1": "value1", "KEY2": "value2"}

    def test_write_env_file_preserves_comments(self):
        env_file = _env_path()
        env_file.write_text("# comment\nKEY1=old\nKEY2=value2\n", encoding="utf-8")
        write_env_file({"KEY1": "new"}, env_file)
        content = env_file.read_text(encoding="utf-8")
        assert "# comment" in content
        assert "KEY1=new" in content
        assert "KEY2=value2" in content

    def test_write_env_file_strips_quotes(self):
        env_file = _env_path()
        env_file.write_text('KEY1="quoted"\n', encoding="utf-8")
        result = read_env_file(env_file)
        assert result == {"KEY1": "quoted"}
