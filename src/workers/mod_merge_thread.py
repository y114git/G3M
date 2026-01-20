import logging
from typing import Dict, List, Any
from PyQt6.QtCore import QThread, pyqtSignal
from managers.multi_mod_merger import MultiModMerger


class ModMergeThread(QThread):
    progress_update = pyqtSignal(int, str)
    status_update = pyqtSignal(str, str)
    finished = pyqtSignal(bool)

    def __init__(self, app_state, mod_manager, chapter_mods: Dict[int, List[Any]], session_manifest_path: str, parent=None, fast_merge: bool = False):
        super().__init__(parent)
        self.app_state = app_state
        self.mod_manager = mod_manager
        self.chapter_mods = chapter_mods
        self.session_manifest_path = session_manifest_path
        self.fast_merge = fast_merge
        self.merger = None
        self._cancelled = False

    def cancel(self):
        self._cancelled = True
        self.requestInterruption()
        if self.merger:
            self.merger._cancelled = True
        try:
            self.status_update.emit('Operation cancelled', 'error')
        except RuntimeError:
            pass

    def _restore_backups(self, require_original_files: bool = False):
        if not self.merger or not self.merger.backup_manager:
            return
        if require_original_files and (not self.merger.backup_manager.original_files):
            return
        for chapter_id in self.chapter_mods.keys():
            if require_original_files and chapter_id not in self.merger.backup_manager.original_files:
                continue
            self.merger.backup_manager.restore_backups(chapter_id)

    def run(self):
        try:
            if self.isInterruptionRequested() or self._cancelled:
                self.finished.emit(False)
                return
            self.merger = MultiModMerger(self.app_state, self.mod_manager, None)
            try:
                self.merger.progress_update.connect(self.progress_update.emit)
                self.merger.status_update.connect(self.status_update.emit)
            except RuntimeError:
                pass
            self.merger._session_manifest_path = self.session_manifest_path
            self.merger._cancelled = False
            if self.isInterruptionRequested() or self._cancelled:
                self.finished.emit(False)
                return
            success = self.merger.process_mod_merge(self.chapter_mods, is_modpack=False, fast_merge=self.fast_merge)
            if self.isInterruptionRequested() or self._cancelled:
                self.merger._cancelled = True
                if self.merger:
                    self._restore_backups()
                success = False
            try:
                self.finished.emit(success)
            except RuntimeError:
                pass
        except Exception as e:
            logging.error(f'ModMergeThread failed: {e}', exc_info=True)
            try:
                self.status_update.emit(f'Merge failed: {str(e)}', 'error')
                self.finished.emit(False)
            except RuntimeError:
                pass
        finally:
            if self.merger:
                if (self.isInterruptionRequested() or self._cancelled) and self.merger.backup_manager:
                    self._restore_backups(require_original_files=True)
                if self.isInterruptionRequested() or self._cancelled:
                    self.merger.cleanup(force=True)
                else:
                    self.merger.cleanup(force=False)
