"""Placeholder dialog shown for the former community entry point."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from config.config import SOCIAL_LINKS
from services.localization_service import tr
from utils.native_integration import open_url_native


class CommunityDialog(QDialog):
    def __init__(self, parent, app_state) -> None:
        super().__init__(parent)
        self._app_state = app_state
        self.setWindowTitle(tr("community_removed.title"))
        self.setModal(True)
        self.resize(720, 320)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.addStretch(1)
        global_settings = getattr(self._app_state, "global_settings", {}) or {}

        self.heading_label = QLabel(tr("community_removed.heading"))
        self.heading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading_font = self.heading_label.font()
        heading_font.setPointSize(max(18, heading_font.pointSize() + 6))
        heading_font.setBold(True)
        self.heading_label.setFont(heading_font)
        layout.addWidget(self.heading_label)

        layout.addSpacing(28)
        message = QLabel(tr("community_removed.message"))
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message.setWordWrap(True)
        layout.addWidget(message)

        layout.addSpacing(20)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.telegram_button = QPushButton(tr("buttons.telegram"))
        self.telegram_button.clicked.connect(
            lambda: open_url_native(
                global_settings.get(
                    "telegram_url",
                    SOCIAL_LINKS["telegram"],
                )
            )
        )
        self.discord_button = QPushButton(tr("buttons.discord"))
        self.discord_button.clicked.connect(
            lambda: open_url_native(
                global_settings.get(
                    "discord_url",
                    SOCIAL_LINKS["discord"],
                )
            )
        )
        self.close_button = QPushButton(tr("buttons.close"))
        self.close_button.clicked.connect(self.accept)
        for button in (self.telegram_button, self.discord_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_row.addWidget(self.close_button)
        layout.addLayout(close_row)
