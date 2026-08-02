"""sherpa-onnx streaming zipformer ASR backend (Chinese, local, real-time)."""

import logging
import sys
import threading
from pathlib import Path
from typing import Any

import numpy as np

from ..config import get_config
from .base import ASREngine, ASRResult
from .registry import register_asr

logger = logging.getLogger(__name__)


def _resolve_model_dir(model_path: str) -> Path:
    """解析模型目录：优先 _MEIPASS（PyInstaller 解压目录），否则相对/绝对路径。"""
    p = Path(model_path)
    if p.exists():
        return p
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bundled = Path(meipass) / model_path
        if bundled.exists():
            return bundled
    return p


@register_asr("sherpa")
class SherpaStreamingASR(ASREngine):
    """sherpa-onnx streaming zipformer ASR。

    中文实时流式识别，CPU int8 离线推理（RTF ≈ 0.04）。
    提供两套接口：
      - ASREngine.transcribe / transcribe_async：整段识别（兼容段落模式与测试）
      - 流式接口 push_audio / get_partial_text / end_stream：增量实时识别
    """

    is_streaming = True

    # sherpa zh-14M int8 模型固定文件名
    _ENCODER = "encoder-epoch-99-avg-1.int8.onnx"
    _DECODER = "decoder-epoch-99-avg-1.int8.onnx"
    _JOINER = "joiner-epoch-99-avg-1.int8.onnx"
    _TOKENS = "tokens.txt"

    def __init__(self, model_path: str | None = None):
        if model_path is None:
            model_path = get_config().asr.sherpa_model_path
        resolved = _resolve_model_dir(model_path)
        if not resolved.exists():
            raise FileNotFoundError(f"Sherpa model dir not found: {model_path}")
        self._model_dir = resolved
        self._recognizer: Any = None
        self._stream: Any = None
        self._lock = threading.RLock()

    def _load_model(self):
        if self._recognizer is not None:
            return
        try:
            import sherpa_onnx
        except ImportError:
            raise ImportError(
                "SHERPA backend requires sherpa-onnx:\n"
                "  pip install sherpa-onnx"
            )
        encoder = str(self._model_dir / self._ENCODER)
        decoder = str(self._model_dir / self._DECODER)
        joiner = str(self._model_dir / self._JOINER)
        tokens = str(self._model_dir / self._TOKENS)
        for f in (encoder, decoder, joiner, tokens):
            if not Path(f).exists():
                raise FileNotFoundError(f"Sherpa model file missing: {f}")
        self._recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=tokens,
            encoder=encoder,
            decoder=decoder,
            joiner=joiner,
            num_threads=8,
            sample_rate=16000,
            feature_dim=80,
            enable_endpoint_detection=False,
            decoding_method="greedy_search",
            provider="cpu",
        )
        logger.info("Sherpa streaming model loaded: %s", self._model_dir)

    # ── 流式接口 ────────────────────────────────────

    def start_stream(self):
        """开始一个新的流式识别会话。"""
        with self._lock:
            self._load_model()
            if self._recognizer is None:
                raise RuntimeError("Sherpa model failed to load")
            self._stream = self._recognizer.create_stream()

    def push_audio(self, pcm: bytes):
        """推入 int16 PCM 音频块，立即增量解码。"""
        with self._lock:
            if self._stream is None:
                self.start_stream()
            samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
            if len(samples) == 0:
                return
            self._stream.accept_waveform(16000, samples)
            if self._recognizer is None:
                return
            while self._recognizer.is_ready(self._stream):
                self._recognizer.decode_stream(self._stream)

    def get_partial_text(self) -> str:
        """返回当前流式识别的部分结果文本。"""
        with self._lock:
            if self._stream is None or self._recognizer is None:
                return ""
            try:
                return self._recognizer.get_result(self._stream)
            except Exception as e:
                logger.warning("Sherpa get_partial_text failed: %s", e)
                return ""

    def end_stream(self) -> str:
        """结束当前流，返回最终识别文本。"""
        with self._lock:
            if self._stream is None or self._recognizer is None:
                return ""
            try:
                self._stream.input_finished()
                while self._recognizer.is_ready(self._stream):
                    self._recognizer.decode_stream(self._stream)
                text = self._recognizer.get_result(self._stream)
            except Exception as e:
                logger.warning("Sherpa end_stream failed: %s", e)
                text = ""
            self._stream = None
            return text

    # ── ASREngine 接口 ──────────────────────────────

    def transcribe(self, audio_pcm: bytes) -> ASRResult | None:
        """整段识别（兼容段落模式/测试）：一次性喂入全部 PCM。"""
        if not audio_pcm:
            return None
        self._load_model()
        if self._recognizer is None:
            raise RuntimeError("Sherpa model failed to load")
        stream = self._recognizer.create_stream()
        samples = np.frombuffer(audio_pcm, dtype=np.int16).astype(np.float32) / 32768.0
        if len(samples) == 0:
            return None
        stream.accept_waveform(16000, samples)
        stream.input_finished()
        while self._recognizer.is_ready(stream):
            self._recognizer.decode_stream(stream)
        text = self._recognizer.get_result(stream).strip()
        if text:
            logger.debug("Sherpa ASR: %s", text)
            return text, "zh", 1.0
        return None

    def set_language(self, language: str):
        # sherpa zh-14M 为固定中文模型，语言不可切换
        pass

    def close(self):
        self._stream = None
        self._recognizer = None
