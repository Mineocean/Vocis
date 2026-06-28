"""Tests for ASR plugin registry."""

import pytest
from unittest.mock import patch, MagicMock

from backend.asr.registry import _REGISTRY, create_asr, list_backends, register_asr
from backend.asr.base import ASREngine


class TestASRRegistry:
    def test_list_backends(self):
        backends = list_backends()
        assert "mock" in backends
        assert "mimo" in backends
        assert "whisper" in backends

    def test_create_mock_asr(self, mock_config):
        mock_config.asr.backend = "mock"
        engine = create_asr()
        assert isinstance(engine, ASREngine)
        engine.close()

    def test_create_unknown_backend(self, mock_config):
        mock_config.asr.backend = "nonexistent"
        with patch.dict(_REGISTRY, clear=True):
            with pytest.raises(ValueError, match="Unknown ASR backend"):
                create_asr()

    def test_register_custom_backend(self):
        @register_asr("test_custom")
        class CustomASR(ASREngine):
            def transcribe(self, audio_pcm):
                return "custom"

        assert "test_custom" in _REGISTRY
        # Cleanup
        del _REGISTRY["test_custom"]

    def test_mock_asr_transcribe(self, mock_config):
        mock_config.asr.backend = "mock"
        engine = create_asr()
        result = engine.transcribe(b"\x00\x00" * 1000)
        assert result is not None
        assert isinstance(result, str)
        engine.close()

    def test_mock_asr_empty_input(self, mock_config):
        mock_config.asr.backend = "mock"
        engine = create_asr()
        result = engine.transcribe(b"")
        assert result is None
        engine.close()
