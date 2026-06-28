# Vocis (声幕)

Real-time speech recognition + AI translation subtitle overlay.

[中文文档](README_zh.md)

---

## What is Vocis?

Vocis captures system audio (YouTube, meetings, games), recognizes speech in real-time, and displays translated subtitles as an overlay. Perfect for watching foreign content, attending international meetings, or learning languages.

## Features

- **Real-time audio capture** — WASAPI Loopback captures system audio without virtual cables
- **Voice Activity Detection** — Silero VAD (ONNX) detects speech segments accurately
- **Multiple ASR backends** — MiMo (cloud), Whisper (local GPU/CPU), Mock (testing)
- **AI translation** — DeepSeek API with streaming translation and context awareness
- **Subtitle overlay** — Transparent always-on-top window, draggable, configurable
- **System tray** — Minimize to tray, hotkeys for pause/resume and language switching

## Quick Start

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

## Hotkeys

| Hotkey | Action |
|--------|--------|
| `Ctrl+Shift+S` | Pause / Resume |
| `Ctrl+Shift+L` | Switch ASR language |

## Configuration

Settings are stored in `.env` file. Key options:

```env
MIMO_API_KEY=your-mimo-key
DEEPSEEK_API_KEY=your-deepseek-key
SOURCE_LANGUAGE=auto
TARGET_LANGUAGE=中文
ASR_BACKEND=mimo
```

## Building

```bash
pip install pyinstaller
pyinstaller vocis.spec --noconfirm
```

## Architecture

```
Audio Capture → VAD → ASR → Translation → GUI
     ↓           ↓      ↓        ↓          ↓
  sounddevice  Silero  MiMo/   DeepSeek   PySide6
  (WASAPI)    (ONNX)  Whisper   API      (Overlay)
```
