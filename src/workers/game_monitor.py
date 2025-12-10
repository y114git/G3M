import logging
import time
from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot
from utils.game_utils import is_game_running
from utils.network_utils import increment_launch_counter


class GameMonitorWorker(QObject):
    finished = pyqtSignal(bool)

    def __init__(self, process, vanilla_mode, parent=None):
        super().__init__(parent)
        self.process = process
        self.vanilla_mode = vanilla_mode
        self.game_pid = None
        if process and hasattr(process, 'pid'):
            try:
                self.game_pid = process.pid
            except (AttributeError, ValueError):
                pass

    @pyqtSlot()
    def run(self):
        try:
            logging.info('[GAME_MONITOR] Starting game monitoring')
            increment_launch_counter()
            if self.process:
                try:
                    logging.info(f"[GAME_MONITOR] Monitoring process: {(self.process.pid if hasattr(self.process, 'pid') else 'unknown')}")
                    self.process.wait()
                    logging.info('[GAME_MONITOR] Game process finished')
                except Exception as e:
                    logging.warning(f'[GAME_MONITOR] process.wait() failed: {e}', exc_info=True)
                logging.info('[GAME_MONITOR] Emitting finished signal')
                self.finished.emit(self.vanilla_mode)
                return
            game_appeared = False
            consecutive_checks = 0
            for _ in range(45):
                current_thread = QThread.currentThread()
                if current_thread and current_thread.isInterruptionRequested():
                    logging.debug('GameMonitorWorker.run: interruption requested, stopping')
                    return
                if is_game_running(self.game_pid):
                    consecutive_checks += 1
                    if consecutive_checks >= 3:
                        game_appeared = True
                        break
                else:
                    consecutive_checks = 0
                time.sleep(1)
            if not game_appeared:
                self.finished.emit(self.vanilla_mode)
                return
            time.sleep(3)
            while is_game_running(self.game_pid):
                current_thread = QThread.currentThread()
                if current_thread and current_thread.isInterruptionRequested():
                    logging.debug('GameMonitorWorker.run: interruption requested during game monitoring')
                    return
                time.sleep(1)
            time.sleep(2)
            if not is_game_running(self.game_pid):
                logging.info('[GAME_MONITOR] Game is no longer running, emitting finished signal')
                self.finished.emit(self.vanilla_mode)
        except Exception as e:
            logging.error(f'[GAME_MONITOR] Unexpected error: {e}', exc_info=True)
            self.finished.emit(self.vanilla_mode)
