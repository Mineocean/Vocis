"""Local faster-whisper ASR backend."""

import logging
import sys
from pathlib import Path

import numpy as np

from ..config import get_config
from .base import ASREngine, ASRResult
from .registry import register_asr

logger = logging.getLogger(__name__)

# 繁体→简体转换器（惰性初始化，opencc 缺失时降级为原文）
_OPENCC: object | None = None
_OPENCC_READY = False


def _to_simplified(text: str) -> str:
    """将繁体中文转换为简体；opencc 不可用时原样返回。"""
    global _OPENCC, _OPENCC_READY
    if not text or not any("\u4e00" <= c <= "\u9fff" for c in text):
        return text
    if not _OPENCC_READY:
        try:
            from opencc import OpenCC
            _OPENCC = OpenCC("t2s")
        except Exception:
            logger.warning("opencc not available, keeping traditional Chinese")
            _OPENCC = None
        finally:
            _OPENCC_READY = True
    if _OPENCC is not None:
        try:
            return _OPENCC.convert(text)
        except Exception:
            return text
    return text


def _resolve_model_path(model_path: str) -> Path:
    """解析模型路径：优先 _MEIPASS（PyInstaller 解压目录），否则相对/绝对路径。"""
    p = Path(model_path)
    if p.exists():
        return p
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bundled = Path(meipass) / model_path
        if bundled.exists():
            return bundled
    return p


@register_asr("whisper")
class WhisperASR(ASREngine):
    """Local faster-whisper model (NVIDIA GPU acceleration supported)."""

    def __init__(self, model_path: str | None = None, device: str | None = None):
        if model_path is None or device is None:
            cfg = get_config()
            model_path = model_path or cfg.asr.whisper_model_path
            device = device or cfg.asr.whisper_device
        # 校验模型目录存在，缺失时抛异常（由 create_asr 回退 MiMo）
        resolved = _resolve_model_path(model_path)
        if not resolved.exists():
            raise FileNotFoundError(f"Whisper model path not found: {model_path}")
        self._model = None
        self._model_path = str(resolved).replace("\\", "/")
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
                text = _to_simplified(text)
                logger.debug("Whisper ASR: %s", text)
                return text.strip(), info.language, float(info.language_probability)
            return None
        except Exception as e:
            logger.error("Whisper recognition failed: %s", e)
            return None

    def close(self):
        self._model = None
