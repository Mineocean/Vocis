"""Zero-download fallback diarizer: MFCC statistics + cosine clustering.

Good enough to split obviously different voices; prefer the `sherpa`
backend (neural CAM++ embeddings) when its model is available.
"""

import logging

import numpy as np
from scipy.fftpack import dct

from .clustering import CosineClusterDiarizer
from . import register_diarizer

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
FRAME_LEN = 400      # 25 ms
HOP_LEN = 160        # 10 ms
N_FFT = 512
N_MELS = 40
N_MFCC = 20          # c0（能量）丢弃，用 c1..c19
PRE_EMPHASIS = 0.97


def _hz_to_mel(hz):
    return 2595.0 * np.log10(1.0 + hz / 700.0)


def _mel_to_hz(mel):
    return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)


def _mel_filterbank() -> np.ndarray:
    low, high = 20.0, SAMPLE_RATE / 2 - 100.0
    mel_points = np.linspace(_hz_to_mel(low), _hz_to_mel(high), N_MELS + 2)
    hz_points = _mel_to_hz(mel_points)
    bins = np.floor((N_FFT + 1) * hz_points / SAMPLE_RATE).astype(int)
    fbank = np.zeros((N_MELS, N_FFT // 2 + 1), dtype=np.float32)
    for m in range(1, N_MELS + 1):
        left, center, right = bins[m - 1], bins[m], bins[m + 1]
        if center == left:
            center += 1
        if right == center:
            right += 1
        for k in range(left, min(center, fbank.shape[1])):
            fbank[m - 1, k] = (k - left) / (center - left)
        for k in range(center, min(right, fbank.shape[1])):
            fbank[m - 1, k] = (right - k) / (right - center)
    return fbank


_MEL_FB = _mel_filterbank()


def mfcc_embedding(audio_pcm: bytes) -> np.ndarray | None:
    """Mean/std of MFCC c1..c19 for an int16 16 kHz mono segment."""
    n = len(audio_pcm) // 2
    if n < int(0.35 * SAMPLE_RATE):
        return None
    x = np.frombuffer(audio_pcm[: n * 2], dtype=np.int16).astype(np.float32) / 32768.0
    if float(np.sqrt(np.mean(np.square(x)))) < 1e-4:
        return None  # 静音 / 只有底噪

    x = np.append(x[0], x[1:] - PRE_EMPHASIS * x[:-1])
    n_frames = 1 + max(0, (len(x) - FRAME_LEN) // HOP_LEN)
    if n_frames < 8:
        return None
    idx = np.arange(FRAME_LEN)[None, :] + HOP_LEN * np.arange(n_frames)[:, None]
    frames = x[idx] * np.hamming(FRAME_LEN)
    spectrum = np.abs(np.fft.rfft(frames, N_FFT)) ** 2
    mel = spectrum @ _MEL_FB.T
    log_mel = np.log(np.maximum(mel, 1e-10))
    mfcc = dct(log_mel, type=2, axis=1, norm="ortho")[:, 1:N_MFCC]

    feat = np.concatenate([mfcc.mean(axis=0), mfcc.std(axis=0)]).astype(np.float32)
    norm = float(np.linalg.norm(feat))
    if norm < 1e-6:
        return None
    return feat / norm


@register_diarizer("cluster")
class ClusterDiarizer(CosineClusterDiarizer):
    """MFCC statistics + cosine clustering (no model download)."""

    default_threshold = 0.8

    def _embed(self, audio_pcm: bytes) -> np.ndarray | None:
        return mfcc_embedding(audio_pcm)
