import os

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from services.localization_service import tr


class ImportDialog(QDialog):
    def __init__(
        self, parent, feedback_service, import_type: str, file_filter: str | None = None
    ) -> None:
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
        title_key = keys["title_key"]
        instructions_key = keys["instructions_key"]
        from_file_key = keys["from_file_key"]
        from_url_key = keys["from_url_key"]
        from_url_button_key = keys["from_url_button_key"]
        url_placeholder_key = keys["url_placeholder_key"]
        url_required_key = keys["url_required_key"]
        select_archive_key = keys["select_archive_key"]
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
        parent = self.parent()
        start_dir = getattr(parent, "_last_open_dir", None) or os.path.expanduser("~")
        file_path, _ = QFileDialog.getOpenFileName(
            self, tr(self.select_archive_key), start_dir, file_filter_text
        )
        if file_path:
            self.selected_file = file_path
            self.import_method = "file"
            self.accept()

    def _get_import_keys(self) -> dict[str, str]:
        t = self.import_type
        if t in ("game_versions", "mod_versions"):
            title_key = f"{t}.import_title"
            select_key = f"{t}.select_archive"
        else:
            title_key = f"{t}.import_{t}"
            select_key = f"{t}.select_{t[:-1]}_archive"
        return {
            "title_key": title_key,
            "instructions_key": f"{t}.import_instructions",
            "from_file_key": f"{t}.import_from_file",
            "from_url_key": f"{t}.import_from_url",
            "from_url_button_key": f"{t}.import_from_url_button",
            "url_placeholder_key": f"{t}.url_placeholder",
            "url_required_key": f"{t}.url_required",
            "select_archive_key": select_key,
        }

    def _get_file_filter_text(self) -> str:
        if self.file_filter:
            description = (
                tr("file_descriptions.theme_files")
                if self.import_type == "themes"
                else tr(f"{self.import_type}.archive_files")
            )
            return f"{description} ({self.file_filter});;All Files (*)"
        if self.import_type == "themes":
            return f"{tr('file_descriptions.theme_files')} (*.zip);;All Files (*)"
        if self.import_type == "plugins":
            return (
                tr("plugins.archive_files")
                + " (*.zip *.7z *.rar *.tar.gz *.lzma);;All Files (*)"
            )
        return (
            tr("mods.archive_files")
            + " (*.zip *.7z *.rar *.tar.gz *.lzma);;All Files (*)"
        )

    def _import_from_url(self):
        url = self.url_input.text().strip()
        if not url:
            self.feedback_service.show_message(
                "warning", "errors.error", tr(self.url_required_key)
            )
            return
        self.selected_url = url
        self.import_method = "url"
        self.accept()
