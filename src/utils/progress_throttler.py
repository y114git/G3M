"""Progress update throttler to avoid overwhelming the UI."""
import threading
from PyQt6.QtCore import QObject, QTimer


class ProgressThrottler(QObject):
    """Throttles progress updates to avoid overwhelming the UI."""

    def __init__(self, callback, throttle_ms: int = 150, parent=None):
        super().__init__(parent)
        self.callback = callback
        self.throttle_ms = throttle_ms
        self._pending_progress = None
        self._pending_message = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._emit_pending_update)
        self._lock = threading.Lock()

    def update_progress(self, progress: int, message: str):
        with self._lock:
            self._pending_progress = progress
            self._pending_message = message
            if not self._timer.isActive():
                self._timer.start(self.throttle_ms)

    def _emit_pending_update(self):
        with self._lock:
            if self._pending_progress is not None and self._pending_message is not None:
                self.callback(self._pending_progress, self._pending_message)
                self._pending_progress = None
                self._pending_message = None

    def flush(self):
        self._timer.stop()
        self._emit_pending_update()
