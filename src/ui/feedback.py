from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtCore import QObject, pyqtSignal
from localization.manager import tr


class FeedbackManager(QObject):
    status_updated = pyqtSignal(str, str)

    def __init__(self, parent_widget=None):
        super().__init__()
        self.parent_widget = parent_widget

    def show_error(self, message_key: str, details: str = ""):
        title = tr("errors.error")
        message = tr(message_key)

        msg_box = QMessageBox(self.parent_widget)
        msg_box.setIcon(QMessageBox.Icon.Critical)
        msg_box.setWindowTitle(title)
        msg_box.setText(message)

        if details:
            msg_box.setDetailedText(details)

        msg_box.exec()

    def show_warning(self, message_key: str, details: str = ""):
        title = tr("errors.error")
        message = tr(message_key)

        msg_box = QMessageBox(self.parent_widget)
        msg_box.setIcon(QMessageBox.Icon.Warning)
        msg_box.setWindowTitle(title)
        msg_box.setText(message)

        if details:
            msg_box.setDetailedText(details)

        msg_box.exec()

    def show_info(self, message_key: str, details: str = ""):
        title = tr("dialogs.success")
        message = tr(message_key)

        msg_box = QMessageBox(self.parent_widget)
        msg_box.setIcon(QMessageBox.Icon.Information)
        msg_box.setWindowTitle(title)
        msg_box.setText(message)

        if details:
            msg_box.setDetailedText(details)

        msg_box.exec()

    def show_success(self, message_key: str, details: str = ""):
        title = tr("dialogs.success")
        message = tr(message_key)

        msg_box = QMessageBox(self.parent_widget)
        msg_box.setIcon(QMessageBox.Icon.Information)
        msg_box.setWindowTitle(title)
        msg_box.setText(message)

        if details:
            msg_box.setDetailedText(details)

        msg_box.exec()

    def update_status(self, message_key: str, color: str = ""):
        message = tr(message_key)
        self.status_updated.emit(message, color)
