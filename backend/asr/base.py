"""ASR engine abstract base class."""

import asyncio
from abc import ABC, abstractmethod


class ASREngine(ABC):
    """Abstract base class for ASR engines."""

    @abstractmethod
    def transcribe(self, audio_pcm: bytes) -> str | None:
        """Convert PCM audio to text."""
        ...

    async def transcribe_async(self, audio_pcm: bytes) -> str | None:
        """Async version of transcribe. Runs sync version in thread pool."""
        return await asyncio.to_thread(self.transcribe, audio_pcm)

    def set_language(self, language: str):
        """Set recognition language at runtime."""

    def close(self):
        """Release resources."""
