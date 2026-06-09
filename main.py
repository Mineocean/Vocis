"""
Vocis（声幕）—— 实时语音识别 + AI 翻译屏幕字幕。

入口流程：登录窗口 → 菜单栏 → 全局热键 → 音频流水线 → 字幕叠加。
课程设计要求：面向对象、菜单栏、登录、多种控件。
"""

import logging
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QAction
from PySide6.QtWidgets import (
    QApplication,
    QMessageBox,
    QMenuBar,
    QToolBar,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QLabel,
)

from backend.pipeline import SubtitlePipeline
from backend.config import get_config
from gui.overlay import SubtitleOverlay, SubtitleTray
from gui.login import LoginDialog
from gui.settings import SettingsDialog

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("vocis")


# ── 全局热键 ──────────────────────────────────────────

class HotkeyManager:
    def __init__(self, pipeline: SubtitlePipeline, overlay: SubtitleOverlay):
        self.pipeline = pipeline
        self.overlay = overlay
        self._alt_langs = ["auto", "zh", "en", "ja"]
        self._current_lang_idx = 0

    def start(self):
        import threading
        t = threading.Thread(target=self._listen, daemon=True)
        t.start()
        logger.info("全局热键已注册: Ctrl+Shift+S 启停 | Ctrl+Shift+L 切换语言")

    def _listen(self):
        try:
            from pynput import keyboard

            def toggle():
                if self.pipeline.is_paused:
                    self.pipeline.resume()
                    logger.info("热键：已恢复")
                else:
                    self.pipeline.pause()
                    logger.info("热键：已暂停")

            def switch():
                self._current_lang_idx = (self._current_lang_idx + 1) % len(self._alt_langs)
                lang = self._alt_langs[self._current_lang_idx]
                self.pipeline.set_language(lang)
                logger.info("热键：语言 → %s", lang)

            with keyboard.GlobalHotKeys({
                "<ctrl>+<shift>+s": toggle,
                "<ctrl>+<shift>+l": switch,
            }) as h:
                h.join()
        except ImportError:
            logger.warning("pynput 不可用，热键未启用")
        except Exception:
            logger.exception("热键异常")


# ── 主窗口（含菜单栏 + 工具栏）────────────────────────

class VocisMainWindow(QMainWindow):
    """Vocis 主窗口 —— 包含菜单栏和工具栏（课程设计要求）"""

    def __init__(self, pipeline: SubtitlePipeline, overlay: SubtitleOverlay, tray: SubtitleTray):
        super().__init__()
        self.pipeline = pipeline
        self.overlay = overlay
        self.tray = tray

        self.setWindowTitle("Vocis · 声幕")
        self.resize(300, 200)

        # 图标
        icon_path = Path(__file__).parent / "assets" / "vocis_48.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        # 中央控件
        central = QWidget()
        layout = QVBoxLayout(central)
        info = QLabel(
            "Vocis 已在系统托盘运行\n\n"
            "Ctrl+Shift+S  暂停/继续\n"
            "Ctrl+Shift+L  切换识别语言\n\n"
            "右键托盘图标打开菜单"
        )
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(info)
        self.setCentralWidget(central)

        self._build_menu()
        self._build_toolbar()

    def _build_menu(self):
        menubar = self.menuBar()

        # 文件菜单
        file_menu = menubar.addMenu("文件(&F)")
        settings_action = QAction("设置(&S)", self)
        settings_action.triggered.connect(self._open_settings)
        file_menu.addAction(settings_action)
        file_menu.addSeparator()
        quit_action = QAction("退出(&Q)", self)
        quit_action.triggered.connect(self._quit)
        file_menu.addAction(quit_action)

        # 控制菜单
        ctrl_menu = menubar.addMenu("控制(&C)")
        self._toggle_action = QAction("暂停(&P)", self)
        self._toggle_action.triggered.connect(self._toggle_pipeline)
        ctrl_menu.addAction(self._toggle_action)
        reset_action = QAction("重置翻译上下文(&R)", self)
        reset_action.triggered.connect(self._reset_context)
        ctrl_menu.addAction(reset_action)

        # 帮助菜单
        help_menu = menubar.addMenu("帮助(&H)")
        about_action = QAction("关于(&A)", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _build_toolbar(self):
        toolbar = QToolBar("主工具栏")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        toggle_btn = QAction("⏯ 暂停", self)
        toggle_btn.triggered.connect(self._toggle_pipeline)
        toolbar.addAction(toggle_btn)

        settings_btn = QAction("⚙ 设置", self)
        settings_btn.triggered.connect(self._open_settings)
        toolbar.addAction(settings_btn)

        toolbar.addSeparator()

        quit_btn = QAction("✕ 退出", self)
        quit_btn.triggered.connect(self._quit)
        toolbar.addAction(quit_btn)

    def _toggle_pipeline(self):
        if self.pipeline.is_paused:
            self.pipeline.resume()
            self._toggle_action.setText("暂停(&P)")
        else:
            self.pipeline.pause()
            self._toggle_action.setText("继续(&R)")

    def _open_settings(self):
        dlg = SettingsDialog(self)
        if dlg.exec():
            self.overlay.apply_settings()
            cfg = get_config()
            self.pipeline.asr.set_language(cfg.asr.language)

    def _reset_context(self):
        self.pipeline.reset_context()
        logger.info("翻译上下文已重置")

    def _show_about(self):
        QMessageBox.about(
            self,
            "关于 Vocis",
            "Vocis · 声幕 v0.1.0\n\n"
            "实时语音识别 + AI 翻译屏幕字幕\n\n"
            "技术栈：Python + PySide6 + MiMo ASR + DeepSeek\n"
            "2025 课程设计作品",
        )

    def _quit(self):
        self.pipeline.stop()
        self.tray.tray.hide()
        QApplication.quit()


# ── 主应用 ────────────────────────────────────────────

class VocisApp:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setApplicationName("Vocis")
        self.app.setQuitOnLastWindowClosed(False)

        # HuggingFace 国内镜像加速（首次下载时生效，之后本地缓存）
        import os as _os
        if not _os.environ.get("HF_ENDPOINT"):
            _os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

        # 暗色主题已移除，使用系统默认样式
        # qss_path = Path(__file__).parent / "assets" / "style.qss"
        # if qss_path.exists():
        #     self.app.setStyleSheet(qss_path.read_text(encoding="utf-8"))

        # 登录
        login = LoginDialog()
        if login.exec() != LoginDialog.DialogCode.Accepted:
            sys.exit(0)
        # 登录成功后重新加载配置
        import dotenv
        dotenv.load_dotenv(Path(__file__).parent / ".env", override=True)

        self.overlay = SubtitleOverlay()
        self.pipeline = SubtitlePipeline()
        self.tray = SubtitleTray(self.app, pipeline_control=self.pipeline, overlay=self.overlay)
        self.pipeline.on_subtitle(self.overlay.subtitle_signal.emit)

        self.main_window = VocisMainWindow(self.pipeline, self.overlay, self.tray)
        self.hotkeys = HotkeyManager(self.pipeline, self.overlay)

    def start(self):
        if not self.pipeline.start():
            self.tray.tray.hide()
            sys.exit(1)

        self.hotkeys.start()
        self.main_window.show()
        logger.info("Vocis 已启动")

        self.app.exec()

    def stop(self):
        self.pipeline.stop()


def main():
    app = VocisApp()
    app.app.aboutToQuit.connect(app.stop)
    timer = QTimer()
    timer.start(500)
    timer.timeout.connect(lambda: None)
    app.start()


if __name__ == "__main__":
    main()
