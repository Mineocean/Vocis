"""Themed controls —— QSS 无法绘制下拉/数值箭头，这里用 paintEvent 补上。"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QRadioButton,
    QSpinBox,
    QStyle,
    QStyleOptionButton,
    QStyleOptionSpinBox,
)

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


class _ThemedIndicator:
    """画对勾 / 内点：QSS 无法在没有图片资源时绘制选中标记。"""

    _kind = "check"

    def _indicator_rect(self) -> QRectF:
        option = QStyleOptionButton()
        self.initStyleOption(option)  # type: ignore[attr-defined]
        style = self.style()  # type: ignore[attr-defined]
        sub = (
            QStyle.SubElement.SE_CheckBoxIndicator
            if self._kind == "check"
            else QStyle.SubElement.SE_RadioButtonIndicator
        )
        rect = style.subElementRect(sub, option, self)
        if rect.isValid() and rect.width() > 4:
            return QRectF(rect).adjusted(1.5, 1.5, -1.5, -1.5)
        size = 16 if self._kind == "check" else 15
        height = int(self.height())  # type: ignore[attr-defined]
        return QRectF(8, (height - size) / 2, size, size).adjusted(1.5, 1.5, -1.5, -1.5)

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.isChecked():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self._indicator_rect()
        if self._kind == "check":
            pen = QPen(QColor("#08111a"), 2.0)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.drawPolyline(
                QPolygonF(
                    [
                        QPointF(rect.left() + rect.width() * 0.18, rect.top() + rect.height() * 0.52),
                        QPointF(rect.left() + rect.width() * 0.42, rect.top() + rect.height() * 0.76),
                        QPointF(rect.left() + rect.width() * 0.82, rect.top() + rect.height() * 0.26),
                    ]
                )
            )
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#08111a"))
            p.drawEllipse(rect.center(), rect.width() * 0.28, rect.height() * 0.28)
        p.end()


class ThemedCheckBox(_ThemedIndicator, QCheckBox):
    _kind = "check"


class ThemedRadioButton(_ThemedIndicator, QRadioButton):
    _kind = "radio"


class ThemedSpinBox(QSpinBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        _paint_spin_arrows(self)


class ThemedDoubleSpinBox(QDoubleSpinBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        _paint_spin_arrows(self)
