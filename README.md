# Vocis · 声幕

实时语音识别 + AI 翻译屏幕字幕工具。

看外语视频/直播时，自动捕获系统音频，识别语音内容并翻译成目标语言，以悬浮字幕形式显示在屏幕上。

## 功能

- **实时语音识别** — 支持 MiMo 云端 API 和本地 Whisper 模型
- **AI 翻译** — 基于 DeepSeek API，带上下文记忆的整句翻译
- **悬浮字幕** — 半透明置顶窗口，可拖拽移动、调整大小
- **系统音频捕获** — WASAPI Loopback 直接抓取扬声器输出，无需 Stereo Mix
- **全局热键** — `Ctrl+Shift+S` 暂停/继续，`Ctrl+Shift+L` 切换语言
- **系统托盘** — 最小化到托盘，右键菜单控制

## 安装

### 直接运行（推荐）

从 [Releases](https://github.com/Mineocean/Vocis/releases) 下载最新版 `Vocis.exe`，双击运行。

### 从源码运行

```bash
git clone https://github.com/Mineocean/Vocis.git
cd Vocis
pip install -r requirements.txt  # 或使用 pyproject.toml
python main.py
```

## 配置

首次运行会弹出登录窗口，输入 API Key：

| 服务 | 用途 | 获取地址 |
|------|------|----------|
| MiMo ASR | 语音识别 | [platform.xiaomimimo.com](https://platform.xiaomimimo.com) |
| DeepSeek | 翻译 | [platform.deepseek.com](https://platform.deepseek.com) |

也可复制 `.env.example` 为 `.env` 手动配置。

## 技术栈

- Python 3.11+
- PySide6 — GUI 框架
- MiMo-V2.5-ASR — 语音识别（云端/本地）
- DeepSeek API — 翻译服务
- WebRTC VAD — 语音活动检测
- WASAPI Loopback — Windows 系统音频捕获

## 项目结构

```
├── main.py              # 入口，主窗口
├── backend/
│   ├── config.py        # 配置管理
│   ├── pipeline.py      # 主流水线（音频→VAD→ASR→翻译→字幕）
│   ├── capture.py       # 音频捕获
│   ├── vad.py           # 语音活动检测
│   ├── asr.py           # ASR 引擎（MiMo/Whisper/Mock）
│   ├── translator.py    # DeepSeek 翻译客户端
│   └── wasapi_loopback.py  # WASAPI Loopback 实现
├── gui/
│   ├── overlay.py       # 字幕叠加层 + 系统托盘
│   ├── login.py         # 登录窗口
│   └── settings.py      # 设置面板
└── assets/              # 图标资源
```

## 许可证

课程设计作品，仅供学习交流。
