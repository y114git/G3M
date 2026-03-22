import logging

from PyQt6.QtCore import QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QPushButton, QTextBrowser, QVBoxLayout

from services.localization_service import tr


class AnnounceDialog(QDialog):
    accepted_with_ok = pyqtSignal()

    def __init__(self, message: str, link: str = "", parent=None) -> None:
        super().__init__(parent)
        self.link = link
        self.setWindowTitle(tr("dialogs.announce_title"))
        self.setMinimumWidth(750)
        self.setMinimumHeight(600)
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        text_browser = QTextBrowser()
        text_browser.setOpenExternalLinks(True)
        document = text_browser.document()
        if document is not None:
            document.setDefaultStyleSheet("p { margin: 0.5em 0; }")
        try:
            from ui.common.rich_html import set_rich_html

            set_rich_html(text_browser, message)
        except Exception:
            text_browser.setHtml(message)
        text_browser.setReadOnly(True)
        layout.addWidget(text_browser, 1)
        if link:
            link_layout = QHBoxLayout()
            link_layout.addStretch()
            details_button = QPushButton(tr("dialogs.announce_details_button"))
            details_button.clicked.connect(self._open_link)
            link_layout.addWidget(details_button)
            link_layout.addStretch()
            layout.addLayout(link_layout)
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        ok_button = QPushButton(tr("ui.ok"))
        ok_button.clicked.connect(self._on_ok_clicked)
        ok_button.setDefault(True)
        button_layout.addWidget(ok_button)
        layout.addLayout(button_layout)

    def _on_ok_clicked(self):
        self.accepted_with_ok.emit()
        self.accept()

    def _open_link(self):
        if self.link:
            try:
                QDesktopServices.openUrl(QUrl(self.link))
            except Exception as e:
                logging.error(f"Failed to open announce link: {e}")
