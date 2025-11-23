from PyQt6.QtCore import QTimer
from typing import Callable, Optional


class DebounceTimer:

    def __init__(self, delay_ms: int = 200):
        self.delay_ms = delay_ms
        self._timer: Optional[QTimer] = None
        self._callback: Optional[Callable] = None

    def call(self, callback: Callable) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer.deleteLater()
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._callback = callback
        self._timer.timeout.connect(self._execute)
        self._timer.start(self.delay_ms)

    def _execute(self) -> None:
        if self._callback is not None:
            try:
                self._callback()
            except Exception as e:
                import logging
                logging.error(f'DebounceTimer: Error executing callback: {e}', exc_info=True)
        self._timer = None
        self._callback = None

    def cancel(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer.deleteLater()
            self._timer = None
            self._callback = None


def create_debounce_timer(delay_ms: int = 200) -> DebounceTimer:
    return DebounceTimer(delay_ms)
