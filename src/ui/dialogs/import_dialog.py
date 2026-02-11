from typing import Optional
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit, QFileDialog, QDialogButtonBox
from services.localization_service import tr


class ImportDialog(QDialog):

    def __init__(self, parent, feedback_service, import_type: str, file_filter: Optional[str] = None):
        super().__init__(parent)
        self.feedback_service = feedback_service
        self.import_type = import_type
        self.file_filter = file_filter
        self.selected_file = None
        self.selected_url = None
        self.import_method = None
        self.init_ui()

    def init_ui(self):
        keys = self._get_import_keys()
        title_key = keys['title_key']
        instructions_key = keys['instructions_key']
        from_file_key = keys['from_file_key']
        from_url_key = keys['from_url_key']
        from_url_button_key = keys['from_url_button_key']
        url_placeholder_key = keys['url_placeholder_key']
        url_required_key = keys['url_required_key']
        select_archive_key = keys['select_archive_key']
        self.setWindowTitle(tr(title_key))
        self.setMinimumWidth(500)
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        instructions = QLabel(tr(instructions_key))
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        file_button = QPushButton(tr(from_file_key))
        file_button.clicked.connect(self._import_from_file)
        layout.addWidget(file_button)
        url_label = QLabel(tr(from_url_key))
        layout.addWidget(url_label)
        url_layout = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText(tr(url_placeholder_key))
        url_layout.addWidget(self.url_input)
        url_import_button = QPushButton(tr(from_url_button_key))
        url_import_button.clicked.connect(self._import_from_url)
        url_layout.addWidget(url_import_button)
        layout.addLayout(url_layout)
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
        self.select_archive_key = select_archive_key
        self.url_required_key = url_required_key

    def _import_from_file(self):
        file_filter_text = self._get_file_filter_text()
        file_path, _ = QFileDialog.getOpenFileName(self, tr(self.select_archive_key), '', file_filter_text)
        if file_path:
            self.selected_file = file_path
            self.import_method = 'file'
            self.accept()

    def _get_import_keys(self) -> dict[str, str]:
        if self.import_type == 'themes':
            return {'title_key': 'themes.import_themes', 'instructions_key': 'themes.import_instructions', 'from_file_key': 'themes.import_from_file', 'from_url_key': 'themes.import_from_url', 'from_url_button_key': 'themes.import_from_url_button', 'url_placeholder_key': 'themes.url_placeholder', 'url_required_key': 'themes.url_required', 'select_archive_key': 'themes.select_theme_archive'}
        return {'title_key': f'{self.import_type}.import_{self.import_type}', 'instructions_key': f'{self.import_type}.import_instructions', 'from_file_key': f'{self.import_type}.import_from_file', 'from_url_key': f'{self.import_type}.import_from_url', 'from_url_button_key': f'{self.import_type}.import_from_url_button', 'url_placeholder_key': f'{self.import_type}.url_placeholder', 'url_required_key': f'{self.import_type}.url_required', 'select_archive_key': f'{self.import_type}.select_{self.import_type[:-1]}_archive'}

    def _get_file_filter_text(self) -> str:
        if self.file_filter:
            description = tr('file_descriptions.theme_files') if self.import_type == 'themes' else tr(f'{self.import_type}.archive_files')
            return f'{description} ({self.file_filter});;All Files (*)'
        if self.import_type == 'themes':
            return f"{tr('file_descriptions.theme_files')} (*.zip);;All Files (*)"
        if self.import_type == 'plugins':
            return tr('plugins.archive_files') + ' (*.zip *.7z *.rar *.tar.gz *.lzma);;All Files (*)'
        return tr('mods.archive_files') + ' (*.zip *.7z *.rar *.tar.gz *.lzma);;All Files (*)'

    def _import_from_url(self):
        url = self.url_input.text().strip()
        if not url:
            self.feedback_service.show_message('warning', 'errors.error', tr(self.url_required_key))
            return
        self.selected_url = url
        self.import_method = 'url'
        self.accept()
