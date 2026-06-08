"""
VAD —— 语音活动检测，将连续音频流切分为语音段。

基于 WebRTC VAD，对每 30ms 帧进行分类，累积语音帧直到检测到足够长的静音，
然后输出一个完整的语音段。
"""

import logging
import time
from collections import deque
from typing import Optional

import numpy as np
import webrtcvad

from .config import get_config

logger = logging.getLogger(__name__)


class VoiceActivityDetector:
    """
    语音活动检测器。

    将 16kHz float32 音频流切分为帧，检测语音/静音边界。
    连续语音帧累积 → 连续静音超阈值 → 输出语音段。
    """

    def __init__(self):
        cfg = get_config()
        self.vad = webrtcvad.Vad(cfg.vad_aggressiveness)
        self.sample_rate = cfg.sample_rate
        self.frame_ms = cfg.vad_frame_ms
        self.frame_size = int(self.sample_rate * self.frame_ms / 1000)  # 每帧采样数
        self.speech_padding_ms = cfg.speech_padding_ms
        self.min_speech_duration_ms = cfg.min_speech_duration_ms
        self.silence_duration_ms = cfg.silence_duration_ms

        # 状态
        self._buffer: list[bytes] = []  # 当前语音段 PCM 帧
        self._speech_started = False
        self._silence_start: Optional[float] = None
        self._speech_duration_ms = 0
        self._pending_speech_start = False  # 刚检测到语音，等待确认

        # 前置/后置填充帧
        self._pre_speech_buffer = deque(maxlen=int(self.speech_padding_ms / self.frame_ms))

    def _float_to_pcm16(self, frame: np.ndarray) -> bytes:
        """float32 [-1,1] → int16 PCM"""
        frame = np.clip(frame, -1.0, 1.0)
        return (frame * 32767).astype(np.int16).tobytes()

    def process_chunk(self, audio_chunk: np.ndarray) -> list[bytes]:
        """
        处理一个音频块（约 100ms），返回已完成的语音段列表（PCM 字节）。

        :param audio_chunk: float32 numpy 数组，单声道
        :return: 完成的语音段列表（每个为一个完整句子的 PCM bytes）
        """
        segments = []

        # 切分为 VAD 帧
        n_frames = len(audio_chunk) // self.frame_size
        for i in range(n_frames):
            start = i * self.frame_size
            frame = audio_chunk[start:start + self.frame_size]
            pcm_frame = self._float_to_pcm16(frame)

            try:
                is_speech = self.vad.is_speech(pcm_frame, self.sample_rate)
            except Exception:
                is_speech = False

            now = time.monotonic()

            if is_speech:
                if not self._speech_started:
                    # 语音开始：先追加前置缓冲
                    for pre_frame in self._pre_speech_buffer:
                        self._buffer.append(pre_frame)
                    self._pre_speech_buffer.clear()
                    self._speech_started = True
                    self._speech_duration_ms = 0
                    self._silence_start = None
                    logger.debug("语音段开始")
                self._buffer.append(pcm_frame)
                self._speech_duration_ms += self.frame_ms
            else:
                if self._speech_started:
                    if self._silence_start is None:
                        self._silence_start = now
                    self._buffer.append(pcm_frame)  # 保留静音帧用于后置填充

                    silence_elapsed = (now - self._silence_start) * 1000
                    if silence_elapsed >= self.silence_duration_ms:
                        # 静音超阈值，语音段结束
                        if self._speech_duration_ms >= self.min_speech_duration_ms:
                            audio_data = b"".join(self._buffer)
                            segments.append(audio_data)
                            logger.debug(
                                "语音段完成: %d ms, %d bytes",
                                self._speech_duration_ms,
                                len(audio_data),
                            )
                        else:
                            logger.debug("语音段过短(<%dms)，丢弃", self.min_speech_duration_ms)
                        # 重置
                        self._buffer.clear()
                        self._speech_started = False
                        self._silence_start = None
                else:
                    # 静音中，保持在预缓冲
                    self._pre_speech_buffer.append(pcm_frame)

        return segments

    def flush(self) -> list[bytes]:
        """刷新：输出当前缓冲区中未完成的语音段"""
        segments = []
        if self._speech_started and self._speech_duration_ms >= self.min_speech_duration_ms:
            audio_data = b"".join(self._buffer)
            segments.append(audio_data)
            logger.debug("刷新语音段: %d ms", self._speech_duration_ms)
        self._buffer.clear()
        self._speech_started = False
        self._silence_start = None
        self._pre_speech_buffer.clear()
        return segments

    def reset(self):
        """完全重置状态"""
        self._buffer.clear()
        self._speech_started = False
        self._silence_start = None
        self._pre_speech_buffer.clear()
