import logging
from typing import Dict, List
from PyQt6.QtCore import QThread, pyqtSignal
from managers.gamebanana_update_manager import GameBananaUpdateManager
from models.mod_models import ModInfo
logger = logging.getLogger(__name__)


class CheckGBUpdatesThread(QThread):
    update_found = pyqtSignal(str, bool)
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(dict)

    def __init__(self, mods_dir: str, mods_to_check: List[ModInfo] = None, parent=None):
        super().__init__(parent)
        self.mods_dir = mods_dir
        self.mods_to_check = mods_to_check
        self._cancelled = False

    def cancel(self):
        self._cancelled = True
        self.requestInterruption()

    def run(self):
        try:
            update_manager = GameBananaUpdateManager(self.mods_dir)
            updates = {}
            if self.mods_to_check:
                mods_list = self.mods_to_check
            else:
                mods_list = update_manager.get_installed_gamebanana_mods()
            total = len(mods_list)
            for idx, mod_info in enumerate(mods_list):
                if self._cancelled or self.isInterruptionRequested():
                    logger.debug('CheckGBUpdatesThread: Cancelled by user')
                    break
                try:
                    mod_id = mod_info.gamebanana_mod_id
                    if not mod_id:
                        continue
                    has_update = update_manager.check_mod_for_updates(mod_info)
                    updates[mod_id] = has_update
                    self.progress.emit(idx + 1, total)
                    self.update_found.emit(mod_id, has_update)
                except Exception as e:
                    logger.warning(f'CheckGBUpdatesThread: Error checking mod {mod_info.name}: {e}')
                    continue
            if not self._cancelled:
                self.finished.emit(updates)
        except Exception as e:
            logger.error(f'CheckGBUpdatesThread: Error during update check: {e}', exc_info=True)
            self.finished.emit({})
