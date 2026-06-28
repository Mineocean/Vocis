# Vocis (声幕)

实时语音识别 + AI 翻译字幕叠加层。

[English](README.md) | [许可证: MIT](LICENSE)

---

## Vocis 是什么？

Vocis 实时捕获系统音频（YouTube、会议、游戏），识别语音并显示翻译字幕叠加层。适合观看外语内容、参加国际会议或学习语言。

## 功能特点

- **实时音频捕获** — WASAPI Loopback 直接捕获系统音频，无需虚拟声卡
- **语音活动检测** — Silero VAD (ONNX) 精准检测语音段
- **多 ASR 后端** — MiMo（云端）、Whisper（本地 GPU/CPU）、Mock（测试）
- **AI 翻译** — DeepSeek API，支持流式翻译和上下文感知
- **字幕叠加层** — 透明置顶窗口，可拖拽，可配置
- **系统托盘** — 最小化到托盘，热键暂停/恢复和切换语言

## 下载

从 [GitHub Releases](https://github.com/Mineocean/Vocis/releases) 下载最新的 `Vocis.exe`。

## 快速开始

1. 从 [Releases](https://github.com/Mineocean/Vocis/releases) 下载 `Vocis.exe`
2. 双击运行 — 首次运行向导会引导你配置 API 密钥
3. 自动捕获系统音频，字幕以叠加层形式显示

## 热键

| 热键 | 功能 |
|------|------|
| `Ctrl+Shift+S` | 暂停 / 恢复 |
| `Ctrl+Shift+L` | 切换 ASR 语言 |

## 配置

设置存储在可执行文件旁边的 `.env` 文件中。主要选项：

```env
MIMO_API_KEY=你的MiMo密钥
DEEPSEEK_API_KEY=你的DeepSeek密钥
SOURCE_LANGUAGE=auto
TARGET_LANGUAGE=中文
ASR_BACKEND=mimo
```

## 从源码构建

```bash
pip install -e ".[dev]"
pip install pyinstaller
pyinstaller vocis.spec --noconfirm
```

## 架构

```
音频捕获 → VAD → ASR → 翻译 → GUI
   ↓        ↓      ↓      ↓      ↓
sounddevice Silero MiMo/ DeepSeek PySide6
 (WASAPI)  (ONNX) Whisper  API   (叠加层)
```

## 许可证

本项目基于 [MIT 许可证](LICENSE) 开源。
