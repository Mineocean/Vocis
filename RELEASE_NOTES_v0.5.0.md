# Vocis v0.5.0 — 多提供商 + 说话人分离 + 全新界面

## 亮点

### 1. 翻译不再绑定 DeepSeek
一个 OpenAI 兼容客户端覆盖全部主流端点，换提供商只需要改三行配置：

| 提供商 | 键 | 默认端点 |
|---|---|---|
| DeepSeek | `deepseek` | api.deepseek.com |
| OpenAI | `openai` | api.openai.com/v1 |
| Moonshot / Kimi | `moonshot` | api.moonshot.cn/v1 |
| 通义千问 / 百炼 | `qwen` | dashscope.aliyuncs.com/compatible-mode/v1 |
| 智谱 GLM | `zhipu` | open.bigmodel.cn/api/paas/v4 |
| Groq | `groq` | api.groq.com/openai/v1 |
| 硅基流动 | `siliconflow` | api.siliconflow.cn/v1 |
| Ollama 本地 | `ollama` | localhost:11434/v1 |
| 自定义 | `custom` | 任意 OpenAI 兼容地址 |

- 提供商专属字段（如 DeepSeek 的 `thinking`）只发给对应提供商，不会再让其他端点 400
- Base URL 归一化只补根路径的 `/v1`，不再改坏智谱 `/api/paas/v4`、DashScope `/compatible-mode/v1`
- 旧 `.env` 的 `DEEPSEEK_*` 继续生效，无需迁移

### 2. 云端 ASR 也支持任意 OpenAI 兼容端点
新增 `openai` / `groq` / `siliconflow` 三个云端后端（`/audio/transcriptions`），
与本地 Whisper / Sherpa 并存：

```env
ASR_BACKEND=groq
ASR_API_KEY=gsk_...
ASR_MODEL=whisper-large-v3-turbo
```

### 3. 说话人分离（谁在说）
每个 VAD 语音段做一次说话人嵌入 + 在线余弦聚类，字幕带彩色「说话人 N」标签：

- **sherpa（推荐）**：CAM++ 说话人嵌入（192 维），首次启用自动下载约 27MB 模型
  - 实测 3 位真实说话人、交叉发言：同一人余弦相似度 0.65–0.88，不同人 < 0.46，
    阈值 0.55 全部分对
  - 每段嵌入约 25–75ms，跑在工作线程，不阻塞字幕链路
- **cluster（零下载）**：MFCC 统计特征 + 聚类，无模型依赖，精度较低，作为兜底
- 短语音段沿用上一位说话人，避免抖动；段内所有字幕共用同一标签
- 设置里可调「最多人数」「相似度阈值」，主窗口有说话人图例与一键重置

```env
DIARIZATION_ENABLED=true
DIARIZATION_BACKEND=sherpa
DIARIZATION_MAX_SPEAKERS=4
```

### 4. 性能与稳定性
- Silero VAD 推理移出事件循环线程（`asyncio.to_thread`），字幕链路不再被每个 100ms
  音频块的 ONNX 推理拖住
- 增量识别段结束时必然发出最终帧：翻译失败也不会吞掉原文
- `apply_config()` 现在会按需重建翻译客户端 / ASR / 说话人分离，换提供商后立即生效，
  翻译缓存也不会串味
- 段落模式下每段先判说话人再识别，说话人与字幕一一对应

### 5. 全新界面
- 统一深色主题（`assets/style.qss`）、圆角玻璃卡片、强调色、完整中英文案
- 设置对话框：翻译 / 语音识别 / 说话人 / 显示 / 音频 / 关于，每个云端后端带连接测试
- 悬浮字幕：说话人彩色胶囊、淡入淡出、流式更新不抖动
- 主窗口：提供商摘要、说话人图例、暂停/继续、重置说话人

## 升级注意

- 依赖未变化（`sherpa-onnx` 仍是可选 extra：`pip install "vocis[sherpa]"`）
- 说话人分离默认关闭，开启后会下载一次模型（也可以手动放到 `models/diarization/`
  或设置 `DIARIZATION_MODEL_PATH`）
- `.env` 新增键见 `.env.example`；旧键保持兼容
