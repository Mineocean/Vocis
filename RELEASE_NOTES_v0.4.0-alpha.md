# Vocis v0.4.0-alpha

**Previous Version:** v0.3.0-alpha

> Alpha 版：核心链路已通，实时字幕为实验特性，可能存在断句/识别不稳定的情况。

---

## 新功能

- **本地语音识别（faster-whisper）** — 不再依赖云端 MiMo，语音识别全部在本机完成（默认 `base` 模型，多语言自动检测），彻底消除 ASR 网络延迟。模型缺失时自动回退 MiMo 云端。
  - 配置项（`.env`）：`ASR_BACKEND`（`whisper`/`sherpa`/`mimo`/`mock`）、`WHISPER_MODEL`、`WHISPER_MODEL_PATH`。
- **sherpa-onnx 流式识别（中文，默认后端）** — 真正的流式 ASR（zipformer int8 流式模型），音频边采集边增量解码，字幕逐字/逐词实时滚动。实测比实时快 25 倍、识别比 whisper base 更准。
  - 配置项：`SHERPA_MODEL_PATH`（默认 `models/sherpa-streaming-zh-14M`）、`STREAM_SENTENCE_CHARS`（按字数切句，默认 12）。
- **中文直出字幕（跳过翻译）** — 源语言等于目标语言时直接显示原文，不再做无意义翻译（`SKIP_TRANSLATE_SAME_LANG`，默认 `true`）。
- **繁体自动转简体** — whisper 输出繁体时自动转简体显示。
- **字幕常显开关** — 设置页新增"永久显示"勾选（`SUBTITLE_DURATION=0`），字幕不再淡出，解决一闪一闪问题。

## 关键修复

- **识别碎片/静音导致的幻觉** — 增量模式加入门禁：短于 0.4s 或纯静音（RMS < 0.005）的片段直接跳过，不再送识别。
- **悬浮窗位置复位** — 用户手动拖拽位置后，下一句更新不再自动复位到配置位置。
- **CI 构建缺模型** — 新增 `scripts/fetch_models.py` 在构建前自动下载 sherpa/whisper 模型，release 版 exe 内置完整模型。
- **CI 测试依赖本地模型** — whisper 相关测试改用临时目录，CI 上不再因缺模型失败。

## 其他

- 新增依赖：`sherpa-onnx`、`opencc-python-reimplemented`（可选 extras：`whisper`/`sherpa`）。
- 测试从 32 个增至 47 个（新增 sherpa 注册/流式/回退、管线按字数切句等）。
- exe 体积增至约 312MB（内置 sherpa + whisper 双模型）。
