"""MiMo-V2.5-ASR cloud backend."""

import asyncio
import base64
import io
import logging
import wave
from typing import Optional

import httpx

from .base import ASREngine
from .registry import register_asr
from ..config import get_config
from ..utils import normalize_api_url

logger = logging.getLogger(__name__)


def pcm_to_wav(pcm_data: bytes, sample_rate: int = 16000, channels: int = 1, bits: int = 16) -> bytes:
    """Wrap raw PCM data in WAV format."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(bits // 8)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


@register_asr("mimo")
class MiMoASR(ASREngine):
    """MiMo-V2.5-ASR cloud API."""

    def __init__(self):
        cfg = get_config()
        self.api_key = cfg.asr.api_key
        self.language = cfg.asr.language
        self.model = cfg.asr.model
        self._client: Optional[httpx.AsyncClient] = None
        self._closed = False
        self.base_url = normalize_api_url(cfg.asr.base_url)

    @property
    def client(self) -> httpx.AsyncClient:
        if self._closed:
            raise RuntimeError("MiMoASR is closed")
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "api-key": self.api_key,
                    "Content-Type": "application/json",
                },
                timeout=10.0,
            )
        return self._client

    def set_language(self, language: str):
        self.language = language

    async def transcribe_async(self, audio_pcm: bytes) -> Optional[str]:
        if not audio_pcm:
            return None

        wav_data = pcm_to_wav(audio_pcm, sample_rate=16000)
        audio_b64 = base64.b64encode(wav_data).decode("ascii")
        data_url = f"data:audio/wav;base64,{audio_b64}"

        body = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {"data": data_url},
                        }
                    ],
                }
            ],
            "asr_options": {"language": self.language},
        }

        try:
            resp = await self.client.post("/chat/completions", json=body)
            resp.raise_for_status()
            data = resp.json()
            text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            if text:
                logger.debug("MiMo ASR: %s", text)
                return text.strip()
            logger.warning("MiMo ASR returned empty text")
            return None
        except httpx.HTTPStatusError as e:
            logger.error("MiMo HTTP %d: %s", e.response.status_code, e.response.text[:200])
            return None
        except Exception as e:
            logger.error("MiMo request error: %s", e)
            return None

    def transcribe(self, audio_pcm: bytes) -> Optional[str]:
        """Sync fallback - runs async in new event loop."""
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                logger.warning("Sync transcribe called in async context, use transcribe_async instead")
                return None
            return loop.run_until_complete(self.transcribe_async(audio_pcm))
        except RuntimeError:
            return asyncio.run(self.transcribe_async(audio_pcm))

    def close(self):
        """Close the HTTP client."""
        if self._client:
            try:
                asyncio.run(self._client.aclose())
            except RuntimeError:
                pass
            self._client = None
