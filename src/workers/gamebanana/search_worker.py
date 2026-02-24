"""GameBanana mod search worker.

This module provides a worker thread for searching GameBanana mods.
"""
import logging
import time
from PyQt6.QtCore import QThread, pyqtSignal
from config.constants import GAMEBANANA_GAME_IDS, GAMEBANANA_PER_PAGE, UI_COLORS
from services.localization_service import tr
from adapters.gamebanana_adapter import GameBananaAPI
from typing import List
from models.mod_models import ModInfo
from config.constants import SEARCH_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)


class SearchGameBananaModsThread(QThread):
    result = pyqtSignal(list)
    status = pyqtSignal(str, str)
    priority_metadata_added = pyqtSignal(int)

    def __init__(self, game_id: int, search_string: str, start_page: int = 1, num_pages: int = 1, sort: str = 'best_match', parent=None, metadata_cache=None):
        super().__init__(parent)
        self.game_id = game_id
        self.search_string = search_string
        self.start_page = start_page
        self.num_pages = num_pages
        self.sort = sort
        self.api = GameBananaAPI()
        self.metadata_cache = metadata_cache
        self._cancelled = False
        self._mods_needing_metadata = []
        self._start_time = None

    def cancel(self):
        self._cancelled = True

    def run(self):
        self._start_time = time.time()
        new_mods: List[ModInfo] = []
        try:
            game_name = next((name for name, id_val in GAMEBANANA_GAME_IDS.items() if id_val == self.game_id), None)
            if not game_name:
                self.result.emit([])
                return
            if not self.search_string or len(self.search_string.strip()) < 2:
                self.result.emit([])
                return
            for page in range(self.start_page, self.start_page + self.num_pages):
                if self._cancelled or self.isInterruptionRequested():
                    break
                if time.time() - self._start_time > SEARCH_TIMEOUT_SECONDS:
                    logger.warning(f'SearchGameBananaModsThread: Search timeout after {SEARCH_TIMEOUT_SECONDS} seconds')
                    break
                search_result = self.api.search_mods(self.game_id, search_string=self.search_string, page=page, per_page=GAMEBANANA_PER_PAGE, sort=self.sort)
                if not search_result:
                    break
                records = search_result.get('_aRecords', [])
                if not records:
                    break
                for record in records:
                    if self._cancelled or self.isInterruptionRequested():
                        break
                    if time.time() - self._start_time > SEARCH_TIMEOUT_SECONDS:
                        break
                    model_name = record.get('_sModelName')
                    if model_name not in ('Mod', 'Wip', 'WIP'):
                        continue
                    is_wip = model_name in ('Wip', 'WIP')
                    mod_id = record.get('_idRow')
                    if not mod_id:
                        continue
                    hide_wips = False
                    try:
                        if (p := self.parent()) and (a := getattr(p, 'app_state', None)):
                            hide_wips = getattr(a, 'local_config', {}).get('hide_wips_without_downloads', False)
                    except Exception:
                        pass
                    if hide_wips and is_wip:
                        try:
                            if not int(record.get('_nDownloadCount') or 0):
                                continue
                        except (ValueError, TypeError):
                            continue
                    mod_info = self.api._map_mod_data(record, game_name, is_wip=is_wip)
                    if not mod_info:
                        continue
                    if mod_id:
                        mod_id_str = str(mod_id)
                        downloads_from_gb = record.get('_nDownloadCount')
                        downloads_value = 0
                        if downloads_from_gb is not None:
                            try:
                                downloads_value = int(downloads_from_gb)
                            except (ValueError, TypeError):
                                downloads_value = 0
                        mod_info.downloads = downloads_value
                        if self.metadata_cache:
                            cache_valid = self.metadata_cache.is_valid(mod_id_str)
                            if cache_valid:
                                cached_downloads = self.metadata_cache.get_field(mod_id_str, 'downloads')
                                cached_tagline = self.metadata_cache.get_field(mod_id_str, 'tagline')
                                cached_category = self.metadata_cache.get_field(mod_id_str, 'category')
                                if cached_downloads is not None and cached_downloads > 0:
                                    mod_info.downloads = cached_downloads
                                elif downloads_value > 0:
                                    mod_info.downloads = downloads_value
                                if cached_tagline:
                                    mod_info.tagline = cached_tagline
                                if cached_category:
                                    mod_info.gamebanana_category = cached_category
                        downloads_from_record = record.get('_nDownloadCount')
                        description_from_record = record.get('_sDescription', '')
                        has_description_in_record = description_from_record and description_from_record.strip() and (len(description_from_record.strip()) >= 10)
                        category_from_record = record.get('_aCategory') or record.get('Category')
                        has_category_in_record = bool(category_from_record)
                        needs_downloads = downloads_from_record is None and (not cache_valid if self.metadata_cache else True)
                        needs_tagline = not has_description_in_record and (not cache_valid if self.metadata_cache else True)
                        needs_category = not has_category_in_record and (not cache_valid if self.metadata_cache else True)
                        if (needs_downloads or needs_tagline or needs_category) and (not cache_valid if self.metadata_cache else True):
                            self._mods_needing_metadata.append(mod_id_str)
                            try:
                                mod_info.has_full_metadata = False
                            except Exception:
                                pass
                        else:
                            try:
                                mod_info.has_full_metadata = True
                            except Exception:
                                pass
                        new_mods.append(mod_info)
                if len(records) < GAMEBANANA_PER_PAGE:
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
                            except (AttributeError, RuntimeError):
                                pass
                    if app_state and hasattr(app_state, 'gamebanana_mods_needing_metadata'):
                        existing = getattr(app_state, 'gamebanana_mods_needing_metadata', [])
                        new_ids = list(self._mods_needing_metadata)
                        existing_set = set(existing)
                        new_unique = [mod_id for mod_id in new_ids if mod_id not in existing_set]
                        app_state.gamebanana_mods_needing_metadata = new_unique + existing
                        if new_unique:
                            logger.info(f'SearchGameBananaModsThread: Prioritized {len(new_unique)} search result mods at front of metadata queue')
                            self.priority_metadata_added.emit(len(new_unique))
                except (AttributeError, RuntimeError, TypeError):
                    pass
            self.result.emit(new_mods)
        except Exception as e:
            logger.error(f'Error searching GameBanana mods: {e}', exc_info=True)
            self.status.emit(tr('errors.gamebanana_fetch_failed', error=str(e)), UI_COLORS['status_error'])
            self.result.emit([])
