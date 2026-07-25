"""Dialog for creating a new game version."""

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from services.localization_service import tr
from ui.common.dialog_theme import build_dialog_theme_stylesheet


class CreateVersionDialog(QDialog):
    """Version name input dialog with optional profile selection."""

    def __init__(
        self, game_name: str, app_state, profiles: list[str] | None = None, parent=None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("game_versions.create_title"))
        self.setMinimumWidth(380)
        self.setModal(True)
        self._version_name = ""
        self._selected_profile: str | None = None
        self._game_name = game_name
        self._profiles = profiles or []
        self._build_ui(game_name, self._profiles)
        self.setStyleSheet(build_dialog_theme_stylesheet(app_state))

    def _build_ui(self, game_name: str, profiles: list[str]):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 16, 20, 16)

        self._info_label = QLabel()
        self._info_label.setWordWrap(True)
        layout.addWidget(self._info_label)

        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText(tr("game_versions.name_placeholder"))
        layout.addWidget(self._name_input)

        profile_row = QHBoxLayout()
        self._profile_label = QLabel()
        profile_row.addWidget(self._profile_label)
        self._profile_combo = QComboBox()
        self._profile_combo.addItem(tr("game_versions.without_profile"), None)
        for pname in profiles:
            self._profile_combo.addItem(pname, pname)
        profile_row.addWidget(self._profile_combo, 1)
        layout.addLayout(profile_row)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._ok_button = QPushButton()
        self._ok_button.clicked.connect(self._on_accept)
        self._cancel_button = QPushButton()
        self._cancel_button.clicked.connect(self.reject)
        btn_row.addWidget(self._ok_button)
        btn_row.addWidget(self._cancel_button)
        layout.addLayout(btn_row)

        self._name_input.returnPressed.connect(self._on_accept)
        self.relocalize_ui()

    def relocalize_ui(self) -> None:
        self.setWindowTitle(tr("game_versions.create_title"))
        self._info_label.setText(tr("game_versions.create_info", game=self._game_name))
        self._name_input.setPlaceholderText(tr("game_versions.name_placeholder"))
        current_profile = self._profile_combo.currentData()
        self._profile_combo.setItemText(0, tr("game_versions.without_profile"))
        index = self._profile_combo.findData(current_profile)
        if index >= 0:
            self._profile_combo.setCurrentIndex(index)
        self._profile_label.setText(tr("game_versions.apply_profile"))
        self._ok_button.setText(tr("game_versions.create_button"))
        self._cancel_button.setText(tr("common.close"))

    def _on_accept(self):
        name = self._name_input.text().strip()
        if name:
            self._version_name = name
            self._selected_profile = self._profile_combo.currentData()
            self.accept()
        else:
            self._name_input.setFocus()
            self._name_input.setStyleSheet("border: 2px solid red;")

    @property
    def version_name(self) -> str:
        return self._version_name

    @property
    def selected_profile(self) -> str | None:
        return self._selected_profile
