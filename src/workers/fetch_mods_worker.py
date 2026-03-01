"""Worker thread for fetching mod lists from remote sources."""
import json
import os
from typing import Any, List, Optional, Tuple
import logging
from PyQt6.QtCore import QThread, pyqtSignal
from config.constants import UI_COLORS, GAMEBANANA_GAME_IDS, GAMEBANANA_PER_PAGE
from services.localization_service import tr
from models.mod_models import ModInfo
from utils.mod_utils import get_mod_key

logger = logging.getLogger(__name__)


class FetchModsThread(QThread):
    """Background thread for fetching mod lists from remote sources."""
    result = pyqtSignal(bool)
    status = pyqtSignal(str, str)

    def __init__(self, main_window_or_context, force_update=False, parent=None):
        super().__init__(parent)
        if hasattr(main_window_or_context, 'app_state'):
            self.main_window = main_window_or_context
        else:
            self.main_window = type('MainWindowProxy', (), {'app_state': main_window_or_context.app_state, 'settings_service': main_window_or_context.settings_service})()
        self.force_update = force_update

    def run(self):
        try:
            logger.info('FetchModsThread: Starting mod fetch')
            all_mods = []
            try:
                logger.info('FetchModsThread: Starting GameBanana fetch')
                metadata_cache = None
                sort_param = 'default'
                app_state = getattr(self.main_window, 'app_state', None)
                if app_state and hasattr(app_state, 'cache_dir'):
                    sort_param = getattr(app_state, 'gamebanana_sort', 'default')
                    try:
                        from adapters.gamebanana_cache import GameBananaMetadataCache
                        cache_dir = app_state.cache_dir
                        metadata_cache = GameBananaMetadataCache(cache_dir)
                        logger.info(f'FetchModsThread: Initialized metadata cache in {cache_dir}')
                    except Exception as e:
                        logger.warning(f'FetchModsThread: Failed to initialize metadata cache: {e}', exc_info=True)

                class GameBananaFetcher:

                    def __init__(self, sort_param='default', metadata_cache=None, app_state=None):
                        self.all_mods = []
                        self.all_mods_needing_metadata = []
                        self.api = None
                        self.sort_param = sort_param
                        self.metadata_cache = metadata_cache
                        self.app_state = app_state
                        self.status: Optional[Any] = None

                    def fetch_mods(self, initial_pages: int = 3):
                        from adapters.gamebanana_adapter import GameBananaAPI
                        self.api = GameBananaAPI()
                        selected_game = 'deltarune'
                        if self.app_state and hasattr(self.app_state, 'local_config'):
                            selected_game = self.app_state.local_config.get('selected_search_game', 'deltarune')
                        gamebanana_game = selected_game
                        if gamebanana_game not in GAMEBANANA_GAME_IDS:
                            logger.warning(f'GameBananaFetcher: Unknown game {gamebanana_game}, defaulting to deltarune')
                            gamebanana_game = 'deltarune'
                        game_id = GAMEBANANA_GAME_IDS[gamebanana_game]
                        logger.info(f'GameBananaFetcher.fetch_mods: Starting fetch for {selected_game} (GameBanana: {gamebanana_game}) with sort={self.sort_param}, initial_pages={initial_pages}')
                        if hasattr(self, 'status') and self.status:
                            self.status(tr('status.fetching_gamebanana_mods', game=gamebanana_game.upper()), UI_COLORS['status_info'])
                        game_mods, game_mods_needing_metadata = self._fetch_game_mods(gamebanana_game, game_id, start_page=1, num_pages=initial_pages, sort=self.sort_param)
                        if game_mods:
                            self.all_mods.extend(game_mods)
                            self.all_mods_needing_metadata.extend(game_mods_needing_metadata)
                            logger.info(f'GameBananaFetcher: Fetched {len(game_mods)} mods for {gamebanana_game} (pages 1-{initial_pages}), {len(game_mods_needing_metadata)} need metadata')
                        logger.info(f'GameBananaFetcher.fetch_mods: Total fetched {len(self.all_mods)} mods')
                        return (self.all_mods, self.all_mods_needing_metadata)

                    def _fetch_game_mods(self, game_name: str, game_id: int, start_page: int = 1, num_pages: int = 3, sort: str = 'default') -> Tuple[List[ModInfo], List[str]]:
                        mods = []
                        mods_needing_metadata = []
                        try:
                            if not self.api:
                                return (mods, mods_needing_metadata)

                            try:
                                import asyncio
                                from utils.async_metadata_loader import AsyncGameModsLoader
                                pages_to_load = list(range(start_page, start_page + num_pages))
                                async_loader = AsyncGameModsLoader(max_concurrent=3)
                                mods, mods_needing_metadata = asyncio.run(async_loader.load_game_mods_async(
                                    game_name, game_id, pages_to_load, GAMEBANANA_PER_PAGE, sort, self.metadata_cache, self.app_state
                                ))
                                logger.debug(f'AsyncGameModsLoader: Loaded {len(mods)} mods for {game_name}')
                            except Exception as async_error:
                                logger.warning(f'Async loading failed for {game_name}, falling back to sequential: {async_error}')

                                for page in range(start_page, start_page + num_pages):
                                    mods_data, page_mods_needing_metadata = self.api.get_game_mods(game_id, page=page, per_page=GAMEBANANA_PER_PAGE, sort=sort, metadata_cache=self.metadata_cache, app_state=self.app_state)
                                    if not mods_data:
                                        logger.debug(f'No mods data for {game_name} page {page}')
                                        break
                                    mods_needing_metadata.extend(page_mods_needing_metadata)
                                    for mod_info in mods_data:
                                        if mod_info:
                                            mods.append(mod_info)
                                    if len(mods_data) < GAMEBANANA_PER_PAGE:
                                        break
                                    logger.debug(f'Fetched page {page} for {game_name}: {len(mods_data)} mods, {len(page_mods_needing_metadata)} need metadata')
                        except Exception as e:
                            logger.error(f'Error fetching mods for {game_name}: {e}', exc_info=True)
                        return (mods, mods_needing_metadata)
                fetcher = GameBananaFetcher(sort_param=sort_param, metadata_cache=metadata_cache, app_state=app_state)

                fetcher.status = lambda msg, color: self.status.emit(msg, color)
                initial_pages = 3
                gamebanana_mods, mods_needing_metadata = fetcher.fetch_mods(initial_pages=initial_pages)
                if gamebanana_mods:
                    all_mods.extend(gamebanana_mods)
                    logger.info(f'FetchModsThread: Added {len(gamebanana_mods)} GameBanana mods to list, {len(mods_needing_metadata)} need metadata')
                    unique_mods_needing_metadata = list(set(mods_needing_metadata))
                    if unique_mods_needing_metadata and metadata_cache:
                        app_state = getattr(self.main_window, 'app_state', None)
                        if app_state:
                            if not hasattr(app_state, 'gamebanana_mods_needing_metadata'):
                                app_state.gamebanana_mods_needing_metadata = []
                            existing = set(app_state.gamebanana_mods_needing_metadata)
                            new_ids = set(unique_mods_needing_metadata)
                            app_state.gamebanana_mods_needing_metadata = list(existing | new_ids)
                            logger.info(f'FetchModsThread: Merged {len(new_ids)} new mod IDs needing metadata with {len(existing)} existing, total: {len(app_state.gamebanana_mods_needing_metadata)}')
                    app_state = getattr(self.main_window, 'app_state', None)
                    if app_state:
                        selected_game = app_state.local_config.get('selected_search_game', 'deltarune') if hasattr(app_state, 'local_config') else 'deltarune'
                        gamebanana_game = selected_game
                        if gamebanana_game in GAMEBANANA_GAME_IDS:
                            game_id = GAMEBANANA_GAME_IDS[gamebanana_game]
                            game_mods_count = len(gamebanana_mods)
                            pages_loaded = (game_mods_count - 1) // GAMEBANANA_PER_PAGE + 1 if game_mods_count > 0 else initial_pages
                            app_state.gamebanana_loaded_pages[game_id] = pages_loaded
            except Exception as e:
                logger.error(f'FetchModsThread: Failed to fetch GameBanana mods: {e}', exc_info=True)
            local_mods = self._get_local_mods()
            mod_service = getattr(self.main_window, 'mod_service', None)
            installed_mods_with_files = {}
            if mod_service:
                try:
                    for installed_mod in mod_service.get_installed_mods_list():
                        key = installed_mod.get('key') or installed_mod.get('mod_key')
                        if key and installed_mod.get('files'):
                            installed_mods_with_files[key] = installed_mod
                except Exception as e:
                    logger.warning(f'FetchModsThread: Error getting installed mods: {e}')
            existing_mods_with_files = {}
            app_state = getattr(self.main_window, 'app_state', None)
            if app_state and hasattr(app_state, 'all_mods'):
                for mod in app_state.all_mods:
                    key = get_mod_key(mod)
                    if key and hasattr(mod, 'files') and mod.files:
                        existing_mods_with_files[key] = mod
            all_mods_filtered = []
            for mod in all_mods:
                key = get_mod_key(mod)
                is_local_key = key and isinstance(key, str) and key.startswith('local_')
                if is_local_key:
                    continue
                is_gamebanana_mod = key and key.startswith('gb_')
                if is_gamebanana_mod and (key in existing_mods_with_files or key in installed_mods_with_files):
                    if key in existing_mods_with_files:
                        existing_mod = existing_mods_with_files[key]
                        if hasattr(existing_mod, 'files') and existing_mod.files:
                            mod.files = existing_mod.files
                    elif key in installed_mods_with_files:
                        installed_mod_config = installed_mods_with_files[key]
                        if installed_mod_config.get('files'):
                            mod_service = getattr(self.main_window, 'mod_service', None)
                            if mod_service:
                                try:
                                    temp_mod = mod_service.create_mod_object_from_info(installed_mod_config, [])
                                    if hasattr(temp_mod, 'files') and temp_mod.files:
                                        mod.files = temp_mod.files
                                except Exception as e:
                                    logger.debug(f'Failed to load files for installed mod {key}: {e}')
                    all_mods_filtered.append(mod)
                elif key and key in existing_mods_with_files:
                    existing_mod = existing_mods_with_files[key]
                    for attr in ['name', 'author', 'tagline', 'game_version', 'description_url', 'downloads', 'icon_url', 'is_verified']:
                        if hasattr(mod, attr):
                            setattr(existing_mod, attr, getattr(mod, attr))
                    all_mods_filtered.append(existing_mod)
                elif key and key in installed_mods_with_files:
                    installed_mod_config = installed_mods_with_files[key]
                    mod_service = getattr(self.main_window, 'mod_service', None)
                    if mod_service:
                        mod_with_files = mod_service.create_mod_object_from_info(installed_mod_config, all_mods_filtered)
                        for attr in ['name', 'author', 'tagline', 'game_version', 'description_url', 'downloads', 'icon_url', 'is_verified']:
                            if hasattr(mod, attr):
                                setattr(mod_with_files, attr, getattr(mod, attr))
                        all_mods_filtered.append(mod_with_files)
                    else:
                        all_mods_filtered.append(mod)
                else:
                    all_mods_filtered.append(mod)
            for local_mod in local_mods:
                key = get_mod_key(local_mod)
                if key and key not in {get_mod_key(m) for m in all_mods_filtered}:
                    all_mods_filtered.append(local_mod)
            app_state = getattr(self.main_window, 'app_state', None)
            if app_state:
                app_state.all_mods_updated.emit(all_mods_filtered)
            self._update_remote_exists_flags(all_mods)
            logger.info('FetchModsThread: Mod fetch completed successfully')
            self.result.emit(True)
        except Exception as e:
            logger.error(f'FetchModsThread: Error in run: {e}', exc_info=True)
            self.status.emit(str(e), UI_COLORS['status_error'])
            self.result.emit(False)

    def _get_local_mods(self) -> List[ModInfo]:
        local_mods = []
        app_state = getattr(self.main_window, 'app_state', None)
        if app_state and hasattr(app_state, 'all_mods'):
            for mod in app_state.all_mods:
                key = get_mod_key(mod)
                is_local_key = key and isinstance(key, str) and key.startswith('local_')
                if is_local_key:
                    local_mods.append(mod)
            logger.debug(f'_get_local_mods: Found {len(local_mods)} local mods in app_state')
        return local_mods

    def _update_remote_exists_flags(self, all_mods: List[ModInfo]):
        remote_mod_keys = {mod.key for mod in all_mods}
        app_state = getattr(self.main_window, 'app_state', None)
        mod_service = getattr(self.main_window, 'mod_service', None)
        settings_service = getattr(self.main_window, 'settings_service', None)
        if not app_state or not hasattr(app_state, 'mods_dir') or (not os.path.exists(app_state.mods_dir)):
            return
        if not mod_service:
            return
        try:
            mods_metadata = mod_service._read_metadata()
            metadata_updated = False
            for folder_name in os.listdir(app_state.mods_dir):
                folder_path = os.path.join(app_state.mods_dir, folder_name)
                if not os.path.isdir(folder_path):
                    continue
                config_path = os.path.join(folder_path, 'config.json')
                if not os.path.exists(config_path):
                    continue
                try:
                    if settings_service:
                        config_data = settings_service.read_json(config_path)
                    else:
                        with open(config_path, 'r', encoding='utf-8') as f:
                            config_data = json.load(f)
                    if not config_data:
                        continue
                    key = config_data.get('key') or config_data.get('mod_key')
                    is_local_key = key and isinstance(key, str) and key.startswith('local_')
                    if not key or is_local_key:
                        continue
                    is_available_now = key in remote_mod_keys
                    mod_meta = mods_metadata.get(key, {})
                    if mod_meta.get('is_available_on_server') != is_available_now:
                        mod_meta['is_available_on_server'] = is_available_now
                        mods_metadata[key] = mod_meta
                        metadata_updated = True
                except (IOError, json.JSONDecodeError):
                    continue
            if metadata_updated:
                mod_service._write_metadata(mods_metadata)
        except Exception as e:
            logging.warning(f'Failed to update remote exists flags in metadata: {e}')
