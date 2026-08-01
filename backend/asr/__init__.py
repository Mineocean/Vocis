"""ASR backend package with plugin registry."""

# Import backends to trigger registration
from . import mimo, mock, whisper
from .base import ASREngine
from .registry import create_asr, list_backends, register_asr

__all__ = ["ASREngine", "create_asr", "list_backends", "mimo", "mock", "register_asr", "whisper"]
