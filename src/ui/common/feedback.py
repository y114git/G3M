"""User feedback and dialog management."""

from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QMessageBox

from services.localization_service import tr

if TYPE_CHECKING:
    from models.app_state import AppState


class FeedbackManager(QObject):
    """Manages user feedback through dialogs and status messages."""

    status_updated = pyqtSignal(str, str)

    def __init__(self, parent_widget=None, tr_func=None) -> None:
        super().__init__()
        self.parent_widget = parent_widget
        self.app_state: AppState | None = None
        self._tr = tr_func or tr

    def _should_show_dialog(self):
        if self.app_state and hasattr(self.app_state, "game_is_running"):
            return not self.app_state.game_is_running
        return True

    @staticmethod
    def _format_html(text: str) -> str:
        return text.replace("\\n", "<br>").replace("\n", "<br>")

    def show_message(
        self, message_type: str, message_key: str, details: str = "", **kwargs
    ):
        if not self._should_show_dialog():
            return
        _t = self._tr
        type_map = {
            "error": (QMessageBox.Icon.Critical, _t("errors.error")),
            "warning": (QMessageBox.Icon.Warning, _t("dialogs.warning")),
            "info": (QMessageBox.Icon.Information, _t("dialogs.info")),
            "success": (QMessageBox.Icon.Information, _t("dialogs.success")),
        }
        icon, title = type_map.get(
            message_type, (QMessageBox.Icon.Information, _t("dialogs.success"))
        )
        message = _t(message_key, **kwargs)
        msg_box = QMessageBox(None)
        msg_box.setIcon(icon)
        msg_box.setWindowTitle(title)
        if details:
            details_html = self._format_html(details)
            full_message = f"{message}<br><br>{details_html}"
        else:
            full_message = self._format_html(message)
        msg_box.setText(full_message)
        msg_box.exec()

    def ask_question(
        self,
        title_key: str,
        message_key: str,
        details: str = "",
        default_yes: bool = False,
        **kwargs,
    ) -> bool:
        if not self._should_show_dialog():
            return False
        _t = self._tr
        title = _t(title_key, **kwargs)
        message = _t(message_key, **kwargs)
        msg_box = QMessageBox(None)
        msg_box.setIcon(QMessageBox.Icon.Question)
        msg_box.setWindowTitle(title)
        if details:
            details_html = self._format_html(details)
            message_html = self._format_html(message)
            full_message = f"{message_html}<br><br>{details_html}"
        else:
            full_message = self._format_html(message)
        msg_box.setText(full_message)
        msg_box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if default_yes:
            msg_box.setDefaultButton(QMessageBox.StandardButton.Yes)
        else:
            msg_box.setDefaultButton(QMessageBox.StandardButton.No)
        reply = msg_box.exec()
        return reply == QMessageBox.StandardButton.Yes

    def update_status(self, message: str, color: str = ""):
        self.status_updated.emit(message, color)
