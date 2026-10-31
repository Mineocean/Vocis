"""
翻译客户端 —— 任意 OpenAI 兼容 /chat/completions 端点。

- 提供商由 TRANSLATOR_PROVIDER 决定（deepseek/openai/moonshot/qwen/zhipu/groq/
  siliconflow/ollama/custom），端点与默认模型来自 backend.providers.presets
- 整句翻译 + 上句上下文，支持流式增量输出
- 精确匹配缓存 + 时间窗口去重
- 每个提供商的专有请求字段（如 DeepSeek 的 thinking）只发给它自己
"""

import asyncio
import json
import logging
from collections.abc import AsyncGenerator

import httpx

from .cache import TranslationCache
from .config import get_config
from .providers.presets import TRANSLATION_PRESETS
from .utils import normalize_api_url

logger = logging.getLogger(__name__)


class OpenAICompatTranslator:
    """OpenAI 兼容聊天补全翻译客户端。"""

    def __init__(self, *, provider: str | None = None):
        cfg = get_config().translator
        self.provider = (provider or cfg.provider).lower()
        if self.provider not in TRANSLATION_PRESETS:
            logger.warning("未注册的翻译提供商 '%s'，按自定义端点处理", self.provider)
        self.api_key = cfg.api_key
        self.base_url = normalize_api_url(cfg.base_url)
        self.model = cfg.model
        self.target_language = cfg.target_language
        self.temperature = cfg.temperature
        self.max_tokens = cfg.max_tokens
        self._extra_body = cfg.extra_body
        self.cache = TranslationCache(get_config().cache_window_seconds)
        self._prev_original: str | None = None
        self._prev_translation: str | None = None
        self._client: httpx.AsyncClient | None = None
        self._closed = False

    # ── 连接 ────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    @property
    def client(self) -> httpx.AsyncClient:
        if self._closed:
            raise RuntimeError("Translator is closed")
        if self._client is None:
            if not self.base_url:
                raise ValueError(
                    f"翻译提供商 {self.provider} 没有配置 API 地址，请在设置中填写 Base URL"
                )
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=self._headers(),
                timeout=httpx.Timeout(30.0, connect=8.0),
            )
        return self._client

    def _body(self, text: str, *, stream: bool) -> dict:
        body = {
            "model": self.model,
            "messages": self._build_messages(text),
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if stream:
            body["stream"] = True
        if self._extra_body:
            body.update(self._extra_body)
        return body

    # ── 翻译 ────────────────────────────────────────

    async def translate_async(self, text: str) -> str | None:
        """整句翻译。返回 None 表示失败（调用方决定是否显示占位符）。"""
        if not text or not text.strip():
            return None
        text = text.strip()

        cached = self.cache.get(text)
        if cached is not None:
            return cached

        body = self._body(text, stream=False)
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                resp = await self.client.post("/chat/completions", json=body)
                if resp.status_code in (429, 500, 502, 503, 504) and attempt == 0:
                    logger.warning("Translation HTTP %d, retrying", resp.status_code)
                    await asyncio.sleep(0.8)
                    continue
                resp.raise_for_status()
                data = resp.json()
                content = (data.get("choices") or [{}])[0].get("message", {}).get("content")
                if not content:
                    logger.warning("Translation returned empty content: %s", str(data)[:200])
                    return None
                translation = content.strip()
                self.cache.put(text, translation)
                self._prev_original, self._prev_translation = text, translation
                logger.debug("Translation: %s → %s", text[:40], translation[:40])
                return translation
            except httpx.HTTPStatusError as e:
                logger.error(
                    "Translation HTTP %d (%s): %s",
                    e.response.status_code,
                    self.provider,
                    e.response.text[:200],
                )
                return None
            except Exception as e:
                last_error = e
                if self._closed:
                    return None
                if attempt == 0:
                    logger.warning("Translation retry (%s): %s", self.provider, e)
                    await asyncio.sleep(0.5)
                    self._client = None
        logger.error("Translation request error: %s", last_error)
        return None

    async def translate_stream_async(self, text: str) -> AsyncGenerator[str, None]:
        """流式翻译：逐块 yield 译文片段。"""
        if not text or not text.strip():
            return
        text = text.strip()

        cached = self.cache.get(text)
        if cached is not None:
            yield cached
            return

        body = self._body(text, stream=True)
        full_translation = ""
        try:
            async with self.client.stream(
                "POST", "/chat/completions", json=body, timeout=httpx.Timeout(30.0, connect=8.0)
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if not data_str or data_str == "[DONE]":
                        break
                    try:
                        delta = json.loads(data_str)["choices"][0].get("delta", {})
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
                    content = delta.get("content") or ""
                    if content:
                        full_translation += content
                        yield content
        except httpx.HTTPStatusError as e:
            logger.error(
                "Stream translation HTTP %d (%s): %s",
                e.response.status_code,
                self.provider,
                e.response.text[:200],
            )
            return
        except Exception as e:
            logger.error("Stream translation error (%s): %s", self.provider, e)
            return

        if full_translation:
            self.cache.put(text, full_translation)
            self._prev_original, self._prev_translation = text, full_translation
            logger.debug("Stream translation done: %s → %s", text[:40], full_translation[:40])

    # ── 提示词 ──────────────────────────────────────

    def _build_messages(self, text: str) -> list[dict]:
        """构造翻译请求的消息列表（上一句作为上下文）。"""
        messages: list[dict] = [
            {
                "role": "system",
                "content": (
                    f"你是专业的实时字幕翻译。把用户给出的字幕文本翻译成{self.target_language}。"
                    "只输出译文本身，不要解释、注释、引号或任何前后缀。"
                    "保持原文语气与口语感，专有名词保持通行译名。"
                ),
            }
        ]
        if self._prev_original and self._prev_translation:
            messages.append(
                {
                    "role": "user",
                    "content": f"上一句原文：{self._prev_original}\n上一句译文：{self._prev_translation}",
                }
            )
            messages.append(
                {"role": "assistant", "content": f"已了解上下文，继续翻译为{self.target_language}。"}
            )
        messages.append({"role": "user", "content": text})
        return messages

    def reset_context(self):
        """重置上下文（例如切换视频时调用）"""
        self._prev_original = None
        self._prev_translation = None

    def close(self):
        """同步关闭（供非异步线程调用）。"""
        self._closed = True
        if self._client:
            try:
                asyncio.run(self._client.aclose())
            except Exception:
                pass
            self._client = None

    async def close_async(self):
        """异步关闭。"""
        self._closed = True
        if self._client:
            await self._client.aclose()
            self._client = None


def create_translator() -> OpenAICompatTranslator:
    """按当前配置创建翻译客户端。"""
    return OpenAICompatTranslator()
