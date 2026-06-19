"""User feedback and dialog management."""

import html
import json
import logging
from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QStyle,
    QVBoxLayout,
)

from services.localization_service import tr
from services.warning_service import (
    WarningEvent,
    WarningSeverity,
    get_warning_definition,
    normalize_warning_preferences,
)

if TYPE_CHECKING:
    from models.app_state import AppState

logger = logging.getLogger(__name__)


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
        warning_id = ""
        if isinstance(message, WarningEvent):
            definition = get_warning_definition(message.warning_id)
            warning_id = definition.warning_id
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
            full_message = self._format_html(message_text)
            if details:
                full_message = f"{full_message}<br><br>{self._format_html(details)}"
            action, dont_show_again = self._exec_patching_warning_dialog(
                title,
                full_message,
                icon,
                bool(warning_id),
                bool(report_path),
            )
            if dont_show_again:
                self._disable_warning(warning_id)
            if action == "continue":
                return True
            if action in {"cancel", ""}:
                return False
            if action == "report" and report_path:
                from ui.dialogs.conflicts_dialog import ConflictsDialog

                ConflictsDialog(report_path, parent=self.parent_widget).exec()

    def _exec_patching_warning_dialog(
        self,
        title: str,
        message_html: str,
        icon: QMessageBox.Icon,
        allow_disable: bool,
        has_report: bool,
    ) -> tuple[str, bool]:
        dialog = QDialog(self.parent_widget)
        dialog.setWindowTitle(title)
        dialog.setModal(True)
        dialog.setMinimumWidth(420)
        dialog.setObjectName("patching_warning_dialog")
        result = {"action": "cancel"}

        root = QVBoxLayout(dialog)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(12)

        body = QHBoxLayout()
        body.setSpacing(12)
        icon_label = QLabel(dialog)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        icon_map = {
            QMessageBox.Icon.Critical: QStyle.StandardPixmap.SP_MessageBoxCritical,
            QMessageBox.Icon.Warning: QStyle.StandardPixmap.SP_MessageBoxWarning,
            QMessageBox.Icon.Information: QStyle.StandardPixmap.SP_MessageBoxInformation,
        }
        pixmap = dialog.style().standardIcon(
            icon_map.get(icon, QStyle.StandardPixmap.SP_MessageBoxWarning)
        ).pixmap(32, 32)
        icon_label.setPixmap(pixmap)
        body.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)

        message_label = QLabel(dialog)
        message_label.setTextFormat(Qt.TextFormat.RichText)
        message_label.setWordWrap(True)
        message_label.setText(message_html)
        message_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        body.addWidget(message_label, 1)
        root.addLayout(body)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        dont_show_checkbox = None
        if allow_disable:
            dont_show_checkbox = QCheckBox(
                self._tr("dialogs.patching_warning.dont_show_again"), dialog
            )
            buttons.addWidget(dont_show_checkbox, 0, Qt.AlignmentFlag.AlignLeft)
        buttons.addStretch(1)

        if has_report:
            report_btn = QPushButton(self._tr("dialogs.conflicts.open_report"), dialog)
            report_btn.clicked.connect(lambda: (result.update(action="report"), dialog.accept()))
            buttons.addWidget(report_btn)

        continue_btn = QPushButton(
            self._tr("dialogs.patching_warning.continue_button"), dialog
        )
        cancel_btn = QPushButton(
            self._tr("dialogs.patching_warning.cancel_button"), dialog
        )
        continue_btn.clicked.connect(
            lambda: (result.update(action="continue"), dialog.accept())
        )
        cancel_btn.clicked.connect(lambda: (result.update(action="cancel"), dialog.reject()))
        buttons.addWidget(continue_btn)
        buttons.addWidget(cancel_btn)
        root.addLayout(buttons)
        cancel_btn.setDefault(True)
        dialog.exec()
        return result["action"], bool(dont_show_checkbox and dont_show_checkbox.isChecked())

    def _disable_warning(self, warning_id: str) -> None:
        if not warning_id or self.app_state is None:
            return
        config = getattr(self.app_state, "local_config", None)
        if not isinstance(config, dict):
            return
        prefs = normalize_warning_preferences(config)
        overrides = prefs.setdefault("warning_overrides", {})
        overrides[warning_id] = False
        config_path = getattr(self.app_state, "config_path", "")
        if not config_path:
            return
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
        except Exception:
            logger.warning("Failed to persist warning preference", exc_info=True)

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
