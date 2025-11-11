from typing import Optional
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit
from managers.localization_manager import tr
from ui.common.styling import get_theme_color


class CreateModpackDialog(QDialog):

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.modpack_name = None
        self.setWindowTitle(tr('dialogs.create_modpack_title'))
        self.setMinimumSize(450, 200)
        self.setup_ui()
        self._apply_theme()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        info_label = QLabel(tr('dialogs.create_modpack_info'))
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        name_layout = QHBoxLayout()
        name_label = QLabel(tr('dialogs.modpack_name_label'))
        name_label.setMinimumWidth(120)
        name_layout.addWidget(name_label)
        self.name_input = QLineEdit()
        self.name_input.setText(tr('dialogs.modpack_default_name'))
        self.name_input.selectAll()
        name_layout.addWidget(self.name_input)
        layout.addLayout(name_layout)
        layout.addStretch()
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        cancel_button = QPushButton(tr('buttons.close'))
        cancel_button.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel_button)
        ok_button = QPushButton(tr('ui.ok'))
        ok_button.clicked.connect(self._accept_dialog)
        ok_button.setDefault(True)
        buttons_layout.addWidget(ok_button)
        layout.addLayout(buttons_layout)

    def _accept_dialog(self):
        name = self.name_input.text().strip()
        if not name:
            return
        self.modpack_name = name
        self.accept()

    def get_modpack_name(self) -> Optional[str]:
        return self.modpack_name

    def _apply_theme(self):
        bg_color = get_theme_color(self.app_state.local_config, 'background', '#000000')
        border_color = get_theme_color(self.app_state.local_config, 'border', 'white')
        button_color = get_theme_color(self.app_state.local_config, 'button', 'black')
        hover_color = get_theme_color(self.app_state.local_config, 'button_hover', '#333')
        text_color = get_theme_color(self.app_state.local_config, 'text', 'white')
        self.setStyleSheet(f'\n            QDialog {{\n                background-color: {bg_color};\n                color: {text_color};\n            }}\n            QLineEdit {{\n                background-color: {bg_color};\n                border: 2px solid {border_color};\n                color: {text_color};\n                padding: 8px;\n                font-size: 13px;\n            }}\n            QLineEdit:focus {{\n                border: 2px solid {hover_color};\n            }}\n            QPushButton {{\n                background-color: {button_color};\n                border: 2px solid {border_color};\n                color: {text_color};\n                padding: 8px 15px;\n                font-weight: bold;\n            }}\n            QPushButton:hover {{\n                background-color: {hover_color};\n            }}\n            QPushButton:pressed {{\n                background-color: {hover_color};\n            }}\n            QLabel {{\n                color: {text_color};\n            }}\n        ')
