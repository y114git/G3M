"""Thread management utilities.

This module provides utilities for safely managing Qt threads.
"""
import logging
from PyQt6.QtCore import QThread


def safe_stop_thread(thread, timeout=2000):
    """Safely stop a Qt thread with timeout and termination fallback.

    Args:
        thread: QThread instance to stop.
        timeout: Timeout in milliseconds to wait for thread to stop.
    """
    if not thread or not isinstance(thread, QThread):
        return
    try:
        if not thread.isRunning():
            return
        thread.requestInterruption()
        thread.quit()
        if thread.wait(timeout):
            return
        logging.warning(f'safe_stop_thread: thread {type(thread).__name__} did not stop in {timeout}ms, terminating')
        thread.terminate()
        if not thread.wait(1000):
            logging.error(f'safe_stop_thread: failed to terminate thread {type(thread).__name__}')
        elif thread.isRunning():
            logging.error(f'safe_stop_thread: {type(thread).__name__} still running after terminate and wait')
    except Exception as e:
        logging.error(f'safe_stop_thread: error stopping thread {type(thread).__name__}: {e}', exc_info=True)
