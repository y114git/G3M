"""Dialog for creating modpacks."""

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from services.localization_service import tr
from ui.common.dialog_theme import apply_dialog_theme


class CreateModpackDialog(QDialog):
    def __init__(self, app_state, parent=None) -> None:
        super().__init__(parent)
        self.app_state = app_state
        self.modpack_name = None
        self.xdelta_modpack = False
        self._default_name_text = tr("dialogs.modpack_default_name")
        self.setWindowTitle(tr("dialogs.create_modpack_title"))
        self.setMinimumSize(450, 250)
        self.setup_ui()
        self._apply_theme()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        self.info_label = QLabel()
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)
        name_layout = QHBoxLayout()
        self.name_label = QLabel()
        self.name_label.setMinimumWidth(120)
        name_layout.addWidget(self.name_label)
        self.name_input = QLineEdit()
        self.name_input.setText(self._default_name_text)
        self.name_input.selectAll()
        name_layout.addWidget(self.name_input)
        layout.addLayout(name_layout)
        self.xdelta_checkbox = QCheckBox(tr("checkboxes.xdelta_modpack"))
        self.xdelta_checkbox.setChecked(False)
        layout.addWidget(self.xdelta_checkbox)
        layout.addStretch()
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        self.cancel_button = QPushButton()
        self.cancel_button.clicked.connect(self.reject)
        buttons_layout.addWidget(self.cancel_button)
        self.ok_button = QPushButton()
        self.ok_button.clicked.connect(self._accept_dialog)
        self.ok_button.setDefault(True)
        buttons_layout.addWidget(self.ok_button)
        layout.addLayout(buttons_layout)
        self.relocalize_ui()

    def relocalize_ui(self) -> None:
        self.setWindowTitle(tr("dialogs.create_modpack_title"))
        self.info_label.setText(tr("dialogs.create_modpack_info"))
        self.name_label.setText(tr("dialogs.modpack_name_label"))
        new_default = tr("dialogs.modpack_default_name")
        if self.name_input.text() == self._default_name_text:
            self.name_input.setText(new_default)
            self.name_input.selectAll()
        self._default_name_text = new_default
        self.xdelta_checkbox.setText(tr("checkboxes.xdelta_modpack"))
        self.cancel_button.setText(tr("buttons.close"))
        self.ok_button.setText(tr("ui.ok"))

    def _accept_dialog(self):
        name = self.name_input.text().strip()
        if not name:
            return
        self.modpack_name = name
        self.xdelta_modpack = self.xdelta_checkbox.isChecked()
        self.accept()

    def get_modpack_name(self) -> str | None:
        return self.modpack_name

    def get_xdelta_modpack(self) -> bool:
        return self.xdelta_modpack

    def _apply_theme(self):
        apply_dialog_theme(self, self.app_state)
