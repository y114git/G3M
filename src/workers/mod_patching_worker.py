"""Worker thread for multi-mod patching operations."""
import logging
import threading
from typing import Dict, List, Any, Optional
from PyQt6.QtCore import QThread, pyqtSignal
from services.mod_patching_service import ModPatcher


class ModPatchingThread(QThread):
    """Background thread for mod patching operations."""
    progress_update = pyqtSignal(int, str)
    status_update = pyqtSignal(str, str)
    finished = pyqtSignal(bool)
    warning_confirmation_needed = pyqtSignal(str, str, str)

    def __init__(self, app_state, mod_service, chapter_mods: Dict[int, List[Any]], session_manifest_path: str, parent=None, fast_merge: bool = False):
        super().__init__(parent)
        self.app_state = app_state
        self.mod_service = mod_service
        self.chapter_mods = chapter_mods
        self.session_manifest_path = session_manifest_path
        self.fast_merge = fast_merge
        self.patcher = None
        self._cancelled = False
        self._warning_response: Optional[bool] = None
        self._warning_event = threading.Event()

    def set_warning_response(self, response: bool):
        self._warning_response = response
        self._warning_event.set()

    def _handle_warning(self, warning_type: str, title: str, message: str) -> bool:
        self._warning_event.clear()
        self._warning_response = None
        self.warning_confirmation_needed.emit(warning_type, title, message)
        self._warning_event.wait()
        return self._warning_response if self._warning_response is not None else True

    def cancel(self):
        self._cancelled = True
        self.requestInterruption()
        if self.patcher:
            self.patcher._cancelled = True
        try:
            self.status_update.emit('Operation cancelled', 'error')
        except RuntimeError:
            pass

    def _restore_backups(self, require_original_files: bool = False):
        if not self.patcher or not self.patcher.backup_service:
            return
        if require_original_files and (not self.patcher.backup_service.original_files):
            return
        for chapter_id in self.chapter_mods.keys():
            if require_original_files and chapter_id not in self.patcher.backup_service.original_files:
                continue
            self.patcher.backup_service.restore_backups(chapter_id)

    def run(self):
        success = False
        try:
            if self.isInterruptionRequested() or self._cancelled:
                self.finished.emit(False)
                return
            self.patcher = ModPatcher(self.app_state, self.mod_service, None)
            try:
                self.patcher.progress_update.connect(self.progress_update.emit)
                self.patcher.status_update.connect(self.status_update.emit)
            except RuntimeError:
                pass
            self.patcher._warning_callback = self._handle_warning
            self.patcher.warning_confirmation_needed.connect(lambda wt, t, m: self.warning_confirmation_needed.emit(wt, t, m))
            self.patcher._session_manifest_path = self.session_manifest_path
            self.patcher._cancelled = False
            if self.isInterruptionRequested() or self._cancelled:
                self.finished.emit(False)
                return
            success = self.patcher.process_mod_merge(self.chapter_mods, is_modpack=False, fast_merge=self.fast_merge)
            if self.isInterruptionRequested() or self._cancelled:
                self.patcher._cancelled = True
                if self.patcher:
                    self._restore_backups()
                success = False
            try:
                self.finished.emit(success)
            except RuntimeError:
                pass
        except Exception as e:
            logging.error(f'ModPatchingThread failed: {e}', exc_info=True)
            try:
                self.status_update.emit(f'Patching failed: {str(e)}', 'error')
                self.finished.emit(False)
            except RuntimeError:
                pass
        finally:
            if self.patcher:
                should_restore = (self.isInterruptionRequested() or self._cancelled or not success)
                if should_restore and self.patcher.backup_service:
                    self._restore_backups(require_original_files=True)
                if self.isInterruptionRequested() or self._cancelled or not success:
                    self.patcher.cleanup(force=True)
                else:
                    self.patcher.cleanup(force=False)
