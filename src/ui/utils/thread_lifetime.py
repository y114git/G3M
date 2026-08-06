"""Native-safe lifetime handling for QThread wrappers."""

from PyQt6.QtCore import QThread

from services.background_operations import background_operations


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
