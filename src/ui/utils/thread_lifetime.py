"""Native-safe lifetime handling for QThread wrappers."""

import contextlib
import logging
from typing import Any

from PyQt6.QtCore import QThread

logger = logging.getLogger(__name__)

_retiring_threads: dict[int, Any] = {}
_running_threads: dict[int, Any] = {}


class ManagedQThread(QThread):
    """QThread whose Python wrapper is retained for its entire native run."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.finished.connect(self._release_native_lifetime)

    def start(self, priority=QThread.Priority.InheritPriority) -> None:
        _running_threads[id(self)] = self
        try:
            super().start(priority)
        except Exception:
            _running_threads.pop(id(self), None)
            raise

    def _release_native_lifetime(self) -> None:
        _running_threads.pop(id(self), None)


def retire_qthread(thread) -> None:
    """Delete a thread only after its native run method has returned."""
    if thread is None:
        return
    try:
        if not thread.isRunning():
            thread.deleteLater()
            return
    except (AttributeError, RuntimeError):
        return

    key = id(thread)
    if key in _retiring_threads:
        return
    _retiring_threads[key] = thread

    def _delete_after_native_finish() -> None:
        retained = _retiring_threads.pop(key, None)
        if retained is None:
            return
        with contextlib.suppress(RuntimeError):
            retained.deleteLater()

    try:
        thread.finished.connect(_delete_after_native_finish)
        if not thread.isRunning():
            _delete_after_native_finish()
    except (AttributeError, RuntimeError, TypeError):
        logger.debug("Unable to retain QThread until completion", exc_info=True)
        _retiring_threads.pop(key, None)
