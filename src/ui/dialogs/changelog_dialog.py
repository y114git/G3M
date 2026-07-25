"""Dialog for viewing changelog entries."""

from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QDialog, QPushButton, QTextBrowser, QVBoxLayout

from config.config import NETWORK_TIMEOUT_MEDIUM
from services.localization_service import tr
from workers.changelog_worker import FetchChangelogWorker


class ChangelogDialog(QDialog):
    def __init__(self, parent=None, source: str = "") -> None:
        super().__init__(parent)
        self._thread = None
        self._worker = None
        self._source = (source or "").strip()
        self._showing_loading = True
        self._load_failed = False
        self.setWindowTitle(tr("buttons.changelog"))
        self.resize(820, 620)
        self._init_ui()
        self._load_changelog()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        self.text_browser = QTextBrowser(self)
        self.text_browser.setOpenExternalLinks(True)
        self.text_browser.setMarkdown(f"<i>{tr('status.loading')}</i>")
        layout.addWidget(self.text_browser)
        self.close_button = QPushButton(tr("buttons.close"), self)
        self.close_button.clicked.connect(self.accept)
        layout.addWidget(self.close_button)

    def _load_changelog(self):
        if not self._source:
            self._showing_loading = False
            self._load_failed = True
            self.text_browser.setMarkdown(tr("status.changelog_load_failed"))
            return
        self._thread = QThread(self)
        self._worker = FetchChangelogWorker(self._source)
        self._worker.moveToThread(self._thread)
        self._worker.finished.connect(self._on_changelog_loaded)
        self._worker.finished.connect(self._thread.quit)
        self._thread.started.connect(self._worker.run)
        self._thread.finished.connect(self._cleanup_thread)
        self._thread.start()

    def _on_changelog_loaded(self, text: str):
        self._showing_loading = False
        self.text_browser.setMarkdown(text)

    def relocalize_ui(self) -> None:
        self.setWindowTitle(tr("buttons.changelog"))
        self.close_button.setText(tr("buttons.close"))
        if self._showing_loading:
            self.text_browser.setMarkdown(f"<i>{tr('status.loading')}</i>")
        elif self._load_failed:
            self.text_browser.setMarkdown(tr("status.changelog_load_failed"))

    def _cleanup_thread(self):
        if self._worker:
            self._worker.deleteLater()
            self._worker = None
        if self._thread:
            self._thread.deleteLater()
            self._thread = None

    def _stop_thread(self) -> bool:
        if not self._thread:
            return True
        if not self._thread.isRunning():
            self._cleanup_thread()
            return True
        self._thread.requestInterruption()
        self._thread.quit()
        thread_finished = self._thread.wait(int(NETWORK_TIMEOUT_MEDIUM * 1000))
        if thread_finished:
            self._cleanup_thread()
        return thread_finished

    def closeEvent(self, event):
        if not self._stop_thread():
            event.ignore()
            return
        super().closeEvent(event)
