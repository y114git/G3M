from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import QComboBox, QWidget, QLabel


class NoScrollComboBox(QComboBox):

    def wheelEvent(self, event):
        event.ignore()


class _ZeroHintWidget(QWidget):

    def sizeHint(self) -> QSize:
        return QSize(0, 0)

    def minimumSizeHint(self) -> QSize:
        return QSize(0, 0)


class AnimatedToolTip(QLabel):
    """Custom tooltip widget with animation support."""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setWindowFlags(
            Qt.WindowType.ToolTip |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setObjectName("animated_tooltip")
        self.setContentsMargins(12, 10, 12, 10)
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.setMaximumWidth(400)

    def paintEvent(self, event):
        from PyQt6.QtWidgets import QStyle, QStyleOption
        from PyQt6.QtGui import QPainter
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        opt = QStyleOption()
        opt.initFrom(self)
        self.style().drawPrimitive(QStyle.PrimitiveElement.PE_Widget, opt, p, self)
        super().paintEvent(event)
