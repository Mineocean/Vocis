"""
DeepSeek 翻译客户端 + 翻译缓存。

- 使用 DeepSeek 开放平台 API（OpenAI 兼容格式）
- 整句翻译，带上句上下文
- 精确匹配缓存 + 时间窗口去重
- 支持流式翻译
"""

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from typing import cast

import httpx

from .cache import TranslationCache
from .config import get_config
from .utils import create_http_client, normalize_api_url

logger = logging.getLogger(__name__)


class DeepSeekTranslator:
    """DeepSeek 翻译客户端"""

    def __init__(self):
        cfg = get_config()
        self.api_key = cfg.translator.api_key
        self.base_url = normalize_api_url(cfg.translator.base_url)
        self.model = cfg.translator.model
        self.target_language = cfg.translator.target_language
        self.cache = TranslationCache(cfg.cache_window_seconds)
        self._prev_original: str | None = None
        self._prev_translation: str | None = None
        self._client: httpx.AsyncClient | None = None
        self._closed = False

    @property
    def client(self) -> httpx.AsyncClient:
        if self._closed:
            raise RuntimeError("DeepSeekTranslator is closed")
        if self._client is None:
            self._client = cast(
                httpx.AsyncClient,
                create_http_client(
                    base_url=self.base_url,
                    api_key=self.api_key,
                    async_client=True,
                ),
            )
        return self._client

    async def translate_async(self, text: str) -> str | None:
        """Async translate text."""
        if not text or not text.strip():
            return None

        text = text.strip()

        cached = self.cache.get(text)
        if cached is not None:
            return cached

        messages = self._build_messages(text)
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 1024,
            "thinking": {"type": "disabled"},
        }

        for attempt in range(3):
            try:
                resp = await self.client.post("/chat/completions", json=body)
                resp.raise_for_status()
                data = resp.json()
                content = (data.get("choices") or [{}])[0].get("message", {}).get("content")
                if not content:
                    logger.warning("API returned empty content: %s", str(data)[:200])
                    return None
                translation = content.strip()
                break
            except httpx.HTTPStatusError as e:
                logger.error("Translation HTTP %d: %s", e.response.status_code, e.response.text[:200])
                return None
            except Exception as e:
                if attempt < 2 and not self._closed:
                    logger.warning("Translation retry %d/3: %s", attempt + 1, e)
                    await asyncio.sleep(1.0 * (attempt + 1))
                    self._client = None
                else:
                    logger.error("Translation request error: %s", e)
                    return None

        self.cache.put(text, translation)
        self._prev_original = text
        self._prev_translation = translation
        logger.debug("Translation: %s → %s", text[:40], translation[:40])
        return translation

    async def translate_stream_async(self, text: str) -> AsyncGenerator[str, None]:
        """Async streaming translation."""
        if not text or not text.strip():
            return

        text = text.strip()

        cached = self.cache.get(text)
        if cached is not None:
            yield cached
            return

        messages = self._build_messages(text)
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 1024,
            "stream": True,
            "thinking": {"type": "disabled"},
        }

        full_translation = ""
        try:
            async with self.client.stream("POST", "/chat/completions", json=body, timeout=30.0) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        delta = data.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            full_translation += content
                            yield content
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
        except httpx.HTTPStatusError as e:
            logger.error("Stream translation HTTP %d: %s", e.response.status_code, e.response.text[:200])
            return
        except Exception as e:
            logger.error("Stream translation error: %s", e)
            return

        if full_translation:
            self.cache.put(text, full_translation)
            self._prev_original = text
            self._prev_translation = full_translation
            logger.debug("Stream translation done: %s → %s", text[:40], full_translation[:40])

    def _build_messages(self, text: str) -> list[dict]:
        """构造翻译请求的消息列表"""
        messages = []
        system_prompt = (
            f"你是一个专业的翻译助手。将以下文本翻译成{self.target_language}。"
            f"只输出翻译结果，不要添加任何解释、注释或标点之外的额外内容。"
            f"保持原文的语气和风格。"
        )
        messages.append({"role": "system", "content": system_prompt})

        # 带上句上下文
        if self._prev_original and self._prev_translation:
            context = (
                f"前一句原文：{self._prev_original}\n"
                f"前一句译文：{self._prev_translation}"
            )
            messages.append({"role": "user", "content": context})
            ack = (
                f"好的，我已了解上下文，将继续翻译为{self.target_language}。"
                if self.target_language
                else "好的，我已了解上下文。"
            )
            messages.append({"role": "assistant", "content": ack})

        messages.append({"role": "user", "content": text})
        return messages

    def reset_context(self):
        """重置上下文（例如切换视频时调用）"""
        self._prev_original = None
        self._prev_translation = None

    def close(self):
        """Close the HTTP client."""
        self._closed = True
        if self._client:
            try:
                asyncio.run(self._client.aclose())
            except RuntimeError:
                pass
            self._client = None

    async def close_async(self):
        """Async close."""
        self._closed = True
        if self._client:
            await self._client.aclose()
            self._client = None
