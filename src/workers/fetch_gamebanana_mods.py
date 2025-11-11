import logging
from typing import List, Optional, Dict, Any
from PyQt6.QtCore import QThread, pyqtSignal
from config.constants import GAMEBANANA_GAME_IDS, GAMEBANANA_PER_PAGE, UI_COLORS
from managers.localization_manager import tr
from models.mod_models import ModInfo
from utils.gamebanana_api import GameBananaAPI
logger = logging.getLogger(__name__)


class FetchGameBananaModsThread(QThread):
    result = pyqtSignal(list)
    status = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.api = GameBananaAPI()
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        all_mods = []
        try:
            for game_name, game_id in GAMEBANANA_GAME_IDS.items():
                if self._cancelled:
                    break
                self.status.emit(tr('status.fetching_gamebanana_mods', game=game_name.upper()), UI_COLORS['status_info'])
                game_mods = self._fetch_game_mods(game_name, game_id)
                if game_mods:
                    all_mods.extend(game_mods)
                    logger.info(f'Fetched {len(game_mods)} mods for {game_name}')
            self.result.emit(all_mods)
            if all_mods:
                self.status.emit(tr('status.gamebanana_mods_fetched', count=len(all_mods)), UI_COLORS['status_success'])
            else:
                self.status.emit(tr('status.no_gamebanana_mods_found'), UI_COLORS['status_info'])
        except Exception as e:
            logger.error(f'Error fetching GameBanana mods: {e}', exc_info=True)
            self.status.emit(tr('errors.gamebanana_fetch_failed', error=str(e)), UI_COLORS['status_error'])
            self.result.emit([])

    def _fetch_game_mods(self, game_name: str, game_id: int) -> List[ModInfo]:
        mods = []
        page = 1
        max_mods_to_fetch = 100
        max_pages = 5
        logger.info(f'FetchGameBananaModsThread: Fetching mods for {game_name} (ID: {game_id})')
        try:
            while page <= max_pages and (not self._cancelled) and (len(mods) < max_mods_to_fetch):
                if self._cancelled:
                    break
                logger.debug(f'FetchGameBananaModsThread: Fetching page {page} for {game_name}')
                mods_data, mods_needing_metadata = self.api.get_game_mods(game_id, page=page, per_page=GAMEBANANA_PER_PAGE, sort='new')
                if not mods_data:
                    logger.debug(f'FetchGameBananaModsThread: No mods data for {game_name} page {page}')
                    break
                logger.debug(f'FetchGameBananaModsThread: Found {len(mods_data)} mods on page {page}')
                for mod_data in mods_data:
                    if self._cancelled or len(mods) >= max_mods_to_fetch:
                        break
                    try:
                        mod_info = self._convert_dict_to_modinfo(mod_data, game_name)
                        if mod_info:
                            mods.append(mod_info)
                    except Exception as e:
                        logger.warning(f'FetchGameBananaModsThread: Error converting mod data: {e}')
                        continue
                if len(mods_data) < GAMEBANANA_PER_PAGE or len(mods) >= max_mods_to_fetch:
                    break
                page += 1
            logger.info(f'FetchGameBananaModsThread: Fetched {len(mods)} mods for {game_name}')
        except Exception as e:
            logger.error(f'FetchGameBananaModsThread: Error fetching mods for {game_name}: {e}', exc_info=True)
        return mods

    def _convert_dict_to_modinfo(self, mod_data: Dict[str, Any], game_name: str) -> Optional[ModInfo]:
        try:
            mod_id = mod_data.get('gamebanana_mod_id')
            if not mod_id:
                return None
            downloads = mod_data.get('downloads', 0)
            if downloads is None:
                downloads = 0
            try:
                downloads = int(downloads) if downloads is not None else 0
            except (ValueError, TypeError):
                downloads = 0
            mod_info = ModInfo(key=mod_data.get('key', f'gb_{mod_id}'), name=mod_data.get('name', 'Unknown Mod'), version=mod_data.get('version', '1.0.0'), author=mod_data.get('author', tr('defaults.unknown')), game_version=mod_data.get('game_version', tr('defaults.not_specified')), tagline=mod_data.get('tagline', tr('status.no_description_status')), description_url=mod_data.get('description_url', ''), downloads=downloads, modgame=mod_data.get('modgame', game_name), is_verified=mod_data.get('is_verified', False), icon_url=mod_data.get('icon_url'), tags=mod_data.get('tags', []), hide_mod=False, is_local_mod=False, ban_status=False, files={}, created_date=mod_data.get('created_date'), last_updated=mod_data.get('last_updated'), external_url=mod_data.get('external_url'), screenshots_url=mod_data.get('screenshots_url', []), full_description=mod_data.get('full_description'), is_gamebanana_mod=True, gamebanana_mod_id=str(mod_id), gamebanana_mod_type=mod_data.get('gamebanana_mod_type', 'Mod'), gamebanana_last_update_timestamp=mod_data.get('gamebanana_last_update_timestamp'))
            return mod_info
        except Exception as e:
            logger.error(f'Error converting mod data dict to ModInfo: {e}', exc_info=True)
            return None
