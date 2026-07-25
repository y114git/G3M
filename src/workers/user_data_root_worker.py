"""Background preparation of a selected G3M data directory."""

from PyQt6.QtCore import pyqtSignal

from services.user_data_root_service import (
    DataRootChangeResult,
    prepare_data_root_change,
)
from ui.utils.thread_lifetime import ManagedQThread


class UserDataRootWorker(ManagedQThread):
    completed = pyqtSignal(object)

    def __init__(
        self,
        source: str,
        destination: str,
        *,
        copy_data: bool,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._source = source
        self._destination = destination
        self._copy_data = copy_data
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            result = prepare_data_root_change(
                self._source,
                self._destination,
                copy_data=self._copy_data,
                cancelled=lambda: self._cancelled or self.isInterruptionRequested(),
            )
        except Exception as error:
            result = DataRootChangeResult(
                "io_error", self._destination, str(error)
            )
        self.completed.emit(result)
