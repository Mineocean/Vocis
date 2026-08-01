# Vocis v0.2.2

**Previous Version:** v0.2.1

---

## 新功能

- **自动更新检查** — 启动时后台检查 GitHub Releases，发现新版本时在系统托盘弹出提示（可手动触发工作流）。

## Bug 修复

- **线程安全** — 修复事件循环/线程交互中的竞态与崩溃保护问题；热键路由改为回主线程执行。
- **事件循环阻塞** — 同步 ASR 转写改为在线程池中执行，避免阻塞异步事件循环。
- **Whisper 兼容性** — `assert` 改为 `RuntimeError`，兼容 `python -O` 运行。
- **API 适配** — 修复 MiMo 请求 `extra_body` 封装、语言循环切换、默认设备 ID 0。
- **资源清理** — 移除废弃 API、未释放资源与死代码，减少无意义日志。

---

**Full Changelog:** https://github.com/Mineocean/Vocis/compare/v0.2.1...v0.2.2
