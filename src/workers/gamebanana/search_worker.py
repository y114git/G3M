"""GameBanana mod search worker.

This module provides a worker thread for searching GameBanana mods.
"""

import logging
import time

from PyQt6.QtCore import pyqtSignal

from adapters.gamebanana_adapter import GameBananaAPI
from config.config import (
    GAMEBANANA_PER_PAGE,
    SEARCH_TIMEOUT_SECONDS,
    UI_COLORS,
)
from models.game_modes import get_gamebanana_reverse_map
from models.mod_models import BrowserModInfo
from services.localization_service import tr
from ui.utils.thread_lifetime import ManagedQThread

logger = logging.getLogger(__name__)


def _safe_emit(owner: str, signal, *args) -> None:
    try:
        signal.emit(*args)
    except Exception as e:
        logger.warning("%s: failed to emit signal: %s", owner, e, exc_info=True)


class SearchGameBananaModsThread(ManagedQThread):
    result = pyqtSignal(list)
    status = pyqtSignal(str, str)

    def __init__(
        self,
        game_id: int,
        search_string: str,
        start_page: int = 1,
        num_pages: int = 1,
        sort: str = "relevant",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.game_id = game_id
        self.search_string = search_string
        self.start_page = start_page
        self.num_pages = num_pages
        self.sort = sort
        self.api = GameBananaAPI()
        self._cancelled = False
        self._start_time = None

    def cancel(self):
        self._cancelled = True

    def run(self):
        self._start_time = time.time()
        new_mods: list[BrowserModInfo] = []
        try:
            game_name = get_gamebanana_reverse_map().get(self.game_id)
            if not game_name:
                _safe_emit(self.__class__.__name__, self.result, [])
                return
            if not self.search_string or len(self.search_string.strip()) < 2:
                _safe_emit(self.__class__.__name__, self.result, [])
                return
            for page in range(self.start_page, self.start_page + self.num_pages):
                if self._cancelled or self.isInterruptionRequested():
                    break
                if time.time() - self._start_time > SEARCH_TIMEOUT_SECONDS:
                    logger.warning(
                        f"SearchGameBananaModsThread: Search timeout after {SEARCH_TIMEOUT_SECONDS} seconds"
                    )
                    break
                search_result = self.api.search_mods(
                    self.game_id,
                    search_string=self.search_string,
                    page=page,
                    per_page=GAMEBANANA_PER_PAGE,
                    sort=self.sort,
                )
                if not search_result:
                    break
                records = search_result.get("_aRecords", [])
                if not records:
                    break
                for record in records:
                    if self._cancelled or self.isInterruptionRequested():
                        break
                    if time.time() - self._start_time > SEARCH_TIMEOUT_SECONDS:
                        break
                    model_name = record.get("_sModelName")
                    if model_name not in ("Mod", "Wip", "WIP"):
                        continue
                    is_wip = model_name in ("Wip", "WIP")
                    mod_info = self.api._map_mod_data(record, game_name, is_wip=is_wip)
                    if not mod_info:
                        continue
                    new_mods.append(mod_info)
                if len(records) < GAMEBANANA_PER_PAGE:
                    break
            _safe_emit(self.__class__.__name__, self.result, new_mods)
        except Exception as e:
            logger.error(f"Error searching GameBanana mods: {e}", exc_info=True)
            _safe_emit(
                self.__class__.__name__,
                self.status,
                tr("errors.gamebanana_fetch_failed", error=str(e)),
                UI_COLORS["status_error"],
            )
            _safe_emit(self.__class__.__name__, self.result, [])
