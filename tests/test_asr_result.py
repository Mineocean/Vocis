"""v0.4 本地 ASR：三元组契约与配置默认值测试。"""

import asyncio

from backend.config import AppConfig
from backend.asr.base import ASREngine, ASRResult


def test_config_whisper_model_path_default():
    cfg = AppConfig()
    assert cfg.asr.whisper_model_path == "models/faster-whisper-base"


def test_config_skip_translate_default_true():
    cfg = AppConfig()
    assert cfg.asr.skip_translate_when_same_lang is True


class _DummyEngine(ASREngine):
    def transcribe(self, audio_pcm: bytes) -> ASRResult | None:
        return "hello", "en", 0.95


def test_transcribe_async_returns_tuple():
    result = asyncio.run(_DummyEngine().transcribe_async(b"data"))
    assert isinstance(result, tuple)
    text, lang, prob = result
    assert text == "hello"
    assert lang == "en"
    assert prob == 0.95

