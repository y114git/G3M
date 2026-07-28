"""Worker thread for PizzaOven normal-mod conversion."""

from __future__ import annotations

import logging
from typing import Any, Protocol

from PyQt6.QtCore import QThread, pyqtSignal

from services.pizza_oven_conversion_service import (
    PizzaOvenConversionError,
    PizzaOvenConversionResult,
)

logger = logging.getLogger(__name__)


class PizzaOvenConverter(Protocol):
    def convert(
        self,
        source_dir: str,
        mods_dir: str,
        game_path: str,
        *,
        source_file_path: str | None = None,
        gamebanana_metadata: dict[str, Any] | None = None,
        progress_callback=None,
    ) -> PizzaOvenConversionResult: ...


class PizzaOvenConversionWorker(QThread):
    progress = pyqtSignal(int)
    status = pyqtSignal(str, str)
    conversion_finished = pyqtSignal(bool, str, object)

    def __init__(
        self,
        conversion_service: PizzaOvenConverter,
        source_dir: str,
        mods_dir: str,
        game_path: str,
        *,
        source_file_path: str | None = None,
        gamebanana_metadata: dict | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._conversion_service = conversion_service
        self._source_dir = source_dir
        self._mods_dir = mods_dir
        self._game_path = game_path
        self._source_file_path = source_file_path
        self._gamebanana_metadata = gamebanana_metadata or {}

    def _safe_emit(self, signal, *args) -> None:
        try:
            signal.emit(*args)
        except Exception as e:
            logger.warning(
                "PizzaOvenConversionWorker: failed to emit %s: %s",
                getattr(signal, "signal", signal.__class__.__name__),
                e,
                exc_info=True,
            )

    def run(self) -> None:
        try:
            result = self._conversion_service.convert(
                self._source_dir,
                self._mods_dir,
                self._game_path,
                source_file_path=self._source_file_path,
                gamebanana_metadata=self._gamebanana_metadata,
                progress_callback=self._on_progress,
            )
            self._safe_emit(self.conversion_finished, True, result.mod_dir, result)
        except PizzaOvenConversionError as e:
            self._safe_emit(self.conversion_finished, False, str(e), None)
        except Exception as e:
            logger.error("PizzaOven conversion failed: %s", e, exc_info=True)
            self._safe_emit(self.conversion_finished, False, str(e), None)

    def _on_progress(self, value: int, message: str) -> None:
        self._safe_emit(self.progress, value)
        self._safe_emit(self.status, message, "status_info")
