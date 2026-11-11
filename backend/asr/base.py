"""ASR engine abstract base class."""

import asyncio
from abc import ABC, abstractmethod

# language 允许 None：部分云端后端（MiMo 等）不返回检测语言
ASRResult = tuple[str, str | None, float]


class ASREngine(ABC):
    """Abstract base class for ASR engines.

    transcribe 返回 `(text, language, probability) | None`：
      - text: 识别文本
      - language: 检测到的源语言代码（zh/en/ja；无法检测返回 None）
      - probability: 语言置信度 0.0~1.0

    流式后端（Sherpa）把 `is_streaming` 设为 True，并实现
    start_stream / push_audio / get_partial_text / end_stream。
    """

    backend: str = ""

    #: True 表示实现了下面的流式接口
    is_streaming: bool = False

    @abstractmethod
    def transcribe(self, audio_pcm: bytes) -> ASRResult | None:
        """Convert PCM audio to text with detected language."""
        ...

    async def transcribe_async(self, audio_pcm: bytes) -> ASRResult | None:
        """Async version of transcribe. Runs sync version in thread pool."""
        return await asyncio.to_thread(self.transcribe, audio_pcm)

    # ── 流式接口（非流式后端不应调用） ──────────────

    def start_stream(self):
        """开始一个新的流式识别会话。"""
        raise NotImplementedError(f"{type(self).__name__} is not a streaming ASR")

    def push_audio(self, pcm: bytes):
        """推入一段 int16 PCM 音频。"""
        raise NotImplementedError(f"{type(self).__name__} is not a streaming ASR")

    def get_partial_text(self) -> str:
        """返回当前流式识别的部分结果。"""
        return ""

    def end_stream(self) -> str:
        """结束当前流并返回最终文本。"""
        return ""

    def set_language(self, language: str):
        """Set recognition language at runtime."""

    def close(self):
        """Release resources."""
