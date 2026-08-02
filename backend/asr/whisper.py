"""Local faster-whisper ASR backend."""

import logging
from pathlib import Path

import numpy as np

from ..config import get_config
from .base import ASREngine, ASRResult
from .registry import register_asr

logger = logging.getLogger(__name__)


@register_asr("whisper")
class WhisperASR(ASREngine):
    """Local faster-whisper model (NVIDIA GPU acceleration supported)."""

    def __init__(self, model_path: str | None = None, device: str | None = None):
        if model_path is None or device is None:
            cfg = get_config()
            model_path = model_path or cfg.asr.whisper_model_path
            device = device or cfg.asr.whisper_device
        # 校验模型目录存在，缺失时抛异常（由 create_asr 回退 MiMo）
        if not Path(model_path).exists():
            raise FileNotFoundError(f"Whisper model path not found: {model_path}")
        self._model = None
        self._model_path = model_path
        self._device = device
        self._language: str | None = None

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
                        self._model_path, device, compute)
            self._model = WhisperModel(
                self._model_path,
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

    def transcribe(self, audio_pcm: bytes) -> ASRResult | None:
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
                return text.strip(), info.language, float(info.language_probability)
            return None
        except Exception as e:
            logger.error("Whisper recognition failed: %s", e)
            return None

    def close(self):
        self._model = None
