# Vocis (声幕)

Real-time speech recognition + AI translation subtitle overlay.

[English](#english) | [中文](#中文)

---

## English

### What is Vocis?

Vocis captures system audio (YouTube, meetings, games), recognizes speech in real-time, and displays translated subtitles as an overlay. Perfect for watching foreign content, attending international meetings, or learning languages.

### Features

- **Real-time audio capture** — WASAPI Loopback captures system audio without virtual cables
- **Voice Activity Detection** — Silero VAD (ONNX) detects speech segments accurately
- **Multiple ASR backends** — MiMo (cloud), Whisper (local GPU/CPU), Mock (testing)
- **AI translation** — DeepSeek API with streaming translation and context awareness
- **Subtitle overlay** — Transparent always-on-top window, draggable, configurable
- **System tray** — Minimize to tray, hotkeys for pause/resume and language switching

### Quick Start

1. Install Python 3.11+
2. Install dependencies:
   ```bash
   pip install -e .
   ```
3. Run Vocis:
   ```bash
   python main.py
   ```
4. First-run wizard guides API key configuration

### Hotkeys

| Hotkey | Action |
|--------|--------|
| `Ctrl+Shift+S` | Pause / Resume |
| `Ctrl+Shift+L` | Switch ASR language |

### Configuration

Settings are stored in `.env` file. Key options:

```env
MIMO_API_KEY=your-mimo-key
DEEPSEEK_API_KEY=your-deepseek-key
SOURCE_LANGUAGE=auto
TARGET_LANGUAGE=中文
ASR_BACKEND=mimo
```

### Building

```bash
pip install pyinstaller
pyinstaller vocis.spec --noconfirm
```

### Architecture

```
Audio Capture → VAD → ASR → Translation → GUI
     ↓           ↓      ↓        ↓          ↓
  sounddevice  Silero  MiMo/   DeepSeek   PySide6
  (WASAPI)    (ONNX)  Whisper   API      (Overlay)
```

---

## 中文

### Vocis 是什么？

Vocis 实时捕获系统音频（YouTube、会议、游戏），识别语音并显示翻译字幕叠加层。适合观看外语内容、参加国际会议或学习语言。

### 功能特点

- **实时音频捕获** — WASAPI Loopback 直接捕获系统音频，无需虚拟声卡
- **语音活动检测** — Silero VAD (ONNX) 精准检测语音段
- **多 ASR 后端** — MiMo（云端）、Whisper（本地 GPU/CPU）、Mock（测试）
- **AI 翻译** — DeepSeek API，支持流式翻译和上下文感知
- **字幕叠加层** — 透明置顶窗口，可拖拽，可配置
- **系统托盘** — 最小化到托盘，热键暂停/恢复和切换语言

### 快速开始

1. 安装 Python 3.11+
2. 安装依赖：
   ```bash
   pip install -e .
   ```
3. 运行 Vocis：
   ```bash
   python main.py
   ```
4. 首次运行向导引导 API 密钥配置

### 热键

| 热键 | 功能 |
|------|------|
| `Ctrl+Shift+S` | 暂停 / 恢复 |
| `Ctrl+Shift+L` | 切换 ASR 语言 |

### 配置

设置存储在 `.env` 文件中。主要选项：

```env
MIMO_API_KEY=你的MiMo密钥
DEEPSEEK_API_KEY=你的DeepSeek密钥
SOURCE_LANGUAGE=auto
TARGET_LANGUAGE=中文
ASR_BACKEND=mimo
```

### 构建

```bash
pip install pyinstaller
pyinstaller vocis.spec --noconfirm
```

### 架构

```
音频捕获 → VAD → ASR → 翻译 → GUI
   ↓        ↓      ↓      ↓      ↓
sounddevice Silero MiMo/ DeepSeek PySide6
 (WASAPI)  (ONNX) Whisper  API   (叠加层)
```
