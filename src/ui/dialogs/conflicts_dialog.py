"""Dialog for viewing mod conflict results."""

import logging
import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from services.g3mtool_patching_service import G3MToolPatchingService
from services.localization_service import tr
from utils.native_integration import open_path_native
from utils.process_utils import format_filesystem_error

logger = logging.getLogger(__name__)


class ConflictsDialog(QDialog):
    """Informational dialog showing merge conflict report.

    Does not block game launch or modpack flow - purely informational.
    """

    def __init__(self, report_md_path: str, parent=None) -> None:
        super().__init__(parent)
        self.report_md_path = report_md_path
        self.setWindowTitle(tr("dialogs.conflicts.title"))
        self.setMinimumWidth(700)
        self.setMinimumHeight(500)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowCloseButtonHint)
        self._md_content = ""
        self._conflicts_count = 0
        self._auto_resolved = 0
        self._parse_report()
        self._setup_ui()

    def _parse_report(self):
        try:
            with open(self.report_md_path, encoding="utf-8") as f:
                self._md_content = f.read()
            self._conflicts_count, self._auto_resolved = (
                G3MToolPatchingService._parse_conflict_counts(self._md_content)
            )
        except Exception:
            self._md_content = ""

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        self.title_label = QLabel(tr("dialogs.conflicts.title"))
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        layout.addWidget(self.title_label)
        self.stats_label = QLabel()
        self.stats_label.setWordWrap(True)
        layout.addWidget(self.stats_label)
        report_browser = QTextBrowser()
        report_browser.setOpenExternalLinks(False)
        report_browser.setMarkdown(self._md_content)
        layout.addWidget(report_browser)
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        self.open_report_button = QPushButton(tr("dialogs.conflicts.open_report"))
        self.open_report_button.clicked.connect(self._open_report_file)
        button_layout.addWidget(self.open_report_button)
        self.close_button = QPushButton(tr("common.close"))
        self.close_button.clicked.connect(self.accept)
        button_layout.addWidget(self.close_button)
        button_layout.addStretch()
        layout.addLayout(button_layout)
        self.relocalize_ui()

    def relocalize_ui(self) -> None:
        self.setWindowTitle(tr("dialogs.conflicts.title"))
        self.title_label.setText(tr("dialogs.conflicts.title"))
        self.stats_label.setText(
            tr(
                "dialogs.conflicts.summary",
                conflicts=self._conflicts_count,
                auto_resolved=self._auto_resolved,
            )
        )
        self.open_report_button.setText(tr("dialogs.conflicts.open_report"))
        self.close_button.setText(tr("common.close"))

    def _safe_information(self, title: str, message: str) -> None:
        try:
            QMessageBox.information(self, title, message)
        except Exception:
            logger.exception("ConflictsDialog: failed to show information message")

    def _safe_warning(self, title: str, message: str) -> None:
        try:
            QMessageBox.warning(self, title, message)
        except Exception:
            logger.exception("ConflictsDialog: failed to show warning message")

    def _open_report_file(self):
        if not os.path.exists(self.report_md_path):
            self._safe_information(
                tr("dialogs.conflicts.title"),
                tr("errors.file_not_found", path=self.report_md_path),
            )
            return
        try:
            if not open_path_native(self.report_md_path):
                raise RuntimeError(f"Failed to open report: {self.report_md_path}")
        except Exception as e:
            self._safe_warning(
                tr("errors.error"),
                format_filesystem_error(e, path=self.report_md_path),
            )
