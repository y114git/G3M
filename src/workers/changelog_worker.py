"""Changelog fetching worker."""

import os
import time

import requests
from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot

from config.constants import NETWORK_TIMEOUT_MEDIUM
from services.localization_service import tr
from utils.network_utils import get_session


class FetchChangelogWorker(QObject):
    finished = pyqtSignal(str)

    def __init__(self, source_path_or_url: str, parent=None) -> None:
        super().__init__(parent)
        self.source = source_path_or_url

    @pyqtSlot()
    def run(self):
        thread = QThread.currentThread()
        try:
            if thread.isInterruptionRequested():
                return
            if self.source.startswith(("http://", "https://")):
                resp = get_session().get(
                    self.source,
                    params={"ts": int(time.time())},
                    headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
                    timeout=NETWORK_TIMEOUT_MEDIUM,
                )
                if thread.isInterruptionRequested():
                    return
                resp.raise_for_status()
                if thread.isInterruptionRequested():
                    return
                text = resp.text
            else:
                path = (
                    self.source
                    if os.path.exists(self.source)
                    else (
                        self.source.replace(".md", ".txt")
                        if os.path.exists(self.source.replace(".md", ".txt"))
                        else None
                    )
                )
                if thread.isInterruptionRequested():
                    return
                if path:
                    with open(path, encoding="utf-8", errors="replace") as f:
                        text = f.read()
                else:
                    text = self.source
        except (
            requests.RequestException,
            FileNotFoundError,
            OSError,
            UnicodeDecodeError,
        ):
            if thread.isInterruptionRequested():
                return
            text = tr("errors.changelog_load_failed")
        if thread.isInterruptionRequested():
            return
        self.finished.emit(text)
