"""Background worker for cancellable plugin hook execution."""

from __future__ import annotations

import logging
import os
import shutil

from PyQt6.QtCore import QThread, pyqtSignal

from models.plugin_models import PluginTaskRuntime

logger = logging.getLogger(__name__)


def _safe_emit(owner: str, signal, *args) -> None:
    try:
        signal.emit(*args)
    except Exception as e:
        logger.warning("%s: failed to emit signal: %s", owner, e, exc_info=True)


class PluginHookThread(QThread):
    """Runs a plugin hook with shared progress and cancellation support."""

    progress_update = pyqtSignal(int, str)
    status_update = pyqtSignal(str, str)
    finished = pyqtSignal(bool)

    def __init__(
        self,
        runtime_service,
        hook_name: str,
        hook_args: tuple,
        *,
        base_progress: int,
        progress_span: int,
        backup_manager_provider=None,
        restore_backups_callback=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.runtime_service = runtime_service
        self.hook_name = hook_name
        self.hook_args = hook_args
        self.base_progress = int(base_progress)
        self.progress_span = max(0, int(progress_span))
        self.backup_manager_provider = backup_manager_provider
        self.restore_backups_callback = restore_backups_callback
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True
        self.requestInterruption()
        _safe_emit(self.__class__.__name__, self.status_update, "Operation cancelled", "error")

    def _is_cancelled(self) -> bool:
        return self._cancelled or self.isInterruptionRequested()

    def _emit_progress(self, progress: int, message: str = "") -> None:
        bounded = max(0, min(int(progress), 100))
        mapped = self.base_progress + round((self.progress_span * bounded) / 100)
        _safe_emit(
            self.__class__.__name__,
            self.progress_update,
            max(0, min(mapped, 100)),
            message,
        )

    def _emit_status(self, message: str, status_type: str = "info") -> None:
        _safe_emit(self.__class__.__name__, self.status_update, message, status_type)

    def _copy_backups(self, destination_dir: str) -> list[str]:
        backup_manager = (
            self.backup_manager_provider() if callable(self.backup_manager_provider) else None
        )
        if not backup_manager or not getattr(backup_manager, "backup_dir", ""):
            return []
        src_dir = backup_manager.backup_dir
        if not src_dir or not os.path.isdir(src_dir):
            return []
        os.makedirs(destination_dir, exist_ok=True)
        copied: list[str] = []
        for name in sorted(os.listdir(src_dir)):
            src_path = os.path.join(src_dir, name)
            if not os.path.isfile(src_path):
                continue
            dest_path = os.path.join(destination_dir, name)
            shutil.copy2(src_path, dest_path)
            copied.append(dest_path)
        return copied

    def _build_task_runtime(self) -> PluginTaskRuntime:
        return PluginTaskRuntime(
            set_progress_callback=self._emit_progress,
            set_status_callback=self._emit_status,
            is_cancelled_callback=self._is_cancelled,
            get_backup_manager_callback=self.backup_manager_provider,
            restore_backups_callback=self.restore_backups_callback,
            copy_backups_callback=self._copy_backups,
        )

    def run(self) -> None:
        success = False
        task_runtime = None
        try:
            task_runtime = self._build_task_runtime()
            self._emit_progress(0, "")
            results = self.runtime_service.execute_hook_with_runtime(
                self.hook_name,
                task_runtime,
                *self.hook_args,
            )
            if self._is_cancelled():
                self.runtime_service.execute_hook_with_runtime(
                    "mod_apply_cancelled",
                    task_runtime,
                    {"hook": self.hook_name, "reason": "cancelled"},
                    *self.hook_args,
                )
                success = False
            else:
                success = not any(result is False for result in results)
            self._emit_progress(100 if success else 0, "")
        except InterruptedError:
            self.runtime_service.execute_hook_with_runtime(
                "mod_apply_cancelled",
                task_runtime or self._build_task_runtime(),
                {"hook": self.hook_name, "reason": "cancelled"},
                *self.hook_args,
            )
            success = False
        except Exception as error:
            logger.error("PluginHookThread failed: %s", error, exc_info=True)
            _safe_emit(
                self.__class__.__name__,
                self.status_update,
                f"Plugin hook failed: {error}",
                "error",
            )
            success = False
        finally:
            _safe_emit(self.__class__.__name__, self.finished, success)
