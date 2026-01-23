from PyQt6.QtCore import QSize
from PyQt6.QtWidgets import QComboBox, QWidget


class NoScrollComboBox(QComboBox):

    def wheelEvent(self, event):
        event.ignore()


class _ZeroHintWidget(QWidget):

    def sizeHint(self) -> QSize:
        return QSize(0, 0)

    def minimumSizeHint(self) -> QSize:
        return QSize(0, 0)
