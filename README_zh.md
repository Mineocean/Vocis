# Vocis (声幕)

实时语音识别 + AI 翻译字幕叠加层，支持说话人区分。

[English](README.md) | [许可证: MIT](LICENSE) | [v0.5 更新说明](RELEASE_NOTES_v0.5.0.md)

---

## Vocis 是什么？

Vocis 实时捕获系统音频（YouTube、会议、游戏），识别语音、判断**是谁在说话**，并显示翻译字幕叠加层。适合观看外语内容、参加国际会议或学习语言。

## 功能特点

- **实时音频捕获** — WASAPI Loopback 直接捕获系统音频，无需虚拟声卡
- **语音活动检测** — Silero VAD (ONNX) 精准切分语音段
- **多 ASR 后端** — MiMo 云端、任意 OpenAI 兼容 /audio/transcriptions（OpenAI / Groq / 硅基流动 / 自定义）、本地 faster-whisper、本地 sherpa-onnx 流式中文、Mock 测试
- **任意 OpenAI 兼容翻译提供商** — DeepSeek、OpenAI、Moonshot/Kimi、通义千问（DashScope）、智谱 GLM、Groq、硅基流动、Ollama 本地模型、自定义端点；流式翻译 + 上句上下文 + 缓存
- **说话人分离** — 每个 VAD 语音段提取说话人嵌入（sherpa-onnx CAM++ 192 维）并在线聚类，字幕带彩色「说话人 1/2/3」标签；另有零下载的 MFCC 聚类兜底后端
- **现代化悬浮字幕** — 深色玻璃卡片、说话人彩色胶囊、淡入淡出、可拖拽/缩放、始终置顶
- **系统托盘** — 最小化到托盘，热键暂停/恢复、切换语言

## 下载

从 [GitHub Releases](https://github.com/Mineocean/Vocis/releases) 下载最新的 Vocis.exe。

## 快速开始

1. 下载 Vocis.exe 并运行 — 首次向导会让你填翻译 API Key
2. 系统音频自动捕获，字幕以叠加层显示
3. 打开设置可切换提供商、选择本地/云端 ASR、开启说话人标签

## 热键

| 热键 | 功能 |
|------|------|
| Ctrl+Shift+S | 暂停 / 恢复 |
| Ctrl+Shift+L | 切换 ASR 语言 |

## 配置

设置保存在可执行文件旁边的 .env（GUI 会自动写入）。主要选项：

    # 翻译：提供商 id 见 backend/providers/presets.py
    TRANSLATOR_PROVIDER=deepseek
    TRANSLATOR_API_KEY=你的密钥
    # BASE_URL / MODEL 留空 = 用提供商预设
    TRANSLATOR_BASE_URL=
    TRANSLATOR_MODEL=
    TARGET_LANGUAGE=中文

    # ASR：whisper | sherpa | mimo | openai | groq | siliconflow | mock
    ASR_BACKEND=sherpa
    SHERPA_MODEL_PATH=models/sherpa-streaming-zh-14M
    WHISPER_MODEL_PATH=models/faster-whisper-base
    SOURCE_LANGUAGE=auto
    SKIP_TRANSLATE_SAME_LANG=true

    # 说话人分离（首次启用自动下载约 27MB 模型）
    DIARIZATION_ENABLED=true
    DIARIZATION_BACKEND=sherpa   # 或 cluster（零下载）
    DIARIZATION_MAX_SPEAKERS=4

旧版 .env 继续可用：选中对应提供商/后端时会读取 DEEPSEEK_API_KEY、DEEPSEEK_BASE_URL、MIMO_API_KEY。

完整选项见 [.env.example](.env.example)。

## 从源码构建

    pip install -e ".[dev]"
    pip install ".[sherpa]"   # 可选：本地流式 ASR + 神经说话人分离
    pip install pyinstaller
    pyinstaller vocis.spec --noconfirm

## 架构

    音频捕获 → VAD → ASR → 说话人嵌入 → 翻译 → GUI
       ↓        ↓      ↓         ↓            ↓       ↓
    sounddevice Silero whisper/  CAM++/MFCC  OpenAI    PySide6
     (WASAPI)  (ONNX) sherpa/   在线聚类     兼容端点   (叠加层)
                      云端

- backend/providers/presets.py — 所有提供商端点/模型的一张表
- backend/translator.py — OpenAI 兼容聊天补全翻译客户端
- backend/asr/ — ASR 后端插件注册表
- backend/diarization/ — 说话人嵌入 + 在线聚类注册表
- backend/pipeline.py — 异步 采集/VAD/ASR/说话人/翻译 流水线

## 许可证

本项目基于 [MIT 许可证](LICENSE) 开源。
