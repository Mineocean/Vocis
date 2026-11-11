"""OpenAI-compatible /audio/transcriptions ASR backend.

同一套实现覆盖 OpenAI、Groq、SiliconFlow 等兼容端点以及自定义端点：
端点、默认模型、鉴权方式都来自 backend.providers.presets.ASR_PRESETS。
"""

import asyncio
import logging

import httpx

from ..config import get_config
from ..utils import normalize_api_url
from ..work import tracked_async
from .audio import pcm_to_wav
from .base import ASREngine, ASRResult
from .registry import register_asr

logger = logging.getLogger(__name__)


@register_asr("openai")
@register_asr("groq")
@register_asr("siliconflow")
@register_asr("custom")
class OpenAICompatibleASR(ASREngine):
    """Cloud ASR over the OpenAI transcription protocol."""

    def __init__(self):
        cfg = get_config().asr
        self.provider = cfg.backend
        self.api_key = cfg.api_key
        self.base_url = normalize_api_url(cfg.base_url)
        self.model = cfg.model
        self.language = "" if cfg.language == "auto" else cfg.language
        self._client: httpx.AsyncClient | None = None

    def set_language(self, language: str):
        self.language = "" if language == "auto" else language

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            if not self.base_url:
                raise ValueError(
                    f"ASR 端点 {self.provider} 没有配置 API 地址，请在设置中填写 Base URL"
                )
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=httpx.Timeout(60.0, connect=8.0),
            )
        return self._client

    @tracked_async
    async def transcribe_async(self, audio_pcm: bytes) -> ASRResult | None:
        if not audio_pcm:
            return None

        data: dict[str, str] = {"model": self.model}
        if self.language:
            data["language"] = self.language
        # whisper-1 支持 verbose_json（能拿到检测语言）；gpt-4o-transcribe 只支持 json
        data["response_format"] = "verbose_json" if "whisper" in self.model.lower() else "json"
        files = {"file": ("audio.wav", pcm_to_wav(audio_pcm), "audio/wav")}

        try:
            resp = await self.client.post("/audio/transcriptions", data=data, files=files)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error(
                "ASR HTTP %d (%s): %s", e.response.status_code, self.provider, e.response.text[:200]
            )
            return None
        except Exception as e:
            logger.error("ASR request error (%s): %s", self.provider, e)
            return None

        try:
            payload = resp.json()
        except ValueError:
            payload = None

        if isinstance(payload, dict):
            text = payload.get("text", "")
            lang = payload.get("language") or None
        else:
            text = resp.text
            lang = None
        text = (text or "").strip()
        if not text:
            logger.warning("%s ASR returned empty text", self.provider)
            return None
        logger.debug("%s ASR: %s", self.provider, text)
        # 云端返回的 language 是可信的检测结果，但没有置信度
        return text, lang, 1.0 if lang else 0.0

    def transcribe(self, audio_pcm: bytes) -> ASRResult | None:
        """Sync fallback — runs async in a new event loop when possible."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.transcribe_async(audio_pcm))
        logger.warning("Sync transcribe called in async context, use transcribe_async instead")
        return None

    def close(self):
        if self._client:
            try:
                asyncio.run(self._client.aclose())
            except Exception:
                pass
            self._client = None
