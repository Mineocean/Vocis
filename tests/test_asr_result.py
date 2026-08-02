"""v0.4 本地 ASR：三元组契约与配置默认值测试。"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from backend.config import AppConfig
from backend.asr.base import ASREngine, ASRResult
from backend.asr.mock import MockASR
from backend.asr.mimo import MiMoASR
from backend.asr.whisper import WhisperASR


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


def test_mock_asr_returns_zh_tuple():
    asr = MockASR()
    result = asr.transcribe(b"data")
    assert result is not None
    text, lang, prob = result
    assert isinstance(text, str)
    assert lang == "zh"
    assert prob == 1.0


@patch("backend.asr.mimo.get_config")
@patch("backend.asr.mimo.httpx.AsyncClient")
def test_mimo_asr_returns_no_lang_tuple(MockClient, mock_cfg):
    mock_cfg.return_value = MagicMock(
        asr=MagicMock(api_key="k", base_url="https://x/v1", model="m", language="auto")
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"choices": [{"message": {"content": "你好"}}]}
    MockClient.return_value.post = AsyncMock(return_value=mock_resp)
    asr = MiMoASR()
    result = asyncio.run(asr.transcribe_async(b"\x00" * 3200))
    assert result == ("你好", None, 0.0)


@patch("backend.asr.whisper.get_config")
def test_whisper_returns_tuple_with_language(mock_cfg):
    cfg = MagicMock(
        asr=MagicMock(
            whisper_model="base",
            whisper_device="cpu",
            whisper_model_path="models/faster-whisper-base",
        )
    )
    mock_cfg.return_value = cfg

    mock_model = MagicMock()
    mock_info = MagicMock(language="zh", language_probability=0.99)
    mock_seg = MagicMock(text="你好")
    mock_model.transcribe.return_value = ([mock_seg], mock_info)
    asr = WhisperASR()
    asr._model = mock_model
    result = asr.transcribe(b"\x00" * 3200)
    assert result == ("你好", "zh", 0.99)
    assert asr._model_path == "models/faster-whisper-base"

