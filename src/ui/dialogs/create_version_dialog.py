"""Dialog for creating a new version."""
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QHBoxLayout

from services.localization_service import tr
from ui.common.dialog_theme import build_dialog_theme_stylesheet


class CreateVersionDialog(QDialog):
    """Version name input dialog."""

    def __init__(self, game_name: str, app_state, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('versions.create_title'))
        self.setMinimumWidth(380)
        self.setModal(True)
        self._version_name = ''
        self._build_ui(game_name)
        self.setStyleSheet(build_dialog_theme_stylesheet(app_state))

    def _build_ui(self, game_name: str):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 16, 20, 16)

        info = QLabel(tr('versions.create_info', game=game_name))
        info.setWordWrap(True)
        layout.addWidget(info)

        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText(tr('versions.name_placeholder'))
        layout.addWidget(self._name_input)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        ok_btn = QPushButton(tr('versions.create_button'))
        ok_btn.clicked.connect(self._on_accept)
        cancel_btn = QPushButton(tr('common.close'))
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        self._name_input.returnPressed.connect(self._on_accept)

    def _on_accept(self):
        name = self._name_input.text().strip()
        if name:
            self._version_name = name
            self.accept()
        else:
            self._name_input.setFocus()
            self._name_input.setStyleSheet("border: 2px solid red;")

    @property
    def version_name(self) -> str:
        return self._version_name
