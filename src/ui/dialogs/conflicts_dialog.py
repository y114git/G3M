import os
from typing import Dict, Any
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QTextEdit, QHBoxLayout, QMessageBox
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from services.localization_service import tr
from services.patching_log_service import get_conflicts_log_path


class ConflictsDialog(QDialog):

    def __init__(self, conflicts_summary: Dict[str, Any], config_dir: str, parent=None):
        super().__init__(parent)
        self.conflicts_summary = conflicts_summary
        self.config_dir = config_dir
        self.setWindowTitle(tr('dialogs.conflicts.title'))
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowCloseButtonHint)
        self._setup_ui()

    def closeEvent(self, event):
        self.reject()
        event.accept()

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
        message_label = QLabel(tr('dialogs.conflicts.message'))
        message_label.setWordWrap(True)
        layout.addWidget(message_label)
        if self.conflicts_summary.get('mod_pairs'):
            mod_pairs_label = QLabel(tr('dialogs.conflicts.conflicting_mods'))
            mod_pairs_font = QFont()
            mod_pairs_font.setBold(True)
            mod_pairs_label.setFont(mod_pairs_font)
            layout.addWidget(mod_pairs_label)
            mod_pairs_text = QTextEdit()
            mod_pairs_text.setReadOnly(True)
            mod_pairs_text.setMaximumHeight(150)
            mod_pairs_text.setPlainText('\n'.join([f'• {pair[0]} ↔ {pair[1]}' for pair in self.conflicts_summary['mod_pairs']]))
            layout.addWidget(mod_pairs_text)
        total_conflicts = self.conflicts_summary.get('total_conflicts', 0)
        count_label = QLabel(tr('dialogs.conflicts.total_conflicts', count=total_conflicts))
        count_label.setWordWrap(True)
        layout.addWidget(count_label)
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        open_logs_button = QPushButton(tr('dialogs.conflicts.open_logs_and_launch'))
        open_logs_button.clicked.connect(self._open_logs_and_launch)
        button_layout.addWidget(open_logs_button)
        continue_button = QPushButton(tr('dialogs.conflicts.continue_without_logs'))
        continue_button.clicked.connect(self.accept)
        button_layout.addWidget(continue_button)
        layout.addLayout(button_layout)

    def _open_logs_and_launch(self):
        merge_conflicts_log = get_conflicts_log_path()
        opened = False
        if os.path.exists(merge_conflicts_log):
            try:
                if os.name == 'nt':
                    os.startfile(merge_conflicts_log)
                elif os.name == 'posix':
                    if os.uname().sysname == 'Darwin':
                        os.system(f'open "{merge_conflicts_log}"')
                    else:
                        os.system(f'xdg-open "{merge_conflicts_log}"')
                opened = True
            except Exception as e:
                QMessageBox.warning(self, tr('errors.error'), tr('dialogs.conflicts.failed_to_open_log', file=os.path.basename(merge_conflicts_log), error=str(e)))
        if not opened:
            QMessageBox.information(self, tr('dialogs.conflicts.no_logs_title'), tr('dialogs.conflicts.no_logs_message'))
        self.accept()
