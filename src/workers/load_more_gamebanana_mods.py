import logging
from PyQt6.QtCore import QThread, pyqtSignal
from config.constants import GAMEBANANA_GAME_IDS, GAMEBANANA_PER_PAGE, UI_COLORS
from managers.localization_manager import tr
from utils.gamebanana_api import GameBananaAPI
logger = logging.getLogger(__name__)


class LoadMoreGameBananaModsThread(QThread):
    result = pyqtSignal(list)
    status = pyqtSignal(str, str)

    def __init__(self, game_id: int, start_page: int, num_pages: int = 2, sort: str = 'default', parent=None, metadata_cache=None):
        super().__init__(parent)
        self.game_id = game_id
        self.start_page = start_page
        self.num_pages = num_pages
        self.sort = sort
        self.api = GameBananaAPI()
        self.metadata_cache = metadata_cache
        self._cancelled = False
        self._mods_needing_metadata = []

    def cancel(self):
        self._cancelled = True

    def run(self):
        new_mods = []
        try:
            game_name = None
            for name, id_val in GAMEBANANA_GAME_IDS.items():
                if id_val == self.game_id:
                    game_name = name
                    break
            if not game_name:
                logger.error(f'Unknown game_id: {self.game_id}')
                self.result.emit([])
                return
            for page in range(self.start_page, self.start_page + self.num_pages):
                if self._cancelled or self.isInterruptionRequested():
                    break
                app_state = None
                try:
                    parent = self.parent()
                    if parent and hasattr(parent, 'app_state'):
                        app_state = parent.app_state
                except Exception:
                    pass
                mods_data, mods_needing_metadata = self.api.get_game_mods(self.game_id, page=page, per_page=GAMEBANANA_PER_PAGE, sort=self.sort, metadata_cache=self.metadata_cache, app_state=app_state)
                if not mods_data or len(mods_data) == 0:
                    break
                self._mods_needing_metadata.extend(mods_needing_metadata)
                for mod_info in mods_data:
                    if self._cancelled or self.isInterruptionRequested():
                        break
                    if mod_info:
                        new_mods.append(mod_info)
                if len(mods_data) < GAMEBANANA_PER_PAGE:
                    if page < self.start_page + self.num_pages - 1:
                        continue
                    else:
                        break
            if self._mods_needing_metadata:
                try:
                    parent = self.parent()
                    app_state = None
                    if parent:
                        if hasattr(parent, 'app_state'):
                            app_state = getattr(parent, 'app_state', None)
                        else:
                            try:
                                grandparent = parent.parent() if hasattr(parent, 'parent') else None
                                if grandparent and hasattr(grandparent, 'app_state'):
                                    app_state = getattr(grandparent, 'app_state', None)
                            except (AttributeError, RuntimeError) as e:
                                logger.debug(f'LoadMoreGameBananaModsThread: Error accessing parent hierarchy: {e}')
                    if app_state and hasattr(app_state, 'gamebanana_mods_needing_metadata'):
                        existing = set(getattr(app_state, 'gamebanana_mods_needing_metadata', []))
                        new_ids = set(self._mods_needing_metadata)
                        app_state.gamebanana_mods_needing_metadata = list(existing | new_ids)
                        logger.debug(f'LoadMoreGameBananaModsThread: Added {len(new_ids)} mod IDs to metadata loading queue')
                except (AttributeError, RuntimeError, TypeError) as e:
                    logger.debug(f'LoadMoreGameBananaModsThread: Could not access app_state: {e} (this is OK if parent is not AppWindow)')
            self.result.emit(new_mods)
        except Exception as e:
            logger.error(f'Error loading more GameBanana mods: {e}', exc_info=True)
            self.status.emit(tr('errors.gamebanana_fetch_failed', error=str(e)), UI_COLORS['status_error'])
            self.result.emit([])
