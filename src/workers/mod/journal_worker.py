"""Background journal maintenance outside the Qt GUI thread."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import pyqtSignal

from services.mod_operation_executor import (
    ModOperationJournal,
    remove_path,
    remove_tree,
)
from ui.utils.thread_lifetime import ManagedQThread
from ui.utils.thread_lifetime import safe_emit as _safe_emit


class ModOperationJournalThread(ManagedQThread):
    """Checkpoint or restore one durable operation journal off the UI thread."""

    result_ready = pyqtSignal(object)

    def __init__(
        self,
        action: str,
        *,
        journal: ModOperationJournal | None = None,
        journal_root: str | Path | None = None,
        force: bool = False,
        cleanup_info: dict | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.action = action
        self.journal = journal
        self.journal_root = Path(journal_root) if journal_root is not None else None
        self.force = force
        self.cleanup_info = cleanup_info or {}
        self.result = (False, ["journal worker did not finish"])
        self.error: Exception | None = None

    def run(self) -> None:
        journal_restored = False
        errors: list[str] = []
        try:
            journal = self.journal
            if journal is None and self.journal_root is not None:
                journal = ModOperationJournal.load(self.journal_root)
            if journal is not None:
                if self.action == "checkpoint":
                    journal.checkpoint()
                    journal_restored = True
                elif self.action == "restore":
                    if self.force:
                        journal.restore(force=True)
                    else:
                        journal.restore()
                    journal_restored = True
                elif self.action == "retire":
                    journal.retire()
                    journal_restored = True
                elif self.action == "discard":
                    journal.discard()
                    journal_restored = True
                elif self.action == "verify":
                    journal.verify_deployed()
                    journal_restored = True
                elif self.action == "recover":
                    if journal.state not in {"restored", "retired"}:
                        journal.restore()
                    journal_restored = True
                else:
                    raise ValueError(f"unsupported journal action: {self.action}")
            elif self.action != "restore":
                raise ValueError("journal is required for this action")
            else:
                journal_restored = True
        except Exception as error:
            self.error = error
            errors.append(str(error))
        if journal_restored and self.action in {"restore", "retire"}:
            for folder in self.cleanup_info.get("mus_folders", []):
                try:
                    remove_tree(Path(folder))
                except OSError as error:
                    errors.append(f"music folder {folder}: {error}")
            target_exe = self.cleanup_info.get("target_exe")
            try:
                if target_exe:
                    remove_path(Path(target_exe))
            except OSError as error:
                errors.append(f"direct launch exe: {error}")
        self.result = (journal_restored, errors)
        _safe_emit(
            self.__class__.__name__,
            self.result_ready,
            self.result,
        )
