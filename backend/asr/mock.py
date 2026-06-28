"""Mock ASR backend for testing."""

import logging
from typing import Optional

from .base import ASREngine
from .registry import register_asr

logger = logging.getLogger(__name__)


@register_asr("mock")
class MockASR(ASREngine):
    """Mock ASR - returns preset texts, for testing translation/GUI pipeline."""

    _mock_texts = [
        "Hello, how are you today?",
        "The weather is beautiful outside.",
        "I think artificial intelligence is fascinating.",
        "What time does the meeting start tomorrow?",
        "Could you please pass me the salt?",
        "This is a test of the emergency broadcast system.",
        "Machine learning has changed the world dramatically.",
        "Let's grab some coffee after work.",
    ]

    def __init__(self):
        self._counter = 0

    def transcribe(self, audio_pcm: bytes) -> Optional[str]:
        if not audio_pcm:
            return None
        text = self._mock_texts[self._counter % len(self._mock_texts)]
        self._counter += 1
        logger.info("Mock ASR: %s", text)
        return text
