"""
轻量 i18n —— 跟随系统语言，支持 UI_LANGUAGE 覆盖（zh/en）。

不引入 gettext，直接维护中英文映射表，覆盖向导/托盘/设置/主窗口的关键文案。
"""

import os
from typing import Any

_ZH: dict[str, str] = {
    # 通用
    "app_title": "Vocis 声幕",
    # 主窗口
    "running": "运行中",
    "paused": "已暂停",
    "source_language": "源语言：",
    "auto": "自动",
    "chinese_zh": "中文 (zh)",
    "english_en": "英文 (en)",
    "japanese_ja": "日文 (ja)",
    "pause": "暂停",
    "resume": "继续",
    "settings": "设置",
    "view_log": "查看日志",
    "quit": "退出",
    "show_main_window": "显示主窗口",
    # 托盘
    "status_running": "● 运行中",
    "tray_tooltip": "Vocis 声幕",
    # 设置
    "settings_title": "设置",
    "tab_api": "API",
    "tab_language": "语言",
    "tab_display": "显示",
    "tab_audio": "音频",
    "mimo_key": "MiMo ASR Key：",
    "deepseek_key": "DeepSeek Key：",
    "test": "测试",
    "enter_mimo_key": "请输入 MiMo API Key",
    "enter_ds_key": "请输入 DeepSeek API Key",
    "ui_language": "界面语言：",
    "ui_lang_auto": "跟随系统",
    "ui_lang_zh": "中文",
    "ui_lang_en": "English",
    "test_progress": "测试中...",
    "screen_primary": "主屏幕",
    "target_language": "目标语言：",
    "target_lang_placeholder": "中文 / English / 日本語",
    "font_size": "字号：",
    "position": "位置：",
    "screen": "屏幕：",
    "subtitle_duration": "字幕停留时长 (ms)：",
    "permanent": "常驻",
    "stream_translation": "流式翻译（边翻边显示）",
    "audio_devices": "音频设备：",
    "asr_backend": "ASR 后端：",
    "whisper_model": "Whisper 模型：",
    "device": "设备：",
    "whisper_model_path": "Whisper 模型路径：",
    "skip_translate_same_lang": "源语言 = 目标语言时跳过翻译（如中文音频直接显示原文）",
    "gpu_checking": "检测中...",
    "gpu_cuda": "GPU: {name} ({mem} GB)\nCUDA: {cuda}",
    "gpu_cpu_mode": "CPU 模式（每句约 1-2 秒）\nGPU: pip install torch --index-url https://download.pytorch.org/whl/cu126",
    "gpu_no_torch": "PyTorch 未安装。",
    "channels_info": "声道：{channels} | 采样率：{rate} Hz | 接口：{api}",
    # 连接测试
    "test_enter_mimo_key": "请先输入 MiMo API Key。",
    "test_enter_ds_key": "请先输入 DeepSeek API Key。",
    "test_connected": "连接成功。",
    "test_auth_failed": "认证失败 (HTTP {code})。请检查 API Key。",
    "test_http_error": "服务器返回 HTTP {code}: {text}",
    "test_request_failed": "请求失败：{error}",
    "test_ok": "连接成功",
    "test_fail": "连接失败",
    # 向导
    "wizard_title": "Vocis 首次配置",
    "wizard_welcome": "欢迎使用 Vocis",
    "wizard_desc": "实时语音识别 + AI 翻译字幕悬浮窗。\n\n本向导将帮你配置 API Key。\n你可以跳过，稍后在设置中配置。",
    "wizard_api_config": "API 配置",
    "wizard_mimo_group": "MiMo ASR（语音识别）",
    "wizard_mimo_ph": "输入 MiMo API Key（使用 Whisper 时可选）",
    "wizard_ds_group": "DeepSeek（翻译）",
    "wizard_ds_ph": "输入 DeepSeek API Key",
    "wizard_remember": "将 Key 保存到 .env 文件",
    "wizard_complete": "配置完成",
    "wizard_ready": "Vocis 已就绪。\n\n快捷键：\n  Ctrl+Shift+S  暂停 / 继续\n  Ctrl+Shift+L  切换语言\n\n双击托盘图标打开主窗口，右键查看菜单。",
    "wizard_back": "上一步",
    "wizard_next": "下一步",
    "wizard_skip": "跳过",
    "wizard_finish": "完成",
    # 更新通知
    "update_available": "发现新版本 {version}",
    "update_download": "下载：{url}",
    # 日志 / 错误
    "log_view": "查看日志",
}


def _detect_language() -> str:
    """检测系统语言：中文系统返回 zh，否则 en。"""
    override = os.getenv("UI_LANGUAGE", "").strip().lower()
    if override in ("zh", "en"):
        return override
    try:
        import ctypes
        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        if lang_id == 2052 or (0x0400 <= lang_id < 0x0800):
            return "zh"
    except (AttributeError, OSError):
        pass
    return "en"


_language = _detect_language()


def current_language() -> str:
    return _language


def tr(key: str, **kwargs: Any) -> str:
    """返回 key 对应的本地化文本，支持 {placeholder} 格式化。"""
    if _language == "zh":
        text = _ZH.get(key, key)
    else:
        text = key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text


def reload_language():
    """根据环境变量重新检测语言（设置保存后调用）。"""
    global _language
    _language = _detect_language()
