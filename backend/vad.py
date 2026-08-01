"""
VAD — Voice Activity Detection using Silero VAD (ONNX).

Splits continuous audio stream into speech segments using Silero VAD model.
Detects speech/silence boundaries and outputs complete speech segments.
"""

import logging
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort

from .config import get_config

logger = logging.getLogger(__name__)

DEFAULT_MODEL_URL = "https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx"


class VoiceActivityDetector:
    """Silero VAD-based voice activity detector."""

    def __init__(self):
        cfg = get_config()
        self.sample_rate = cfg.sample_rate  # 16000
        self.threshold = cfg.vad_threshold
        self.speech_padding_ms = cfg.speech_padding_ms
        self.min_speech_duration_ms = cfg.min_speech_duration_ms
        self.silence_duration_ms = cfg.silence_duration_ms
        self.max_speech_duration_ms = cfg.max_speech_duration_ms

        self._session: ort.InferenceSession | None = None
        self._model_path = self._resolve_model_path(cfg.vad_model_path)

        # State
        self._buffer: list[np.ndarray] = []
        self._speech_started = False
        self._silence_start: float | None = None
        self._speech_duration_ms = 0

        # Pre-speech buffer (padding)
        self._pre_speech_buffer: list[np.ndarray] = []
        self._pre_speech_max_frames = int(self.speech_padding_ms / 30)  # ~30ms per call

        # 余数缓冲：承接上一 chunk 末尾不足一个窗口的采样，避免音频损失
        self._remainder = np.zeros(0, dtype=np.float32)

        # Silero VAD internal state (SR=16000)
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        # 前 64 采样 context：官方 Silero v5 ONNX 需要拼接 context，输入为 64+512=576
        self._context = np.zeros((1, 64), dtype=np.float32)

    def _resolve_model_path(self, configured_path: str) -> Path:
        if configured_path and Path(configured_path).exists():
            return Path(configured_path)

        # Default: assets/models/silero_vad.onnx
        default = Path(__file__).parent.parent / "assets" / "models" / "silero_vad.onnx"
        if default.exists():
            return default

        # Fallback: download to cache
        cache_dir = Path.home() / ".cache" / "vocis"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cached = cache_dir / "silero_vad.onnx"
        if cached.exists():
            return cached

        logger.info("Downloading Silero VAD model to %s", cached)
        self._download_model(cached)
        return cached

    def _download_model(self, dest: Path):
        """Download Silero VAD ONNX model."""
        import httpx
        try:
            resp = httpx.get(DEFAULT_MODEL_URL, follow_redirects=True, timeout=60)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
            logger.info("Silero VAD model downloaded: %s", dest)
        except Exception as e:
            logger.error("Failed to download Silero VAD model: %s", e)
            raise

    def _ensure_model(self):
        """Lazy-load ONNX model."""
        if self._session is not None:
            return
        logger.info("Loading Silero VAD model: %s", self._model_path)
        self._session = ort.InferenceSession(
            str(self._model_path),
            providers=["CPUExecutionProvider"],
        )
        logger.info("Silero VAD model loaded")

    def _reset_state(self):
        """Reset internal LSTM state."""
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, 64), dtype=np.float32)

    def process_chunk(self, audio_chunk: np.ndarray) -> list[bytes]:
        """
        Process an audio chunk (~100ms float32), return completed speech segments.

        :param audio_chunk: float32 numpy array, mono, 16kHz
        :return: list of completed speech segments (PCM int16 bytes)
        """
        self._ensure_model()
        segments = []

        # 把上一 chunk 的余数拼接进来，避免采样丢失
        audio_chunk = np.concatenate((self._remainder, audio_chunk)) if self._remainder.size else audio_chunk

        # Silero VAD processes at 16kHz, window size 512 samples (~32ms)
        window_size = 512
        n_windows = len(audio_chunk) // window_size
        self._remainder = audio_chunk[n_windows * window_size:].copy()

        for i in range(n_windows):
            start = i * window_size
            window = audio_chunk[start:start + window_size]
            if len(window) < window_size:
                break

            # Run Silero VAD inference
            sr_array = np.array([self.sample_rate], dtype=np.int64)
            # 拼接前 64 采样 context（官方 Silero v5 ONNX 协议，输入 64+512=576）
            input_tensor = np.concatenate((self._context, window.reshape(1, -1)), axis=1).astype(np.float32)

            try:
                output, self._state = self._session.run(None, {
                    "input": input_tensor,
                    "state": self._state,
                    "sr": sr_array,
                })
                speech_prob = float(output[0][0])
            except Exception:
                speech_prob = 0.0
            # 更新 context：取本次输入末尾 64 采样
            self._context = input_tensor[:, -64:].copy()

            is_speech = speech_prob >= self.threshold
            now = time.monotonic()

            if is_speech:
                if not self._speech_started:
                    # Speech starts: prepend buffered frames
                    self._buffer.extend(self._pre_speech_buffer)
                    self._pre_speech_buffer.clear()
                    self._speech_started = True
                    self._speech_duration_ms = 0
                    self._silence_start = None

                self._buffer.append(window.copy())
                self._speech_duration_ms += int(window_size / self.sample_rate * 1000)

                # 防止连续说话时语音段无限累积：达到最大时长即使没有静音也强制切段
                if self._speech_duration_ms >= self.max_speech_duration_ms:
                    audio_data = self._concat_segments(self._buffer)
                    segments.append(audio_data)
                    logger.debug("Speech segment force-cut at max duration: %d ms", self._speech_duration_ms)
                    self._buffer.clear()
                    self._speech_started = False
                    self._silence_start = None
                    # 注意：连续语音中强制切段，不重置 VAD state/context，保持语音连贯性
            else:
                if self._speech_started:
                    if self._silence_start is None:
                        self._silence_start = now
                    self._buffer.append(window.copy())  # Keep silence frames for trailing padding

                    silence_elapsed = (now - self._silence_start) * 1000
                    if silence_elapsed >= self.silence_duration_ms:
                        # Silence exceeded threshold — speech segment complete
                        if self._speech_duration_ms >= self.min_speech_duration_ms:
                            audio_data = self._concat_segments(self._buffer)
                            segments.append(audio_data)
                            logger.debug("Speech segment: %d ms", self._speech_duration_ms)
                        else:
                            logger.debug("Speech too short (<%dms), discarded", self.min_speech_duration_ms)

                        self._buffer.clear()
                        self._speech_started = False
                        self._silence_start = None
                        self._reset_state()
                else:
                    # Silence: keep in pre-speech buffer
                    self._pre_speech_buffer.append(window.copy())
                    if len(self._pre_speech_buffer) > self._pre_speech_max_frames:
                        self._pre_speech_buffer.pop(0)

        return segments

    def _concat_segments(self, frames: list[np.ndarray]) -> bytes:
        """Convert float32 frames to int16 PCM bytes."""
        audio = np.concatenate(frames)
        audio = np.clip(audio, -1.0, 1.0)
        return (audio * 32767).astype(np.int16).tobytes()

    def flush(self) -> list[bytes]:
        """Flush: output any incomplete speech segment in the buffer."""
        segments = []
        if self._speech_started and self._speech_duration_ms >= self.min_speech_duration_ms:
            audio_data = self._concat_segments(self._buffer)
            segments.append(audio_data)
            logger.debug("Flushed speech segment: %d ms", self._speech_duration_ms)
        self._buffer.clear()
        self._speech_started = False
        self._silence_start = None
        self._pre_speech_buffer.clear()
        self._remainder = np.zeros(0, dtype=np.float32)
        self._reset_state()
        return segments

    def reset(self):
        """Fully reset all internal state."""
        self._buffer.clear()
        self._speech_started = False
        self._silence_start = None
        self._speech_duration_ms = 0
        self._pre_speech_buffer.clear()
        self._remainder = np.zeros(0, dtype=np.float32)
        self._reset_state()
