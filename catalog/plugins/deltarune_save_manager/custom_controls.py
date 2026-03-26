from typing import override

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QLabel


class ClickableLabel(QLabel):
    clicked = pyqtSignal(int, int)
    double_clicked = pyqtSignal(int, int)
    hover_entered = pyqtSignal(int, int)
    hover_left = pyqtSignal(int, int)

    def __init__(self, chapter: int, slot: int, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._ch = chapter
        self._sl = slot

    def mousePressEvent(self, ev):
        if ev and ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._ch, self._sl)
        super().mousePressEvent(ev)

    def mouseDoubleClickEvent(self, ev):
        if ev and ev.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self._ch, self._sl)
        super().mouseDoubleClickEvent(ev)

    @override
    def enterEvent(self, ev):
        self.hover_entered.emit(self._ch, self._sl)
        super().enterEvent(ev)

    @override
    def leaveEvent(self, ev):
        self.hover_left.emit(self._ch, self._sl)
        super().leaveEvent(ev)
