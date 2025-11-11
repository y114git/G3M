from PyQt6.QtWidgets import QComboBox


class NoScrollComboBox(QComboBox):

    def wheelEvent(self, event):
        event.ignore()
