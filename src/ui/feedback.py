from typing import TYPE_CHECKING, Optional
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtCore import QObject, pyqtSignal
from localization.manager import tr

if TYPE_CHECKING:
    from core.app_state import AppState


class FeedbackManager(QObject):
    status_updated = pyqtSignal(str, str)

    def __init__(self, parent_widget=None):
        super().__init__()
        self.parent_widget = parent_widget
        self.app_state: Optional['AppState'] = None  # Will be set by the app

    def _should_show_dialog(self):
        """Check if we should show a dialog (not during game)."""
        if self.app_state and hasattr(self.app_state, 'game_is_running'):
            return not self.app_state.game_is_running
        return True

    def show_error(self, message_key: str, details: str = "", **kwargs):
        # Don't show dialogs while game is running
        if not self._should_show_dialog():
            return

        title = tr("errors.error")
        message = tr(message_key, **kwargs)

        msg_box = QMessageBox(self.parent_widget)
        msg_box.setIcon(QMessageBox.Icon.Critical)
        msg_box.setWindowTitle(title)

        # Combine message and details in the main text with HTML support
        if details:
            # Replace \n with <br> for proper line breaks in QMessageBox
            details_html = details.replace('\\n', '<br>').replace('\n', '<br>')
            full_message = f"{message}<br><br>{details_html}"
        else:
            # Replace \n with <br> for proper line breaks in QMessageBox
            full_message = message.replace('\\n', '<br>').replace('\n', '<br>')

        msg_box.setText(full_message)

        msg_box.exec()

    def show_warning(self, message_key: str, details: str = "", **kwargs):
        # Don't show dialogs while game is running
        if not self._should_show_dialog():
            return

        title = tr("errors.error")
        message = tr(message_key, **kwargs)

        msg_box = QMessageBox(self.parent_widget)
        msg_box.setIcon(QMessageBox.Icon.Warning)
        msg_box.setWindowTitle(title)

        # Combine message and details in the main text with HTML support
        if details:
            # Replace \n with <br> for proper line breaks in QMessageBox
            details_html = details.replace('\\n', '<br>').replace('\n', '<br>')
            full_message = f"{message}<br><br>{details_html}"
        else:
            # Replace \n with <br> for proper line breaks in QMessageBox
            full_message = message.replace('\\n', '<br>').replace('\n', '<br>')

        msg_box.setText(full_message)

        msg_box.exec()

    def show_info(self, message_key: str, details: str = "", **kwargs):
        # Don't show dialogs while game is running
        if not self._should_show_dialog():
            return

        title = tr("dialogs.success")
        message = tr(message_key, **kwargs)

        msg_box = QMessageBox(self.parent_widget)
        msg_box.setIcon(QMessageBox.Icon.Information)
        msg_box.setWindowTitle(title)

        # Combine message and details in the main text with HTML support
        if details:
            # Replace \n with <br> for proper line breaks in QMessageBox
            details_html = details.replace('\\n', '<br>').replace('\n', '<br>')
            full_message = f"{message}<br><br>{details_html}"
        else:
            # Replace \n with <br> for proper line breaks in QMessageBox
            full_message = message.replace('\\n', '<br>').replace('\n', '<br>')

        msg_box.setText(full_message)

        msg_box.exec()

    def show_success(self, message_key: str, details: str = "", **kwargs):
        # Don't show dialogs while game is running
        if not self._should_show_dialog():
            return

        title = tr("dialogs.success")
        message = tr(message_key, **kwargs)

        msg_box = QMessageBox(self.parent_widget)
        msg_box.setIcon(QMessageBox.Icon.Information)
        msg_box.setWindowTitle(title)

        # Combine message and details in the main text with HTML support
        if details:
            # Replace \n with <br> for proper line breaks in QMessageBox
            details_html = details.replace('\\n', '<br>').replace('\n', '<br>')
            full_message = f"{message}<br><br>{details_html}"
        else:
            # Replace \n with <br> for proper line breaks in QMessageBox
            full_message = message.replace('\\n', '<br>').replace('\n', '<br>')

        msg_box.setText(full_message)

        msg_box.exec()

    def ask_question(self, title_key: str, message_key: str, details: str = "", default_yes: bool = False, **kwargs) -> bool:
        # Don't show dialogs while game is running
        if not self._should_show_dialog():
            return False

        title = tr(title_key, **kwargs)
        message = tr(message_key, **kwargs)

        msg_box = QMessageBox(self.parent_widget)
        msg_box.setIcon(QMessageBox.Icon.Question)
        msg_box.setWindowTitle(title)

        # Combine message and details if both are provided
        if details:
            details_html = details.replace('\\n', '<br>').replace('\n', '<br>')
            message_html = message.replace('\\n', '<br>').replace('\n', '<br>')
            full_message = f"{message_html}<br><br>{details_html}"
        else:
            full_message = message.replace('\\n', '<br>').replace('\n', '<br>')

        msg_box.setText(full_message)

        msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

        if default_yes:
            msg_box.setDefaultButton(QMessageBox.StandardButton.Yes)
        else:
            msg_box.setDefaultButton(QMessageBox.StandardButton.No)

        reply = msg_box.exec()
        return reply == QMessageBox.StandardButton.Yes

    def ask_custom_question(self, icon: QMessageBox.Icon, title_key: str, message_key: str, buttons: list[tuple[str, QMessageBox.ButtonRole, str]], default_button_key: str | None = None, **kwargs) -> str | None:
        # Don't show dialogs while game is running
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

    def update_status(self, message: str, color: str = ""):
        self.status_updated.emit(message, color)
