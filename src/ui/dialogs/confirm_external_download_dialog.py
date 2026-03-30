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
        msg = QLabel(combined_text)
        msg.setWordWrap(True)
        msg.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(msg)
        btns = QHBoxLayout()
        btns.addStretch()
        no_btn = QPushButton(tr("downloads.confirm_no"))
        no_btn.clicked.connect(self.reject)
        btns.addWidget(no_btn)
        yes_btn = QPushButton(tr("downloads.confirm_yes"))
        yes_btn.setDefault(True)
        yes_btn.clicked.connect(self.accept)
        btns.addWidget(yes_btn)
        layout.addLayout(btns)
