"""
配置管理 —— 从 .env 文件和环境变量加载配置。

优先级：环境变量 > .env 文件 > 提供商预设默认值 > 硬编码默认值

环境变量命名约定：
- 翻译：TRANSLATOR_PROVIDER / TRANSLATOR_API_KEY / TRANSLATOR_BASE_URL / TRANSLATOR_MODEL
  （未设置时回退到旧版 DEEPSEEK_*，保证老 .env 不需要改）
- 语音识别：ASR_BACKEND / ASR_API_KEY / ASR_BASE_URL / ASR_MODEL
  （云端后端未设置时回退到该后端的旧版 *_API_KEY 等变量）
- 说话人分离：DIARIZATION_*
"""

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import dotenv

from .providers.presets import LOCAL_ASR_BACKENDS, asr_preset, translation_preset


def app_dir() -> Path:
    """应用根目录：PyInstaller 打包后为 exe 所在目录，开发时为项目根目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


_env_path = app_dir() / ".env"
if _env_path.exists():
    dotenv.load_dotenv(_env_path)


def _env(key: str, default: str = "") -> str:
    if not key:
        return default
    return os.getenv(key, default)


def _env_bool(key: str, default: bool) -> bool:
    return _env(key, "true" if default else "false").strip().lower() in ("1", "true", "yes", "on")


def _env_int(key: str, default: int) -> int:
    try:
        return int(_env(key, str(default)))
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(_env(key, str(default)))
    except ValueError:
        return default


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
    """ASR 配置（本地 whisper/sherpa，云端 MiMo / OpenAI 兼容 /audio/transcriptions）"""

    backend: str = field(default_factory=lambda: _env("ASR_BACKEND", "mimo").lower())
    language: str = field(default_factory=lambda: _env("SOURCE_LANGUAGE", "auto"))
    api_key: str = field(default_factory=lambda: _env("ASR_API_KEY"))
    base_url: str = field(default_factory=lambda: _env("ASR_BASE_URL"))
    model: str = field(default_factory=lambda: _env("ASR_MODEL"))
    whisper_model: str = field(default_factory=lambda: _env("WHISPER_MODEL", "tiny"))  # tiny/base/small/medium
    whisper_device: str = field(default_factory=lambda: _env("WHISPER_DEVICE", "cuda"))  # cuda / cpu
    whisper_model_path: str = field(
        default_factory=lambda: _env("WHISPER_MODEL_PATH", "models/faster-whisper-base")
    )
    sherpa_model_path: str = field(
        default_factory=lambda: _env("SHERPA_MODEL_PATH", "models/sherpa-streaming-zh-14M")
    )
    skip_translate_when_same_lang: bool = field(
        default_factory=lambda: _env_bool("SKIP_TRANSLATE_SAME_LANG", True)
    )

    def __post_init__(self):
        # 云端后端：把通用 ASR_* 缺失项填成预设/旧版变量，保证老 .env 继续可用
        preset = asr_preset(self.backend)
        if preset.get("protocol") == "local":
            return
        if not self.api_key:
            self.api_key = _env(preset.get("key_env", ""))
        if not self.base_url:
            self.base_url = _env(preset.get("base_url_env", "")) or preset.get("base_url", "")
        if not self.model:
            self.model = _env(preset.get("model_env", "")) or preset.get("default_model", "")

    @property
    def is_local(self) -> bool:
        return self.backend in LOCAL_ASR_BACKENDS

    @property
    def protocol(self) -> str:
        return asr_preset(self.backend).get("protocol", "openai")


@dataclass
class TranslatorConfig:
    """翻译配置 —— 任意 OpenAI 兼容聊天补全端点"""

    provider: str = field(default_factory=lambda: _env("TRANSLATOR_PROVIDER", "deepseek").lower())
    api_key: str = field(default_factory=lambda: _env("TRANSLATOR_API_KEY"))
    base_url: str = field(default_factory=lambda: _env("TRANSLATOR_BASE_URL"))
    model: str = field(default_factory=lambda: _env("TRANSLATOR_MODEL"))
    target_language: str = field(default_factory=lambda: _env("TARGET_LANGUAGE", "中文"))
    temperature: float = field(default_factory=lambda: _env_float("TRANSLATOR_TEMPERATURE", 0.1))
    max_tokens: int = field(default_factory=lambda: _env_int("TRANSLATOR_MAX_TOKENS", 512))

    def __post_init__(self):
        preset = translation_preset(self.provider)
        if not self.api_key:
            self.api_key = _env(preset.get("key_env", ""))
        if not self.base_url:
            self.base_url = _env(preset.get("base_url_env", "")) or preset.get("base_url", "")
        if not self.model:
            self.model = _env(preset.get("model_env", "")) or preset.get("default_model", "")

    @property
    def preset(self) -> dict:
        return translation_preset(self.provider)

    @property
    def requires_key(self) -> bool:
        return bool(self.preset.get("requires_key", True))

    @property
    def extra_body(self) -> dict:
        """提供商特有的请求体字段（如 DeepSeek 的 thinking 开关）。"""
        return dict(self.preset.get("extra_body", {}))


@dataclass
class DiarizationConfig:
    """说话人分离（说话人聚类）配置"""

    enabled: bool = field(default_factory=lambda: _env_bool("DIARIZATION_ENABLED", False))
    # sherpa = 神经说话人嵌入（CAM++，首次使用自动下载 ~27MB 模型，推荐）
    # cluster = 零依赖 MFCC 统计聚类（无需下载，精度较低）
    backend: str = field(default_factory=lambda: _env("DIARIZATION_BACKEND", "sherpa").lower())
    # 最多区分多少个说话人；超过后归入最相近的已有人声
    max_speakers: int = field(default_factory=lambda: _env_int("DIARIZATION_MAX_SPEAKERS", 4))
    # 余弦相似度阈值：越高越"粘"旧说话人（同一人不易分裂），越低越容易分出新人
    # 留空 = 使用该后端的实测默认值（sherpa 0.55 / cluster 0.80）
    threshold: float | None = field(
        default_factory=lambda: _env_float("DIARIZATION_THRESHOLD", 0.0) or None
    )
    # 太短的语音段不参与判人（容易误判），但仍会沿用上一段的说话人
    min_seconds: float = field(default_factory=lambda: _env_float("DIARIZATION_MIN_SECONDS", 0.6))
    # 自定义说话人嵌入模型路径（留空自动找/下载）
    model_path: str = field(default_factory=lambda: _env("DIARIZATION_MODEL_PATH"))


@dataclass
class DisplayConfig:
    """字幕显示配置"""

    font_size: int = field(default_factory=lambda: _env_int("FONT_SIZE", 16))
    subtitle_duration_ms: int = field(default_factory=lambda: _env_int("SUBTITLE_DURATION", 5000))  # 0=常驻
    subtitle_position: str = field(default_factory=lambda: _env("SUBTITLE_POSITION", "bottom"))
    subtitle_screen: str = field(default_factory=lambda: _env("SUBTITLE_SCREEN", "0"))
    stream_translation: bool = field(default_factory=lambda: _env_bool("STREAM_TRANSLATION", True))
    speaker_colors: bool = field(default_factory=lambda: _env_bool("SPEAKER_COLORS", True))


@dataclass
class AppConfig:
    """应用总配置"""

    asr: ASRConfig = field(default_factory=ASRConfig)
    translator: TranslatorConfig = field(default_factory=TranslatorConfig)
    diarization: DiarizationConfig = field(default_factory=DiarizationConfig)
    display: DisplayConfig = field(default_factory=DisplayConfig)
    source_language: str = field(default_factory=lambda: _env("SOURCE_LANGUAGE", "auto"))
    target_language: str = field(default_factory=lambda: _env("TARGET_LANGUAGE", "中文"))
    cache_window_seconds: int = field(default_factory=lambda: _env_int("CACHE_WINDOW_SECONDS", 30))
    audio_device: str = field(default_factory=lambda: _env("AUDIO_DEVICE", "auto"))
    sample_rate: int = 16000
    vad_threshold: float = field(default_factory=lambda: _env_float("VAD_THRESHOLD", 0.5))
    vad_model_path: str = field(default_factory=lambda: _env("VAD_MODEL_PATH", ""))
    speech_padding_ms: int = field(default_factory=lambda: _env_int("VAD_PADDING_MS", 400))
    min_speech_duration_ms: int = field(default_factory=lambda: _env_int("VAD_MIN_SPEECH_MS", 300))
    silence_duration_ms: int = field(default_factory=lambda: _env_int("VAD_SILENCE_MS", 350))
    max_speech_duration_ms: int = field(default_factory=lambda: _env_int("VAD_MAX_SPEECH_MS", 5000))

    # ── 增量实时识别（方案 D：滚动累积 + 文本差分） ──
    incremental_enabled: bool = field(default_factory=lambda: _env_bool("INCREMENTAL_ENABLED", True))
    incremental_interval: float = field(default_factory=lambda: _env_float("INCREMENTAL_INTERVAL", 1.2))
    incremental_max_seconds: float = field(default_factory=lambda: _env_float("INCREMENTAL_MAX_SECONDS", 5.0))
    stream_sentence_chars: int = field(default_factory=lambda: _env_int("STREAM_SENTENCE_CHARS", 12))

    def needs_setup(self) -> bool:
        """首次运行是否需要向导：翻译是核心功能，缺 Key 且提供商要求 Key 就需要。"""
        if not env_path().exists():
            return True
        return self.translator.requires_key and not self.translator.api_key


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
