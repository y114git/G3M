"""Worker thread for multi-mod patching operations."""
import logging
from typing import Dict, List, Any, Optional
from PyQt6.QtCore import QThread, pyqtSignal
from services.g3mtool_patching_service import G3MToolPatchingService


class ModPatchingThread(QThread):
    """Background thread for mod patching operations."""
    progress_update = pyqtSignal(int, str)
    status_update = pyqtSignal(str, str)
    finished = pyqtSignal(bool)

    def __init__(self, app_state, mod_service, chapter_mods: Dict[int, List[Any]], session_manifest_path: str, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.mod_service = mod_service
        self.chapter_mods = chapter_mods
        self.session_manifest_path = session_manifest_path
        self.patcher: Optional[G3MToolPatchingService] = None
        self._cancelled = False

    def cancel(self):
        self._cancelled = True
        self.requestInterruption()
        if self.patcher:
            self.patcher.cancel()
        try:
            self.status_update.emit('Operation cancelled', 'error')
        except RuntimeError:
            pass

    def _restore_backups(self):
        """Restore all backups and clear persistent backup dir + manifest."""
        if not self.patcher or not self.patcher.backup_service:
            return
        if not self.patcher.backup_service.original_files and not self.patcher.backup_service.added_files:
            return
        self.patcher.restore_all_backups()

    def run(self):
        success = False
        try:
            if self.isInterruptionRequested() or self._cancelled:
                self.finished.emit(False)
                return
            self.patcher = G3MToolPatchingService(self.app_state, self.mod_service, None)
            try:
                self.patcher.progress_update.connect(self.progress_update.emit)
                self.patcher.status_update.connect(self.status_update.emit)
            except RuntimeError:
                pass
            self.patcher._session_manifest_path = self.session_manifest_path
            if self.isInterruptionRequested() or self._cancelled:
                self.finished.emit(False)
                return
            success = self.patcher.process_mod_patch(self.chapter_mods, is_modpack=False)
            if self.isInterruptionRequested() or self._cancelled:
                self.patcher.cancel()
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
                failed = self.isInterruptionRequested() or self._cancelled or not success
                if failed:
                    self._restore_backups()

                self.patcher.cleanup(force=True)
