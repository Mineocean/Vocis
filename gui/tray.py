"""
系统托盘管理 —— 图标、右键菜单、暂停/继续、设置、退出。

职责：
  - 托盘图标显示
  - 右键菜单（暂停、设置、退出）
  - 暂停/继续 pipeline
  - 打开设置面板并同步配置
"""

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from gui.i18n import tr

if TYPE_CHECKING:
    from backend.pipeline import SubtitlePipeline
    from gui.main_window import MainWindow
    from gui.subtitle_widget import SubtitleWidget

logger = logging.getLogger(__name__)


class TrayManager:
    """系统托盘管理器"""

    def __init__(
        self,
        app: QApplication,
        pipeline: "SubtitlePipeline | None" = None,
        subtitle_widget: "SubtitleWidget | None" = None,
        main_window: "MainWindow | None" = None,
    ):
        self.app = app
        self.pipeline = pipeline
        self.subtitle_widget = subtitle_widget
        self.main_window = main_window
        self.tray = QSystemTrayIcon()
        self.tray.setToolTip(tr("tray_tooltip"))
        self.tray.setIcon(self._load_icon())
        self._build_menu()
        # 双击左键显示主面板
        self.tray.activated.connect(self._on_activated)
        self.tray.show()
        from gui.notification import set_tray
        set_tray(self.tray)
        self._status_action = None
        self._current_lang = "auto"
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
        # 注意：menu 与各 action 必须保存为实例属性，否则 PySide6 的 Python
        # 包装对象会被垃圾回收，导致右键菜单项消失。
        self._menu = QMenu()
        self._status_action = QAction("● " + tr("running"))
        self._status_action.setEnabled(False)
        self._menu.addAction(self._status_action)
        self._menu.addSeparator()
        self._toggle_action = QAction(tr("pause"))
        self._toggle_action.triggered.connect(self._toggle)
        self._menu.addAction(self._toggle_action)
        self._menu.addSeparator()
        self._main_action = QAction(tr("show_main_window"))
        self._main_action.triggered.connect(self._show_main_window)
        self._menu.addAction(self._main_action)
        self._settings_action = QAction(tr("settings"))
        self._settings_action.triggered.connect(self._open_settings)
        self._menu.addAction(self._settings_action)
        self._log_action = QAction(tr("view_log"))
        self._log_action.triggered.connect(self._open_log)
        self._menu.addAction(self._log_action)
        self._menu.addSeparator()
        self._quit_action = QAction(tr("quit"))
        self._quit_action.triggered.connect(self._quit)
        self._menu.addAction(self._quit_action)
        self.tray.setContextMenu(self._menu)

    def retranslate(self):
        """语言切换后刷新菜单文案。"""
        self.tray.setToolTip(tr("tray_tooltip"))
        self._status_action.setText("● " + tr("running"))
        self._toggle_action.setText(
            tr("resume") if self.pipeline and self.pipeline.is_paused else tr("pause")
        )
        self._main_action.setText(tr("show_main_window"))
        self._settings_action.setText(tr("settings"))
        self._log_action.setText(tr("view_log"))
        self._quit_action.setText(tr("quit"))
        if self.main_window:
            self.main_window.retranslate()

    def _on_activated(self, reason):
        """双击左键显示主面板（右键菜单由 setContextMenu 自动处理）。"""
        from PySide6.QtWidgets import QSystemTrayIcon
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_main_window()

    def _show_main_window(self):
        """显示主控制面板并同步状态。"""
        if self.main_window:
            self.main_window.sync_language()
            self.main_window.refresh_status()
            self.main_window.show()
            self.main_window.raise_()
            self.main_window.activateWindow()

    def _load_icon(self) -> QIcon:
        from backend.config import app_dir
        p = app_dir() / "assets" / "vocis_tray_32.png"
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
            self._toggle_action.setText(tr("pause"))
        elif self.pipeline:
            self.pipeline.pause()
            self._toggle_action.setText(tr("resume"))
        self._refresh_main_status()

    def _do_toggle(self):
        """Toggle pause/resume on the Qt main thread (called via QTimer.singleShot)."""
        if not self.pipeline:
            return
        if self.pipeline.is_paused:
            self.pipeline.resume()
            self._toggle_action.setText(tr("pause"))
        else:
            self.pipeline.pause()
            self._toggle_action.setText(tr("resume"))
        self._refresh_main_status()

    def _refresh_main_status(self):
        if self.main_window:
            self.main_window.refresh_status()

    def _do_switch(self):
        """Cycle language on the Qt main thread (called via QTimer.singleShot)."""
        if not self.pipeline:
            return
        langs = ["auto", "zh", "en", "ja"]
        try:
            idx = langs.index(self._current_lang)
        except ValueError:
            idx = 0
        next_lang = langs[(idx + 1) % len(langs)]
        self._current_lang = next_lang
        self.pipeline.set_language(next_lang)
        if self.main_window:
            self.main_window.sync_language()
        logger.info("Language switched to %s", next_lang)

    def _open_settings(self):
        from gui.settings import SettingsDialog
        dlg = SettingsDialog()
        if dlg.exec():
            if self.subtitle_widget:
                self.subtitle_widget.apply_settings()
            if self.pipeline:
                self.pipeline.apply_config()
            self.retranslate()

    def _open_log(self):
        """Open log file in default editor."""
        import subprocess
        import sys
        from backend.config import app_dir
        log_path = app_dir() / "logs" / "vocis.log"
        if log_path.exists():
            if sys.platform == "win32":
                subprocess.Popen(["notepad", str(log_path)])
            else:
                subprocess.Popen(["xdg-open", str(log_path)])

    def _quit(self):
        if self.pipeline:
            self.pipeline.stop()
        if self.main_window:
            self.main_window.hide()
        self.tray.hide()
        self.app.quit()
