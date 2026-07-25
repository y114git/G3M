"""Dialog for creating or editing a custom game."""

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from services.localization_service import tr
from ui.common.dialog_theme import apply_dialog_theme, get_dialog_theme_values


class CustomGameDialog(QDialog):
    """Minimal custom-game editor."""

    def __init__(self, app_state, record=None, parent=None) -> None:
        super().__init__(parent)
        self.app_state = app_state
        self.record = record
        self._is_editing = record is not None
        self.setWindowTitle(
            tr("games.edit_custom_title") if record else tr("games.add_custom_title")
        )
        self.setModal(True)
        self.setMinimumWidth(420)
        self._build_ui()
        apply_dialog_theme(self, self.app_state)
        theme = get_dialog_theme_values(self.app_state)
        self.setStyleSheet(
            self.styleSheet()
            + f" QLabel#customGameHelpLabel {{ color: {theme['secondary_text']}; font-size: 11px; }}"
        )

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.display_name_edit = QLineEdit(
            self.record.display_name if self.record else ""
        )
        self.display_name_edit.setPlaceholderText(tr("games.display_name_placeholder"))
        form.addRow(tr("games.display_name_label"), self.display_name_edit)
        self.primary_executable_edit = QLineEdit(
            self.record.primary_executable if self.record else ""
        )
        self.primary_executable_edit.setPlaceholderText(
            tr("games.primary_executable_placeholder")
        )
        form.addRow(tr("games.primary_executable_label"), self.primary_executable_edit)
        self.executable_help = QLabel(tr("games.primary_executable_help"))
        self.executable_help.setObjectName("customGameHelpLabel")
        self.executable_help.setWordWrap(True)
        form.addRow("", self.executable_help)
        self.data_file_name_edit = QLineEdit(
            self.record.data_file_name if self.record else ""
        )
        self.data_file_name_edit.setPlaceholderText(
            tr("games.data_file_name_placeholder")
        )
        form.addRow(tr("games.data_file_name_label"), self.data_file_name_edit)
        self.data_file_help = QLabel(tr("games.data_file_name_help"))
        self.data_file_help.setObjectName("customGameHelpLabel")
        self.data_file_help.setWordWrap(True)
        form.addRow("", self.data_file_help)
        self.steam_app_id_edit = QLineEdit(
            (self.record.steam_app_id or "") if self.record else ""
        )
        self.steam_app_id_edit.setPlaceholderText(tr("games.steam_app_id_placeholder"))
        form.addRow(tr("games.steam_app_id_label"), self.steam_app_id_edit)
        self.gamebanana_id_edit = QLineEdit(
            str(self.record.gamebanana_id or "") if self.record else ""
        )
        self.gamebanana_id_edit.setPlaceholderText(
            tr("games.gamebanana_id_placeholder")
        )
        form.addRow(tr("games.gamebanana_id_label"), self.gamebanana_id_edit)
        layout.addLayout(form)
        self.form_layout = form
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        for button in self.buttons.buttons():
            button.setMinimumWidth(button.sizeHint().width() + 18)
        layout.addWidget(self.buttons)
        self.relocalize_ui()

    def relocalize_ui(self) -> None:
        self.setWindowTitle(
            tr("games.edit_custom_title")
            if self._is_editing
            else tr("games.add_custom_title")
        )
        for field, label_key, placeholder_key in (
            (
                self.display_name_edit,
                "games.display_name_label",
                "games.display_name_placeholder",
            ),
            (
                self.primary_executable_edit,
                "games.primary_executable_label",
                "games.primary_executable_placeholder",
            ),
            (
                self.data_file_name_edit,
                "games.data_file_name_label",
                "games.data_file_name_placeholder",
            ),
            (
                self.steam_app_id_edit,
                "games.steam_app_id_label",
                "games.steam_app_id_placeholder",
            ),
            (
                self.gamebanana_id_edit,
                "games.gamebanana_id_label",
                "games.gamebanana_id_placeholder",
            ),
        ):
            label = self.form_layout.labelForField(field)
            if isinstance(label, QLabel):
                label.setText(tr(label_key))
            field.setPlaceholderText(tr(placeholder_key))
        self.executable_help.setText(tr("games.primary_executable_help"))
        self.data_file_help.setText(tr("games.data_file_name_help"))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("ui.ok"))
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(
            tr("dialogs.cancel")
        )

    def values(self) -> dict[str, str]:
        return {
            "display_name": self.display_name_edit.text().strip(),
            "primary_executable": self.primary_executable_edit.text().strip(),
            "data_file_name": self.data_file_name_edit.text().strip(),
            "steam_app_id": self.steam_app_id_edit.text().strip(),
            "gamebanana_id": self.gamebanana_id_edit.text().strip(),
        }
