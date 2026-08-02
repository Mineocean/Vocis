"""ASR backend registry and factory."""

import logging

from .base import ASREngine

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, type[ASREngine]] = {}


def register_asr(name: str):
    """Decorator to register an ASR backend."""
    def decorator(cls):
        _REGISTRY[name] = cls
        return cls
    return decorator


def create_asr() -> ASREngine:
    """Create ASR engine from config."""
    from ..config import get_config
    cfg = get_config()
    backend = cfg.asr.backend.lower()

    cls = _REGISTRY.get(backend)
    if cls is None:
        available = list(_REGISTRY.keys())
        logger.warning("Unknown ASR backend '%s', available: %s", backend, available)
        if "mock" in _REGISTRY:
            return _REGISTRY["mock"]()
        raise ValueError(f"Unknown ASR backend: {backend}. Available: {available}")

    try:
        return cls()
    except Exception as e:
        logger.warning("Failed to create ASR backend '%s': %s, falling back to mimo", backend, e)
        if backend != "mimo" and "mimo" in _REGISTRY:
            return _REGISTRY["mimo"]()
        raise


def list_backends() -> list[str]:
    """List registered ASR backend names."""
    return list(_REGISTRY.keys())
