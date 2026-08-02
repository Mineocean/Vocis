"""ASR engine abstract base class."""

import asyncio
from abc import ABC, abstractmethod

ASRResult = tuple[str, str, float]


class ASREngine(ABC):
    """Abstract base class for ASR engines.

    transcribe 返回 `(text, language, probability) | None`：
      - text: 识别文本
      - language: 检测到的源语言代码（zh/en/ja；无法检测返回 None）
      - probability: 语言置信度 0.0~1.0
    """

    @abstractmethod
    def transcribe(self, audio_pcm: bytes) -> ASRResult | None:
        """Convert PCM audio to text with detected language."""
        ...

    async def transcribe_async(self, audio_pcm: bytes) -> ASRResult | None:
        """Async version of transcribe. Runs sync version in thread pool."""
        return await asyncio.to_thread(self.transcribe, audio_pcm)

    def set_language(self, language: str):
        """Set recognition language at runtime."""

    def close(self):
        """Release resources."""
