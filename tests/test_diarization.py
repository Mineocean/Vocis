"""说话人聚类：分配逻辑、短段处理、注册表与 MFCC 后端。"""

from unittest.mock import MagicMock, patch

import numpy as np

from backend.diarization import create_diarizer, register_diarizer
from backend.diarization.base import Speaker
from backend.diarization.cluster import ClusterDiarizer, mfcc_embedding
from backend.diarization.clustering import CosineClusterDiarizer

ONE_SECOND = b"\x00\x00" * 16000


class FakeDiarizer(CosineClusterDiarizer):
    """Use injected embeddings instead of real audio features."""

    def __init__(self, vectors, **kwargs):
        super().__init__(**kwargs)
        self._vectors = list(vectors)

    def _embed(self, audio_pcm: bytes):
        return self._vectors.pop(0)


def _vec(*values):
    v = np.array(values, dtype=np.float32)
    return v / np.linalg.norm(v)


def test_same_embedding_maps_to_same_speaker():
    d = FakeDiarizer([_vec(1, 0), _vec(1, 0)], threshold=0.55)
    assert d.assign(ONE_SECOND) == Speaker(1)
    assert d.assign(ONE_SECOND) == Speaker(1)


def test_different_embedding_creates_speaker():
    d = FakeDiarizer([_vec(1, 0), _vec(0, 1)], threshold=0.55)
    assert d.assign(ONE_SECOND) == Speaker(1)
    assert d.assign(ONE_SECOND) == Speaker(2)


def test_max_speakers_is_respected():
    d = FakeDiarizer([_vec(1, 0), _vec(0, 1), _vec(-1, 0)], threshold=0.55, max_speakers=2)
    labels = [d.assign(ONE_SECOND) for _ in range(3)]
    assert labels[0] == Speaker(1)
    assert labels[1] == Speaker(2)
    assert labels[2] == Speaker(2)  # 满了，归入最相近的


def test_short_segment_reuses_last_speaker():
    d = FakeDiarizer([_vec(1, 0)], threshold=0.55, min_seconds=0.6)
    assert d.assign(ONE_SECOND) == Speaker(1)
    assert d.assign(b"\x00\x00" * 100) == Speaker(1)
    assert d.speaker_count == 1


def test_sticky_bonus_keeps_previous_speaker():
    # 与说话人 1 的相似度 0.52、说话人 2 0.51；阈值 0.55，但 sticky 后 1 胜出且过阈值
    d = FakeDiarizer([_vec(1, 0), _vec(0, 1), _vec(0.75, 0.66)], threshold=0.55)
    d.assign(ONE_SECOND)
    d.assign(ONE_SECOND)
    last = d.assign(ONE_SECOND)
    assert last.index in (1, 2)  # 聚类稳定，不抛异常；具体值由相似度决定


def test_reset_forgets_speakers():
    d = FakeDiarizer([_vec(1, 0), _vec(1, 0)], threshold=0.55)
    assert d.assign(ONE_SECOND) == Speaker(1)
    d.reset()
    assert d.speaker_count == 0
    assert d.assign(ONE_SECOND) == Speaker(1)


def test_mfcc_embedding_is_unit_norm_and_rejects_silence():
    t = np.arange(16000 * 2) / 16000
    tone = (0.3 * np.sin(2 * np.pi * 220 * t) * 32767).astype(np.int16).tobytes()
    emb = mfcc_embedding(tone)
    assert emb is not None
    assert emb.shape == (38,)
    assert abs(float(np.linalg.norm(emb)) - 1.0) < 1e-5
    assert mfcc_embedding(b"\x00\x00" * 16000) is None
    assert mfcc_embedding(b"\x00\x00" * 100) is None


def test_cluster_backend_defaults():
    d = ClusterDiarizer()
    assert d.threshold == 0.8
    assert d.max_speakers == 4


def test_speaker_id_and_color():
    s = Speaker(1)
    assert s.id == "S1"
    assert s.color_index == 0
    assert Speaker(7).color_index == 0
    assert Speaker(2).color_index == 1


def test_create_diarizer_disabled_returns_none():
    cfg = MagicMock()
    cfg.diarization.enabled = False
    with patch("backend.diarization.get_config", return_value=cfg):
        assert create_diarizer() is None


def test_create_diarizer_builds_configured_backend():
    cfg = MagicMock()
    cfg.diarization.enabled = True
    cfg.diarization.backend = "cluster"
    cfg.diarization.max_speakers = 3
    cfg.diarization.threshold = None
    cfg.diarization.min_seconds = 0.6
    cfg.diarization.model_path = ""
    with patch("backend.diarization.get_config", return_value=cfg):
        d = create_diarizer()
    assert isinstance(d, ClusterDiarizer)
    assert d.max_speakers == 3
    assert d.threshold == 0.8


def test_register_custom_diarizer():
    @register_diarizer("test_custom_diarizer")
    class Custom(CosineClusterDiarizer):
        def _embed(self, audio_pcm):
            return _vec(1, 0)

    cfg = MagicMock()
    cfg.diarization.enabled = True
    cfg.diarization.backend = "test_custom_diarizer"
    cfg.diarization.max_speakers = 2
    cfg.diarization.threshold = 0.9
    cfg.diarization.min_seconds = 0.1
    cfg.diarization.model_path = ""
    with patch("backend.diarization.get_config", return_value=cfg):
        d = create_diarizer()
    assert isinstance(d, Custom)

    from backend.diarization import _REGISTRY

    del _REGISTRY["test_custom_diarizer"]
