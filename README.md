# Vocis (声幕)

Real-time speech recognition + AI translation subtitle overlay — with speaker labels.

[中文文档](README_zh.md) | [License: MIT](LICENSE) | [Release notes v0.5](RELEASE_NOTES_v0.5.0.md)

---

## What is Vocis?

Vocis captures system audio (YouTube, meetings, games), recognizes speech in real-time,
identifies **who is speaking**, and shows translated subtitles as an overlay. Perfect for
watching foreign content, attending international meetings, or learning languages.

## Features

- **Real-time audio capture** — WASAPI Loopback, no virtual cable needed
- **Voice Activity Detection** — Silero VAD (ONNX), speech segments cut accurately
- **Multiple ASR backends** — MiMo (cloud), OpenAI-compatible /audio/transcriptions
  (OpenAI, Groq, SiliconFlow, custom), faster-whisper (local), sherpa-onnx streaming
  (local, fastest for Chinese), Mock (testing)
- **Any OpenAI-compatible translation provider** — DeepSeek, OpenAI, Moonshot/Kimi,
  Qwen/DashScope, Zhipu GLM, Groq, SiliconFlow, Ollama (local), or a custom endpoint.
  Streaming translation with one-sentence context and caching
- **Speaker diarization** — every VAD segment gets a neural speaker embedding (CAM++
  192-d via sherpa-onnx) and is assigned to an online speaker cluster, so subtitles are
  tagged Speaker 1 / 2 / 3 with a colour per speaker. A zero-download MFCC fallback
  backend is included
- **Modern overlay UI** — dark glass card, coloured speaker chip, fade in/out,
  draggable/resizable, always-on-top
- **System tray** — hotkeys for pause/resume and language switching

## Download

Download the latest Vocis.exe from
[GitHub Releases](https://github.com/Mineocean/Vocis/releases).

## Quick Start

1. Download Vocis.exe and run it — the first-run wizard asks for a translation API key
2. System audio is captured automatically; subtitles appear as an overlay
3. Open Settings to pick a provider, a local/cloud ASR backend, and enable speaker labels

## Hotkeys

| Hotkey | Action |
|--------|--------|
| Ctrl+Shift+S | Pause / Resume |
| Ctrl+Shift+L | Switch ASR language |

## Configuration

Settings live in .env next to the executable (the GUI writes them). Key options:

    # Translation: provider id from backend/providers/presets.py
    TRANSLATOR_PROVIDER=deepseek
    TRANSLATOR_API_KEY=your-key
    # Leave BASE_URL / MODEL empty to use the provider preset
    TRANSLATOR_BASE_URL=
    TRANSLATOR_MODEL=
    TARGET_LANGUAGE=中文

    # ASR: whisper | sherpa | mimo | openai | groq | siliconflow | mock
    ASR_BACKEND=sherpa
    SHERPA_MODEL_PATH=models/sherpa-streaming-zh-14M
    WHISPER_MODEL_PATH=models/faster-whisper-base
    SOURCE_LANGUAGE=auto
    SKIP_TRANSLATE_SAME_LANG=true

    # Speaker diarization (downloads a ~27 MB model on first use)
    DIARIZATION_ENABLED=true
    DIARIZATION_BACKEND=sherpa   # or: cluster (no download)
    DIARIZATION_MAX_SPEAKERS=4

Legacy .env files keep working: DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, MIMO_API_KEY
are still read when the matching provider/backend is selected.

See [.env.example](.env.example) for every option.

## Building from Source

    pip install -e ".[dev]"
    pip install ".[sherpa]"   # optional: local streaming ASR + neural diarization
    pip install pyinstaller
    pyinstaller vocis.spec --noconfirm

## Architecture

    Audio Capture → VAD → ASR → Speaker embedding → Translation → GUI
         ↓           ↓      ↓          ↓                ↓           ↓
      sounddevice  Silero  whisper/  CAM++/MFCC      OpenAI-     PySide6
      (WASAPI)    (ONNX)  sherpa/   (online          compatible  (overlay)
                           cloud     clustering)      endpoint

- backend/providers/presets.py — every provider endpoint/model in one table
- backend/translator.py — OpenAI-compatible chat-completions translator
- backend/asr/ — ASR backend plugin registry
- backend/diarization/ — speaker embedding + online clustering registry
- backend/pipeline.py — async capture/VAD/ASR/diarization/translation pipeline

## License

MIT — see [LICENSE](LICENSE).
