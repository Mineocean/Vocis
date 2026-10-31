"""Neural speaker diarization with sherpa-onnx speaker embeddings.

Uses the 3D-Speaker CAM++ zh/en model (192-d embeddings, ~28 MB). On real
speech measured here: same-speaker cosine 0.65–0.88, different-speaker
cosine < 0.46 — a 0.55 threshold separates them cleanly.

The model is downloaded once (first use) into models/diarization/ and then
loaded lazily; set DIARIZATION_MODEL_PATH to point at an existing copy.
"""

import logging
import threading
from pathlib import Path

import numpy as np

from ..config import app_dir, get_config
from .clustering import CosineClusterDiarizer
from . import register_diarizer

logger = logging.getLogger(__name__)

MODEL_FILENAME = "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"
MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-recongition-models/" + MODEL_FILENAME
)
MODEL_MIN_BYTES = 20 * 1024 * 1024


def model_candidates() -> list[Path]:
    dirs = []
    configured = get_config().diarization.model_path
    if configured:
        dirs.append(Path(configured))
    dirs += [
        app_dir() / "models" / "diarization" / MODEL_FILENAME,
        app_dir() / "assets" / "models" / MODEL_FILENAME,
        Path.home() / ".cache" / "vocis" / MODEL_FILENAME,
    ]
    return dirs


def resolve_model_path() -> Path | None:
    """Return an existing model file, else the preferred download destination."""
    for p in model_candidates():
        if p.is_file() and p.stat().st_size >= MODEL_MIN_BYTES:
            return p
    return None


def download_model(dest: Path | None = None) -> Path:
    """Download the speaker embedding model (idempotent)."""
    existing = resolve_model_path()
    if existing is not None:
        return existing
    target = dest or (app_dir() / "models" / "diarization" / MODEL_FILENAME)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".part")
    logger.info("Downloading speaker embedding model (~27 MB): %s", MODEL_URL)
    import httpx

    try:
        with httpx.stream(
            "GET", MODEL_URL, follow_redirects=True, timeout=httpx.Timeout(300.0, connect=15.0)
        ) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", "0") or 0)
            written = 0
            with tmp.open("wb") as fh:
                for chunk in resp.iter_bytes(1024 * 1024):
                    fh.write(chunk)
                    written += len(chunk)
                    if total and written // (4 * 1024 * 1024) != (written - len(chunk)) // (4 * 1024 * 1024):
                        logger.info("Speaker model download: %d%%", written * 100 // total)
        if tmp.stat().st_size < MODEL_MIN_BYTES:
            raise RuntimeError(f"downloaded file too small: {tmp.stat().st_size} bytes")
        tmp.replace(target)
        logger.info("Speaker embedding model ready: %s", target)
        return target
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


@register_diarizer("sherpa")
class SherpaEmbeddingDiarizer(CosineClusterDiarizer):
    """CAM++ speaker embedding + online cosine clustering."""

    default_threshold = 0.55

    def __init__(self, *, model_path: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self._model_path = Path(model_path) if model_path else None
        self._extractor = None
        self._load_error: str | None = None
        self._state_lock = threading.Lock()
        self._loading_started = False

    # ── model lifecycle ─────────────────────────────

    def prewarm(self):
        """Load (and if needed download) the model off the critical path."""
        with self._state_lock:
            if self._loading_started or self._extractor is not None or self._load_error is not None:
                return
            self._loading_started = True
        threading.Thread(target=self._ensure_model, name="diarizer-prewarm", daemon=True).start()

    def _ensure_model(self):
        try:
            import sherpa_onnx
        except ImportError:
            self._load_error = "sherpa-onnx not installed (pip install 'vocis[sherpa]')"
            logger.error("Diarization disabled: %s", self._load_error)
            return
        try:
            path = self._model_path
            if path is None:
                found = resolve_model_path()
                path = found if found is not None else download_model()
            cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=str(path), num_threads=2, debug=False, provider="cpu"
            )
            self._extractor = sherpa_onnx.SpeakerEmbeddingExtractor(cfg)
            logger.info("Speaker embedding model loaded: %s", path)
        except Exception as e:  # 模型损坏/下载失败
            self._load_error = str(e)
            logger.error("Failed to load speaker embedding model: %s", e)
        finally:
            with self._state_lock:
                self._loading_started = False

    def _embed(self, audio_pcm: bytes) -> np.ndarray | None:
        # 模型还在后台加载/下载时立即返回，绝不阻塞字幕链路
        if self._extractor is None:
            self.prewarm()
            return None
        x = np.frombuffer(audio_pcm, dtype=np.int16).astype(np.float32) / 32768.0
        if x.size < 1600:
            return None
        try:
            stream = self._extractor.create_stream()
            stream.accept_waveform(16000, x)
            stream.input_finished()
            vec = np.asarray(self._extractor.compute(stream), dtype=np.float32)
        except Exception as e:
            logger.warning("Speaker embedding failed: %s", e)
            return None
        norm = float(np.linalg.norm(vec))
        if norm < 1e-6:
            return None
        return vec / norm

    def close(self):
        super().close()
        self._extractor = None
