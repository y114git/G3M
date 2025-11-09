import os
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit, QFileDialog, QDialogButtonBox
from PyQt6.QtCore import Qt
from managers.localization_manager import tr


class PluginImportDialog(QDialog):

    def __init__(self, parent, plugin_manager, app_state, feedback_manager):
        super().__init__(parent)
        self.plugin_manager = plugin_manager
        self.app_state = app_state
        self.feedback_manager = feedback_manager
        self.selected_file = None
        self.selected_url = None
        self.import_method = None
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle(tr('plugins.import_plugins'))
        self.setMinimumWidth(500)
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        instructions = QLabel(tr('plugins.import_instructions'))
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        file_button = QPushButton(tr('plugins.import_from_file'))
        file_button.clicked.connect(self._import_from_file)
        layout.addWidget(file_button)
        url_label = QLabel(tr('plugins.import_from_url'))
        layout.addWidget(url_label)
        url_layout = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText(tr('plugins.url_placeholder'))
        url_layout.addWidget(self.url_input)
        url_import_button = QPushButton(tr('plugins.import_from_url_button'))
        url_import_button.clicked.connect(self._import_from_url)
        url_layout.addWidget(url_import_button)
        layout.addLayout(url_layout)
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _import_from_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, tr('plugins.select_plugin_archive'), '', tr('plugins.archive_files') + ' (*.zip *.7z *.rar *.tar.gz *.lzma);;All Files (*)')
        if file_path:
            self.selected_file = file_path
            self.import_method = 'file'
            self.accept()

    def _import_from_url(self):
        url = self.url_input.text().strip()
        if not url:
            self.feedback_manager.show_message('warning', 'errors.error', tr('plugins.url_required'))
            return
        self.selected_url = url
        self.import_method = 'url'
        self.accept()
