"""Cosine clustering shared by every diarization backend.

Backends only need to provide an embedding for a speech segment; speaker
assignment, centroid updates and the max-speaker cap live here.
"""

import logging
import threading

import numpy as np

from .base import Speaker, SpeakerDiarizer

logger = logging.getLogger(__name__)

STICKY_BONUS = 0.05   # 说话人轮次连续：给上一位一点惯性，避免逐段抖动
CENTROID_ALPHA = 0.3  # 质心指数滑动平均


class CosineClusterDiarizer(SpeakerDiarizer):
    """Online speaker clustering on L2-normalized embeddings."""

    default_threshold = 0.6

    def __init__(
        self,
        max_speakers: int = 4,
        threshold: float | None = None,
        min_seconds: float = 0.6,
    ):
        self.max_speakers = max(1, int(max_speakers))
        self.threshold = float(threshold if threshold is not None else self.default_threshold)
        self.min_seconds = float(min_seconds)
        self._centroids: list[np.ndarray] = []
        self._last: int | None = None
        self._lock = threading.Lock()

    # ── backend hook ────────────────────────────────

    def _embed(self, audio_pcm: bytes) -> np.ndarray | None:
        """Return an L2-normalized embedding, or None when the audio is unusable."""
        raise NotImplementedError

    # ── assignment ──────────────────────────────────

    def assign(self, audio_pcm: bytes) -> Speaker | None:
        if not audio_pcm:
            return None
        with self._lock:
            # 太短：不参与判人，沿用上一位（没有就暂不标注）
            if len(audio_pcm) < int(self.min_seconds * 16000) * 2:
                return Speaker(self._last + 1) if self._last is not None else None

            emb = self._embed(audio_pcm)
            if emb is None:
                return Speaker(self._last + 1) if self._last is not None else None

            if not self._centroids:
                return Speaker(self._add_speaker(emb) + 1)

            sims = np.array([float(c @ emb) for c in self._centroids])
            if self._last is not None:
                sims[self._last] += STICKY_BONUS
            best = int(np.argmax(sims))

            if sims[best] >= self.threshold or len(self._centroids) >= self.max_speakers:
                updated = (1 - CENTROID_ALPHA) * self._centroids[best] + CENTROID_ALPHA * emb
                norm = float(np.linalg.norm(updated))
                if norm > 1e-6:
                    self._centroids[best] = updated / norm
                self._last = best
                return Speaker(best + 1)

            speaker = self._add_speaker(emb)
            logger.info(
                "New speaker %d (best similarity %.2f < %.2f)",
                speaker + 1, sims[best], self.threshold,
            )
            return Speaker(speaker + 1)

    def _add_speaker(self, emb: np.ndarray) -> int:
        self._centroids.append(emb)
        self._last = len(self._centroids) - 1
        return self._last

    def reset(self):
        with self._lock:
            self._centroids.clear()
            self._last = None

    def close(self):
        self.reset()

    @property
    def speaker_count(self) -> int:
        return len(self._centroids)
