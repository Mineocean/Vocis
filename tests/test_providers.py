"""多提供商配置、预置表与 OpenAI 兼容协议的测试。"""

import asyncio
import json

import httpx
import pytest

import backend.config as config_mod
from backend.config import AppConfig, reload_config
from backend.providers.presets import (
    ASR_PRESETS,
    LOCAL_ASR_BACKENDS,
    TRANSLATION_PRESETS,
    asr_preset,
    translation_preset,
)
from backend.translator import create_translator
from backend.utils import normalize_api_url

_ENV_KEYS = [
    "TRANSLATOR_PROVIDER", "TRANSLATOR_API_KEY", "TRANSLATOR_BASE_URL", "TRANSLATOR_MODEL",
    "TRANSLATOR_TEMPERATURE", "TRANSLATOR_MAX_TOKENS",
    "DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL",
    "OPENAI_API_KEY", "GROQ_API_KEY",
    "ASR_BACKEND", "ASR_API_KEY", "ASR_BASE_URL", "ASR_MODEL",
    "MIMO_API_KEY", "MIMO_BASE_URL", "MIMO_ASR_MODEL",
    "DIARIZATION_ENABLED", "DIARIZATION_BACKEND", "DIARIZATION_THRESHOLD",
    "DIARIZATION_MAX_SPEAKERS", "DIARIZATION_MIN_SECONDS", "DIARIZATION_MODEL_PATH",
    "TARGET_LANGUAGE", "SOURCE_LANGUAGE",
]


@pytest.fixture
def clean_env(monkeypatch):
    """清掉真实 .env / 进程环境，构造确定性的配置。"""
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    yield monkeypatch
    config_mod.reload_config()


def _translator(clean_env, **env):
    for key, value in env.items():
        clean_env.setenv(key, value)
    reload_config()
    return create_translator()


def test_presets_are_complete():
    for provider, preset in TRANSLATION_PRESETS.items():
        assert preset["name"]
        assert preset["name_zh"]
        assert isinstance(preset["models"], list)
        if provider != "custom":
            assert preset["base_url"].startswith("http")
            assert preset["default_model"]
    for backend, preset in ASR_PRESETS.items():
        assert preset["protocol"] in ("openai", "mimo")
        if backend != "custom":
            assert preset["base_url"].startswith("http")
            assert preset["default_model"]
    assert set(LOCAL_ASR_BACKENDS) == {"whisper", "sherpa", "mock"}


def test_unknown_provider_falls_back_to_custom():
    assert translation_preset("nope")["base_url"] == ""
    assert asr_preset("nope")["protocol"] == "openai"


def test_normalize_api_url_keeps_vendor_paths():
    assert normalize_api_url("https://api.deepseek.com") == "https://api.deepseek.com/v1"
    assert normalize_api_url("https://api.deepseek.com/") == "https://api.deepseek.com/v1"
    assert normalize_api_url("https://api.deepseek.com/v1/") == "https://api.deepseek.com/v1"
    assert (
        normalize_api_url("https://dashscope.aliyuncs.com/compatible-mode/v1")
        == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    assert (
        normalize_api_url("https://open.bigmodel.cn/api/paas/v4")
        == "https://open.bigmodel.cn/api/paas/v4"
    )
    assert normalize_api_url("") == ""


def test_translation_provider_defaults(clean_env):
    cfg = AppConfig()
    # 无任何环境变量时默认 DeepSeek 预设
    assert cfg.translator.provider == "deepseek"
    assert cfg.translator.base_url == "https://api.deepseek.com"
    assert cfg.translator.model == "deepseek-v4-pro"
    assert cfg.translator.requires_key is True
    assert cfg.translator.extra_body == {"thinking": {"type": "disabled"}}


def test_legacy_deepseek_env_still_works(clean_env):
    clean_env.setenv("DEEPSEEK_API_KEY", "sk-legacy")
    clean_env.setenv("DEEPSEEK_BASE_URL", "https://proxy.example.com/v1")
    clean_env.setenv("DEEPSEEK_MODEL", "deepseek-chat")
    cfg = AppConfig()
    assert cfg.translator.api_key == "sk-legacy"
    assert cfg.translator.base_url == "https://proxy.example.com/v1"
    assert cfg.translator.model == "deepseek-chat"


def test_switch_provider_uses_its_preset(clean_env):
    clean_env.setenv("TRANSLATOR_PROVIDER", "openai")
    clean_env.setenv("OPENAI_API_KEY", "sk-openai")
    cfg = AppConfig()
    assert cfg.translator.provider == "openai"
    assert cfg.translator.api_key == "sk-openai"
    assert cfg.translator.base_url == "https://api.openai.com/v1"
    assert cfg.translator.model == "gpt-4o-mini"
    assert cfg.translator.extra_body == {}


def test_ollama_needs_no_key(clean_env):
    clean_env.setenv("TRANSLATOR_PROVIDER", "ollama")
    cfg = AppConfig()
    assert cfg.translator.requires_key is False
    assert cfg.translator.base_url == "http://localhost:11434/v1"


def test_asr_cloud_preset_and_local_backend(clean_env):
    clean_env.setenv("ASR_BACKEND", "groq")
    clean_env.setenv("ASR_API_KEY", "gsk-test")
    cfg = AppConfig()
    assert cfg.asr.api_key == "gsk-test"
    assert cfg.asr.base_url == "https://api.groq.com/openai/v1"
    assert cfg.asr.model == "whisper-large-v3-turbo"
    assert cfg.asr.protocol == "openai"
    assert cfg.asr.is_local is False

    clean_env.setenv("ASR_BACKEND", "whisper")
    cfg = AppConfig()
    assert cfg.asr.is_local is True
    assert cfg.asr.protocol == "local"


def test_asr_mimo_legacy_env(clean_env):
    clean_env.setenv("ASR_BACKEND", "mimo")
    clean_env.setenv("MIMO_API_KEY", "mimo-key")
    cfg = AppConfig()
    assert cfg.asr.api_key == "mimo-key"
    assert cfg.asr.base_url == "https://api.xiaomimimo.com/v1"
    assert cfg.asr.model == "mimo-v2.5-asr"


def test_deepseek_request_has_thinking_toggled(clean_env):
    translator = _translator(
        clean_env, TRANSLATOR_PROVIDER="deepseek", DEEPSEEK_API_KEY="k"
    )
    body = translator._body("hello", stream=False)
    assert body["thinking"] == {"type": "disabled"}
    assert "stream" not in body
    # base_url 归一化：请求走 /v1/chat/completions
    assert translator.base_url == "https://api.deepseek.com/v1"


def test_other_provider_does_not_receive_deepseek_fields(clean_env):
    translator = _translator(clean_env, TRANSLATOR_PROVIDER="moonshot", MOONSHOT_API_KEY="k")
    body = translator._body("hello", stream=False)
    assert "thinking" not in body
    assert body["model"] == "moonshot-v1-8k"


def test_translate_async_uses_openai_protocol(clean_env):
    translator = _translator(clean_env, TRANSLATOR_PROVIDER="openai", OPENAI_API_KEY="k")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "你好"}}]}
        )

    async def run():
        translator._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=translator.base_url,
            headers=translator._headers(),
        )
        return await translator.translate_async("hello")

    assert asyncio.run(run()) == "你好"
    assert seen["url"].endswith("/chat/completions")
    assert seen["auth"] == "Bearer k"
    assert seen["body"]["model"] == "gpt-4o-mini"


def test_stream_translation_parses_sse(clean_env):
    translator = _translator(clean_env, TRANSLATOR_PROVIDER="openai", OPENAI_API_KEY="k")

    def handler(request: httpx.Request) -> httpx.Response:
        chunks = [
            {"choices": [{"delta": {"content": "你"}}]},
            {"choices": [{"delta": {"content": "好"}}]},
        ]
        body = "".join(
            f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n" for chunk in chunks
        ) + "data: [DONE]\n\n"
        return httpx.Response(200, content=body.encode("utf-8"))

    async def run():
        translator._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url=translator.base_url
        )
        return [chunk async for chunk in translator.translate_stream_async("hello")]

    assert asyncio.run(run()) == ["你", "好"]


def test_missing_base_url_is_reported(clean_env):
    translator = _translator(clean_env, TRANSLATOR_PROVIDER="custom")
    with pytest.raises(ValueError):
        _ = translator.client
def test_openai_asr_posts_multipart_and_parses_language(clean_env):
    from backend.asr.openai_compat import OpenAICompatibleASR

    clean_env.setenv("ASR_BACKEND", "openai")
    clean_env.setenv("ASR_API_KEY", "k")
    clean_env.setenv("ASR_MODEL", "whisper-1")
    reload_config()
    engine = OpenAICompatibleASR()
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        body = request.read()
        seen["body"] = body
        return httpx.Response(200, json={"text": " 你好 ", "language": "zh"})

    async def run():
        engine._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=engine.base_url,
            headers={"Authorization": "Bearer k"},
        )
        return await engine.transcribe_async(b"\x00\x00" * 1600)

    assert asyncio.run(run()) == ("你好", "zh", 1.0)
    assert seen["path"].endswith("/audio/transcriptions")
    assert b'name="model"' in seen["body"]
    assert b"verbose_json" in seen["body"]


def test_openai_asr_handles_plain_text_response(clean_env):
    from backend.asr.openai_compat import OpenAICompatibleASR

    clean_env.setenv("ASR_BACKEND", "siliconflow")
    clean_env.setenv("ASR_API_KEY", "k")
    reload_config()
    engine = OpenAICompatibleASR()

    async def run():
        engine._client = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, text="hello world")),
            base_url=engine.base_url,
        )
        return await engine.transcribe_async(b"\x00\x00" * 1600)

    assert asyncio.run(run()) == ("hello world", None, 0.0)
