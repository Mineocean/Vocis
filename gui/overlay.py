"""
GUI —— 可拖拽 / 可调整大小的字幕叠加层 + 系统托盘。

特性：
  - 半透明黑色圆角背景条
  - 鼠标拖拽移动位置
  - 右下角拖拽调整大小
  - 始终置顶
"""

import logging
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer, QPoint, QSize, QRect, Signal, QObject
from PySide6.QtGui import (
    QFont, QAction, QIcon, QPainter, QColor, QPen,
)
from PySide6.QtWidgets import (
    QApplication, QLabel, QSystemTrayIcon, QMenu,
    QVBoxLayout, QWidget,
)

from backend.config import get_config, read_env_file

if TYPE_CHECKING:
    from backend.pipeline import SubtitlePipeline

logger = logging.getLogger(__name__)

HANDLE = 14


class SubtitleOverlay(QWidget):
    """可拖拽移动 + 右下角调整大小的字幕叠加层"""

    FONT_FAMILY = "Microsoft YaHei, Segoe UI, sans-serif"

    # 跨线程安全信号
    subtitle_signal = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Vocis")
        self._dragging = False
        self._resizing = False
        self._drag_start = QPoint()
        self._resize_start = QSize()
        self._hide_delay_ms = 5000
        self._position = "bottom"  # bottom / center / top
        self._screen_index = 0

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.resize(520, 80)

        self._apply_position()

        # ── 内容容器 ──
        self._content = QWidget(self)
        self._content.setStyleSheet(
            "background-color: rgba(0,0,0,0.55); border-radius: 12px;"
        )
        self._content.setMouseTracking(True)

        lay = QVBoxLayout(self._content)
        lay.setContentsMargins(16, 8, 16 + HANDLE, 8)
        lay.setSpacing(1)

        self._orig = QLabel("")
        self._orig.setFont(QFont(self.FONT_FAMILY, 16, QFont.Weight.Bold))
        self._orig.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._orig.setStyleSheet("color: #ffffff; background: transparent;")
        self._orig.setWordWrap(True)
        self._orig.hide()

        self._trans = QLabel("")
        self._trans.setFont(QFont(self.FONT_FAMILY, 13))
        self._trans.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._trans.setStyleSheet("color: #cccccc; background: transparent;")
        self._trans.setWordWrap(True)
        self._trans.hide()

        lay.addWidget(self._orig)
        lay.addWidget(self._trans)

        self._hide_timer = QTimer()
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._fade_out)

        # 连接跨线程信号
        self.subtitle_signal.connect(self.show_subtitle)

    def _get_target_screen(self):
        """获取目标屏幕"""
        screens = QApplication.screens()
        if 0 <= self._screen_index < len(screens):
            return screens[self._screen_index]
        return QApplication.primaryScreen()

    def _apply_position(self):
        """根据配置设置字幕位置"""
        screen = self._get_target_screen()
        if not screen:
            return
        g = screen.availableGeometry()
        w, h = self.width(), self.height()
        x = g.center().x() - w // 2

        if self._position == "top":
            y = g.top() + 40
        elif self._position == "center":
            y = g.center().y() - h // 2
        else:  # bottom
            y = g.bottom() - h - 40

        self.move(x, y)

    # ── 布局 ──────────────────────────────────────────

    def resizeEvent(self, event):
        self._content.resize(self.width(), self.height())
        super().resizeEvent(event)

    # ── 鼠标：拖拽 + resize ───────────────────────────

    def _in_handle(self, pos) -> bool:
        return (
            self.width() - HANDLE <= pos.x() <= self.width()
            and self.height() - HANDLE <= pos.y() <= self.height()
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._in_handle(event.position()):
                self._resizing = True
                self._drag_start = event.globalPosition().toPoint()
                self._resize_start = self.size()
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            else:
                self._dragging = True
                self._drag_start = (
                    event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                )
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            p = event.globalPosition().toPoint() - self._drag_start
            self.move(p)
        elif self._resizing:
            d = event.globalPosition().toPoint() - self._drag_start
            nw = max(200, self._resize_start.width() + d.x())
            nh = max(50, self._resize_start.height() + d.y())
            self.resize(nw, nh)
        elif self._in_handle(event.position()):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        else:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._dragging = False
        self._resizing = False
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(255, 255, 255, 80), 2))
        bx, by = self.width() - 8, self.height() - 4
        for i in range(3):
            p.drawLine(bx - i * 5, by, bx, by - i * 5)
        p.end()

    # ── 显示 ──────────────────────────────────────────

    def show_subtitle(self, original: str, translation: str):
        self._orig.setText(original)
        self._trans.setText(translation)
        self._orig.show()
        self._trans.show()

        # 自适应大小
        self._orig.adjustSize()
        self._trans.adjustSize()
        tw = max(self._orig.width(), self._trans.width())
        th = self._orig.height() + self._trans.height()
        w = max(300, min(900, tw + 48 + HANDLE))
        h = max(50, th + 24)
        self.resize(w, h)

        self._apply_position()
        self.show()
        if self._hide_delay_ms > 0:
            self._hide_timer.start(self._hide_delay_ms)

    def _fade_out(self):
        if self._hide_delay_ms == 0:
            return
        self._orig.hide()
        self._trans.hide()
        self.hide()

    def apply_settings(self):
        env = read_env_file()
        fs = int(env.get("FONT_SIZE", "16"))
        self._orig.setFont(QFont(self.FONT_FAMILY, fs, QFont.Weight.Bold))
        self._trans.setFont(QFont(self.FONT_FAMILY, max(10, fs - 3)))
        self._hide_delay_ms = int(env.get("SUBTITLE_DURATION", "5000"))
        self._position = env.get("SUBTITLE_POSITION", "bottom")
        self._screen_index = int(env.get("SUBTITLE_SCREEN", "0"))
        self._apply_position()


class SubtitleTray:
    def __init__(self, app: QApplication, pipeline_control: "Optional[SubtitlePipeline]" = None, overlay: "Optional[SubtitleOverlay]" = None):
        self.app = app
        self.pipeline = pipeline_control
        self.overlay = overlay
        self.tray = QSystemTrayIcon()
        self.tray.setToolTip("Vocis")
        self.tray.setIcon(self._icon())
        self._build_menu()
        self.tray.show()

    def _build_menu(self):
        m = QMenu()
        self._ta = QAction("暂停")
        self._ta.triggered.connect(self._toggle)
        m.addAction(self._ta)
        m.addSeparator()
        sa = QAction("设置")
        sa.triggered.connect(self._settings)
        m.addAction(sa)
        m.addSeparator()
        qa = QAction("退出")
        qa.triggered.connect(self._quit)
        m.addAction(qa)
        self.tray.setContextMenu(m)

    def _icon(self):
        p = Path(__file__).parent.parent / "assets" / "vocis_tray_32.png"
        if p.exists():
            return QIcon(str(p))
        from PySide6.QtGui import QPixmap
        pm = QPixmap(32, 32)
        pm.fill(Qt.GlobalColor.transparent)
        pt = QPainter(pm)
        pt.setBrush(QColor("#16162c"))
        pt.setPen(Qt.PenStyle.NoPen)
        pt.drawRoundedRect(4, 4, 24, 24, 6, 6)
        pt.setPen(QColor("#4a9eff"))
        pt.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        pt.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "V")
        pt.end()
        return QIcon(pm)

    def _toggle(self):
        if self.pipeline and self.pipeline.is_paused:
            self.pipeline.resume()
            self._ta.setText("暂停")
        elif self.pipeline:
            self.pipeline.pause()
            self._ta.setText("继续")

    def _settings(self):
        from gui.settings import SettingsDialog
        d = SettingsDialog()
        if d.exec() and self.overlay:
            self.overlay.apply_settings()
            if self.pipeline:
                self.pipeline.asr.set_language(get_config().asr.language)

    def _quit(self):
        if self.pipeline:
            self.pipeline.stop()
        self.tray.hide()
        self.app.quit()
