import logging
from typing import Dict, List, Any
from PyQt6.QtCore import QThread, pyqtSignal
from managers.multi_mod_merger import MultiModMerger


class ModMergeThread(QThread):
    progress_update = pyqtSignal(int, str)
    status_update = pyqtSignal(str, str)
    finished = pyqtSignal(bool)

    def __init__(self, app_state, mod_manager, chapter_mods: Dict[int, List[Any]], session_manifest_path: str, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.mod_manager = mod_manager
        self.chapter_mods = chapter_mods
        self.session_manifest_path = session_manifest_path
        self.merger = None
        self._cancelled = False

    def cancel(self):
        self._cancelled = True
        if self.merger:
            self.merger._cancelled = True
        self.status_update.emit('Operation cancelled', 'error')

    def run(self):
        try:
            self.merger = MultiModMerger(self.app_state, self.mod_manager, None)
            self.merger.progress_update.connect(self.progress_update.emit)
            self.merger.status_update.connect(self.status_update.emit)
            self.merger._session_manifest_path = self.session_manifest_path
            self.merger._cancelled = False
            if self._cancelled:
                self.finished.emit(False)
                return
            success = self.merger.merge_mods_for_chapters(self.chapter_mods)
            if self._cancelled:
                self.merger._cancelled = True
                if self.merger:
                    for chapter_id in self.chapter_mods.keys():
                        self.merger._restore_backups(chapter_id)
                success = False
            self.finished.emit(success)
        except Exception as e:
            logging.error(f'ModMergeThread failed: {e}', exc_info=True)
            self.status_update.emit(f'Merge failed: {str(e)}', 'error')
            self.finished.emit(False)
