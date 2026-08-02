"""v0.4 本地 ASR：三元组契约与配置默认值测试。"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.config import AppConfig
from backend.asr.base import ASREngine, ASRResult
from backend.asr.mock import MockASR
from backend.asr.mimo import MiMoASR
from backend.asr.whisper import WhisperASR
from backend.pipeline import SubtitlePipeline


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
def test_whisper_returns_tuple_with_language(mock_cfg, tmp_path):
    cfg = MagicMock(
        asr=MagicMock(
            whisper_model="base",
            whisper_device="cpu",
            whisper_model_path=str(tmp_path),
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
    assert asr._model_path == str(tmp_path).replace("\\", "/")


@patch("backend.pipeline.get_config")
def test_should_skip_translate_when_same_lang(mock_cfg):
    cfg = MagicMock()
    cfg.asr.skip_translate_when_same_lang = True
    cfg.translator.target_language = "中文"
    mock_cfg.return_value = cfg

    p = SubtitlePipeline.__new__(SubtitlePipeline)
    # 中文源 + 中文目标 → 跳过
    assert p._should_skip_translate("zh", 0.98) is True
    # 低置信度 → 不跳过（保守走翻译）
    assert p._should_skip_translate("zh", 0.3) is False
    # 英文源 + 中文目标 → 不跳过
    assert p._should_skip_translate("en", 0.95) is False


@patch("backend.pipeline.get_config")
def test_should_not_skip_when_disabled(mock_cfg):
    cfg = MagicMock()
    cfg.asr.skip_translate_when_same_lang = False
    cfg.translator.target_language = "中文"
    mock_cfg.return_value = cfg

    p = SubtitlePipeline.__new__(SubtitlePipeline)
    assert p._should_skip_translate("zh", 0.98) is False


def test_map_lang():
    assert SubtitlePipeline._map_lang("zh") == "中文"
    assert SubtitlePipeline._map_lang("en") == "英文"
    assert SubtitlePipeline._map_lang("ja") == "日文"
    assert SubtitlePipeline._map_lang(None) == "中文"
    assert SubtitlePipeline._map_lang("fr") == "中文"


def test_whisper_raises_when_model_missing():
    with pytest.raises(FileNotFoundError):
        WhisperASR(model_path="nonexistent-dir", device="cpu")


@patch("backend.asr.whisper.get_config")
def test_whisper_accepts_existing_path(mock_cfg, tmp_path):
    cfg = MagicMock(
        asr=MagicMock(
            whisper_model="base",
            whisper_device="cpu",
            whisper_model_path=str(tmp_path),
        )
    )
    mock_cfg.return_value = cfg
    asr = WhisperASR()
    assert asr._model_path == str(tmp_path).replace("\\", "/")
    assert asr._device == "cpu"


@patch("backend.asr.whisper.get_config")
@patch("backend.config.get_config")
def test_create_asr_falls_back_to_mimo(mock_cfg, mock_whisper_cfg):
    cfg = MagicMock(asr=MagicMock(backend="whisper", whisper_model_path="nonexistent-model-dir"))
    mock_cfg.return_value = cfg
    mock_whisper_cfg.return_value = cfg
    from backend.asr.registry import _REGISTRY

    with patch.dict(
        _REGISTRY,
        {
            "whisper": WhisperASR,
            "mimo": MagicMock(return_value="mimo-engine"),
        },
        clear=True,
    ):
        from backend.asr.registry import create_asr

        engine = create_asr()
    assert engine == "mimo-engine"

