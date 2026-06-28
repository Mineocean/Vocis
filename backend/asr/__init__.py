"""ASR backend package with plugin registry."""

from .base import ASREngine
from .registry import register_asr, create_asr, list_backends

# Import backends to trigger registration
from . import mimo, whisper, mock  # noqa: F401

__all__ = ["ASREngine", "register_asr", "create_asr", "list_backends", "mimo", "whisper", "mock"]
