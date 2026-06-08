"""
DeepSeek 翻译客户端 + 翻译缓存。

- 使用 DeepSeek 开放平台 API（OpenAI 兼容格式）
- 整句翻译，带上句上下文
- 精确匹配缓存 + 时间窗口去重
"""

import hashlib
import logging
import time
from typing import Optional

import httpx

from .config import get_config

logger = logging.getLogger(__name__)


class TranslationCache:
    """翻译缓存：精确匹配 + 时间窗口去重"""

    def __init__(self, window_seconds: int = 30):
        self._cache: dict[str, tuple[float, str]] = {}  # hash → (timestamp, translation)
        self._window = window_seconds

    def get(self, text: str) -> Optional[str]:
        """查缓存，命中且未过期返回译文"""
        key = self._hash(text)
        entry = self._cache.get(key)
        if entry is None:
            return None
        ts, translation = entry
        if time.time() - ts <= self._window:
            logger.debug("缓存命中: %s", text[:30])
            return translation
        # 过期，删除
        del self._cache[key]
        logger.debug("缓存过期: %s", text[:30])
        return None

    def put(self, text: str, translation: str):
        """写入缓存"""
        key = self._hash(text)
        self._cache[key] = (time.time(), translation)

    def _hash(self, text: str) -> str:
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    def cleanup(self):
        """清理过期条目"""
        now = time.time()
        expired = [k for k, (ts, _) in self._cache.items() if now - ts > self._window]
        for k in expired:
            del self._cache[k]


class DeepSeekTranslator:
    """DeepSeek 翻译客户端"""

    def __init__(self):
        cfg = get_config()
        self.api_key = cfg.translator.api_key
        base = cfg.translator.base_url.rstrip("/")
        if not base.endswith("/v1"):
            if "/v1/" in base or "/v1" in base:
                idx = base.index("/v1")
                base = base[:idx + 3]
            else:
                base += "/v1"
        self.base_url = base
        self.model = cfg.translator.model
        self.target_language = cfg.translator.target_language
        self.cache = TranslationCache(cfg.cache_window_seconds)
        self._prev_original: Optional[str] = None
        self._prev_translation: Optional[str] = None
        self._client: Optional[httpx.Client] = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=30.0,
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
                if attempt < 2:
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

    def reset_context(self):
        """重置上下文（例如切换视频时调用）"""
        self._prev_original = None
        self._prev_translation = None

    def close(self):
        if self._client:
            self._client.close()
            self._client = None
