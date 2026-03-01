"""Load more GameBanana mods worker."""
import logging
from PyQt6.QtCore import QThread, pyqtSignal
from config.constants import GAMEBANANA_GAME_IDS, GAMEBANANA_PER_PAGE, UI_COLORS
from services.localization_service import tr
from adapters.gamebanana_adapter import GameBananaAPI
logger = logging.getLogger(__name__)


class LoadMoreGameBananaModsThread(QThread):
    result, status = pyqtSignal(list), pyqtSignal(str, str)

    def __init__(self, game_id: int, start_page: int, num_pages: int = 2, sort: str = 'default', parent=None, metadata_cache=None):
        super().__init__(parent)
        self.game_id, self.start_page, self.num_pages, self.sort = game_id, start_page, num_pages, sort
        self.api, self.metadata_cache = GameBananaAPI(), metadata_cache
        self._cancelled, self._mods_needing_metadata = False, []

    def cancel(self): self._cancelled = True

    def _get_app_state(self, use_grandparent=False):
        try:
            parent = self.parent()
            if parent and hasattr(parent, 'app_state'):
                return parent.app_state
            if use_grandparent and parent and (gp := getattr(parent, 'parent', lambda: None)()) and hasattr(gp, 'app_state'):
                return gp.app_state
        except Exception:
            pass
        return None

    def run(self):
        new_mods = []
        try:
            game_name = next((name for name, id_val in GAMEBANANA_GAME_IDS.items() if id_val == self.game_id), None)
            if not game_name:
                logger.error(f'Unknown game_id: {self.game_id}')
                self.result.emit([])
                return

            try:
                import asyncio
                from utils.async_metadata_loader import AsyncGameModsLoader
                pages_to_load = list(range(self.start_page, self.start_page + self.num_pages))
                async_loader = AsyncGameModsLoader(max_concurrent=2)
                mods_data, mods_needing = asyncio.run(async_loader.load_game_mods_async(
                    game_name, self.game_id, pages_to_load, GAMEBANANA_PER_PAGE, self.sort, self.metadata_cache, self._get_app_state()
                ))
                if mods_data:
                    self._mods_needing_metadata.extend(mods_needing)
                    new_mods.extend(m for m in mods_data if m and not (self._cancelled or self.isInterruptionRequested()))
                logger.debug(f'LoadMoreGameBananaModsThread: Async loaded {len(mods_data)} mods for {game_name}')
            except Exception as async_error:
                logger.warning(f'Async loading failed for load_more, falling back to sequential: {async_error}')

                for page in range(self.start_page, self.start_page + self.num_pages):
                    if self._cancelled or self.isInterruptionRequested():
                        break
                    mods_data, mods_needing = self.api.get_game_mods(self.game_id, page=page, per_page=GAMEBANANA_PER_PAGE, sort=self.sort, metadata_cache=self.metadata_cache, app_state=self._get_app_state())
                    if not mods_data:
                        break
                    self._mods_needing_metadata.extend(mods_needing)
                    new_mods.extend(m for m in mods_data if m and not (self._cancelled or self.isInterruptionRequested()))
                    if len(mods_data) < GAMEBANANA_PER_PAGE and page >= self.start_page + self.num_pages - 1:
                        break

            if self._mods_needing_metadata:
                try:
                    if (app_state := self._get_app_state(True)) and hasattr(app_state, 'gamebanana_mods_needing_metadata'):
                        app_state.gamebanana_mods_needing_metadata = list(set(getattr(app_state, 'gamebanana_mods_needing_metadata', [])) | set(self._mods_needing_metadata))
                        logger.debug(f'LoadMoreGameBananaModsThread: Added {len(self._mods_needing_metadata)} mod IDs to metadata queue')
                except (AttributeError, RuntimeError, TypeError) as e:
                    logger.debug(f'LoadMoreGameBananaModsThread: Could not access app_state: {e}')
            self.result.emit(new_mods)
        except Exception as e:
            logger.error(f'Error loading more GameBanana mods: {e}', exc_info=True)
            self.status.emit(tr('errors.gamebanana_fetch_failed', error=str(e)), UI_COLORS['status_error'])
            self.result.emit([])
