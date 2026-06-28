"""ASR engine abstract base class."""

from abc import ABC, abstractmethod
from typing import Optional


class ASREngine(ABC):
    """Abstract base class for ASR engines."""

    @abstractmethod
    def transcribe(self, audio_pcm: bytes) -> Optional[str]:
        """Convert PCM audio to text."""
        ...

    async def transcribe_async(self, audio_pcm: bytes) -> Optional[str]:
        """Async version of transcribe. Default calls sync version."""
        return self.transcribe(audio_pcm)

    def set_language(self, language: str):
        """Set recognition language at runtime."""
        pass

    def close(self):
        """Release resources."""
        pass
