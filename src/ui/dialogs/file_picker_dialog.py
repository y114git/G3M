import webbrowser
from datetime import datetime
from typing import Dict, List, Optional
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout
from services.localization_service import tr


class GameBananaFilePickerDialog(QDialog):

    def __init__(self, parent, files: List[Dict], mod_name: str, external_url: Optional[str] = None):
        super().__init__(parent)
        self.setWindowTitle(tr('dialogs.gamebanana_picker_title', mod_name=mod_name))
        self.files = files or []
        self.external_url = external_url
        self.selected_file: Optional[Dict] = None
        self.resize(720, 420)
        main_layout = QVBoxLayout(self)
        hint_label = QLabel(tr('dialogs.gamebanana_picker_hint'))
        hint_label.setWordWrap(True)
        main_layout.addWidget(hint_label)
        content_layout = QHBoxLayout()
        self.list_widget = QListWidget()
        self.list_widget.itemSelectionChanged.connect(self._on_selection_changed)
        self.list_widget.itemDoubleClicked.connect(lambda _: self._accept_if_selection())
        content_layout.addWidget(self.list_widget, 3)
        self.details_label = QLabel('')
        self.details_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.details_label.setWordWrap(True)
        self.details_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        content_layout.addWidget(self.details_label, 2)
        main_layout.addLayout(content_layout)
        button_row = QHBoxLayout()
        button_row.addStretch()
        if self.external_url:
            open_btn = QPushButton(tr('dialogs.gamebanana_picker_open_page'))
            open_btn.clicked.connect(self._open_external_page)
            button_row.addWidget(open_btn)
        main_layout.addLayout(button_row)
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)
        main_layout.addWidget(button_box)
        self._populate()

    def _populate(self):
        for file_data in self.files:
            display_text = file_data.get('name', 'file')
            item = QListWidgetItem(display_text)
            item.setData(Qt.ItemDataRole.UserRole, file_data)
            self.list_widget.addItem(item)
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)
            self._on_selection_changed()

    def _on_selection_changed(self):
        current = self.list_widget.currentItem()
        if not current:
            self.selected_file = None
            self.details_label.setText('')
            return
        file_data = current.data(Qt.ItemDataRole.UserRole)
        self.selected_file = file_data
        self.details_label.setText(self._build_details_text(file_data))

    def _build_details_text(self, file_data: Dict) -> str:
        description = file_data.get('description') or tr('status.no_description_status')
        template = tr('dialogs.gamebanana_picker_details')
        return template.format(version=file_data.get('version') or tr('defaults.not_specified'), size=self._format_size(file_data.get('size_bytes')), updated=self._format_timestamp(file_data.get('timestamp')), downloads=file_data.get('download_count', 0), format=self._format_gamebanana_format(file_data.get('compatibility')), security=self._format_security(file_data), description=description.strip(), md5=file_data.get('md5') or '—')

    def _format_security(self, file_data: Dict) -> str:
        analysis = file_data.get('analysis_result') or file_data.get('analysis_state')
        av = file_data.get('av_result') or file_data.get('av_state')
        parts = []
        if analysis:
            parts.append(str(analysis))
        if av and av not in parts:
            parts.append(str(av))
        return ', '.join(parts) if parts else tr('defaults.not_specified')

    @staticmethod
    def _format_size(size_bytes: Optional[int]) -> str:
        if not size_bytes or size_bytes <= 0:
            return tr('defaults.not_specified')
        units = ['B', 'KB', 'MB', 'GB']
        size = float(size_bytes)
        unit_idx = 0
        while size >= 1024 and unit_idx < len(units) - 1:
            size /= 1024
            unit_idx += 1
        return f'{size:.2f} {units[unit_idx]}'

    @staticmethod
    def _format_timestamp(timestamp: Optional[int]) -> str:
        if not timestamp:
            return tr('defaults.not_specified')
        try:
            dt = datetime.fromtimestamp(timestamp)
            return dt.strftime('%d.%m.%Y %H:%M')
        except (ValueError, OSError):
            return tr('defaults.not_specified')

    @staticmethod
    def _format_gamebanana_format(format_key: Optional[str]) -> str:
        if format_key == 'deltahub':
            return tr('ui.gamebanana_format_deltahub')
        if format_key == 'deltamod':
            return tr('ui.gamebanana_format_deltamod')
        return tr('defaults.not_specified')

    def _open_external_page(self):
        if self.external_url:
            webbrowser.open(self.external_url)

    def _accept_if_selection(self):
        if self.selected_file:
            self.accept()

    def _on_accept(self):
        if not self.selected_file:
            current_item = self.list_widget.currentItem()
            if current_item:
                self.selected_file = current_item.data(Qt.ItemDataRole.UserRole)
        if self.selected_file:
            self.accept()

    def get_selected_file(self) -> Optional[Dict]:
        return self.selected_file
