"""Shared test fixtures."""

from unittest.mock import MagicMock, patch

import pytest

from backend.cache import TranslationCache


@pytest.fixture
def cache():
    """Create a fresh TranslationCache."""
    return TranslationCache(window_seconds=30, max_size=100)


@pytest.fixture
def mock_config():
    """Mock get_config to return test configuration."""
    with patch("backend.config.get_config") as mock:
        cfg = MagicMock()
        cfg.sample_rate = 16000
        cfg.vad_threshold = 0.5
        cfg.vad_model_path = ""
        cfg.speech_padding_ms = 400
        cfg.min_speech_duration_ms = 300
        cfg.silence_duration_ms = 600
        cfg.asr.backend = "mock"
        cfg.asr.language = "auto"
        cfg.asr.api_key = "test-key"
        cfg.asr.base_url = "https://api.example.com/v1"
        cfg.asr.model = "test-model"
        cfg.asr.whisper_model = "tiny"
        cfg.asr.whisper_device = "cpu"
        cfg.translator.api_key = "test-key"
        cfg.translator.base_url = "https://api.deepseek.com"
        cfg.translator.model = "deepseek-chat"
        cfg.translator.target_language = "中文"
        cfg.display.stream_translation = False
        cfg.display.font_size = 16
        cfg.display.subtitle_duration_ms = 5000
        cfg.display.subtitle_position = "bottom"
        cfg.display.subtitle_screen = "0"
        cfg.cache_window_seconds = 30
        cfg.audio_device = "auto"
        mock.return_value = cfg
        yield cfg
