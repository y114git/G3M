from typing import TYPE_CHECKING, Optional
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtCore import QObject, pyqtSignal
from managers.localization_manager import tr
if TYPE_CHECKING:
    from core.app_state import AppState


class FeedbackManager(QObject):
    status_updated = pyqtSignal(str, str)

    def __init__(self, parent_widget=None):
        super().__init__()
        self.parent_widget = parent_widget
        self.app_state: Optional['AppState'] = None

    def _should_show_dialog(self):
        if self.app_state and hasattr(self.app_state, 'game_is_running'):
            return not self.app_state.game_is_running
        return True

    @staticmethod
    def _format_html(text: str) -> str:
        return text.replace('\\n', '<br>').replace('\n', '<br>')

    def show_message(self, message_type: str, message_key: str, details: str = '', **kwargs):
        if not self._should_show_dialog():
            return
        type_map = {'error': (QMessageBox.Icon.Critical, tr('errors.error')), 'warning': (QMessageBox.Icon.Warning, 'Warning'), 'info': (QMessageBox.Icon.Information, tr('dialogs.success')), 'success': (QMessageBox.Icon.Information, tr('dialogs.success'))}
        icon, title = type_map.get(message_type, (QMessageBox.Icon.Information, tr('dialogs.success')))
        message = tr(message_key, **kwargs)
        msg_box = QMessageBox(self.parent_widget)
        msg_box.setIcon(icon)
        msg_box.setWindowTitle(title)
        if details:
            details_html = self._format_html(details)
            full_message = f'{message}<br><br>{details_html}'
        else:
            full_message = self._format_html(message)
        msg_box.setText(full_message)
        msg_box.exec()

    def ask_question(self, title_key: str, message_key: str, details: str = '', default_yes: bool = False, **kwargs) -> bool:
        if not self._should_show_dialog():
            return False
        title = tr(title_key, **kwargs)
        message = tr(message_key, **kwargs)
        msg_box = QMessageBox(self.parent_widget)
        msg_box.setIcon(QMessageBox.Icon.Question)
        msg_box.setWindowTitle(title)
        if details:
            details_html = self._format_html(details)
            message_html = self._format_html(message)
            full_message = f'{message_html}<br><br>{details_html}'
        else:
            full_message = self._format_html(message)
        msg_box.setText(full_message)
        msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if default_yes:
            msg_box.setDefaultButton(QMessageBox.StandardButton.Yes)
        else:
            msg_box.setDefaultButton(QMessageBox.StandardButton.No)
        reply = msg_box.exec()
        return reply == QMessageBox.StandardButton.Yes

    def ask_custom_question(self, icon: QMessageBox.Icon, title_key: str, message_key: str, buttons: list[tuple[str, QMessageBox.ButtonRole, str]], default_button_key: str | None = None, **kwargs) -> str | None:
        if not self._should_show_dialog():
            return None
        title = tr(title_key)
        message = tr(message_key, **kwargs)
        msg_box = QMessageBox(self.parent_widget)
        msg_box.setIcon(icon)
        msg_box.setWindowTitle(title)
        msg_box.setText(message)
        button_map = {}
        default_button = None
        for text_key, role, return_key in buttons:
            button = msg_box.addButton(tr(text_key), role)
            button_map[button] = return_key
            if return_key == default_button_key:
                default_button = button
        if default_button:
            msg_box.setDefaultButton(default_button)
        msg_box.exec()
        clicked_button = msg_box.clickedButton()
        return button_map.get(clicked_button)

    def update_status(self, message: str, color: str = ''):
        self.status_updated.emit(message, color)
