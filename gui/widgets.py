"""Themed controls —— QSS 无法绘制下拉/数值箭头，这里用 paintEvent 补上。"""

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QSpinBox, QStyle, QStyleOptionSpinBox

from gui.theme import MUTED

_DISABLED = "#56616d"


def _stroke(widget) -> QColor:
    return QColor(MUTED if widget.isEnabled() else _DISABLED)


class ThemedComboBox(QComboBox):
    """QComboBox + 手绘 chevron（QSS 的 down-arrow 在深色主题里默认不可见）。"""

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(_stroke(self), 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        cx = self.width() - 13
        cy = self.height() / 2
        p.drawLine(QPointF(cx - 4, cy - 2), QPointF(cx, cy + 2))
        p.drawLine(QPointF(cx, cy + 2), QPointF(cx + 4, cy - 2))
        p.end()


def _paint_spin_arrows(widget):
    p = QPainter(widget)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_stroke(widget))
    option = QStyleOptionSpinBox()
    widget.initStyleOption(option)
    up = widget.style().subControlRect(
        QStyle.ComplexControl.CC_SpinBox, option, QStyle.SubControl.SC_SpinBoxUp, widget
    )
    down = widget.style().subControlRect(
        QStyle.ComplexControl.CC_SpinBox, option, QStyle.SubControl.SC_SpinBoxDown, widget
    )
    for rect, points in (
        (up, ((-3.5, 1.8), (3.5, 1.8), (0, -2.2))),
        (down, ((-3.5, -1.8), (3.5, -1.8), (0, 2.2))),
    ):
        cx, cy = rect.center().x() + 0.5, rect.center().y() + 0.5
        p.drawPolygon(QPolygonF([QPointF(cx + dx, cy + dy) for dx, dy in points]))
    p.end()


class ThemedSpinBox(QSpinBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        _paint_spin_arrows(self)


class ThemedDoubleSpinBox(QDoubleSpinBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        _paint_spin_arrows(self)
