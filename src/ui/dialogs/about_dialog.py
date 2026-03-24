import os
import platform
import sys
from collections.abc import Callable

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QFont
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from config.config import LAUNCHER_VERSION, SOCIAL_LINKS
from services.localization_service import localization_service, tr
from utils.path_utils import get_user_data_root


class AboutDialog(QDialog):
    RELEASES_URL = "https://github.com/y114git/DELTAHUB/releases"
    WIKI_URL = "https://github.com/y114git/DELTAHUB/wiki"
    ISSUES_URL = "https://github.com/y114git/DELTAHUB/issues"

    def __init__(
        self, parent, app_state, on_report_bug: Callable[[], None] | None = None
    ) -> None:
        super().__init__(parent)
        self.app_state = app_state
        self._on_report_bug = on_report_bug
        self.data_root = self._resolve_data_root()
        self.setWindowTitle(tr("ui.about_title"))
        self.setMinimumWidth(620)
        self._init_ui()

    def _resolve_data_root(self) -> str:
        config_dir = getattr(self.app_state, "config_dir", "") or ""
        if config_dir:
            parent_dir = os.path.dirname(config_dir)
            if parent_dir:
                return parent_dir
        return get_user_data_root()

    def _current_language_name(self) -> str:
        language_code = localization_service.get_current_language()
        return localization_service.get_available_languages().get(
            language_code, language_code.upper()
        )

    @staticmethod
    def _current_os_name() -> str:
        return f"{platform.system()} {platform.release()} ({platform.machine()})"

    @staticmethod
    def _current_python_version() -> str:
        return sys.version.split()[0]

    def _add_info_row(self, layout: QVBoxLayout, label_text: str, value_text: str):
        row_layout = QHBoxLayout()
        row_label = QLabel(label_text)
        row_value = QLineEdit(value_text)
        row_value.setReadOnly(True)
        row_layout.addWidget(row_label)
        row_layout.addWidget(row_value, 1)
        layout.addLayout(row_layout)
        return row_label, row_value

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        self.title_label = QLabel("DELTAHUB")
        title_font = QFont(self.font())
        title_font.setPointSize(max(14, title_font.pointSize() + 4))
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title_label)

        self.summary_label = QLabel(tr("ui.about_dialog_text"))
        self.summary_label.setWordWrap(True)
        self.summary_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.summary_label)

        info_layout = QVBoxLayout()
        self.version_label, self.version_value = self._add_info_row(
            info_layout,
            tr("ui.about_version_label", version="").rstrip(),
            LAUNCHER_VERSION,
        )
        self.language_label, self.language_value = self._add_info_row(
            info_layout,
            tr("ui.about_language_label", language="").rstrip(),
            self._current_language_name(),
        )
        self.os_label, self.os_value = self._add_info_row(
            info_layout, tr("ui.about_os_label"), self._current_os_name()
        )
        self.python_label, self.python_value = self._add_info_row(
            info_layout, tr("ui.about_python_label"), self._current_python_version()
        )
        self.data_folder_label, self.data_path_edit = self._add_info_row(
            info_layout, tr("ui.about_data_folder"), self.data_root
        )
        layout.addLayout(info_layout)

        links_layout = QHBoxLayout()
        self.releases_button = QPushButton(tr("ui.about_releases"))
        self.releases_button.clicked.connect(lambda: self._open_url(self.RELEASES_URL))
        self.wiki_button = QPushButton(tr("ui.about_wiki"))
        self.wiki_button.clicked.connect(lambda: self._open_url(self.WIKI_URL))
        self.issues_button = QPushButton(tr("ui.about_issues"))
        self.issues_button.clicked.connect(lambda: self._open_url(self.ISSUES_URL))
        links_layout.addWidget(self.releases_button)
        links_layout.addWidget(self.wiki_button)
        links_layout.addWidget(self.issues_button)
        layout.addLayout(links_layout)

        actions_layout = QHBoxLayout()
        self.open_folder_button = QPushButton(tr("buttons.open_deltahub_folder"))
        self.open_folder_button.clicked.connect(self._open_data_folder)
        self.report_bug_button = QPushButton(tr("buttons.report_bug"))
        self.report_bug_button.clicked.connect(self._report_bug)
        self.report_bug_button.setEnabled(self._on_report_bug is not None)
        self.telegram_button = QPushButton(tr("buttons.telegram"))
        self.telegram_button.clicked.connect(
            lambda: self._open_url(SOCIAL_LINKS["telegram"])
        )
        self.discord_button = QPushButton(tr("buttons.discord"))
        self.discord_button.clicked.connect(
            lambda: self._open_url(SOCIAL_LINKS["discord"])
        )
        self.close_button = QPushButton(tr("buttons.close"))
        self.close_button.clicked.connect(self.reject)
        actions_layout.addWidget(self.open_folder_button)
        actions_layout.addWidget(self.report_bug_button)
        actions_layout.addStretch(1)
        actions_layout.addWidget(self.telegram_button)
        actions_layout.addWidget(self.discord_button)
        actions_layout.addWidget(self.close_button)
        layout.addLayout(actions_layout)

    def _open_url(self, url: str):
        QDesktopServices.openUrl(QUrl(url))

    def _open_data_folder(self):
        if self.data_root and os.path.exists(self.data_root):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.data_root))

    def _report_bug(self):
        if self._on_report_bug is None:
            return
        self.accept()
        self._on_report_bug()
