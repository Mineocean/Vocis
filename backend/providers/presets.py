"""OpenAI-compatible provider presets.

两个注册表：

- TRANSLATION_PRESETS: 翻译用的 OpenAI 兼容 /chat/completions 端点
- ASR_PRESETS:         语音识别用的端点（mimo = 私有 chat 协议，其余 = /audio/transcriptions）

新增提供商只需要在这里加一条，不需要改客户端代码。
preset 字段：
  name / name_zh   展示名
  base_url         默认 API 根地址（含版本段，不再自动补 /v1）
  models           推荐模型（仅用于设置界面下拉）
  default_model    默认模型
  protocol         "openai" | "mimo"（ASR 专用）
  key_env          API Key 的旧版环境变量名（向后兼容）
  base_url_env     旧版 base_url 环境变量名（向后兼容）
  model_env        旧版 model 环境变量名（向后兼容）
  extra_body       该提供商特有的请求体字段
  requires_key     是否必须填 Key（本地 Ollama 不需要）
"""

TRANSLATION_PRESETS: dict[str, dict] = {
    "deepseek": {
        "name": "DeepSeek",
        "name_zh": "DeepSeek 深度求索",
        "base_url": "https://api.deepseek.com",
        "models": ["deepseek-v4-pro", "deepseek-chat", "deepseek-reasoner"],
        "default_model": "deepseek-v4-pro",
        "key_env": "DEEPSEEK_API_KEY",
        "base_url_env": "DEEPSEEK_BASE_URL",
        "model_env": "DEEPSEEK_MODEL",
        # DeepSeek 专有：显式关闭思考，翻译场景只要文本
        "extra_body": {"thinking": {"type": "disabled"}},
        "requires_key": True,
    },
    "openai": {
        "name": "OpenAI",
        "name_zh": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1"],
        "default_model": "gpt-4o-mini",
        "key_env": "OPENAI_API_KEY",
        "requires_key": True,
    },
    "moonshot": {
        "name": "Moonshot / Kimi",
        "name_zh": "Moonshot 月之暗面 / Kimi",
        "base_url": "https://api.moonshot.cn/v1",
        "models": ["moonshot-v1-8k", "moonshot-v1-32k", "kimi-latest"],
        "default_model": "moonshot-v1-8k",
        "key_env": "MOONSHOT_API_KEY",
        "requires_key": True,
    },
    "qwen": {
        "name": "Qwen / DashScope",
        "name_zh": "通义千问 / 阿里云百炼",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": ["qwen-plus", "qwen-turbo", "qwen-max"],
        "default_model": "qwen-plus",
        "key_env": "DASHSCOPE_API_KEY",
        "requires_key": True,
    },
    "zhipu": {
        "name": "Zhipu GLM",
        "name_zh": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "models": ["glm-4-flash", "glm-4-plus", "glm-4.5"],
        "default_model": "glm-4-flash",
        "key_env": "ZHIPU_API_KEY",
        "requires_key": True,
    },
    "groq": {
        "name": "Groq",
        "name_zh": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
        "default_model": "llama-3.3-70b-versatile",
        "key_env": "GROQ_API_KEY",
        "requires_key": True,
    },
    "siliconflow": {
        "name": "SiliconFlow",
        "name_zh": "硅基流动 SiliconFlow",
        "base_url": "https://api.siliconflow.cn/v1",
        "models": ["Qwen/Qwen2.5-7B-Instruct", "THUDM/glm-4-9b-chat"],
        "default_model": "Qwen/Qwen2.5-7B-Instruct",
        "key_env": "SILICONFLOW_API_KEY",
        "requires_key": True,
    },
    "ollama": {
        "name": "Ollama (local)",
        "name_zh": "Ollama 本地模型",
        "base_url": "http://localhost:11434/v1",
        "models": ["qwen2.5:7b", "qwen3:8b", "llama3.1:8b"],
        "default_model": "qwen2.5:7b",
        "requires_key": False,
    },
    "custom": {
        "name": "Custom (OpenAI-compatible)",
        "name_zh": "自定义（OpenAI 兼容）",
        "base_url": "",
        "models": [],
        "default_model": "",
        "requires_key": False,
    },
}


ASR_PRESETS: dict[str, dict] = {
    "mimo": {
        "name": "MiMo Cloud",
        "name_zh": "MiMo 云端",
        "base_url": "https://api.xiaomimimo.com/v1",
        "models": ["mimo-v2.5-asr"],
        "default_model": "mimo-v2.5-asr",
        "protocol": "mimo",
        "key_env": "MIMO_API_KEY",
        "base_url_env": "MIMO_BASE_URL",
        "model_env": "MIMO_ASR_MODEL",
        "requires_key": True,
    },
    "openai": {
        "name": "OpenAI",
        "name_zh": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "models": ["whisper-1", "gpt-4o-transcribe", "gpt-4o-mini-transcribe"],
        "default_model": "whisper-1",
        "protocol": "openai",
        "key_env": "OPENAI_API_KEY",
        "requires_key": True,
    },
    "groq": {
        "name": "Groq",
        "name_zh": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "models": ["whisper-large-v3-turbo", "whisper-large-v3"],
        "default_model": "whisper-large-v3-turbo",
        "protocol": "openai",
        "key_env": "GROQ_API_KEY",
        "requires_key": True,
    },
    "siliconflow": {
        "name": "SiliconFlow",
        "name_zh": "硅基流动 SiliconFlow",
        "base_url": "https://api.siliconflow.cn/v1",
        "models": ["FunAudioLLM/SenseVoiceSmall"],
        "default_model": "FunAudioLLM/SenseVoiceSmall",
        "protocol": "openai",
        "key_env": "SILICONFLOW_API_KEY",
        "requires_key": True,
    },
    "custom": {
        "name": "Custom (OpenAI-compatible)",
        "name_zh": "自定义（OpenAI 兼容）",
        "base_url": "",
        "models": [],
        "default_model": "",
        "protocol": "openai",
        "requires_key": False,
    },
}

# 本地后端：没有云端预设，但需要出现在设置界面的后端列表里
LOCAL_ASR_BACKENDS = {
    "whisper": {"name": "Whisper (local)", "name_zh": "Whisper 本地", "protocol": "local"},
    "sherpa": {"name": "Sherpa streaming (local)", "name_zh": "Sherpa 流式本地", "protocol": "local"},
    "mock": {"name": "Mock (test)", "name_zh": "Mock 测试", "protocol": "local"},
}


def translation_preset(provider: str) -> dict:
    return TRANSLATION_PRESETS.get(provider or "", TRANSLATION_PRESETS["custom"])


def asr_preset(backend: str) -> dict:
    backend = (backend or "").lower()
    return ASR_PRESETS.get(backend, LOCAL_ASR_BACKENDS.get(backend, ASR_PRESETS["custom"]))
