"""Tracks application session state and identifiers."""

from __future__ import annotations

import logging
import uuid

from PyQt6.QtCore import QMetaObject, QObject, Qt, QTimer, pyqtSignal

from config.config import ONLINE_UPDATE_INTERVAL
from ui.utils.thread_lifetime import ManagedQThread
from ui.utils.ui_utils import safe_stop_thread
from workers.presence_worker import PresenceWorker

logger = logging.getLogger(__name__)


class SessionManager(QObject):
    online_count_changed = pyqtSignal(int)
    global_settings_received = pyqtSignal(dict)

    def __init__(self, app_state, parent=None) -> None:
        super().__init__(parent)
        self.session_id = uuid.uuid4().hex
        self._thread = ManagedQThread(parent)
        self.worker = PresenceWorker(self.session_id, app_state)
        self.worker.moveToThread(self._thread)
        self.worker.update_online_count.connect(self._handle_online_count)
        self.worker.global_settings_received.connect(self.global_settings_received.emit)
        self._thread.finished.connect(self.worker.deleteLater)
        self.timer = QTimer(parent)
        self.timer.timeout.connect(self.request_presence_refresh)
        self._startup_retry_timer = QTimer(parent)
        self._startup_retry_timer.setSingleShot(True)
        self._startup_retry_timer.setInterval(5000)
        self._startup_retry_timer.timeout.connect(self.request_presence_refresh)

    def start(self) -> None:
        if not self._thread.isRunning():
            self._thread.start()
        self.timer.start(ONLINE_UPDATE_INTERVAL)
        self.request_presence_refresh()

    def request_presence_refresh(self) -> None:
        if not self._thread.isRunning():
            return
        try:
            QMetaObject.invokeMethod(
                self.worker, "run", Qt.ConnectionType.QueuedConnection
            )
        except RuntimeError:
            logger.debug("SessionManager: failed to queue presence refresh")

    def _handle_online_count(self, count: int) -> None:
        self.online_count_changed.emit(count)
        if count < 0 and self._thread.isRunning():
            self._startup_retry_timer.start()
        else:
            self._startup_retry_timer.stop()

    def stop(self) -> None:
        self.timer.stop()
        self._startup_retry_timer.stop()
        timeout_ms = max(
            2000,
            int((self.worker.REQUEST_TIMEOUT_SECONDS + 0.5) * 1000),
        )
        safe_stop_thread(self._thread, timeout=timeout_ms, blocking=True)
