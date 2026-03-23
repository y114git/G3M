"""Color picker utilities for QColorDialog customization."""

from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QColorDialog


def is_pure_black_color(color: QColor) -> bool:
    return (
        color.isValid()
        and color.red() == 0
        and color.green() == 0
        and color.blue() == 0
    )


def get_black_color_picker_seed(color: QColor) -> QColor:
    return QColor.fromHsv(0, 0, 255, color.alpha() if color.isValid() else 255)


class BlackColorPickerEventFilter(QObject):
    def __init__(self, dialog: QColorDialog) -> None:
        super().__init__(dialog)
        self._dialog = dialog

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseButtonPress and is_pure_black_color(
            self._dialog.currentColor()
        ):
            self._dialog.setCurrentColor(
                get_black_color_picker_seed(self._dialog.currentColor())
            )
        return False
