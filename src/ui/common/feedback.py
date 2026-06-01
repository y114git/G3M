"""User feedback and dialog management."""

import html
from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QMessageBox

from services.localization_service import tr
from services.warning_service import (
    WarningEvent,
    WarningSeverity,
    get_warning_definition,
)

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
        return html.escape(text, quote=False).replace("\\n", "<br>").replace(
            "\n", "<br>"
        )

    def show_message(
        self, message_type: str, message_key: str, details: str = "", **kwargs
    ):
        if not self._should_show_dialog():
            return
        t = self._tr
        type_map = {
            "error": (QMessageBox.Icon.Critical, t("errors.error")),
            "warning": (QMessageBox.Icon.Warning, t("dialogs.warning")),
            "info": (QMessageBox.Icon.Information, t("dialogs.info")),
            "success": (QMessageBox.Icon.Information, t("dialogs.success")),
        }
        icon, title = type_map.get(
            message_type, (QMessageBox.Icon.Information, t("dialogs.success"))
        )
        message = t(message_key, **kwargs)
        msg_box = QMessageBox(self.parent_widget)
        msg_box.setIcon(icon)
        msg_box.setWindowTitle(title)
        message_html = self._format_html(message)
        if details:
            details_html = self._format_html(details)
            full_message = f"{message_html}<br><br>{details_html}"
        else:
            full_message = message_html
        msg_box.setText(full_message)
        msg_box.exec()

    def ask_question(
        self,
        title_key: str,
        message_key: str,
        details: str = "",
        default_yes: bool = False,
        details_is_html: bool = False,
        **kwargs,
    ) -> bool:
        if not self._should_show_dialog():
            return False
        t = self._tr
        title = t(title_key, **kwargs)
        message = t(message_key, **kwargs)
        msg_box = QMessageBox(self.parent_widget)
        msg_box.setIcon(QMessageBox.Icon.Question)
        msg_box.setWindowTitle(title)
        if details:
            details_html = details if details_is_html else self._format_html(details)
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

    def ask_patching_warning(
        self,
        message: str | WarningEvent,
        details: str = "",
        report_path: str | None = None,
    ) -> bool:
        if not self._should_show_dialog():
            return False
        icon = QMessageBox.Icon.Warning
        title = self._tr("dialogs.patching_warning.title")
        if isinstance(message, WarningEvent):
            definition = get_warning_definition(message.warning_id)
            context = message.context
            title = self._tr(definition.title_key, **context)
            body = self._tr(definition.body_key, **context)
            message_text = message.fallback_message or body
            details = message.details or details
            report_path = message.report_path or report_path
            icon = {
                WarningSeverity.CRITICAL: QMessageBox.Icon.Critical,
                WarningSeverity.MAJOR: QMessageBox.Icon.Warning,
                WarningSeverity.MINOR: QMessageBox.Icon.Information,
            }[definition.severity]
        else:
            message_text = message
        while True:
            msg_box = QMessageBox(self.parent_widget)
            msg_box.setIcon(icon)
            msg_box.setWindowTitle(title)
            full_message = self._format_html(message_text)
            if details:
                full_message = f"{full_message}<br><br>{self._format_html(details)}"
            msg_box.setText(full_message)
            continue_btn = msg_box.addButton(
                self._tr("dialogs.patching_warning.continue_button"),
                QMessageBox.ButtonRole.AcceptRole,
            )
            cancel_btn = msg_box.addButton(
                self._tr("dialogs.patching_warning.cancel_button"),
                QMessageBox.ButtonRole.RejectRole,
            )
            open_report_btn = None
            if report_path:
                open_report_btn = msg_box.addButton(
                    self._tr("dialogs.conflicts.open_report"),
                    QMessageBox.ButtonRole.ActionRole,
                )
            msg_box.setDefaultButton(cancel_btn)
            msg_box.exec()
            clicked = msg_box.clickedButton()
            if clicked == continue_btn:
                return True
            if clicked == cancel_btn or clicked is None:
                return False
            if clicked == open_report_btn and report_path:
                from ui.dialogs.conflicts_dialog import ConflictsDialog

                ConflictsDialog(report_path, parent=self.parent_widget).exec()

    def update_status(self, message: str, color: str = ""):
        self.status_updated.emit(message, color)

    def scoped(self, tr_func=None):
        return _ScopedFeedbackManager(self, tr_func or self._tr)


class _ScopedFeedbackManager:
    """Delegates feedback behavior while overriding translation scope."""

    def __init__(self, base_manager: FeedbackManager, tr_func) -> None:
        self._base_manager = base_manager
        self._tr = tr_func

    def __getattr__(self, name) -> object:
        return getattr(self._base_manager, name)

    def show_message(
        self, message_type: str, message_key: str, details: str = "", **kwargs
    ):
        return FeedbackManager.show_message(
            self,
            message_type,
            message_key,
            details,
            **kwargs,
        )

    def ask_question(
        self,
        title_key: str,
        message_key: str,
        details: str = "",
        default_yes: bool = False,
        details_is_html: bool = False,
        **kwargs,
    ) -> bool:
        return FeedbackManager.ask_question(
            self,
            title_key,
            message_key,
            details,
            default_yes,
            details_is_html,
            **kwargs,
        )

    def ask_patching_warning(
        self,
        message: str | WarningEvent,
        details: str = "",
        report_path: str | None = None,
    ) -> bool:
        return FeedbackManager.ask_patching_warning(
            self,
            message,
            details,
            report_path,
        )

    def update_status(self, message: str, color: str = ""):
        self._base_manager.update_status(message, color)

    def _should_show_dialog(self):
        return self._base_manager._should_show_dialog()

    @property
    def parent_widget(self):
        return self._base_manager.parent_widget
