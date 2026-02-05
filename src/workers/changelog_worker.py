"""Changelog fetching worker."""
import os
import time
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot
from config.constants import NETWORK_TIMEOUT_MEDIUM
from services.localization_service import tr
from utils.network_utils import get_session


class FetchChangelogWorker(QObject):
    finished = pyqtSignal(str)

    def __init__(self, source_path_or_url: str, parent=None):
        super().__init__(parent)
        self.source = source_path_or_url

    @pyqtSlot()
    def run(self):
        try:
            if self.source.startswith(('http://', 'https://')):
                resp = get_session().get(self.source, params={'ts': int(time.time())}, headers={'Cache-Control': 'no-cache', 'Pragma': 'no-cache'}, timeout=NETWORK_TIMEOUT_MEDIUM)
                resp.raise_for_status()
                text = resp.text
            else:
                path = self.source if os.path.exists(self.source) else (self.source.replace('.md', '.txt') if os.path.exists(self.source.replace('.md', '.txt')) else None)
                text = open(path, 'r', encoding='utf-8', errors='replace').read() if path else self.source
        except Exception:
            text = tr('errors.changelog_load_failed')
        self.finished.emit(text)
