import logging
from PyQt6.QtCore import QThread


def safe_stop_thread(thread, timeout=2000):
    if not thread:
        return
    if isinstance(thread, QThread):
        try:
            if not thread.isRunning():
                return
            thread.requestInterruption()
            thread.quit()
            if not thread.wait(timeout):
                logging.warning(f'safe_stop_thread: thread {type(thread).__name__} did not stop in {timeout}ms, terminating')
                thread.terminate()
                if not thread.wait(1000):
                    logging.error(f'safe_stop_thread: failed to terminate thread {type(thread).__name__}')
                elif thread.isRunning():
                    logging.error(f'safe_stop_thread: {type(thread).__name__} still running after terminate and wait')
        except Exception as e:
            logging.error(f'safe_stop_thread: error stopping thread {type(thread).__name__}: {e}', exc_info=True)
