import logging
from PyQt6.QtCore import QThread


def safe_stop_thread(thread, timeout=2000, blocking=False):
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
        except Exception as e:
            logging.error(f'safe_stop_thread: error stopping thread {type(thread).__name__}: {e}', exc_info=True)
