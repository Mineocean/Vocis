"""
配置管理 —— 从 .env 文件和环境变量加载配置。

优先级：环境变量 > .env 文件 > 默认值
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

import dotenv

_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    dotenv.load_dotenv(_env_path)


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


@dataclass
class ASRConfig:
    """ASR 配置（MiMo 云端 / Whisper 本地）"""
    backend: str = field(default_factory=lambda: _env("ASR_BACKEND", "whisper"))  # whisper | mimo | mock
    api_key: str = field(default_factory=lambda: _env("MIMO_API_KEY"))
    base_url: str = field(default_factory=lambda: _env("MIMO_BASE_URL", "https://api.xiaomimimo.com/v1"))
    model: str = field(default_factory=lambda: _env("MIMO_ASR_MODEL", "mimo-v2.5-asr"))
    language: str = field(default_factory=lambda: _env("SOURCE_LANGUAGE", "auto"))
    whisper_model: str = field(default_factory=lambda: _env("WHISPER_MODEL", "tiny"))  # tiny/base/small/medium
    whisper_device: str = field(default_factory=lambda: _env("WHISPER_DEVICE", "cuda"))  # cuda / cpu


@dataclass
class TranslatorConfig:
    """DeepSeek 翻译配置"""
    api_key: str = field(default_factory=lambda: _env("DEEPSEEK_API_KEY"))
    base_url: str = field(default_factory=lambda: _env("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    model: str = field(default_factory=lambda: _env("DEEPSEEK_MODEL", "deepseek-v4-pro"))
    target_language: str = field(default_factory=lambda: _env("TARGET_LANGUAGE", "中文"))


@dataclass
class DisplayConfig:
    """字幕显示配置"""
    font_size: int = field(default_factory=lambda: int(_env("FONT_SIZE", "16")))
    subtitle_duration_ms: int = field(default_factory=lambda: int(_env("SUBTITLE_DURATION", "5000")))  # 0=常驻
    subtitle_position: str = field(default_factory=lambda: _env("SUBTITLE_POSITION", "bottom"))
    subtitle_screen: str = field(default_factory=lambda: _env("SUBTITLE_SCREEN", "0"))


@dataclass
class AppConfig:
    """应用总配置"""
    asr: ASRConfig = field(default_factory=ASRConfig)
    translator: TranslatorConfig = field(default_factory=TranslatorConfig)
    display: DisplayConfig = field(default_factory=DisplayConfig)
    source_language: str = field(default_factory=lambda: _env("SOURCE_LANGUAGE", "auto"))
    target_language: str = field(default_factory=lambda: _env("TARGET_LANGUAGE", "中文"))
    cache_window_seconds: int = field(default_factory=lambda: int(_env("CACHE_WINDOW_SECONDS", "30")))
    audio_device: str = field(default_factory=lambda: _env("AUDIO_DEVICE", "auto"))
    sample_rate: int = 16000
    vad_aggressiveness: int = 2
    vad_frame_ms: int = 30
    speech_padding_ms: int = 400
    min_speech_duration_ms: int = 300
    silence_duration_ms: int = 600


def get_config() -> AppConfig:
    """获取全局配置单例"""
    return AppConfig()
