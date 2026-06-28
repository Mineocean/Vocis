# Ubiquitous Language

## 音频处理

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **AudioChunk** | 从系统音频捕获的一段原始音频数据（float32 numpy 数组） | 音频块、音频片段、audio block |
| **PCM** | 脉冲编码调制的原始音频字节数据（int16），用于 VAD 和 ASR 输入 | 原始音频、pcm bytes |
| **Sample Rate** | 每秒音频采样数，项目标准为 16000Hz | 采样率、sr |

## 语音识别

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **ASR** | 自动语音识别，将音频转为文本 | 语音转文字、STT、speech-to-text |
| **VAD** | 语音活动检测，将连续音频流切分为语音段 | 语音检测、voice activity detection |
| **Speech Segment** | VAD 输出的一段完整语音（从开始到静音结束） | 语音段、语音片段 |
| **Transcription** | ASR 引擎对一段语音的识别结果文本 | 识别结果、转写文本 |

## 翻译

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Translation** | 翻译引擎对原文的目标语言输出 | 译文、翻译结果 |
| **Context** | 翻译时携带的上一句原文+译文，用于保持语义连贯 | 上下文、翻译上下文 |
| **Target Language** | 翻译的目标语言（如中文、English、日本語） | 目标语言、输出语言 |
| **Source Language** | ASR 识别的语言（auto/zh/en/ja） | 源语言、识别语言 |

## 字幕显示

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Subtitle** | 屏幕上显示的一对原文+译文字幕 | 字幕、字幕条 |
| **Overlay** | 半透明置顶悬浮窗口，用于显示字幕 | 字幕叠加层、悬浮窗、字幕窗口 |
| **Fade Out** | 字幕在设定时间后自动隐藏 | 自动消失、字幕隐藏 |
| **Position** | 字幕在屏幕上的位置（bottom/center/top） | 字幕位置、显示位置 |

## 系统集成

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Pipeline** | 主流水线，串联音频捕获→VAD→ASR→翻译→字幕输出 | 流水线、处理链路 |
| **WASAPI Loopback** | Windows 音频 API 的回环模式，直接从扬声器抓取系统音频 | 系统音频捕获、loopback |
| **Hotkey** | 全局热键，Ctrl+Shift+S 启停，Ctrl+Shift+L 切语言 | 快捷键、热键 |
| **Tray** | 系统托盘图标及右键菜单 | 托盘、系统托盘 |

## 配置

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Config** | 应用配置单例，从 .env 文件和环境变量加载 | 配置、设置 |
| **API Key** | 调用云端服务的认证密钥（MiMo/DeepSeek） | 密钥、api key |
| **Backend** | ASR 引擎类型（mimo/whisper/mock） | 后端、asr backend |

## Relationships

- **Pipeline** 包含 **AudioCapture** → **VAD** → **ASR** → **Translator** → **Overlay**
- **VAD** 将 **AudioChunk** 切分为多个 **Speech Segment**
- **ASR** 将 **Speech Segment** 转为 **Transcription**
- **Translator** 将 **Transcription** 转为 **Translation**，可携带 **Context**
- **Subtitle** = **Transcription** + **Translation**
- **Overlay** 显示 **Subtitle**，支持 **Position** 配置和 **Fade Out**

## Example dialogue

> **Dev:** "用户切了语言之后，**Pipeline** 需要重置什么？"
>
> **Domain Expert:** "只需要更新 **ASR** 的 **Source Language**。**Translator** 的 **Target Language** 不变，**Context** 也不用重置——除非用户主动点「重置翻译上下文」。"
>
> **Dev:** "那 **VAD** 呢？切换语言对它有影响吗？"
>
> **Domain Expert:** "没有。**VAD** 只看音频能量和频谱，不关心语言。它输出的 **Speech Segment** 是纯 PCM 字节，跟语言无关。"
>
> **Dev:** "明白了。所以切语言的链路是：热键 → `pipeline.set_language()` → `asr.set_language()`，其他模块不动。"
>
> **Domain Expert:** "对。而且 `set_language('auto')` 会让 **ASR** 自动检测，不需要用户指定具体语种。"

## Flagged ambiguities

- "后端" 在代码中同时指 **Backend**（ASR 引擎类型）和 Python 的 `backend/` 包目录——语境不同含义不同，讨论架构时需区分。
- "语言" 在配置中同时出现 `SOURCE_LANGUAGE`（ASR 识别语言）和 `TARGET_LANGUAGE`（翻译目标语言）——建议对话中始终用 **Source Language** / **Target Language** 区分。
