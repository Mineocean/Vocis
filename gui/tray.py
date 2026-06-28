"""
系统托盘管理 —— 图标、右键菜单、暂停/继续、设置、退出。

职责：
  - 托盘图标显示
  - 右键菜单（暂停、设置、退出）
  - 暂停/继续 pipeline
  - 打开设置面板并同步配置
"""

import logging
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QAction, QIcon, QPainter, QColor
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu

from backend.config import get_config

if TYPE_CHECKING:
    from backend.pipeline import SubtitlePipeline
    from gui.subtitle_widget import SubtitleWidget

logger = logging.getLogger(__name__)


class TrayManager:
    """系统托盘管理器"""

    def __init__(
        self,
        app: QApplication,
        pipeline: "Optional[SubtitlePipeline]" = None,
        subtitle_widget: "Optional[SubtitleWidget]" = None,
    ):
        self.app = app
        self.pipeline = pipeline
        self.subtitle_widget = subtitle_widget
        self.tray = QSystemTrayIcon()
        self.tray.setToolTip("Vocis")
        self.tray.setIcon(self._load_icon())
        self._build_menu()
        self.tray.show()
        from gui.notification import set_tray
        set_tray(self.tray)
        self._status_action = None
        self._setup_hotkeys()

    def _setup_hotkeys(self):
        """Register global hotkeys in background thread."""
        import threading

        def _listen():
            try:
                from pynput import keyboard

                def toggle():
                    QTimer.singleShot(0, self.tray, self._do_toggle)

                def switch():
                    QTimer.singleShot(0, self.tray, self._do_switch)

                with keyboard.GlobalHotKeys({
                    "<ctrl>+<shift>+s": toggle,
                    "<ctrl>+<shift>+l": switch,
                }) as h:
                    h.join()
            except ImportError:
                logger.warning("pynput not available, hotkeys disabled")
            except Exception:
                logger.exception("Hotkey error")

        t = threading.Thread(target=_listen, daemon=True)
        t.start()
        logger.info("Global hotkeys registered: Ctrl+Shift+S pause/resume | Ctrl+Shift+L switch language")

    def _build_menu(self):
        m = QMenu()
        self._status_action = QAction("● Running")
        self._status_action.setEnabled(False)
        m.addAction(self._status_action)
        m.addSeparator()
        self._toggle_action = QAction("暂停")
        self._toggle_action.triggered.connect(self._toggle)
        m.addAction(self._toggle_action)
        m.addSeparator()
        settings_action = QAction("设置")
        settings_action.triggered.connect(self._open_settings)
        m.addAction(settings_action)
        log_action = QAction("View Log")
        log_action.triggered.connect(self._open_log)
        m.addAction(log_action)
        m.addSeparator()
        quit_action = QAction("退出")
        quit_action.triggered.connect(self._quit)
        m.addAction(quit_action)
        self.tray.setContextMenu(m)

    def _load_icon(self) -> QIcon:
        p = Path(__file__).parent.parent / "assets" / "vocis_tray_32.png"
        if p.exists():
            return QIcon(str(p))
        # 回退：绘制简易图标
        from PySide6.QtGui import QPixmap
        pm = QPixmap(32, 32)
        pm.fill(Qt.GlobalColor.transparent)
        pt = QPainter(pm)
        pt.setBrush(QColor("#18181b"))
        pt.setPen(Qt.PenStyle.NoPen)
        pt.drawRoundedRect(4, 4, 24, 24, 6, 6)
        pt.setPen(QColor("#059669"))
        pt.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        pt.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "V")
        pt.end()
        return QIcon(pm)

    def _toggle(self):
        if self.pipeline and self.pipeline.is_paused:
            self.pipeline.resume()
            self._toggle_action.setText("暂停")
        elif self.pipeline:
            self.pipeline.pause()
            self._toggle_action.setText("继续")

    def _do_toggle(self):
        """Toggle pause/resume on the Qt main thread (called via QTimer.singleShot)."""
        if not self.pipeline:
            return
        if self.pipeline.is_paused:
            self.pipeline.resume()
            self._toggle_action.setText("暂停")
        else:
            self.pipeline.pause()
            self._toggle_action.setText("继续")

    def _do_switch(self):
        """Cycle language on the Qt main thread (called via QTimer.singleShot)."""
        if not self.pipeline:
            return
        langs = ["auto", "zh", "en", "ja"]
        cfg = get_config()
        try:
            idx = langs.index(cfg.asr.language)
        except ValueError:
            idx = 0
        next_lang = langs[(idx + 1) % len(langs)]
        self.pipeline.set_language(next_lang)
        logger.info("Language switched to %s", next_lang)

    def _open_settings(self):
        from gui.settings import SettingsDialog
        dlg = SettingsDialog()
        if dlg.exec():
            if self.subtitle_widget:
                self.subtitle_widget.apply_settings()
            if self.pipeline:
                self.pipeline.apply_config()

    def _update_status(self, status: str):
        """Update tray tooltip with status."""
        self.tray.setToolTip(f"Vocis — {status}")

    def _open_log(self):
        """Open log file in default editor."""
        import subprocess
        import sys
        log_path = Path(__file__).parent.parent / "logs" / "vocis.log"
        if log_path.exists():
            if sys.platform == "win32":
                subprocess.Popen(["notepad", str(log_path)])
            else:
                subprocess.Popen(["xdg-open", str(log_path)])

    def _quit(self):
        if self.pipeline:
            self.pipeline.stop()
        self.tray.hide()
        self.app.quit()
