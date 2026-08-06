"""Background support archive builder."""

from __future__ import annotations

import threading

from PyQt6.QtCore import pyqtSignal

from ui.utils.thread_lifetime import ManagedQThread


class SupportPackageWorker(ManagedQThread):
    completed = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(
        self,
        service,
        destination,
        selected,
        log_names,
        log_days,
        runtime_metrics=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._destination = destination
        self._selected = selected
        self._log_names = log_names
        self._log_days = log_days
        self._runtime_metrics = runtime_metrics
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def run(self) -> None:
        try:
            result = self._service.build(
                self._destination,
                self._selected,
                log_names=self._log_names,
                log_days=self._log_days,
                runtime_metrics=self._runtime_metrics,
                cancelled=self._cancelled.is_set,
            )
        except InterruptedError:
            return
        except Exception as error:
            self.failed.emit(str(error))
        else:
            self.completed.emit(result)
