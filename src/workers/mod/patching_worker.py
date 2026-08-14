"""Worker thread for multi-mod patching operations."""

import logging
import threading
from collections.abc import Iterable
from typing import Any

from PyQt6.QtCore import pyqtSignal

from models.execution_plan import PatchPlan
from services.g3mtool_patching_service import G3MToolPatchingService
from ui.utils.thread_lifetime import ManagedQThread
from ui.utils.thread_lifetime import safe_emit as _safe_emit

logger = logging.getLogger(__name__)


class ModPatchingThread(ManagedQThread):
    """Background thread for mod patching operations."""

    progress_update = pyqtSignal(int, str)
    status_update = pyqtSignal(str, str)
    warning_confirmation_needed = pyqtSignal(object, str, object)
    result_ready = pyqtSignal(bool)

    def __init__(
        self,
        app_state,
        mod_service,
        patch_plan: PatchPlan,
        session_manifest_path: str,
        parent=None,
        *,
        plan_mods: Iterable[Any] = (),
    ) -> None:
        super().__init__(parent)
        self.app_state = app_state
        self.mod_service = mod_service
        self.patch_plan = patch_plan
        self._plan_mods = tuple(plan_mods)
        self.session_manifest_path = session_manifest_path
        self.patcher: G3MToolPatchingService | None = None
        self._cancelled = False
        self._warning_event = threading.Event()
        self._warning_result = True

    def cancel(self):
        self._cancelled = True
        self.requestInterruption()
        self._warning_event.set()
        if self.patcher:
            self.patcher.cancel()
        _safe_emit(self.__class__.__name__, self.status_update, "Operation cancelled", "error")

    def confirm_warning(self, accepted: bool):
        self._warning_result = accepted
        self._warning_event.set()

    def _request_warning_confirmation(
        self, message: object, details: str = "", report_path: str | None = None
    ) -> bool:
        self._warning_result = True
        self._warning_event.clear()
        _safe_emit(
            self.__class__.__name__,
            self.warning_confirmation_needed,
            message,
            details,
            report_path,
        )
        while not self._warning_event.wait(0.1):
            if self.isInterruptionRequested() or self._cancelled:
                return False
        return self._warning_result and not (
            self.isInterruptionRequested() or self._cancelled
        )

    def _restore_backups(self):
        """Restore all backups and clear persistent backup dir + manifest."""
        if not self.patcher or not self.patcher.backup_service:
            return
        if (
            not self.patcher.backup_service.original_files
            and not self.patcher.backup_service.added_files
        ):
            return
        self.patcher.restore_all_backups()

    def run(self):
        success = False
        try:
            if self.isInterruptionRequested() or self._cancelled:
                return
            self.patcher = G3MToolPatchingService(
                self.app_state, self.mod_service, None
            )
            try:
                self.patcher.progress_update.connect(
                    lambda progress, message: _safe_emit(
                        self.__class__.__name__,
                        self.progress_update,
                        progress,
                        message,
                    )
                )
                self.patcher.status_update.connect(
                    lambda message, status_type: _safe_emit(
                        self.__class__.__name__,
                        self.status_update,
                        message,
                        status_type,
                    )
                )
            except RuntimeError:
                logger.debug("Failed to connect patcher signals")
            self.patcher._session_manifest_path = self.session_manifest_path
            self.patcher.warning_handler = self._request_warning_confirmation
            if self.isInterruptionRequested() or self._cancelled:
                return
            mods_by_id = {
                str(getattr(mod, "id", "")): mod
                for mod in getattr(self.app_state, "all_mods", ())
                if getattr(mod, "id", None)
            }
            mods_by_id.update(
                {
                    str(getattr(mod, "id", "")): mod
                    for mod in self._plan_mods
                    if getattr(mod, "id", None)
                }
            )
            success = self.patcher.process_patch_plan(
                self.patch_plan, mods_by_id.get, is_modpack=False
            )
            if self.isInterruptionRequested() or self._cancelled:
                self.patcher.cancel()
                success = False
        except Exception as e:
            logger.error(f"ModPatchingThread failed: {e}", exc_info=True)
            _safe_emit(
                self.__class__.__name__,
                self.status_update,
                f"Patching failed: {e!s}",
                "error",
            )
        finally:
            try:
                if self.patcher:
                    failed = (
                        self.isInterruptionRequested() or self._cancelled or not success
                    )
                    if failed:
                        self._restore_backups()
                    self.patcher.cleanup(force=True)
            finally:
                _safe_emit(self.__class__.__name__, self.result_ready, success)
