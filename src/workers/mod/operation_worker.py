"""Background execution for one validated operation mod operation plan."""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import pyqtSignal

from services.localization_service import tr
from services.mod_operation_executor import (
    ModOperationCancelledError,
    ModOperationExecutionError,
    ModOperationExecutor,
    ModOperationJournal,
    ModPatchMismatchError,
)
from services.mod_operation_support import create_g3mtool_merger, create_g3mtool_patcher
from ui.utils.thread_lifetime import ManagedQThread
from ui.utils.thread_lifetime import safe_emit as _safe_emit
from utils.mod.archive import ArchiveVirtualPath
from utils.mod.operation_plan import ModOperationPlan, PlannedModOperation

logger = logging.getLogger(__name__)


def _display_path(value: Path | ArchiveVirtualPath | None) -> str:
    if value is None:
        return ""
    if isinstance(value, ArchiveVirtualPath):
        member = value.member.rstrip("/")
        return member.rsplit("/", 1)[-1] if member else value.archive.name
    return value.name or str(value)


def _log_path(value: Path | ArchiveVirtualPath | None) -> str:
    if value is None:
        return ""
    if isinstance(value, ArchiveVirtualPath):
        return f"{value.archive}!/{value.member}"
    return str(value)


def _operation_status_key(operation_type: str) -> str:
    return {
        "patch": "operation_patching",
        "overwrite": "operation_overwriting",
        "soft-overwrite": "operation_soft_overwriting",
        "hard-overwrite": "operation_hard_overwriting",
        "extract": "operation_extracting",
        "soft-extract": "operation_soft_extracting",
        "hard-extract": "operation_hard_extracting",
    }.get(operation_type, "operation_processing")


def describe_step(
    operations: tuple[PlannedModOperation, ...],
    operation: PlannedModOperation,
    current: int,
    total: int,
    percent: int = 0,
) -> str:
    """The status line for one step, written the same while it runs and once it is done."""
    target = operation.target or operation.source
    merged = ModOperationExecutor.merge_operations(operations, operation)
    if merged:
        message = tr(
            "status.operation_merging",
            count=len(merged),
            patch_types=", ".join(dict.fromkeys(_patch_format(item.source) for item in merged)),
            target=_display_path(target),
            current=current,
            total=total,
        )
    else:
        message = tr(
            f"status.{_operation_status_key(operation.type)}",
            patch_type=_patch_format(operation.source) if operation.type == "patch" else "",
            from_file=_display_path(operation.source),
            target=_display_path(target),
            current=current,
            total=total,
        )
    return tr("status.operation_percent", message=message, percent=percent) if percent else message


def _patch_format(value: Path | ArchiveVirtualPath) -> str:
    suffix = Path(_display_path(value)).suffix.casefold()
    return {
        ".xdelta": "XDELTA",
        ".vcdiff": "VCDIFF",
        ".g3mpatch": "G3MPatch",
        ".csx": "CSX",
    }.get(suffix, tr("status.patch_format_generic"))


class ModOperationThread(ManagedQThread):
    """Apply ordered mod operations off the UI thread and retain their journal."""

    progress_update = pyqtSignal(int, str)
    status_update = pyqtSignal(str, str)
    result_ready = pyqtSignal(bool)

    def __init__(
        self,
        app_state,
        plan: ModOperationPlan,
        journal_root: str | Path,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.app_state = app_state
        self.plan = plan
        self.journal_root = Path(journal_root)
        self.journal: ModOperationJournal | None = None
        self._cancelled = False
        self._patcher = create_g3mtool_patcher(app_state, is_cancelled=self._is_cancelled)
        self._merger = create_g3mtool_merger(app_state, is_cancelled=self._is_cancelled)

    def cancel(self) -> None:
        self._cancelled = True
        self.requestInterruption()

    def _is_cancelled(self) -> bool:
        return self._cancelled or self.isInterruptionRequested()

    def _on_step_progress(
        self,
        overall: float,
        completed: int,
        total: int,
        operation: PlannedModOperation,
        percent: int,
    ) -> None:
        """Smooth progress inside one step, from the percent the patch backend reports."""
        weight = len(ModOperationExecutor.merge_operations(self.plan.operations, operation)) or 1
        message = describe_step(
            self.plan.operations, operation, completed + weight, total, percent
        )
        if percent in (0, 25, 50, 75, 100):
            logger.info(
                "Mod operation step %s/%s: %s%% (index=%s type=%s)",
                completed + weight,
                total,
                percent,
                operation.index,
                operation.type,
            )
        _safe_emit(
            self.__class__.__name__,
            self.progress_update,
            int(overall * 100),
            message,
        )

    def _on_progress(
        self, completed: int, total: int, operation: PlannedModOperation
    ) -> None:
        merged = ModOperationExecutor.merge_operations(self.plan.operations, operation)
        if merged:
            logger.info(
                "Merged mod patches: indexes=%s count=%s patch_types=%s progress=%s/%s target=%s",
                [item.index for item in merged],
                len(merged),
                ", ".join(dict.fromkeys(_patch_format(item.source) for item in merged)),
                completed,
                total,
                _log_path(operation.target),
            )
        else:
            logger.info(
                "Mod operation completed: index=%s type=%s patch_type=%s progress=%s/%s source=%s target=%s",
                operation.index,
                operation.type,
                _patch_format(operation.source) if operation.type == "patch" else "",
                completed,
                total,
                _log_path(operation.source),
                _log_path(operation.target),
            )
        _safe_emit(
            self.__class__.__name__,
            self.progress_update,
            int(completed * 100 / max(total, 1)),
            describe_step(self.plan.operations, operation, completed, total),
        )

    def run(self) -> None:
        success = False
        try:
            if self._is_cancelled():
                return
            executor = ModOperationExecutor(
                self.journal_root, patcher=self._patcher, merger=self._merger
            )
            self.journal = executor.execute(
                self.plan,
                progress=self._on_progress,
                is_cancelled=self._is_cancelled,
                step_progress=self._on_step_progress,
            )
            success = not self._is_cancelled()
        except ModOperationCancelledError as error:
            logger.info("Mod operation plan cancelled; applied files were restored (%s)", error)
        except ModPatchMismatchError as error:
            # An expected, user-fixable failure: the executor already restored the files, so no traceback.
            logger.error("Mod operation plan failed: %s", error)
            _safe_emit(
                self.__class__.__name__,
                self.status_update,
                tr("errors.mod_patch_mismatch", mod=error.mod_id or "?", patch=error.patch),
                "error",
            )
        except ModOperationExecutionError as error:
            logger.error("Mod operation plan failed: %s", error)
            _safe_emit(
                self.__class__.__name__,
                self.status_update,
                tr("errors.mod_patching_failed"),
                "error",
            )
        except Exception as error:
            logger.error("Mod operation plan failed: %s", error, exc_info=True)
            _safe_emit(
                self.__class__.__name__,
                self.status_update,
                tr("errors.mod_patching_failed"),
                "error",
            )
        finally:
            _safe_emit(self.__class__.__name__, self.result_ready, success)
