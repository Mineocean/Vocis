"""
字幕叠加层 —— 深色玻璃卡片式悬浮字幕。

职责：
  - 原文 + 译文双行，按文本量自适应尺寸（宽 320-980）
  - 说话人彩色胶囊标签（Speaker.index 从 1 开始）
  - 拖拽移动 + 右下角 resize；用户手动拖动后不再自动复位
  - 显示/隐藏用 windowOpacity 淡入淡出
  - 流式更新节流到 ~20fps，避免每个字符都 resize 抖动

main.py 直接连接两个信号，签名不能改：
    pipeline.on_subtitle(overlay.subtitle_signal.emit)
    pipeline.on_subtitle_stream(overlay._stream_signal.emit)
"""

import logging

from PySide6.QtCore import QPoint, QPropertyAnimation, QRect, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from backend.config import get_config
from gui.i18n import tr
from gui.theme import FONT_FAMILIES, speaker_color

logger = logging.getLogger(__name__)


def _font(px: int, weight: QFont.Weight = QFont.Weight.Normal, bold: bool = False) -> QFont:
    f = QFont()
    f.setFamilies(FONT_FAMILIES)
    f.setPixelSize(max(8, int(px)))
    f.setWeight(QFont.Weight.Bold if bold else weight)
    return f


class SubtitleWidget(QWidget):
    """可拖拽 / 可 resize 的玻璃卡片字幕层。"""

    # 跨线程安全信号（pipeline 回调直接 emit）
    subtitle_signal = Signal(str, str, object)
    _stream_signal = Signal(str, str, bool, object)

    SHADOW = 16          # 阴影预留边距
    PAD_X = 18
    PAD_TOP = 12
    PAD_BOTTOM = 13
    PILL_H = 20
    GAP = 7
    MIN_W = 320
    MAX_W = 980
    MIN_H = 64
    HANDLE = 18
    FADE_MS = 140
    STREAM_MS = 50       # 20fps 合并流式更新

    def __init__(self):
        super().__init__()
        self.setObjectName("subtitleOverlay")
        self.setWindowTitle("Vocis")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)
        self.resize(520, 96)

        self._dragging = False
        self._resizing = False
        self._drag_start = QPoint()
        self._resize_start_w = 0
        self._user_positioned = False
        self._user_width: int | None = None

        self._hide_delay_ms = 5000
        self._position = "bottom"
        self._screen_index = 0
        self._speaker_colors = True

        self._original = ""
        self._translation = ""
        self._speaker = None
        self._pending: tuple[str, str, bool, object] | None = None
        self._fade_target = 1.0

        self._build_ui()

        self.subtitle_signal.connect(self.show_subtitle)
        self._stream_signal.connect(self._on_stream)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._fade_out)

        self._stream_timer = QTimer(self)
        self._stream_timer.setInterval(self.STREAM_MS)
        self._stream_timer.timeout.connect(self._flush_stream)

        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.finished.connect(self._on_fade_finished)

        self.apply_settings()

    # ── 构建 ──────────────────────────────────────────

    def _build_ui(self):
        self._content = QWidget(self)
        self._content.setObjectName("subtitleCard")
        self._content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._content.setMouseTracking(True)

        shadow = QGraphicsDropShadowEffect(self._content)
        shadow.setBlurRadius(36)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 190))
        self._content.setGraphicsEffect(shadow)

        lay = QVBoxLayout(self._content)
        lay.setContentsMargins(self.PAD_X, self.PAD_TOP, self.PAD_X, self.PAD_BOTTOM)
        lay.setSpacing(self.GAP)

        self._pill = QLabel("")
        self._pill.setFont(_font(11, bold=True))
        self._pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pill.setFixedHeight(self.PILL_H)
        self._pill.hide()

        pill_row = QHBoxLayout()
        pill_row.setContentsMargins(0, 0, 0, 0)
        pill_row.setSpacing(0)
        pill_row.addWidget(self._pill, 0, Qt.AlignmentFlag.AlignLeft)
        pill_row.addStretch(1)
        lay.addLayout(pill_row)

        self._orig = QLabel("")
        self._orig.setFont(_font(16, bold=True))
        self._orig.setWordWrap(True)
        self._orig.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._orig.setStyleSheet("background: transparent; color: #ffffff;")
        self._orig.hide()

        self._trans = QLabel("")
        self._trans.setFont(_font(13))
        self._trans.setWordWrap(True)
        self._trans.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._trans.setStyleSheet("background: transparent; color: #cbd5e1;")
        self._trans.hide()

        lay.addWidget(self._orig)
        lay.addWidget(self._trans)

    # ── 配置 ──────────────────────────────────────────

    def apply_settings(self):
        """从配置重新加载显示设置（字号 / 时长 / 位置 / 屏幕 / 说话人配色）。"""
        cfg = get_config()
        fs = max(10, min(48, int(cfg.display.font_size)))
        self._orig.setFont(_font(fs, bold=True))
        self._trans.setFont(_font(max(9, fs - 3)))
        self._hide_delay_ms = max(0, int(cfg.display.subtitle_duration_ms))

        position = str(cfg.display.subtitle_position or "bottom").lower()
        self._position = position if position in ("bottom", "center", "top") else "bottom"
        try:
            self._screen_index = int(cfg.display.subtitle_screen or 0)
        except (TypeError, ValueError):
            self._screen_index = 0
        self._speaker_colors = bool(cfg.display.speaker_colors)

        if self._speaker is not None:
            self._set_speaker(self._speaker)
        if self._original or self._translation:
            self._relayout()
        self._apply_position()

    def _get_target_screen(self):
        screens = QApplication.screens()
        if 0 <= self._screen_index < len(screens):
            return screens[self._screen_index]
        return QApplication.primaryScreen()

    def _apply_position(self):
        if self._user_positioned:
            return
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
        else:
            y = g.bottom() - h - 40
        self.move(x, y)

    # ── 尺寸 / 文本 ───────────────────────────────────

    @staticmethod
    def _text_height(text: str, font: QFont, width: int) -> int:
        if not text:
            return 0
        fm = QFontMetrics(font)
        rect = fm.boundingRect(
            QRect(0, 0, max(1, width), 100000),
            int(Qt.TextFlag.TextWordWrap),
            text,
        )
        return max(fm.lineSpacing(), rect.height()) + 2

    @staticmethod
    def _natural_width(text: str, font: QFont) -> int:
        if not text:
            return 0
        return QFontMetrics(font).horizontalAdvance(text)

    def _relayout(self):
        """根据当前文本重新计算窗口尺寸。"""
        has_trans = bool(self._translation and self._translation.strip())
        has_pill = self._speaker is not None

        max_content = self.MAX_W - 2 * (self.SHADOW + self.PAD_X)
        natural = max(
            self._natural_width(self._original, self._orig.font()),
            self._natural_width(self._translation, self._trans.font()) if has_trans else 0,
        )
        if self._user_width is not None:
            w = max(self.MIN_W, min(self.MAX_W, self._user_width))
        else:
            w = max(self.MIN_W, min(self.MAX_W, natural + 2 * (self.SHADOW + self.PAD_X)))
        content_w = max(120, w - 2 * (self.SHADOW + self.PAD_X))
        content_w = min(content_w, max_content)

        h_o = self._text_height(self._original, self._orig.font(), content_w)
        h_t = self._text_height(self._translation, self._trans.font(), content_w) if has_trans else 0
        content_h = self.PAD_TOP + self.PAD_BOTTOM + h_o
        if has_trans:
            content_h += self.GAP + h_t
        if has_pill:
            content_h += self.PILL_H + self.GAP
        h = max(self.MIN_H, content_h + 2 * self.SHADOW)

        # 标签固定宽高，保证窗口高度与文本布局完全一致
        self._orig.setFixedWidth(content_w)
        self._orig.setFixedHeight(h_o)
        self._orig.setVisible(bool(self._original))
        if has_trans:
            self._trans.setFixedWidth(content_w)
            self._trans.setFixedHeight(h_t)
            self._trans.setVisible(True)
        else:
            self._trans.setVisible(False)
        self._pill.setVisible(has_pill)

        self.resize(w, h)
        self._content.resize(w - 2 * self.SHADOW, h - 2 * self.SHADOW)
        self._content.move(self.SHADOW, self.SHADOW)
        lay = self._content.layout()
        if lay is not None:
            lay.activate()

    def _update_display(self, original: str, translation: str, speaker=None):
        self._original = original or ""
        self._translation = translation or ""
        self._set_speaker(speaker)
        self._orig.setText(self._original)
        self._trans.setText(self._translation)
        self._relayout()

    def _set_speaker(self, speaker):
        self._speaker = speaker
        if speaker is None:
            self._pill.hide()
            return
        index = int(getattr(speaker, "index", 1) or 1)
        color_index = getattr(speaker, "color_index", index - 1)
        if self._speaker_colors:
            bg = speaker_color(color_index)
            fg = "#08111a"
        else:
            bg = "rgba(255, 255, 255, 0.16)"
            fg = "#e6edf3"
        text = tr("speaker_n", n=index)
        self._pill.setStyleSheet(
            "background-color: %s; color: %s; border-radius: 9px; "
            "padding: 1px 9px; font-size: 11px; font-weight: 600;" % (bg, fg)
        )
        self._pill.setText(text)
        self._pill.setFixedWidth(QFontMetrics(self._pill.font()).horizontalAdvance(text) + 22)
        self._pill.show()

    # ── 显示 / 淡入淡出 ───────────────────────────────

    def show_subtitle(self, original: str, translation: str, speaker=None):
        """非流式字幕（pipeline.on_subtitle）。"""
        self._pending = None
        self._stream_timer.stop()
        self._update_display(original, translation, speaker)
        self._show_animated()
        if self._hide_delay_ms > 0:
            self._hide_timer.start(self._hide_delay_ms)
        else:
            self._hide_timer.stop()

    def _on_stream(self, original: str, translation: str, is_final: bool, speaker):
        """流式字幕（pipeline.on_subtitle_stream），合并到 ~20fps。"""
        self._pending = (original, translation, is_final, speaker)
        if is_final:
            self._flush_stream()
            if self._hide_delay_ms > 0:
                self._hide_timer.start(self._hide_delay_ms)
            else:
                self._hide_timer.stop()
            return
        self._hide_timer.stop()
        if not self.isVisible():
            self._flush_stream()
        elif not self._stream_timer.isActive():
            self._stream_timer.start()

    def _flush_stream(self):
        pending = self._pending
        if pending is None:
            self._stream_timer.stop()
            return
        self._pending = None
        original, translation, _is_final, speaker = pending
        self._update_display(original, translation, speaker)
        self._show_animated()
        if self._pending is None:
            self._stream_timer.stop()

    def _show_animated(self):
        if self.isVisible() and self.windowOpacity() >= 0.99:
            return
        self._fade.stop()
        if not self.isVisible():
            self.setWindowOpacity(0.0)
            self.show()
        self._fade_target = 1.0
        self._fade.setDuration(self.FADE_MS)
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(1.0)
        self._fade.start()

    def _fade_out(self):
        if self._hide_delay_ms == 0 or not self.isVisible():
            return
        self._fade.stop()
        self._fade_target = 0.0
        self._fade.setDuration(self.FADE_MS)
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.start()

    def _on_fade_finished(self):
        if self._fade_target <= 0.01:
            self.hide()
            self.setWindowOpacity(1.0)
            self._fade_target = 1.0

    # ── 鼠标：拖拽 + resize ───────────────────────────

    def _in_handle(self, pos) -> bool:
        x = self.width() - self.SHADOW - self.HANDLE
        y = self.height() - self.SHADOW - self.HANDLE
        return pos.x() >= x and pos.y() >= y

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._in_handle(event.position()):
                self._resizing = True
                self._drag_start = event.globalPosition().toPoint()
                self._resize_start_w = self.width()
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            else:
                self._dragging = True
                self._drag_start = (
                    event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                )
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            self.move(event.globalPosition().toPoint() - self._drag_start)
        elif self._resizing:
            dx = event.globalPosition().toPoint().x() - self._drag_start.x()
            width = max(self.MIN_W, min(self.MAX_W, self._resize_start_w + dx))
            self.resize(width, self.height())
            self._content.resize(width - 2 * self.SHADOW, self.height() - 2 * self.SHADOW)
        elif self._in_handle(event.position()):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        else:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging:
            self._user_positioned = True
        if self._resizing:
            self._user_width = self.width()
            self._relayout()
            self._apply_position()
        self._dragging = False
        self._resizing = False
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event):
        self._content.setGeometry(
            self.SHADOW,
            self.SHADOW,
            max(1, self.width() - 2 * self.SHADOW),
            max(1, self.height() - 2 * self.SHADOW),
        )
        super().resizeEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(255, 255, 255, 70), 2))
        bx = self.width() - self.SHADOW - 7
        by = self.height() - self.SHADOW - 7
        for i in range(3):
            p.drawLine(bx - i * 5, by, bx, by - i * 5)
        p.end()
