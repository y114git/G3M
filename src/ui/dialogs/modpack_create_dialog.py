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
        self.setWindowTitle(tr("dialogs.create_modpack_title"))
        self.setMinimumSize(450, 250)
        self.setup_ui()
        self._apply_theme()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        info_label = QLabel(tr("dialogs.create_modpack_info"))
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        name_layout = QHBoxLayout()
        name_label = QLabel(tr("dialogs.modpack_name_label"))
        name_label.setMinimumWidth(120)
        name_layout.addWidget(name_label)
        self.name_input = QLineEdit()
        self.name_input.setText(tr("dialogs.modpack_default_name"))
        self.name_input.selectAll()
        name_layout.addWidget(self.name_input)
        layout.addLayout(name_layout)
        self.xdelta_checkbox = QCheckBox(tr("checkboxes.xdelta_modpack"))
        self.xdelta_checkbox.setChecked(False)
        layout.addWidget(self.xdelta_checkbox)
        layout.addStretch()
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        cancel_button = QPushButton(tr("buttons.close"))
        cancel_button.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel_button)
        ok_button = QPushButton(tr("ui.ok"))
        ok_button.clicked.connect(self._accept_dialog)
        ok_button.setDefault(True)
        buttons_layout.addWidget(ok_button)
        layout.addLayout(buttons_layout)

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
