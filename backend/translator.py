"""
DeepSeek 翻译客户端 + 翻译缓存。

- 使用 DeepSeek 开放平台 API（OpenAI 兼容格式）
- 整句翻译，带上句上下文
- 精确匹配缓存 + 时间窗口去重
- 支持流式翻译
"""

import json
import logging
import time
from typing import Generator, Optional

import httpx

from .cache import TranslationCache
from .config import get_config
from .utils import normalize_api_url, create_http_client

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
        self._prev_original: Optional[str] = None
        self._prev_translation: Optional[str] = None
        self._client: Optional[httpx.Client] = None
        self._closed = False

    @property
    def client(self) -> httpx.Client:
        if self._closed:
            raise RuntimeError("DeepSeekTranslator 已关闭")
        if self._client is None:
            self._client = create_http_client(
                base_url=self.base_url,
                api_key=self.api_key,
            )
        return self._client

    def translate(self, text: str) -> Optional[str]:
        """
        翻译文本。先查缓存，未命中则调用 API。

        :param text: 原文
        :return: 译文，失败返回 None
        """
        if not text or not text.strip():
            return None

        text = text.strip()

        # 1. 查缓存
        cached = self.cache.get(text)
        if cached is not None:
            return cached

        # 2. 构造上下文消息
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
            messages.append({"role": "assistant", "content": "好的，我已了解上下文。"})

        messages.append({"role": "user", "content": text})

        # 3. API 请求
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 1024,
            "extra_body": {"thinking": {"type": "disabled"}},
        }

        last_err = None
        for attempt in range(3):
            try:
                resp = self.client.post("/chat/completions", json=body)
                resp.raise_for_status()
                data = resp.json()
                translation = data["choices"][0]["message"]["content"].strip()
                break
            except httpx.HTTPStatusError as e:
                logger.error("翻译 HTTP %d: %s", e.response.status_code, e.response.text[:200])
                return None
            except Exception as e:
                last_err = e
                if attempt < 2 and not self._closed:
                    import time
                    logger.warning("翻译重试 %d/3: %s", attempt + 1, e)
                    time.sleep(1.0 * (attempt + 1))
                    self._client = None  # 重建连接
                else:
                    logger.error("翻译请求异常: %s", e)
                    return None

        # 4. 存入缓存、更新上下文
        self.cache.put(text, translation)
        self._prev_original = text
        self._prev_translation = translation

        logger.info("翻译: %s → %s", text[:40], translation[:40])
        return translation

    def translate_stream(self, text: str) -> Generator[str, None, None]:
        """
        流式翻译：逐 token 返回翻译结果。

        :param text: 原文
        :yield: 翻译片段
        """
        if not text or not text.strip():
            return

        text = text.strip()

        # 1. 查缓存（命中则一次性返回）
        cached = self.cache.get(text)
        if cached is not None:
            yield cached
            return

        # 2. 构造上下文消息
        messages = self._build_messages(text)

        # 3. 流式 API 请求
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 1024,
            "stream": True,
            "extra_body": {"thinking": {"type": "disabled"}},
        }

        full_translation = ""
        try:
            with self.client.stream("POST", "/chat/completions", json=body, timeout=30.0) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
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
            logger.error("流式翻译 HTTP %d: %s", e.response.status_code, e.response.text[:200])
            return
        except Exception as e:
            logger.error("流式翻译异常: %s", e)
            return

        # 4. 存入缓存、更新上下文
        if full_translation:
            self.cache.put(text, full_translation)
            self._prev_original = text
            self._prev_translation = full_translation
            logger.info("流式翻译完成: %s → %s", text[:40], full_translation[:40])

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
            messages.append({"role": "assistant", "content": "好的，我已了解上下文。"})

        messages.append({"role": "user", "content": text})
        return messages

    def reset_context(self):
        """重置上下文（例如切换视频时调用）"""
        self._prev_original = None
        self._prev_translation = None

    def close(self):
        self._closed = True
        if self._client:
            self._client.close()
            self._client = None
