"""
主控制面板 —— 状态显示、暂停/继续、语言切换、设置入口。

由托盘图标双击左键打开；关闭窗口时隐藏而非退出，保持托盘常驻。
"""

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui.i18n import tr

logger = logging.getLogger(__name__)

LANGS = ["auto", "zh", "en", "ja"]


class MainWindow(QWidget):
    """Vocis 主控制面板。"""

    def __init__(self, tray_manager=None, pipeline=None, subtitle_widget=None):
        super().__init__()
        self.tray_manager = tray_manager
        self.pipeline = pipeline
        self.subtitle_widget = subtitle_widget

        self.setWindowTitle(tr("app_title"))
        self.setFixedSize(380, 300)
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint)

        from backend.config import app_dir
        icon_path = app_dir() / "assets" / "vocis_32.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # ── 标题 ──
        title_row = QHBoxLayout()
        self._status_dot = QLabel("●")
        self._status_dot.setStyleSheet("color: #22c55e; font-size: 16px;")
        self._status_label = QLabel(tr("running"))
        self._status_label.setStyleSheet("font-size: 14px; font-weight: 600;")
        title_row.addWidget(self._status_dot)
        title_row.addWidget(self._status_label)
        title_row.addStretch()
        layout.addLayout(title_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: rgba(128,128,128,0.3);")
        layout.addWidget(sep)

        # ── 语言 ──
        lang_row = QHBoxLayout()
        self._lang_title = QLabel(tr("source_language"))
        lang_row.addWidget(self._lang_title)
        self._lang_combo = QComboBox()
        self._lang_combo.addItems(
            [tr("auto"), tr("chinese_zh"), tr("english_en"), tr("japanese_ja")]
        )
        self._lang_combo.setCurrentIndex(0)
        self._lang_combo.currentIndexChanged.connect(self._on_lang_changed)
        lang_row.addWidget(self._lang_combo)
        lang_row.addStretch()
        layout.addLayout(lang_row)

        # ── 按钮 ──
        self._toggle_btn = QPushButton(tr("pause"))
        self._toggle_btn.clicked.connect(self._toggle)
        layout.addWidget(self._toggle_btn)

        self._settings_btn = QPushButton(tr("settings"))
        self._settings_btn.clicked.connect(self._open_settings)
        layout.addWidget(self._settings_btn)

        self._log_btn = QPushButton(tr("view_log"))
        self._log_btn.clicked.connect(self._open_log)
        layout.addWidget(self._log_btn)

        self._quit_btn = QPushButton(tr("quit"))
        self._quit_btn.clicked.connect(self._quit)
        layout.addWidget(self._quit_btn)

        layout.addStretch()

    # ── 对外 ──

    def retranslate(self):
        """语言切换后刷新界面文案。"""
        self.setWindowTitle(tr("app_title"))
        self._status_label.setText(tr("running") if not self.pipeline or not self.pipeline.is_paused else tr("paused"))
        self._lang_title.setText(tr("source_language"))
        self._lang_combo.setItemText(0, tr("auto"))
        self._lang_combo.setItemText(1, tr("chinese_zh"))
        self._lang_combo.setItemText(2, tr("english_en"))
        self._lang_combo.setItemText(3, tr("japanese_ja"))
        self._settings_btn.setText(tr("settings"))
        self._log_btn.setText(tr("view_log"))
        self._quit_btn.setText(tr("quit"))
        self.refresh_status()

    def refresh_status(self):
        """根据 pipeline 状态刷新 UI。"""
        if not self.pipeline:
            return
        paused = self.pipeline.is_paused
        self._status_dot.setStyleSheet(
            "color: #f59e0b; font-size: 16px;" if paused else "color: #22c55e; font-size: 16px;"
        )
        self._status_label.setText(tr("paused") if paused else tr("running"))
        self._toggle_btn.setText(tr("resume") if paused else tr("pause"))

    def sync_language(self):
        """从当前配置同步语言下拉框。"""
        if not self.pipeline:
            return
        lang = self.pipeline.current_language
        if lang in LANGS:
            self._lang_combo.setCurrentIndex(LANGS.index(lang))

    # ── 内部 ──

    def _on_lang_changed(self, idx: int):
        if self.pipeline:
            self.pipeline.set_language(LANGS[idx])
            logger.info("Language switched to %s", LANGS[idx])

    def _toggle(self):
        if self.tray_manager:
            self.tray_manager._toggle()
        self.refresh_status()

    def _open_settings(self):
        from gui.settings import SettingsDialog
        dlg = SettingsDialog(self)
        if dlg.exec():
            if self.subtitle_widget:
                self.subtitle_widget.apply_settings()
            if self.pipeline:
                self.pipeline.apply_config()
            self.sync_language()
            self.refresh_status()

    def _open_log(self):
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
        if self.tray_manager:
            self.tray_manager._quit()

    def closeEvent(self, event):
        """关闭主窗口时隐藏而非退出，应用驻留托盘。"""
        self.hide()
        event.ignore()
