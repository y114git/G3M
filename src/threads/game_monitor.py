import time
from PyQt6.QtCore import QThread, pyqtSignal
from utils.game_utils import is_game_running
from utils.network_utils import increment_launch_counter

class GameMonitorThread(QThread):
    finished = pyqtSignal(bool)

    def __init__(self, process, vanilla_mode, parent=None):
        super().__init__(parent)
        self.process = process
        self.vanilla_mode = vanilla_mode

    def run(self):
        increment_launch_counter()
        if self.process:
            try:
                self.process.wait()
            except Exception:
                pass
            finally:
                self.finished.emit(self.vanilla_mode)
                return
        game_appeared = False
        consecutive_checks = 0
        for _ in range(45):
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
            time.sleep(1)
        time.sleep(2)
        if not is_game_running():
            self.finished.emit(self.vanilla_mode)
