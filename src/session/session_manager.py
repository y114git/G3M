"""Tracks application session state and identifiers."""

from __future__ import annotations

import logging
import uuid

from PyQt6.QtCore import QMetaObject, QObject, Qt, QThread, QTimer, pyqtSignal

from config.config import ONLINE_UPDATE_INTERVAL
from ui.utils.ui_utils import safe_stop_thread
from workers.presence_worker import PresenceWorker

logger = logging.getLogger(__name__)


class SessionManager(QObject):
    online_count_changed = pyqtSignal(int)

    def __init__(self, app_state, parent=None) -> None:
        super().__init__(parent)
        self.session_id = uuid.uuid4().hex
        self.thread = QThread(parent)
        self.worker = PresenceWorker(self.session_id, app_state)
        self.worker.moveToThread(self.thread)
        self.worker.update_online_count.connect(self.online_count_changed.emit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.timer = QTimer(parent)
        self.timer.timeout.connect(self.request_presence_refresh)

    def start(self) -> None:
        if not self.thread.isRunning():
            self.thread.start()
        self.timer.start(ONLINE_UPDATE_INTERVAL)
        self.request_presence_refresh()

    def request_presence_refresh(self) -> None:
        if not self.thread.isRunning():
            return
        try:
            QMetaObject.invokeMethod(
                self.worker, "run", Qt.ConnectionType.QueuedConnection
            )
        except RuntimeError:
            logger.debug("SessionManager: failed to queue presence refresh")

    def stop(self) -> None:
        self.timer.stop()
        timeout_ms = max(
            2000,
            int((getattr(self.worker, "_REQUEST_TIMEOUT_SECONDS", 2) + 0.5) * 1000),
        )
        safe_stop_thread(self.thread, timeout=timeout_ms, blocking=True)
