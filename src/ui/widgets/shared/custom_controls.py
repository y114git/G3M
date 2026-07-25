"""Shared custom Qt controls used across the UI."""

from typing import Any, cast

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QComboBox, QLabel


class NoScrollComboBox(QComboBox):
    def wheelEvent(self, e):
        cast(Any, e).ignore()


class AnimatedToolTip(QLabel):
    """Custom tooltip widget with animation support."""

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(text, parent)
        self._preserve_fade_effect = False
        self._is_fading_out = False
        self.setWindowFlags(
            Qt.WindowType.ToolTip
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setObjectName("animated_tooltip")
        self.setContentsMargins(12, 10, 12, 10)
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.setMaximumWidth(400)

    def paintEvent(self, a0):
        from PyQt6.QtGui import QPainter
        from PyQt6.QtWidgets import QStyle, QStyleOption

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        opt = QStyleOption()
        opt.initFrom(self)
        style = self.style()
        if style is not None:
            style.drawPrimitive(QStyle.PrimitiveElement.PE_Widget, opt, p, self)
        super().paintEvent(a0)
