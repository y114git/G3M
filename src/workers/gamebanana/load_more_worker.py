"""Load more GameBanana mods worker."""

import logging

from PyQt6.QtCore import pyqtSignal

from adapters.gamebanana_adapter import GameBananaAPI
from config.config import GAMEBANANA_PER_PAGE, UI_COLORS
from models.game_modes import get_gamebanana_reverse_map
from services.localization_service import tr
from ui.utils.thread_lifetime import ManagedQThread

logger = logging.getLogger(__name__)


def _safe_emit(owner: str, signal, *args) -> None:
    try:
        signal.emit(*args)
    except Exception as e:
        logger.warning("%s: failed to emit signal: %s", owner, e, exc_info=True)


class LoadMoreGameBananaModsThread(ManagedQThread):
    result, status = pyqtSignal(list), pyqtSignal(str, str)

    def __init__(
        self,
        game_id: int,
        start_page: int,
        num_pages: int = 2,
        sort: str = "relevant",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.game_id, self.start_page, self.num_pages, self.sort = (
            game_id,
            start_page,
            num_pages,
            sort,
        )
        self.api = GameBananaAPI()
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        new_mods = []
        try:
            game_name = get_gamebanana_reverse_map().get(self.game_id)
            if not game_name:
                logger.error(f"Unknown game_id: {self.game_id}")
                _safe_emit(self.__class__.__name__, self.result, [])
                return

            for page in range(self.start_page, self.start_page + self.num_pages):
                if self._cancelled or self.isInterruptionRequested():
                    break
                mods_data, _ = self.api.get_game_mods(
                    self.game_id,
                    page=page,
                    per_page=GAMEBANANA_PER_PAGE,
                    sort=self.sort,
                )
                if not mods_data:
                    break
                new_mods.extend(
                    m
                    for m in mods_data
                    if m and not (self._cancelled or self.isInterruptionRequested())
                )
                if len(mods_data) < GAMEBANANA_PER_PAGE:
                    break
            _safe_emit(self.__class__.__name__, self.result, new_mods)
        except Exception as e:
            logger.error(f"Error loading more GameBanana mods: {e}", exc_info=True)
            _safe_emit(
                self.__class__.__name__,
                self.status,
                tr("errors.gamebanana_fetch_failed", error=str(e)),
                UI_COLORS["status_error"],
            )
            _safe_emit(self.__class__.__name__, self.result, [])
