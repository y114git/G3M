from typing import Callable, Optional
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QComboBox, QTabWidget, QLabel, QFrame, QWidget

class NoScrollComboBox(QComboBox):

    def wheelEvent(self, event):
        event.ignore()

class NoScrollTabWidget(QTabWidget):

    def wheelEvent(self, event):
        event.ignore()

class ClickableLabel(QLabel):
    clicked = pyqtSignal(int, int)
    doubleClicked = pyqtSignal(int, int)

    def __init__(self, chapter: int, slot: int, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._ch = chapter
        self._sl = slot

    def mousePressEvent(self, ev):
        if ev and ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._ch, self._sl)
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev):
        super().mouseReleaseEvent(ev)

    def mouseDoubleClickEvent(self, ev):
        if ev and ev.button() == Qt.MouseButton.LeftButton:
            self.doubleClicked.emit(self._ch, self._sl)
        super().mouseDoubleClickEvent(ev)

class SlotFrame(QFrame):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.chapter_id: int = -1
        self.assigned_mod = None
        self.content_widget: Optional[QWidget] = None
        self.mod_icon: Optional[QLabel] = None
        self.is_selected: bool = False
        self.click_handler: Optional[Callable] = None
        self.double_click_handler: Optional[Callable] = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.click_handler:
            self.click_handler()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.double_click_handler:
            self.double_click_handler()
        super().mouseDoubleClickEvent(event)