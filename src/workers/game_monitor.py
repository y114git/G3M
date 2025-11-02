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

    @pyqtSlot()
    def run(self):
        try:
            increment_launch_counter()
            if self.process:
                try:
                    self.process.wait()
                except Exception as e:
                    logging.warning(f'GameMonitorWorker.run: process.wait() failed: {e}', exc_info=True)
                finally:
                    self.finished.emit(self.vanilla_mode)
                    return
            game_appeared = False
            consecutive_checks = 0
            for _ in range(45):
                if QThread.currentThread().isInterruptionRequested():
                    logging.debug('GameMonitorWorker.run: interruption requested, stopping')
                    return
                if is_game_running():
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
            while is_game_running():
                if QThread.currentThread().isInterruptionRequested():
                    logging.debug('GameMonitorWorker.run: interruption requested during game monitoring')
                    return
                time.sleep(1)
            time.sleep(2)
            if not is_game_running():
                self.finished.emit(self.vanilla_mode)
        except Exception as e:
            logging.error(f'GameMonitorWorker.run: unexpected error: {e}', exc_info=True)
            self.finished.emit(self.vanilla_mode)
