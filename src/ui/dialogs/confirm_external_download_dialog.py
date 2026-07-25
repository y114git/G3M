"""Confirmation dialog before downloading from external URL."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from services.localization_service import tr
from ui.common.dialog_theme import build_dialog_theme_stylesheet


class ConfirmExternalDownloadDialog(QDialog):
    """Small dialog asking user to confirm download from external source."""

    def __init__(self, url: str, app_state=None, parent=None) -> None:
        super().__init__(parent)
        self._url = url
        self.setWindowTitle(tr("downloads.confirm_external_title"))
        self.setMinimumWidth(400)
        self.setModal(True)
        self._build_ui()
        if app_state:
            self.setStyleSheet(build_dialog_theme_stylesheet(app_state))

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        combined_text = f"{tr('downloads.confirm_external_message')}\n{tr('downloads.confirm_link', link=self._url)}"
        self.message_label = QLabel(combined_text)
        self.message_label.setWordWrap(True)
        self.message_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.message_label)
        btns = QHBoxLayout()
        btns.addStretch()
        self.no_button = QPushButton(tr("downloads.confirm_no"))
        self.no_button.clicked.connect(self.reject)
        btns.addWidget(self.no_button)
        self.yes_button = QPushButton(tr("downloads.confirm_yes"))
        self.yes_button.setDefault(True)
        self.yes_button.clicked.connect(self.accept)
        btns.addWidget(self.yes_button)
        layout.addLayout(btns)

    def relocalize_ui(self) -> None:
        self.setWindowTitle(tr("downloads.confirm_external_title"))
        self.message_label.setText(
            f"{tr('downloads.confirm_external_message')}\n{tr('downloads.confirm_link', link=self._url)}"
        )
        self.no_button.setText(tr("downloads.confirm_no"))
        self.yes_button.setText(tr("downloads.confirm_yes"))
