"""Speaker diarization registry."""

import logging
from collections.abc import Callable

from ..config import get_config
from .base import Speaker, SpeakerDiarizer

logger = logging.getLogger(__name__)

# 注册表存"可调用工厂"而不是 type[...]：各后端构造函数都接受
# max_speakers/threshold/min_seconds，但抽象基类本身没有这些参数。
_REGISTRY: dict[str, Callable[..., SpeakerDiarizer]] = {}


def register_diarizer(name: str):
    """Decorator to register a diarization backend."""

    def decorator(cls):
        _REGISTRY[name] = cls
        return cls

    return decorator


def create_diarizer() -> SpeakerDiarizer | None:
    """Build the configured diarizer, or None when diarization is off."""
    from . import cluster, sherpa_embedding  # noqa: F401  (register built-in backends)

    cfg = get_config().diarization
    if not cfg.enabled:
        return None
    cls = _REGISTRY.get(cfg.backend)
    if cls is None:
        logger.warning(
            "Unknown diarization backend '%s', available: %s", cfg.backend, list(_REGISTRY)
        )
        return None
    if cfg.backend == "sherpa":
        import importlib.util

        if importlib.util.find_spec("sherpa_onnx") is None:
            logger.warning("sherpa-onnx 未安装，说话人分离退回零依赖的 cluster 后端")
            cls = _REGISTRY["cluster"]
    try:
        diarizer = cls(
            max_speakers=cfg.max_speakers,
            threshold=cfg.threshold,
            min_seconds=cfg.min_seconds,
        )
    except Exception as e:
        logger.error("Failed to create diarizer '%s': %s", cfg.backend, e)
        return None
    # 神经模型：后台加载/下载，避免阻塞启动；加载失败时退回零依赖的 MFCC 聚类
    if hasattr(diarizer, "prewarm"):
        diarizer.prewarm()
    return diarizer


__all__ = ["Speaker", "SpeakerDiarizer", "create_diarizer", "register_diarizer"]
