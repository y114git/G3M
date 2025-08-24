from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QPen, QBrush, QPainterPath
from PyQt6.QtWidgets import QLabel

class OutlinedTextLabel(QLabel):

    def __init__(self, text: str='', parent=None, outline_color=QColor('white'), fill_color=QColor('black'), outline_width: float=1.0):
        super().__init__(text, parent)
        self._outline_color = QColor(outline_color)
        self._fill_color = QColor(fill_color)
        self._outline_width = float(outline_width)
        self._outline_opacity = 1.0
        self._left_margin = 0
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def setColors(self, fill, outline):
        self._fill_color = QColor(fill)
        self._outline_color = QColor(outline)
        self.update()

    def setOutlineWidth(self, w: float):
        try:
            self._outline_width = max(0.0, float(w))
        except Exception:
            self._outline_width = 0.0
        self.update()

    def setOutlineOpacity(self, opacity: float):
        try:
            self._outline_opacity = min(1.0, max(0.0, float(opacity)))
        except Exception:
            self._outline_opacity = 1.0
        self.update()

    def setLeftMargin(self, m: int):
        self._left_margin = max(0, int(m))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        font = self.font()
        painter.setFont(font)
        text = self.text() or ''
        if not text:
            return
        rect = self.rect()
        fm = self.fontMetrics()
        ascent = fm.ascent()
        descent = fm.descent()
        x = rect.x() + self._left_margin
        y = rect.y() + (rect.height() + ascent - descent) / 2
        path = QPainterPath()
        path.addText(x, y, font, text)
        pen_color = QColor(self._outline_color)
        pen_color.setAlphaF(self._outline_opacity * pen_color.alphaF())
        pen = QPen(pen_color)
        pen.setWidthF(self._outline_width)
        pen.setStyle(Qt.PenStyle.SolidLine)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(QBrush(self._fill_color))
        painter.drawPath(path)