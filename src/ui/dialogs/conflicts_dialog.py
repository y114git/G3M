import os
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QTextBrowser, QHBoxLayout, QMessageBox
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from services.localization_service import tr
from services.g3mtool_patching_service import G3MToolPatchingService


class ConflictsDialog(QDialog):
    """Informational dialog showing merge conflict report.

    Does not block game launch or modpack flow — purely informational.
    """

    def __init__(self, report_md_path: str, parent=None):
        super().__init__(parent)
        self.report_md_path = report_md_path
        self.setWindowTitle(tr('dialogs.conflicts.title'))
        self.setMinimumWidth(700)
        self.setMinimumHeight(500)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowCloseButtonHint)
        self._md_content = ''
        self._conflicts_count = 0
        self._auto_resolved = 0
        self._parse_report()
        self._setup_ui()

    def _parse_report(self):
        try:
            with open(self.report_md_path, 'r', encoding='utf-8') as f:
                self._md_content = f.read()
            self._conflicts_count, self._auto_resolved = G3MToolPatchingService._parse_conflict_counts(self._md_content)
        except Exception:
            self._md_content = ''

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        title_label = QLabel(tr('dialogs.conflicts.title'))
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)
        stats_text = f'Conflicts: {self._conflicts_count}'
        if self._auto_resolved > 0:
            stats_text += f'  |  Auto-resolved: {self._auto_resolved}'
        stats_label = QLabel(stats_text)
        stats_label.setWordWrap(True)
        layout.addWidget(stats_label)
        report_browser = QTextBrowser()
        report_browser.setOpenExternalLinks(False)
        report_browser.setMarkdown(self._md_content)
        layout.addWidget(report_browser)
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        open_report_button = QPushButton(tr('dialogs.conflicts.open_report'))
        open_report_button.clicked.connect(self._open_report_file)
        button_layout.addWidget(open_report_button)
        close_button = QPushButton(tr('common.close'))
        close_button.clicked.connect(self.accept)
        button_layout.addWidget(close_button)
        button_layout.addStretch()
        layout.addLayout(button_layout)

    def _open_report_file(self):
        if not os.path.exists(self.report_md_path):
            QMessageBox.information(self, 'Report', 'Report file not found.')
            return
        try:
            if os.name == 'nt':
                os.startfile(self.report_md_path)
            elif os.name == 'posix':
                import platform as _plat
                if _plat.system() == 'Darwin':
                    os.system(f'open "{self.report_md_path}"')
                else:
                    os.system(f'xdg-open "{self.report_md_path}"')
        except Exception as e:
            QMessageBox.warning(self, tr('errors.error'), str(e))
