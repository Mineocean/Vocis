"""v0.4 本地 ASR：三元组契约与配置默认值测试。"""

from backend.config import AppConfig


def test_config_whisper_model_path_default():
    cfg = AppConfig()
    assert cfg.asr.whisper_model_path == "models/faster-whisper-base"


def test_config_skip_translate_default_true():
    cfg = AppConfig()
    assert cfg.asr.skip_translate_when_same_lang is True
