"""
配置管理 —— 从 .env 文件和环境变量加载配置。

优先级：环境变量 > .env 文件 > 默认值
"""

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import dotenv


def app_dir() -> Path:
    """应用根目录：PyInstaller 打包后为 exe 所在目录，开发时为项目根目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


_env_path = app_dir() / ".env"
if _env_path.exists():
    dotenv.load_dotenv(_env_path)


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def env_path() -> Path:
    """返回 .env 文件路径"""
    return _env_path


def read_env_file(path: Path | None = None) -> dict[str, str]:
    """读取 .env 文件为 dict，保留注释和格式信息以外的键值对"""
    p = path or _env_path
    env: dict[str, str] = {}
    if not p.exists():
        return env
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def write_env_file(env: dict[str, str], path: Path | None = None):
    """写入 .env 文件，保留原有注释和格式"""
    p = path or _env_path
    if not p.exists():
        lines = [f"{k}={v}\n" for k, v in env.items()]
        p.write_text("".join(lines), encoding="utf-8")
        return
    existing = p.read_text(encoding="utf-8").splitlines()
    updated_keys: set[str] = set()
    new_lines: list[str] = []
    for line in existing:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k = stripped.split("=")[0].strip()
            if k in env:
                new_lines.append(f"{k}={env[k]}")
                updated_keys.add(k)
                continue
        new_lines.append(line)
    for k, v in env.items():
        if k not in updated_keys:
            new_lines.append(f"{k}={v}")
    content = "\n".join(new_lines)
    if not content.endswith("\n"):
        content += "\n"
    p.write_text(content, encoding="utf-8")


@dataclass
class ASRConfig:
    """ASR 配置（MiMo 云端 / Whisper 本地）"""
    backend: str = field(default_factory=lambda: _env("ASR_BACKEND", "mimo"))  # whisper | mimo | mock
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
    stream_translation: bool = field(default_factory=lambda: _env("STREAM_TRANSLATION", "true").lower() == "true")


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
    vad_threshold: float = field(default_factory=lambda: float(_env("VAD_THRESHOLD", "0.5")))
    vad_model_path: str = field(default_factory=lambda: _env("VAD_MODEL_PATH", ""))
    speech_padding_ms: int = field(default_factory=lambda: int(_env("VAD_PADDING_MS", "400")))
    min_speech_duration_ms: int = field(default_factory=lambda: int(_env("VAD_MIN_SPEECH_MS", "300")))
    silence_duration_ms: int = field(default_factory=lambda: int(_env("VAD_SILENCE_MS", "350")))
    max_speech_duration_ms: int = field(default_factory=lambda: int(_env("VAD_MAX_SPEECH_MS", "5000")))

    # ── 增量实时识别（方案 D：滚动累积 + 文本差分） ──
    incremental_enabled: bool = field(default_factory=lambda: _env("INCREMENTAL_ENABLED", "true").lower() == "true")
    incremental_interval: float = field(default_factory=lambda: float(_env("INCREMENTAL_INTERVAL", "1.2")))
    incremental_max_seconds: float = field(default_factory=lambda: float(_env("INCREMENTAL_MAX_SECONDS", "5.0")))


_config_instance: AppConfig | None = None


def get_config() -> AppConfig:
    """获取全局配置单例"""
    global _config_instance
    if _config_instance is None:
        _config_instance = AppConfig()
    return _config_instance


def reload_config() -> AppConfig:
    """重新加载配置（用于 .env 更新后）"""
    global _config_instance
    _config_instance = AppConfig()
    return _config_instance
