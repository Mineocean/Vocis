"""Local faster-whisper ASR backend."""

import logging
from typing import Optional

import numpy as np

from .base import ASREngine
from .registry import register_asr
from ..config import get_config

logger = logging.getLogger(__name__)


@register_asr("whisper")
class WhisperASR(ASREngine):
    """Local faster-whisper model (NVIDIA GPU acceleration supported)."""

    def __init__(self, model_size: Optional[str] = None, device: Optional[str] = None):
        if model_size is None or device is None:
            cfg = get_config()
            model_size = model_size or cfg.asr.whisper_model
            device = device or cfg.asr.whisper_device
        self._model = None
        self._model_size = model_size
        self._device = device
        self._language: Optional[str] = None

    def _load_model(self):
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel

            device = self._device
            compute = "int8"
            if device in ("cuda", "auto"):
                try:
                    import torch
                    if torch.cuda.is_available():
                        compute = "float16"
                        device = "cuda"
                        logger.info("Using CUDA GPU acceleration (float16)")
                    elif device == "cuda":
                        logger.warning("CUDA not available, falling back to CPU")
                        device = "cpu"
                    else:
                        logger.info("CUDA not available, using CPU")
                        device = "cpu"
                except ImportError:
                    logger.warning("torch not installed, falling back to CPU")
                    device = "cpu"

            logger.info("Loading Whisper model: %s (device=%s, compute=%s)",
                        self._model_size, device, compute)
            self._model = WhisperModel(
                self._model_size,
                device=device,
                compute_type=compute,
            )
            logger.info("Whisper model loaded")
        except ImportError:
            raise ImportError(
                "WHISPER backend requires faster-whisper:\n"
                "  pip install faster-whisper"
            )
        except Exception as e:
            logger.error("Failed to load Whisper model: %s", e)
            raise

    def set_language(self, language: str):
        self._language = None if language == "auto" else language

    def transcribe(self, audio_pcm: bytes) -> Optional[str]:
        if not audio_pcm:
            return None

        self._load_model()
        if self._model is None:
            raise RuntimeError("Whisper model failed to load")

        audio_np = np.frombuffer(audio_pcm, dtype=np.int16).astype(np.float32) / 32768.0

        max_samples = 16000 * 15
        if len(audio_np) > max_samples:
            audio_np = audio_np[:max_samples]

        try:
            segments, info = self._model.transcribe(
                audio_np,
                language=self._language,
                beam_size=1,
                vad_filter=False,
            )
            text = " ".join(seg.text.strip() for seg in segments)
            if text:
                logger.debug("Whisper ASR: %s", text)
                return text
            return None
        except Exception as e:
            logger.error("Whisper recognition failed: %s", e)
            return None

    def close(self):
        self._model = None
