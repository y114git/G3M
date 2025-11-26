import logging
from PyQt6.QtCore import QTimer, QThread
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


def format_size_mb(size_bytes: int) -> str:
    if size_bytes <= 0:
        return '0 MB'
    mb = size_bytes / (1024 * 1024)
    return f'{mb:.1f} MB'


def safe_stop_thread(thread, timeout=2000, blocking=True):
    if not thread:
        return
    if isinstance(thread, QThread):
        try:
            if not thread.isRunning():
                return
            thread.requestInterruption()
            thread.quit()
            if blocking:
                if not thread.wait(timeout):
                    logging.warning(f'safe_stop_thread: thread {type(thread).__name__} did not stop in {timeout}ms. Thread may be blocked. Consider checking isInterruptionRequested() in worker loops.')
                    try:
                        thread.terminate()
                        thread.wait(500)
                    except Exception:
                        pass
        except (RuntimeError, AttributeError):
            pass
        except Exception as e:
            logging.error(f'safe_stop_thread: error stopping thread {type(thread).__name__}: {e}', exc_info=True)
