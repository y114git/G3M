"""Worker thread for fetching mod lists from remote sources.

This module handles fetching mods from the cloud database and GameBanana API,
including metadata caching and pagination.
"""
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple
from utils.network_utils import get_session
import logging
from PyQt6.QtCore import QThread, pyqtSignal
from config.constants import CLOUD_FUNCTIONS_BASE_URL, UI_COLORS, GAMEBANANA_GAME_IDS, GAMEBANANA_PER_PAGE
from services.localization_service import tr
from models.mod_models import ModChapterData, ModExtraFile, ModInfo
from utils.file_utils import version_sort_key
logger = logging.getLogger(__name__)
_GAME_MAPPING = {'deltarune': 'deltarune', 'deltarunedemo': 'deltarune', 'undertale': 'undertale', 'undertaleyellow': 'undertaleyellow', 'pizzatower': 'pizzatower', 'sugaryspire': 'sugaryspire'}


class FetchModsThread(QThread):
    """Background thread for fetching mod lists from remote sources."""
    result = pyqtSignal(bool)
    status = pyqtSignal(str, str)

    def __init__(self, main_window_or_context, force_update=False, parent=None):
        """Initialize the fetch mods thread.

        Args:
            main_window_or_context: Main window or context object.
            force_update: Whether to force update cache.
            parent: Parent QObject (optional).
        """
        super().__init__(parent)
        if hasattr(main_window_or_context, 'app_state'):
            self.main_window = main_window_or_context
        else:
            self.main_window = type('MainWindowProxy', (), {'app_state': main_window_or_context.app_state, 'settings_service': main_window_or_context.settings_service})()
        self.force_update = force_update

    def run(self):
        """Run the fetch operation in background thread."""
        try:
            import requests
            logger.info('FetchModsThread: Starting mod fetch')
            all_mods = []
            if CLOUD_FUNCTIONS_BASE_URL:
                try:
                    logger.info('FetchModsThread: Fetching mods from database')
                    app_state = getattr(self.main_window, 'app_state', None)
                    session = get_session(app_state)
                    response = session.get(f'{CLOUD_FUNCTIONS_BASE_URL}/getMods', timeout=15)
                    response.raise_for_status()
                    mods_json = response.json() or {}
                    all_mods = self._parse_mods(mods_json)
                    logger.info(f'FetchModsThread: Parsed {len(all_mods)} mods from database')
                except requests.RequestException as e:
                    logger.warning(f'FetchModsThread: Failed to fetch from database: {e}')
                    error_msg = tr('errors.update_list_failed').format(str(e))
                    self.status.emit(error_msg, UI_COLORS['status_warning'])
                except Exception as e:
                    logger.error(f'FetchModsThread: Error parsing database mods: {e}', exc_info=True)
            else:
                logger.warning('FetchModsThread: CLOUD_FUNCTIONS_BASE_URL not configured')
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
                        from config.constants import GAMEBANANA_GAME_IDS
                        self.api = GameBananaAPI()
                        selected_game = 'deltarune'
                        if self.app_state and hasattr(self.app_state, 'local_config'):
                            selected_game = self.app_state.local_config.get('selected_search_game', 'deltarune')
                        gamebanana_game = _GAME_MAPPING.get(selected_game, 'deltarune')
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
                        from config.constants import GAMEBANANA_PER_PAGE
                        try:
                            if not self.api:
                                return (mods, mods_needing_metadata)
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

                def emit_status(msg, color):
                    self.status.emit(msg, color)
                fetcher.status = emit_status
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
                        gamebanana_game = _GAME_MAPPING.get(selected_game, 'deltarune')
                        if gamebanana_game in GAMEBANANA_GAME_IDS:
                            game_id = GAMEBANANA_GAME_IDS[gamebanana_game]
                            game_mods_count = len(gamebanana_mods)
                            pages_loaded = (game_mods_count - 1) // GAMEBANANA_PER_PAGE + 1 if game_mods_count > 0 else initial_pages
                            app_state.gamebanana_loaded_pages[game_id] = pages_loaded
            except Exception as e:
                logger.error(f'FetchModsThread: Failed to fetch GameBanana mods: {e}', exc_info=True)
            logger.info('FetchModsThread: Getting local mods')
            local_mods = self._get_local_mods()
            logger.info(f'FetchModsThread: Found {len(local_mods)} local mods to preserve')
            installed_gamebanana_mod_keys = set()
            mod_service = getattr(self.main_window, 'mod_service', None)
            if mod_service:
                try:
                    installed_mods = mod_service.get_installed_mods_list()
                    for installed_mod in installed_mods:
                        key = installed_mod.get('key') or installed_mod.get('mod_key')
                        if key and key.startswith('gb_'):
                            installed_gamebanana_mod_keys.add(key)
                    logger.info(f'FetchModsThread: Found {len(installed_gamebanana_mod_keys)} installed GameBanana mods')
                except Exception as e:
                    logger.warning(f'FetchModsThread: Error getting installed GameBanana mods: {e}')
            installed_mods_with_files = {}
            if mod_service:
                try:
                    installed_mods_list = mod_service.get_installed_mods_list()
                    for installed_mod in installed_mods_list:
                        key = installed_mod.get('key') or installed_mod.get('mod_key')
                        if key and installed_mod.get('files'):
                            installed_mods_with_files[key] = installed_mod
                except Exception as e:
                    logger.warning(f'FetchModsThread: Error getting installed mods with files: {e}')
            existing_mods_with_files = {}
            app_state = getattr(self.main_window, 'app_state', None)
            if app_state and hasattr(app_state, 'all_mods'):
                for mod in app_state.all_mods:
                    key = getattr(mod, 'key', None) or getattr(mod, 'mod_key', None)
                    if key and hasattr(mod, 'files') and mod.files:
                        existing_mods_with_files[key] = mod
            all_mods_filtered = []
            for mod in all_mods:
                if hasattr(mod, 'is_local_mod') and mod.is_local_mod:
                    continue
                key = getattr(mod, 'key', None) or getattr(mod, 'mod_key', None)
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
                key = getattr(local_mod, 'key', None) or getattr(local_mod, 'mod_key', None)
                if key and key not in [getattr(m, 'key', None) or getattr(m, 'mod_key', None) for m in all_mods_filtered]:
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

    def _parse_mods(self, mods_json: Dict[str, Any]) -> List[ModInfo]:
        all_mods = []
        logger.debug(f'_parse_mods: Parsing {len(mods_json)} mods from JSON')
        parsed_count = 0
        skipped_count = 0
        for key, data in mods_json.items():
            if not isinstance(data, dict):
                skipped_count += 1
                continue
            try:
                mod = self._parse_single_mod(key, data)
                if mod:
                    all_mods.append(mod)
                    parsed_count += 1
                else:
                    skipped_count += 1
                    logger.debug(f'_parse_mods: Skipped mod {key} - validation failed')
            except Exception as e:
                skipped_count += 1
                logger.warning(f'_parse_mods: Error parsing mod {key}: {e}')
        logger.info(f'_parse_mods: Parsed {parsed_count} mods, skipped {skipped_count}')
        return all_mods

    def _parse_single_mod(self, key: str, data: Dict[str, Any]) -> Optional[ModInfo]:
        try:
            files_data = self._extract_files_data(data)
            composite_version = self._aggregate_versions(files_data)
            base_version = data.get('version')
            game = data.get('game') or data.get('modgame', 'deltarune')
            if game == 'deltarune' and data.get('is_demo_mod', False):
                game = 'deltarunedemo'
            screens_list = data.get('screenshots_url', [])
            if isinstance(screens_list, str):
                screens_list = [s.strip() for s in screens_list.split(',') if s.strip()]
            elif not isinstance(screens_list, list):
                screens_list = []
            tags = data.get('tags', [])
            if isinstance(tags, list):
                tags = ['textedit' if tag == 'translation' else str(tag) for tag in tags if tag]
            elif tags == 'translation':
                tags = ['textedit']
            else:
                tags = []
            data_dict = data.copy()
            data_dict['key'] = key
            data_dict['version'] = f'{base_version}|{composite_version}' if base_version else composite_version
            data_dict['game'] = game
            data_dict['tags'] = tags
            data_dict['screenshots_url'] = screens_list
            data_dict['demo_url'] = files_data.get('demo', {}).get('url') if files_data else None
            data_dict['demo_version'] = files_data.get('demo', {}).get('version', '1.0.0') if files_data else '1.0.0'
            if 'files' in data_dict:
                del data_dict['files']
            if 'chapters' in data_dict:
                del data_dict['chapters']
            mod = ModInfo.from_dict(data_dict)
            if self._process_mod_chapters(mod, files_data):
                return mod
            return None
        except Exception as e:
            logger.error(f'_parse_single_mod: Error parsing mod {key}: {e}', exc_info=True)
            return None

    def _extract_files_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        files_data = {}
        raw_data = data.get('files', data.get('chapters', {}))
        if isinstance(raw_data, list):
            items = [(str(i), chapter_data) for i, chapter_data in enumerate(raw_data) if chapter_data is not None]
        elif isinstance(raw_data, dict):
            items = list(raw_data.items())
        else:
            items = []
        for chapter_key, chapter_data in items:
            if not isinstance(chapter_data, dict):
                continue
            normalized_key = self._normalize_chapter_key(chapter_key)
            if not normalized_key:
                continue
            entry = self._create_file_entry(chapter_data)
            if entry:
                files_data[normalized_key] = entry
        return files_data

    def _normalize_chapter_key(self, key: Any) -> Optional[str]:
        if isinstance(key, str):
            key_lower = key.strip().lower()
            if key_lower == 'menu':
                return '0'
            if key_lower.isdigit():
                return key_lower
            if key_lower in ['demo', 'undertale']:
                return key_lower
            match = re.match('^(?:chapter_|chap_|c)(\\d+)$', key_lower)
            if match:
                return match.group(1)
        elif isinstance(key, int):
            if key == -1:
                return 'demo'
            if 0 <= key <= 4:
                return str(key)
        return None

    def _create_file_entry(self, chapter_data: Dict[str, Any]) -> Dict[str, Any]:
        entry = {}
        data_url = chapter_data.get('data_file_url')
        data_version = chapter_data.get('data_file_version') or chapter_data.get('data_win_version') or '1.0.0'
        if data_url:
            entry.update({'data_file_url': data_url, 'data_file_version': data_version})
        extra_files = chapter_data.get('extra_files', chapter_data.get('extra', []))
        if isinstance(extra_files, list):
            extra_map = {}
            for idx, ef in enumerate(extra_files):
                if isinstance(ef, dict) and ef.get('url'):
                    key = ef.get('key', str(idx))
                    extra_map[str(key)] = {'url': ef['url'], 'version': ef.get('version', '1.0.0')}
            if extra_map:
                entry['extra'] = extra_map
        elif isinstance(chapter_data.get('extra'), dict):
            extra_map = {}
            for k, v in chapter_data.get('extra', {}).items():
                if isinstance(v, dict) and (url := v.get('url')):
                    version = v.get('version') or v.get('data_file_version') or '1.0.0'
                    extra_map[str(k)] = {'url': url, 'version': version}
            if extra_map:
                entry['extra'] = extra_map
        if (desc_url := chapter_data.get('description_url')):
            entry['description_url'] = desc_url
        return entry

    def _get_local_mods(self) -> List[ModInfo]:
        local_mods = []
        app_state = getattr(self.main_window, 'app_state', None)
        if app_state and hasattr(app_state, 'all_mods'):
            for mod in app_state.all_mods:
                if hasattr(mod, 'is_local_mod') and mod.is_local_mod:
                    local_mods.append(mod)
            logger.debug(f'_get_local_mods: Found {len(local_mods)} local mods in app_state')
        return local_mods

    def _aggregate_versions(self, node: Any) -> str:
        collected = set()

        def _walk(n):
            if isinstance(n, dict):
                if (v := n.get('version')):
                    collected.add(v)
                for child in n.values():
                    _walk(child)
            elif isinstance(n, (list, tuple)):
                for item in n:
                    _walk(item)
        _walk(node)
        return '|'.join(sorted(collected, key=version_sort_key, reverse=True)) if collected else '1.0.0'

    def _process_mod_chapters(self, mod: ModInfo, files_data: Dict[str, Any]) -> bool:
        for file_key, chapter_data in files_data.items():
            if not isinstance(chapter_data, dict):
                continue
            has_df_version = not chapter_data.get('data_file_url') or bool(chapter_data.get('data_file_version'))
            extra_files = chapter_data.get('extra', {}).items()
            if not has_df_version:
                return False
            if extra_files and (not all((v.get('version') for _, v in extra_files))):
                return False
            extra_files_list = [ModExtraFile(key=k, **v) for k, v in extra_files]
            mod_chapter = ModChapterData(data_file_url=chapter_data.get('data_file_url'), data_file_version=chapter_data.get('data_file_version'), extra_files=extra_files_list)
            if mod_chapter.is_valid():
                mod.files[file_key] = mod_chapter
        return True

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
                    if not key or config_data.get('is_local_mod', False):
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
