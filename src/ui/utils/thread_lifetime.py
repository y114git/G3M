"""Native-safe lifetime handling for QThread wrappers."""

import logging

from PyQt6.QtCore import QThread

from services.background_operations import background_operations

logger = logging.getLogger(__name__)


def safe_emit(owner: str, signal, *args, emitter=None) -> None:
    try:
        (emitter or signal.emit)(*args)
    except Exception as e:
        logger.warning("%s: failed to emit signal: %s", owner, e, exc_info=True)


class ManagedQThread(QThread):
    """QThread whose Python wrapper is retained for its entire native run."""

    def start(self, priority=QThread.Priority.InheritPriority) -> None:
        background_operations.retain_thread(self)
        try:
            super().start(priority)
        except Exception:
            background_operations.release_thread(self)
            raise


def retire_qthread(thread) -> None:
    """Delete a thread only after its native run method has returned."""
    background_operations.retire_thread(thread)
