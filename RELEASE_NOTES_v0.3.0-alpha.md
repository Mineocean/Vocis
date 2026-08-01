# Vocis v0.3.0-alpha

**Previous Version:** v0.2.2

> Alpha 版：核心链路已通，实时翻译为实验特性，可能存在断句/识别不稳定的情况。

---

## 新功能

- **实时翻译（方案 D：滚动累积 + 文本差分）** — 不再等整段说完，每 1.2s 识别本段累积音频，差分出新增文本，按句子边界增量翻译，字幕边讲边出。
  - 配置项（`.env`）：`INCREMENTAL_ENABLED`（默认 `true`）、`INCREMENTAL_INTERVAL`（默认 `1.2`）、`INCREMENTAL_MAX_SECONDS`（默认 `5.0`）。
- **主控制面板** — 双击托盘图标打开：状态显示、暂停/继续、源语言切换、设置/日志/退出入口。
- **界面语言跟随系统** — 自动检测 Windows 语言（中文/英文），可在设置中切换（`UI_LANGUAGE`）。

## 关键修复

- **VAD 检测完全失效** — Silero VAD v5 ONNX 必须拼接前 64 采样 context（输入 576 而非 512），否则永远检测不到语音。修复后语音段正确触发。
- **Loopback 抓不到系统声音** — `GetDefaultAudioEndpoint` 会话参数由 `eConsole` 改为 `eMultimedia`，现在能抓到播放器/浏览器多媒体会话的音频。
- **暂停时内存泄漏** — 采集队列改有界队列，暂停时停止采集并清空缓冲。
- **`.env` 找不到（打包版）** — 配置文件路径改用 `app_dir()`（exe 所在目录）。
- **默认 ASR 后端矛盾** — 统一为 `mimo`（与 `.env.example`/README 一致）。
- **更新检查跨线程 Qt** — 通知回调改经主线程执行。
- **悬浮窗原文/译文重叠** — 改用 `heightForWidth` 精确计算换行高度。

## 其他

- CI 强化：mypy 不再 `continue-on-error`，覆盖 `gui/`，触发分支含 `dev`。
- 死代码清理（`read_nonblocking`、`_vcall`、`_update_status` 等）。
- 设置页"Test"按钮改为真实连通性测试（MiMo / DeepSeek）。
- GPU 检测不再覆盖用户已选择的设备。
- 移除过时的 `.codewhale/instructions.md`。
