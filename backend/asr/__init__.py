"""ASR backend package with plugin registry."""

# Import backends to trigger registration
from . import mimo, mock, openai_compat, sherpa, whisper
from .base import ASREngine
from .registry import create_asr, list_backends, register_asr

__all__ = [
    "ASREngine",
    "create_asr",
    "list_backends",
    "mimo",
    "mock",
    "openai_compat",
    "register_asr",
    "sherpa",
    "whisper",
]
