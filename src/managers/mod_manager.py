import os
import json
import logging
import zipfile
import shutil
import tempfile
import threading
from dataclasses import dataclass
from typing import Dict, Optional, List, Tuple, Set
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication
from managers.localization_manager import tr
from models.mod_models import ModChapterData
import models.mod_models as mod_models
from workers.background_workers import UrlInstallThread, ModScanThread
from utils.file_utils import sanitize_filename, has_deltamod_info_file
from utils.mod_utils import get_mod_key, get_mod_name, resolve_mod_icon
from config.constants import UI_COLORS, MOD_CONFIG_FILENAME, LEGACY_MOD_CONFIG_FILENAME
import time
from config.constants import CLOUD_FUNCTIONS_BASE_URL
from core.exceptions import ModUninstallationError


@dataclass
class ModFolderInfo:
    mod_key: str
    folder_path: str
    folder_name: str
    config_data: Dict
    config_mtime: float


class ModManager(QObject):
    progress_updated = pyqtSignal(int)
    status_changed = pyqtSignal(str, str)
    mod_list_updated = pyqtSignal()
    installation_finished = pyqtSignal(bool, str)
    url_prompt_required = pyqtSignal(str, str)

    def __init__(self, app_state, feedback_manager, settings_manager=None, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.feedback_manager = feedback_manager
        self.settings_manager = settings_manager
        self._cache_lock = threading.RLock()
        self._mods_cache: Dict[str, ModFolderInfo] = {}
        self._mods_by_name: Dict[str, str] = {}
        self._mods_cache_valid = False
        self._scan_thread: Optional[ModScanThread] = None
        self._scan_in_progress = False

    def _scan_mods_directory(self, old_cache: Optional[Dict[str, ModFolderInfo]] = None) -> Dict[str, ModFolderInfo]:
        cache: Dict[str, ModFolderInfo] = {}
        if old_cache is None:
            old_cache = {}
        normalized_old_cache: Dict[str, ModFolderInfo] = {}
        for key, value in old_cache.items():
            if isinstance(value, dict):
                normalized_old_cache[key] = ModFolderInfo(mod_key=value.get('mod_key', key), folder_path=value.get('folder_path', ''), folder_name=value.get('folder_name', ''), config_data=value.get('config_data', {}), config_mtime=value.get('config_mtime', 0.0))
            elif isinstance(value, ModFolderInfo):
                normalized_old_cache[key] = value
        old_cache = normalized_old_cache
        if not os.path.exists(self.app_state.mods_dir):
            return cache
        try:
            with os.scandir(self.app_state.mods_dir) as entries:
                for entry in entries:
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    folder_name = entry.name
                    folder_path = entry.path
                    from utils.file_utils import migrate_mod_config
                    migrate_mod_config(folder_path)
                    config_path = os.path.join(folder_path, MOD_CONFIG_FILENAME)
                    if not os.path.exists(config_path):
                        continue
                    try:
                        config_mtime = os.path.getmtime(config_path)
                        mod_key = None
                        for old_key, old_info in old_cache.items():
                            if old_info.folder_path == folder_path:
                                mod_key = old_key
                                if config_mtime <= old_info.config_mtime:
                                    cache[mod_key] = old_info
                                    mod_name = old_info.config_data.get('name', '')
                                    if mod_name:
                                        if not hasattr(self, '_temp_mods_by_name'):
                                            self._temp_mods_by_name = {}
                                        self._temp_mods_by_name[mod_name.lower()] = mod_key
                                break
                        if mod_key is None or mod_key not in cache:
                            with open(config_path, 'r', encoding='utf-8') as f:
                                config_data = json.load(f)
                            mod_key = config_data.get('mod_key')
                            if not mod_key:
                                continue
                            mod_info = ModFolderInfo(mod_key=mod_key, folder_path=folder_path, folder_name=folder_name, config_data=config_data, config_mtime=config_mtime)
                            cache[mod_key] = mod_info
                            mod_name = config_data.get('name', '')
                            if mod_name:
                                if not hasattr(self, '_temp_mods_by_name'):
                                    self._temp_mods_by_name = {}
                                self._temp_mods_by_name[mod_name.lower()] = mod_key
                    except OSError as e:
                        logging.warning(f'_scan_mods_directory: failed to access config {config_path}: {e}', exc_info=True, extra={'mod_folder': folder_name, 'config_path': config_path})
                        continue
                    except json.JSONDecodeError as e:
                        logging.warning(f'_scan_mods_directory: invalid JSON in {config_path}: {e}', exc_info=True, extra={'mod_folder': folder_name, 'config_path': config_path, 'json_line': getattr(e, 'lineno', None), 'json_col': getattr(e, 'colno', None)})
                        continue
                    except KeyError as e:
                        logging.debug(f'_scan_mods_directory: missing key in {config_path}: {e}', extra={'mod_folder': folder_name, 'config_path': config_path, 'missing_key': str(e)})
                        continue
        except OSError as e:
            logging.error(f'_scan_mods_directory: failed to list directory {self.app_state.mods_dir}: {e}', exc_info=True, extra={'mods_dir': self.app_state.mods_dir})
        return cache

    def invalidate_mods_cache(self) -> None:
        with self._cache_lock:
            self._mods_cache_valid = False
            self._mods_by_name.clear()

    def _on_scan_completed(self, cache_dict: Dict):
        with self._cache_lock:
            cache = {}
            mods_by_name = {}
            for mod_key, mod_info_dict in cache_dict.items():
                mod_info = ModFolderInfo(mod_key=mod_info_dict['mod_key'], folder_path=mod_info_dict['folder_path'], folder_name=mod_info_dict['folder_name'], config_data=mod_info_dict['config_data'], config_mtime=mod_info_dict['config_mtime'])
                cache[mod_key] = mod_info
                mod_name = mod_info_dict['config_data'].get('name', '')
                if mod_name:
                    mods_by_name[mod_name.lower()] = mod_key
            self._mods_cache = cache
            self._mods_by_name = mods_by_name
            self._mods_cache_valid = True
            self._scan_in_progress = False
            self._scan_thread = None

    def _get_mods_cache(self, use_async: bool = False) -> Dict[str, ModFolderInfo]:
        with self._cache_lock:
            if self._mods_cache_valid:
                normalized_cache: Dict[str, ModFolderInfo] = {}
                for key, value in self._mods_cache.items():
                    if isinstance(value, dict):
                        normalized_cache[key] = ModFolderInfo(mod_key=value.get('mod_key', key), folder_path=value.get('folder_path', ''), folder_name=value.get('folder_name', ''), config_data=value.get('config_data', {}), config_mtime=value.get('config_mtime', 0.0))
                    elif isinstance(value, ModFolderInfo):
                        normalized_cache[key] = value
                if len(normalized_cache) != len(self._mods_cache) or any((isinstance(v, dict) for v in self._mods_cache.values())):
                    self._mods_cache = normalized_cache
                return self._mods_cache.copy()
            if use_async and (not self._scan_in_progress):
                if self._scan_thread and self._scan_thread.isRunning():
                    pass
                else:
                    self._scan_in_progress = True
                    from utils.path_utils import get_user_data_root
                    cache_dir = os.path.join(get_user_data_root(), 'cache')
                    self._scan_thread = ModScanThread(self.app_state.mods_dir, self.parent(), cache_dir=cache_dir)
                    self._scan_thread.scan_completed.connect(self._on_scan_completed)
                    self._scan_thread.start()
            if hasattr(self, '_temp_mods_by_name'):
                del self._temp_mods_by_name
            self._mods_cache = self._scan_mods_directory(old_cache=self._mods_cache)
            if hasattr(self, '_temp_mods_by_name'):
                self._mods_by_name = self._temp_mods_by_name.copy()
                del self._temp_mods_by_name
            else:
                self._mods_by_name = {}
            self._mods_cache_valid = True
            return self._mods_cache.copy()

    def convert_legacy_mods(self) -> bool:
        if not os.path.exists(self.app_state.mods_dir):
            return False
        conversion_happened = False
        try:
            for item_name in os.listdir(self.app_state.mods_dir):
                item_path = os.path.join(self.app_state.mods_dir, item_name)
                if os.path.isfile(item_path) and item_name.lower().endswith(('.zip', '.7z', '.rar', '.tar.gz', '.lzma')):
                    try:
                        is_deltamod_archive = False
                        item_name_lower = item_name.lower()
                        if item_name_lower.endswith('.zip'):
                            with zipfile.ZipFile(item_path, 'r') as zf:
                                if has_deltamod_info_file(zf.namelist()):
                                    is_deltamod_archive = True
                        elif item_name_lower.endswith('.tar.gz'):
                            import tarfile
                            with tarfile.open(item_path, 'r:gz') as tf:
                                if has_deltamod_info_file(tf.getnames()):
                                    is_deltamod_archive = True
                        elif item_name_lower.endswith('.rar'):
                            try:
                                import rarfile
                                with rarfile.RarFile(item_path, 'r') as rf:
                                    if has_deltamod_info_file(rf.namelist()):
                                        is_deltamod_archive = True
                            except (OSError, ImportError) as e:
                                logging.warning(f'convert_legacy_mods: failed to check rar archive {item_name}: {e}', exc_info=True)
                        elif item_name_lower.endswith('.7z'):
                            import py7zr
                            try:
                                with py7zr.SevenZipFile(item_path, mode='r') as zf:
                                    if has_deltamod_info_file(zf.getnames()):
                                        is_deltamod_archive = True
                            except (OSError, ImportError) as e:
                                logging.warning(f'convert_legacy_mods: failed to check 7z archive {item_name}: {e}', exc_info=True)
                        if is_deltamod_archive:
                            self.status_changed.emit(tr('status.deltamod_archive_detected', name=item_name), UI_COLORS['status_info'])
                            QApplication.processEvents()
                            with tempfile.TemporaryDirectory() as temp_dir:
                                shutil.unpack_archive(item_path, temp_dir)
                                content_path = temp_dir
                                contents = os.listdir(temp_dir)
                                if len(contents) == 1 and os.path.isdir(os.path.join(temp_dir, contents[0])):
                                    content_path = os.path.join(temp_dir, contents[0])
                                from utils.deltamod_converter import DeltamodConverter
                                converter = DeltamodConverter(content_path, self.app_state.mods_dir)
                                new_mod_path = converter.convert()
                                if new_mod_path:
                                    self.status_changed.emit(tr('status.deltamod_converted', name=os.path.basename(new_mod_path)), UI_COLORS['status_success'])
                                    os.remove(item_path)
                                    conversion_happened = True
                                    logging.info(f'convert_legacy_mods: converted archive {item_name} -> {new_mod_path}')
                                else:
                                    self.status_changed.emit(tr('errors.deltamod_conversion_failed', name=item_name), UI_COLORS['status_error'])
                                    logging.warning(f'convert_legacy_mods: conversion failed for archive {item_name}')
                    except (OSError, ValueError, shutil.Error) as e:
                        error_msg = f'Failed to process Deltamod archive {item_name}: {e}'
                        logging.error(f'convert_legacy_mods: {error_msg}', exc_info=True)
                        self.status_changed.emit(tr('errors.deltamod_conversion_failed', name=item_name), UI_COLORS['status_error'])
                elif os.path.isdir(item_path):
                    try:
                        dir_contents = os.listdir(item_path)
                        if has_deltamod_info_file(dir_contents) and MOD_CONFIG_FILENAME not in dir_contents and (LEGACY_MOD_CONFIG_FILENAME not in dir_contents):
                            self.status_changed.emit(tr('status.deltamod_detected', name=item_name), UI_COLORS['status_info'])
                            QApplication.processEvents()
                            from utils.deltamod_converter import DeltamodConverter
                            converter = DeltamodConverter(item_path, self.app_state.mods_dir)
                            if converter.convert():
                                shutil.rmtree(item_path)
                                conversion_happened = True
                                logging.info(f'convert_legacy_mods: converted folder {item_name}')
                            else:
                                self.status_changed.emit(tr('errors.deltamod_conversion_failed', name=item_name), UI_COLORS['status_error'])
                                logging.warning(f'convert_legacy_mods: conversion failed for folder {item_name}')
                    except Exception as e:
                        error_msg = f'Failed to process Deltamod folder {item_name}: {e}'
                        logging.error(f'convert_legacy_mods: {error_msg}', exc_info=True)
            if conversion_happened:
                self.invalidate_mods_cache()
                logging.info('convert_legacy_mods: conversion completed, mods cache invalidated')
            return conversion_happened
        except Exception as e:
            error_msg = f'Error during legacy mod conversion: {e}'
            logging.error(f'convert_legacy_mods: {error_msg}', exc_info=True)
            return False

    def load_local_mods(self, _skip_conversion=False):
        if not os.path.exists(self.app_state.mods_dir):
            os.makedirs(self.app_state.mods_dir, exist_ok=True)
            return False
        if not _skip_conversion:
            conversion_happened = self.convert_legacy_mods()
            if conversion_happened:
                return self.load_local_mods(_skip_conversion=True)
        self._get_mods_cache()
        installed_mods = {}
        try:
            for item_name in os.listdir(self.app_state.mods_dir):
                item_path = os.path.join(self.app_state.mods_dir, item_name)
                if not os.path.isdir(item_path):
                    continue
                from utils.file_utils import migrate_mod_config
                migrate_mod_config(item_path)
                config_path = os.path.join(item_path, 'mod_config.json')
                if not os.path.exists(config_path):
                    continue
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config_data = json.load(f)
                    if not config_data:
                        continue
                    mod_key = config_data.get('mod_key')
                    if mod_key:
                        installed_mods[mod_key] = config_data
                    elif config_data.get('is_gamebanana_mod') and config_data.get('gamebanana_mod_id'):
                        mod_id = config_data.get('gamebanana_mod_id')
                        recovered_key = f'gb_{mod_id}'
                        logging.warning(f'load_local_mods: Found GameBanana mod with empty mod_key in {item_path}, recovering as {recovered_key} (ID: {mod_id})')
                        config_data['mod_key'] = recovered_key
                        installed_mods[recovered_key] = config_data
                    else:
                        logging.warning(f'load_local_mods: Found mod with empty mod_key in {item_path}, skipping')
                except (OSError, json.JSONDecodeError, KeyError) as e:
                    logging.debug(f'load_local_mods: failed to load mod from {item_path}: {e}')
            installed_gamebanana_by_id = {}
            installed_gamebanana_by_key = {}
            for mod_key, config_data in installed_mods.items():
                if config_data.get('is_gamebanana_mod') and config_data.get('gamebanana_mod_id'):
                    gb_id = str(config_data.get('gamebanana_mod_id'))
                    installed_gamebanana_by_id[gb_id] = (mod_key, config_data)
                    installed_gamebanana_by_key[mod_key] = config_data
                    logging.debug(f'load_local_mods: Registered installed GameBanana mod - key={mod_key}, id={gb_id}')
            updated_count = 0
            for mod in list(self.app_state.all_mods):
                if mod.key in installed_mods:
                    config_data = installed_mods[mod.key]
                    mod_folder_path = self.get_mod_folder_path(mod.key)
                    if mod_folder_path:
                        config_data = self.get_mod_config(mod.key)
                        resolved_icon = resolve_mod_icon(config_data, mod_folder_path)
                        if resolved_icon:
                            mod.icon_url = resolved_icon
                    if config_data.get('is_gamebanana_mod'):
                        updated_count += 1
                elif hasattr(mod, 'is_gamebanana_mod') and mod.is_gamebanana_mod and hasattr(mod, 'gamebanana_mod_id') and mod.gamebanana_mod_id:
                    gb_id = str(mod.gamebanana_mod_id)
                    if gb_id in installed_gamebanana_by_id:
                        mod_key, config_data = installed_gamebanana_by_id[gb_id]
                        if mod.key != mod_key:
                            logging.debug(f'load_local_mods: Updating mod.key from {mod.key} to {mod_key} for GameBanana mod {gb_id}')
                            mod.key = mod_key
                        mod_folder_path = self.get_mod_folder_path(mod_key)
                        if mod_folder_path:
                            resolved_icon = resolve_mod_icon(config_data, mod_folder_path)
                            if resolved_icon:
                                mod.icon_url = resolved_icon
                        updated_count += 1
            logging.debug(f'load_local_mods: Updated {updated_count} existing GameBanana mods in all_mods')
            existing_keys = {mod.key for mod in self.app_state.all_mods}
            existing_gamebanana_ids = {}
            for mod in self.app_state.all_mods:
                if hasattr(mod, 'is_gamebanana_mod') and mod.is_gamebanana_mod and hasattr(mod, 'gamebanana_mod_id') and mod.gamebanana_mod_id:
                    gb_id = str(mod.gamebanana_mod_id)
                    existing_gamebanana_ids[gb_id] = mod.key
            for mod_key, config_data in list(installed_mods.items()):
                if config_data.get('is_local_mod'):
                    continue
                is_gamebanana_mod = config_data.get('is_gamebanana_mod', False)
                gamebanana_mod_id = config_data.get('gamebanana_mod_id')
                if is_gamebanana_mod and gamebanana_mod_id:
                    gb_id_str = str(gamebanana_mod_id)
                    if mod_key in existing_keys:
                        existing_mod = None
                        for mod in self.app_state.all_mods:
                            if hasattr(mod, 'key') and mod.key == mod_key:
                                existing_mod = mod
                                break
                        if existing_mod:
                            if (not hasattr(existing_mod, 'files') or not existing_mod.files) and config_data.get('files'):
                                try:
                                    new_mod = self.create_mod_object_from_info(config_data, self.app_state.all_mods)
                                    for i, mod in enumerate(self.app_state.all_mods):
                                        if hasattr(mod, 'key') and mod.key == mod_key:
                                            self.app_state.all_mods[i] = new_mod
                                            break
                                except Exception as e:
                                    logging.warning(f'load_local_mods: Failed to reload mod {mod_key} from config: {e}', exc_info=True)
                            continue
                    if gb_id_str in existing_gamebanana_ids:
                        existing_mod_key = existing_gamebanana_ids[gb_id_str]
                        for mod in self.app_state.all_mods:
                            if hasattr(mod, 'gamebanana_mod_id') and str(mod.gamebanana_mod_id) == gb_id_str:
                                if hasattr(mod, 'files') and mod.files:
                                    mod.key = mod_key
                                    existing_keys.discard(existing_mod_key)
                                    existing_keys.add(mod_key)
                                else:
                                    mod.key = mod_key
                                    existing_keys.discard(existing_mod_key)
                                    existing_keys.add(mod_key)
                                break
                        continue
                elif mod_key in existing_keys:
                    existing_mod = None
                    for mod in self.app_state.all_mods:
                        if hasattr(mod, 'key') and mod.key == mod_key:
                            existing_mod = mod
                            break
                    if existing_mod:
                        if (not hasattr(existing_mod, 'files') or not existing_mod.files) and config_data.get('files'):
                            try:
                                new_mod = self.create_mod_object_from_info(config_data, self.app_state.all_mods)
                                for i, mod in enumerate(self.app_state.all_mods):
                                    if hasattr(mod, 'key') and mod.key == mod_key:
                                        self.app_state.all_mods[i] = new_mod
                                        break
                            except Exception as e:
                                logging.warning(f'load_local_mods: Failed to reload mod {mod_key}: {e}', exc_info=True)
                    continue
                try:
                    mod_folder_path = self.get_mod_folder_path(mod_key)
                    icon_url = config_data.get('icon_url', '')
                    if not icon_url and mod_folder_path:
                        resolved_icon = resolve_mod_icon(config_data, mod_folder_path)
                        if resolved_icon:
                            icon_url = resolved_icon
                    if config_data.get('is_gamebanana_mod') and config_data.get('gamebanana_mod_id') and (not icon_url):
                        try:
                            from utils.gamebanana_api import GameBananaAPI
                            api = GameBananaAPI()
                            mod_id = int(config_data.get('gamebanana_mod_id'))
                            preview_media = api.get_mod_preview_media(mod_id)
                            if preview_media:
                                icon_url_from_api = api.extract_icon_url(preview_media)
                                if icon_url_from_api:
                                    icon_url = icon_url_from_api
                                    logging.debug(f'Loaded icon_url from API for GameBanana mod {mod_id}: {icon_url_from_api}')
                                    config_data['icon_url'] = icon_url
                                    from utils.file_utils import atomic_write_json
                                    config_path = os.path.join(mod_folder_path, 'mod_config.json')
                                    atomic_write_json(config_path, config_data, indent=2)
                        except Exception as e:
                            logging.debug(f"Failed to load icon_url for GameBanana mod {config_data.get('gamebanana_mod_id')}: {e}")
                    tags = config_data.get('tags', [])
                    if not isinstance(tags, list):
                        tags = [tags] if tags else []
                    safe_mod_info = {'key': mod_key, 'name': config_data.get('name', 'Installed Mod'), 'version': config_data.get('version', '1.0.0'), 'author': config_data.get('author', tr('defaults.unknown')), 'tagline': config_data.get('tagline', tr('defaults.no_description')), 'game_version': config_data.get('game_version', tr('defaults.not_specified')), 'description_url': '', 'downloads': 0, 'modgame': config_data.get('modgame', 'deltarune'), 'is_verified': False, 'icon_url': icon_url, 'tags': tags, 'hide_mod': False, 'is_local_mod': False, 'ban_status': False, 'demo_url': None, 'demo_version': '1.0.0', 'created_date': config_data.get('created_date', 'N/A'), 'last_updated': config_data.get('created_date', 'N/A'), 'external_url': config_data.get('external_url'), 'is_gamebanana_mod': config_data.get('is_gamebanana_mod', False), 'gamebanana_mod_id': config_data.get('gamebanana_mod_id'), 'gamebanana_mod_type': config_data.get('gamebanana_mod_type'), 'gamebanana_last_update_timestamp': config_data.get('gamebanana_last_update_timestamp')}
                    mod = mod_models.ModInfo(**safe_mod_info)
                    files_data = config_data.get('files', {})
                    for file_key, ch_info in list(files_data.items()):
                        if not isinstance(ch_info, dict):
                            continue
                        extra_files_list = []
                        extra_files_raw = ch_info.get('extra_files', [])
                        if isinstance(extra_files_raw, list):
                            for ef_data in extra_files_raw:
                                if isinstance(ef_data, dict):
                                    try:
                                        extra_files_list.append(mod_models.ModExtraFile(key=ef_data.get('key', ''), version=ef_data.get('version', '1.0.0'), url=ef_data.get('url', '')))
                                    except (KeyError, TypeError, ValueError):
                                        pass
                        elif isinstance(extra_files_raw, dict):
                            for group_key, filenames in extra_files_raw.items():
                                if isinstance(filenames, list):
                                    for filename in filenames:
                                        extra_files_list.append(mod_models.ModExtraFile(key=group_key, version=ch_info.get('versions', {}).get(group_key, '1.0.0') if isinstance(ch_info.get('versions'), dict) else '1.0.0', url=filename))
                        data_file_version = ch_info.get('data_file_version')
                        if not data_file_version and isinstance(ch_info.get('versions'), dict):
                            data_file_version = ch_info.get('versions', {}).get('data')
                        if not data_file_version:
                            data_file_version = '1.0.0'
                        valid_chapter_fields = {'description': ch_info.get('description'), 'data_file_url': ch_info.get('data_file_url'), 'data_file_version': data_file_version, 'extra_files': extra_files_list}
                        mod.files[file_key] = ModChapterData(**valid_chapter_fields)
                    if mod.files:
                        self.app_state.append_mod(mod)
                except Exception as e:
                    logging.warning(f'Failed to create ModInfo for installed mod {mod_key}: {e}', exc_info=True)
            all_mods_filtered = []
            for mod in self.app_state.all_mods:
                if hasattr(mod, 'is_local_mod') and mod.is_local_mod:
                    if hasattr(mod, 'tags') and 'local' in mod.tags:
                        continue
                all_mods_filtered.append(mod)
            self.app_state.all_mods = all_mods_filtered
            for mod_key, config_data in list(installed_mods.items()):
                if config_data.get('is_gamebanana_mod'):
                    gb_id = config_data.get('gamebanana_mod_id')
                    if gb_id:
                        gb_id_str = str(gb_id)
                        if gb_id_str in existing_gamebanana_ids:
                            continue
                    continue
                if not config_data.get('is_local_mod'):
                    continue
                if mod_key in existing_keys:
                    logging.debug(f'load_local_mods: Skipping local mod {mod_key} - already in all_mods')
                    continue
                try:
                    mod_folder_for_icon = self.get_mod_folder_path(mod_key)
                    icon_url = ''
                    if mod_folder_for_icon:
                        resolved_icon = resolve_mod_icon(config_data, mod_folder_for_icon)
                        if resolved_icon:
                            icon_url = resolved_icon
                    safe_mod_info = {'key': mod_key, 'name': config_data.get('name', tr('defaults.local_mod')), 'version': config_data.get('version', '1.0.0'), 'author': config_data.get('author', tr('defaults.unknown')), 'tagline': config_data.get('tagline', tr('defaults.no_description')), 'game_version': config_data.get('game_version', tr('defaults.not_specified')), 'description_url': '', 'downloads': 0, 'modgame': config_data.get('modgame', 'deltarune'), 'is_verified': False, 'icon_url': icon_url, 'tags': ['local'], 'hide_mod': False, 'is_local_mod': config_data.get('is_local_mod', True), 'ban_status': False, 'demo_url': None, 'demo_version': '1.0.0', 'created_date': config_data.get('created_date', 'N/A'), 'last_updated': config_data.get('created_date', 'N/A'), 'external_url': config_data.get('external_url'), 'is_gamebanana_mod': config_data.get('is_gamebanana_mod', False), 'gamebanana_mod_id': config_data.get('gamebanana_mod_id'), 'gamebanana_mod_type': config_data.get('gamebanana_mod_type'), 'gamebanana_last_update_timestamp': config_data.get('gamebanana_last_update_timestamp')}
                    mod = mod_models.ModInfo(**safe_mod_info)
                    files_data = config_data.get('files', {})
                    mod_folder_path = None
                    for folder_name in os.listdir(self.app_state.mods_dir):
                        folder_path = os.path.join(self.app_state.mods_dir, folder_name)
                        from utils.file_utils import migrate_mod_config
                        migrate_mod_config(folder_path)
                        test_config_path = os.path.join(folder_path, 'mod_config.json')
                        if os.path.isfile(test_config_path):
                            try:
                                with open(test_config_path, 'r', encoding='utf-8') as f:
                                    test_config = json.load(f)
                                    if test_config.get('mod_key') == mod_key:
                                        mod_folder_path = folder_path
                                        break
                            except Exception as e:
                                logging.warning(f'Failed reading config {test_config_path}: {e}')
                                continue
                    for file_key, ch_info in list(files_data.items()):
                        chapter_files = ch_info
                        if mod_folder_path:
                            if file_key == 'demo':
                                chapter_folder = os.path.join(mod_folder_path, 'demo')
                            elif file_key == 'undertale':
                                chapter_folder = os.path.join(mod_folder_path, 'undertale')
                            elif file_key in ['0', '1', '2', '3', '4']:
                                if file_key == '0':
                                    chapter_folder = os.path.join(mod_folder_path, 'chapter_0')
                                else:
                                    chapter_folder = os.path.join(mod_folder_path, f'chapter_{file_key}')
                            else:
                                try:
                                    ch_id = int(file_key)
                                    if ch_id == -1:
                                        chapter_folder = os.path.join(mod_folder_path, 'demo')
                                    elif ch_id == 0:
                                        chapter_folder = os.path.join(mod_folder_path, 'chapter_0')
                                    else:
                                        chapter_folder = os.path.join(mod_folder_path, f'chapter_{ch_id}')
                                except ValueError:
                                    continue
                        data_file_url = ''
                        if chapter_files.get('data_file_url') and mod_folder_path:
                            data_file_url = os.path.join(chapter_folder, chapter_files['data_file_url'])
                        from models.mod_models import ModExtraFile
                        extra_files = []
                        if chapter_files.get('extra_files') and mod_folder_path:
                            for group_key, filenames in list(chapter_files['extra_files'].items()):
                                for filename in filenames:
                                    file_path = os.path.join(chapter_folder, filename)
                                    extra_files.append(ModExtraFile(key=group_key, url=file_path, version='1.0.0'))
                        mod_chapter = ModChapterData(description=config_data.get('tagline', ''), data_file_url=data_file_url, data_file_version=chapter_files.get('data_file_version', (ch_info.get('versions', {}) or {}).get('data', '1.0.0')), extra_files=extra_files)
                        mod.files[file_key] = mod_chapter
                    if mod.files:
                        self.app_state.append_mod(mod)
                except Exception as e:
                    logging.warning(f'Failed to build local ModInfo: {e}')
                    continue
            installed_gamebanana_mod_ids = set()
            for mod_key, config_data in installed_mods.items():
                if config_data.get('is_gamebanana_mod') and config_data.get('gamebanana_mod_id'):
                    installed_gamebanana_mod_ids.add(str(config_data.get('gamebanana_mod_id')))
            for mod in self.app_state.all_mods:
                if hasattr(mod, 'is_gamebanana_mod') and mod.is_gamebanana_mod and hasattr(mod, 'gamebanana_mod_id') and mod.gamebanana_mod_id:
                    mod_id_str = str(mod.gamebanana_mod_id)
                    if mod_id_str in installed_gamebanana_mod_ids:
                        current_downloads = getattr(mod, 'downloads', 0) or 0
                        if current_downloads <= 0:
                            try:
                                from utils.gamebanana_api import GameBananaAPI
                                api = GameBananaAPI()
                                downloaded_count = api.get_mod_downloads_only(int(mod.gamebanana_mod_id))
                                if downloaded_count is not None and downloaded_count > 0:
                                    mod.downloads = downloaded_count
                                elif downloaded_count is not None:
                                    mod.downloads = 0
                            except Exception as e:
                                logging.debug(f'load_local_mods: Failed to load downloads from API for mod {mod.key}: {e}')
            metadata = self._read_metadata()
            cleanup_files = metadata.get('mod_files_to_cleanup', [])
            cleanup_dirs = metadata.get('mod_dirs_to_cleanup', [])
            for p in cleanup_files:
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception as e:
                        logging.warning(f'load_local_mods: failed to remove cleanup file {p}: {e}', exc_info=True)
            for d in cleanup_dirs:
                if os.path.exists(d):
                    try:
                        shutil.rmtree(d)
                    except Exception as e:
                        logging.warning(f'load_local_mods: failed to remove cleanup dir {d}: {e}', exc_info=True)
            self._write_metadata({'mod_files_to_cleanup': [], 'mod_dirs_to_cleanup': []})
            return True
        except Exception as e:
            logging.error(f'_load_local_mods_from_folders failed: {e}', exc_info=True)
            return False

    def get_mod_config(self, mod_key: str) -> dict:
        cache = self._get_mods_cache()
        mod_info = cache.get(mod_key)
        if mod_info:
            return mod_info.config_data.copy()
        return {}

    def get_mod_folder_path(self, mod_key: str) -> str:
        cache = self._get_mods_cache()
        mod_info = cache.get(mod_key)
        if mod_info:
            if isinstance(mod_info, dict):
                return mod_info.get('folder_path', '')
            return mod_info.folder_path
        return ''

    @staticmethod
    def resolve_gamebanana_file(mod_info, api, selected_file=None) -> Optional[Dict]:
        if selected_file:
            return selected_file
        files = getattr(mod_info, 'gamebanana_supported_files', []) or []
        if files:
            return files[0]
        try:
            mod_id = getattr(mod_info, 'gamebanana_mod_id', None)
            if not mod_id:
                return None
            compat = api.get_supported_files_for_mod(int(mod_id))
            files = compat.get('supported_files') or []
            if files:
                mod_info.gamebanana_supported_files = files
                mod_info.gamebanana_is_tool_compatible = compat.get('has_supported_files', False)
                mod_info.gamebanana_compatibility_checked = compat.get('compatibility_checked', False)
                return files[0]
        except Exception as e:
            logging.warning(f"ModManager: Failed to resolve GameBanana file for mod {getattr(mod_info, 'gamebanana_mod_id', 'unknown')}: {e}")
        return None

    def install_from_url(self, url: str):
        if self.app_state.is_installing:
            return
        self.app_state.is_installing = True
        self.status_changed.emit(tr('status.downloading_mod'), 'status_info')
        url_install_thread = UrlInstallThread(self.parent(), url)
        url_install_thread.progress.connect(self.progress_updated.emit)
        url_install_thread.status.connect(self.status_changed.emit)
        url_install_thread.finished.connect(self._on_url_install_finished)
        url_install_thread.prompt_required.connect(self.url_prompt_required.emit)
        self.app_state.current_task = url_install_thread
        url_install_thread.start()

    def uninstall_mod(self, mod):
        try:
            self.delete_mod_files(mod)
            self.app_state.is_installing = False
            self.mod_list_updated.emit()
            self.status_changed.emit(tr('status.mod_uninstalled'), 'status_success')
        except PermissionError as e:
            mod_key = get_mod_key(mod) or 'unknown'
            mod_name = get_mod_name(mod, 'Unknown Mod')
            error = ModUninstallationError(f'Permission denied during uninstallation: {e}', mod_key=mod_key, mod_name=mod_name, reason='permission_error')
            logging.error(f'uninstall_mod: permission error: {e}', exc_info=True, extra={'mod_key': mod_key, 'mod_name': mod_name})
            self.feedback_manager.show_message('error', 'errors.uninstall_failed', tr('errors.permission_denied'))
            raise error
        except (OSError, shutil.Error) as e:
            mod_key = get_mod_key(mod) or 'unknown'
            mod_name = get_mod_name(mod, 'Unknown Mod')
            error = ModUninstallationError(f'File operation failed during uninstallation: {e}', mod_key=mod_key, mod_name=mod_name, reason='io_error')
            logging.error(f'uninstall_mod: file operation error: {e}', exc_info=True, extra={'mod_key': mod_key, 'mod_name': mod_name})
            self.feedback_manager.show_message('error', 'errors.uninstall_failed', tr('errors.file_operation_failed', error=str(e)))
            raise error
        except (KeyError, AttributeError) as e:
            mod_key = get_mod_key(mod) or 'unknown'
            mod_name = get_mod_name(mod, 'Unknown Mod')
            error = ModUninstallationError(f'Missing required data: {e}', mod_key=mod_key, mod_name=mod_name, reason='missing_data')
            logging.error(f'uninstall_mod: data error: {e}', exc_info=True, extra={'mod_key': mod_key, 'mod_name': mod_name})
            raise error
        except Exception as e:
            mod_key = get_mod_key(mod) or 'unknown'
            mod_name = get_mod_name(mod, 'Unknown Mod')
            error = ModUninstallationError(f'Unexpected error during uninstallation: {e}', mod_key=mod_key, mod_name=mod_name, reason='unknown')
            logging.error(f'uninstall_mod: unexpected error: {e}', exc_info=True, extra={'mod_key': mod_key, 'mod_name': mod_name})
            self.feedback_manager.show_message('error', 'errors.uninstall_failed', str(e))
            raise error

    def update_mod(self, mod_data):
        if self.app_state.is_installing:
            return
        parent = self.parent()
        mod_ops = getattr(parent, 'mod_ops', None) if parent else None
        if mod_ops:
            mod_ops.install_mod(mod_data, force=True, is_update=True)

    def delete_mod_files(self, mod_data):
        try:
            mod_key = mod_data.get('key', '') if isinstance(mod_data, dict) else mod_data.key
            cache = self._get_mods_cache()
            mod_info = cache.get(mod_key)
            if not mod_info:
                return
            if os.path.exists(mod_info.folder_path):
                import shutil
                shutil.rmtree(mod_info.folder_path)
                self.invalidate_mods_cache()
        except Exception as e:
            logging.error(f'uninstall_mod: cleanup failed: {e}', exc_info=True)

    def get_mod_status(self, mod: mod_models.ModInfo, chapter_id: int) -> str:
        if mod.is_local_mod:
            return 'ready'

        def _collect_remote_versions(m: mod_models.ModInfo, ch_id: int) -> dict:
            if ch_id == -1:
                return {'demo': m.demo_version} if m.is_valid_for_demo() and m.demo_version else {}
            ch = m.get_chapter_data(ch_id)
            if not ch:
                return {}
            d = {}
            if ch.data_file_version:
                d['data'] = ch.data_file_version
            for ef in ch.extra_files:
                d[ef.key] = ef.version
            return d
        remote_versions = _collect_remote_versions(mod, chapter_id)
        if not remote_versions:
            return 'n/a'
        cache = self._get_mods_cache()
        mod_info = cache.get(mod.key)
        if not mod_info:
            return 'install'
        config_data = mod_info.config_data
        if chapter_id == -1:
            file_key = 'demo'
        elif chapter_id == 0:
            file_key = '0'
        elif chapter_id > 0:
            file_key = str(chapter_id)
        else:
            file_key = str(chapter_id)
        local_versions = {}
        files_data = config_data.get('files', {})
        if file_key in files_data:
            file_info = files_data[file_key]
            if file_info.get('data_file_version'):
                local_versions['data'] = file_info['data_file_version']
            versions_data = file_info.get('versions', {})
            for key, version in versions_data.items():
                local_versions[key] = version
        if not local_versions:
            return 'install'
        for k in local_versions.keys():
            if k not in remote_versions:
                return 'update'
        from utils.file_utils import version_sort_key
        for k, rv in remote_versions.items():
            lv = local_versions.get(k)
            if version_sort_key(rv) > version_sort_key(lv or '0.0.0'):
                return 'update'
        return 'ready'

    def mod_has_update_available(self, mod_data) -> bool:
        try:
            if hasattr(mod_data, 'is_gamebanana_mod') and mod_data.is_gamebanana_mod:
                try:
                    from managers.gamebanana_update_manager import GameBananaUpdateManager
                    update_manager = GameBananaUpdateManager(self.app_state.mods_dir)
                    has_update = update_manager.check_mod_for_updates(mod_data)
                    if has_update:
                        logging.info(f'mod_has_update_available: GameBanana mod {mod_data.name} has update available')
                    return has_update
                except Exception as e:
                    logging.warning(f'mod_has_update_available: Error checking GameBanana update for {mod_data.name}: {e}', exc_info=True)
            for chapter_id in range(5):
                if self.mod_has_files_for_chapter(mod_data, chapter_id):
                    if self.get_mod_status(mod_data, chapter_id) == 'update':
                        return True
            return False
        except Exception as e:
            logging.warning(f'mod_has_update_available: exception: {e}', exc_info=True)
            return False

    def is_mod_installed(self, mod_key: str) -> bool:
        with self._cache_lock:
            if not self._mods_cache_valid:
                self._get_mods_cache()
            return mod_key in self._mods_cache

    def find_mod_by_name(self, mod_name: str) -> Optional[str]:
        with self._cache_lock:
            if not self._mods_cache_valid:
                self._get_mods_cache()
            return self._mods_by_name.get(mod_name.lower())

    def check_mod_exists(self, mod_info):
        cache = self._get_mods_cache()
        mod_key = mod_info.get('mod_key', '')
        if mod_key and mod_key in cache:
            return True
        folder_name = mod_info.get('folder_name', '')
        if folder_name:
            for mod_info_cached in cache.values():
                if mod_info_cached.folder_name == folder_name:
                    return True
        mod_name = mod_info.get('name', '')
        if mod_name:
            safe_name = sanitize_filename(mod_name)
            for mod_info_cached in cache.values():
                if mod_info_cached.folder_name == safe_name:
                    return True
        return False

    def mod_has_files_for_chapter(self, mod_data, chapter_id):
        try:
            mod_key = get_mod_key(mod_data)
            if not mod_key:
                return True
            cache = self._get_mods_cache()
            mod_info = cache.get(mod_key)
            if not mod_info:
                return False
            files_data = mod_info.config_data.get('files', {})
            if files_data:
                if chapter_id == -1:
                    file_key = 'demo'
                elif chapter_id == 0:
                    file_key = '0'
                elif chapter_id > 0:
                    file_key = str(chapter_id)
                else:
                    return False
                if chapter_id == -1:
                    return 'demo' in files_data or 'undertale' in files_data
                return file_key in files_data
            chapter_folders = {-1: 'universal', 0: 'menu', 1: 'chapter1', 2: 'chapter2', 3: 'chapter3', 4: 'chapter4'}
            folder_name = chapter_folders.get(chapter_id, 'universal')
            chapter_folder = os.path.join(mod_info.folder_path, folder_name)
            if os.path.exists(chapter_folder):
                return len(os.listdir(chapter_folder)) > 0
            universal_folder = os.path.join(mod_info.folder_path, 'universal')
            if os.path.exists(universal_folder):
                return len(os.listdir(universal_folder)) > 0
            return True
        except Exception as e:
            logging.warning(f'mod_has_files_for_chapter: exception: {e}', exc_info=True)
            return True

    def _read_metadata(self) -> Dict:
        with self.app_state._mods_metadata_lock:
            if not os.path.exists(self.app_state.mods_metadata_path):
                return {}
            try:
                if self.settings_manager:
                    return self.settings_manager.read_json(self.app_state.mods_metadata_path) or {}
                else:
                    with open(self.app_state.mods_metadata_path, 'r', encoding='utf-8') as f:
                        return json.load(f) or {}
            except Exception as e:
                logging.warning(f'_read_metadata: failed: {e}', exc_info=True)
                return {}

    def _write_metadata(self, data: Dict):
        with self.app_state._mods_metadata_lock:
            try:
                if self.settings_manager:
                    self.settings_manager.write_json(self.app_state.mods_metadata_path, data)
                else:
                    from utils.file_utils import atomic_write_json
                    atomic_write_json(self.app_state.mods_metadata_path, data, indent=2)
            except Exception as e:
                logging.error(f'_write_metadata: failed: {e}', exc_info=True)

    def _on_url_install_finished(self, success: bool, message: str):
        self.app_state.is_installing = False
        self.app_state.clear_current_task()
        self.mod_list_updated.emit()
        if success:
            self.invalidate_mods_cache()
            self.status_changed.emit(tr('status.mod_installed'), 'status_success')
        elif self.app_state.current_task and getattr(self.app_state.current_task, '_cancelled', False):
            self.status_changed.emit(tr('status.install_cancelled_by_user'), 'status_info')
        else:
            self.status_changed.emit(tr('status.installation_failed'), 'status_error')
        self.installation_finished.emit(success, message)

    def handle_url_prompt_response(self, response: bool):
        if self.app_state.current_task:
            self.app_state.current_task.prompt_result = response
            self.app_state.current_task.prompt_event.set()

    def create_mod_object_from_info(self, mod_info: dict, all_mods: Optional[list] = None):
        mod_key = mod_info.get('mod_key', '')
        if all_mods:
            for mod in all_mods:
                if hasattr(mod, 'key') and mod.key == mod_key:
                    if hasattr(mod, 'files') and mod.files:
                        return mod
        files_data = mod_info.get('files', {})
        if files_data:
            normalized_files = {}
            for file_key, ch_info in files_data.items():
                if not isinstance(ch_info, dict):
                    continue
                extra_files_list = []
                extra_files_raw = ch_info.get('extra_files', [])
                if isinstance(extra_files_raw, list):
                    for ef_data in extra_files_raw:
                        if isinstance(ef_data, dict):
                            try:
                                extra_files_list.append({'key': ef_data.get('key', ''), 'version': ef_data.get('version', '1.0.0'), 'url': ef_data.get('url', '')})
                            except (KeyError, TypeError, ValueError):
                                pass
                        elif isinstance(ef_data, mod_models.ModExtraFile):
                            extra_files_list.append({'key': ef_data.key, 'version': ef_data.version, 'url': ef_data.url})
                elif isinstance(extra_files_raw, dict):
                    for group_key, filenames in extra_files_raw.items():
                        if isinstance(filenames, list):
                            for filename in filenames:
                                extra_files_list.append({'key': group_key, 'version': ch_info.get('versions', {}).get(group_key, '1.0.0') if isinstance(ch_info.get('versions'), dict) else '1.0.0', 'url': filename})
                data_file_version = ch_info.get('data_file_version') or (ch_info.get('versions', {}).get('data') if isinstance(ch_info.get('versions'), dict) else None) or '1.0.0'
                normalized_files[file_key] = {'description': ch_info.get('description'), 'data_file_url': ch_info.get('data_file_url'), 'data_file_version': data_file_version, 'extra_files': extra_files_list}
            mod_info = mod_info.copy()
            mod_info['files'] = normalized_files
        return mod_models.ModInfo.from_dict(mod_info)

    def fetch_mod_data_by_secret(self, secret_key: str) -> Tuple[Optional[dict], Optional[str], bool]:
        from utils.crypto_utils import possible_secret_hashes
        candidate_hashes = possible_secret_hashes(secret_key.strip())
        mod_data: Optional[dict] = None
        import requests
        found_in_pending = False
        found_hash: Optional[str] = None
        for h in candidate_hashes:
            try:
                from utils.network_utils import get_session
                session = get_session()
                resp = session.get(f'{CLOUD_FUNCTIONS_BASE_URL}/getModData?modId={h}', timeout=10)
                if resp.status_code == 200 and resp.json():
                    mod_data = resp.json()
                    found_hash = h
                    break
                resp = session.get(f'{CLOUD_FUNCTIONS_BASE_URL}/getPendingModData?modId={h}', timeout=10)
                if resp.status_code == 200 and resp.json():
                    mod_data = resp.json()
                    found_hash = h
                    found_in_pending = True
                    break
            except requests.RequestException:
                raise
        if mod_data and found_hash:
            mod_data['key'] = found_hash
        return (mod_data, found_hash, found_in_pending)

    def has_pending_changes(self, hashed_key: str) -> bool:
        import requests
        try:
            from utils.network_utils import get_session
            resp = get_session().get(f'{CLOUD_FUNCTIONS_BASE_URL}/getPendingChangeData?modId={hashed_key}', timeout=10)
            return bool(resp.status_code == 200 and resp.json())
        except requests.RequestException:
            return False

    def withdraw_pending_mod(self, hashed_key: str) -> None:
        import requests
        try:
            from utils.network_utils import get_session
            get_session().post(f'{CLOUD_FUNCTIONS_BASE_URL}/withdrawPendingMod', json={'hashedKey': hashed_key}, timeout=10)
        except requests.RequestException:
            raise

    def withdraw_pending_change(self, hashed_key: str) -> None:
        import requests
        try:
            from utils.network_utils import get_session
            resp = get_session().post(f'{CLOUD_FUNCTIONS_BASE_URL}/withdrawPendingChange', json={'hashedKey': hashed_key}, timeout=10)
            resp.raise_for_status()
        except requests.RequestException:
            raise

    def list_local_mods(self) -> List[dict]:
        local_mods: List[dict] = []
        if not os.path.exists(self.app_state.mods_dir):
            return local_mods
        for folder_name in os.listdir(self.app_state.mods_dir):
            folder_path = os.path.join(self.app_state.mods_dir, folder_name)
            if not os.path.isdir(folder_path):
                continue
            from utils.file_utils import migrate_mod_config
            migrate_mod_config(folder_path)
            config_path = os.path.join(folder_path, 'mod_config.json')
            if not os.path.exists(config_path):
                continue
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                if config_data and config_data.get('is_local_mod'):
                    local_mods.append({'key': config_data.get('mod_key'), 'name': config_data.get('name', 'Unknown mod'), 'data': config_data, 'folder_path': folder_path})
            except Exception as e:
                logging.warning(f'list_local_mods: failed to read {config_path}: {e}', exc_info=True)
                continue
        return local_mods

    def migrate_metadata_from_local_configs(self) -> bool:
        mods_metadata = self._read_metadata()
        updated = False
        if not os.path.exists(self.app_state.mods_dir):
            return False
        for folder_name in os.listdir(self.app_state.mods_dir):
            folder_path = os.path.join(self.app_state.mods_dir, folder_name)
            if not os.path.isdir(folder_path):
                continue
            from utils.file_utils import migrate_mod_config
            migrate_mod_config(folder_path)
            config_path = os.path.join(folder_path, 'mod_config.json')
            if not os.path.exists(config_path):
                continue
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                if not config_data or not isinstance(config_data, dict):
                    continue
                mod_key = config_data.get('mod_key')
                if not mod_key:
                    continue
                if 'installed_date' in config_data or 'is_available_on_server' in config_data:
                    if mod_key not in mods_metadata:
                        mods_metadata[mod_key] = {}
                    if 'installed_date' in config_data:
                        mods_metadata[mod_key]['installed_date'] = config_data.pop('installed_date')
                    if 'is_available_on_server' in config_data:
                        mods_metadata[mod_key]['is_available_on_server'] = config_data.pop('is_available_on_server')
                    from utils.file_utils import atomic_write_json
                    atomic_write_json(config_path, config_data, indent=4)
                    updated = True
            except Exception as e:
                logging.warning(f'Failed to migrate metadata for mod in {folder_name}: {e}')
        if updated:
            self._write_metadata(mods_metadata)
        return updated

    def get_installed_mods_list(self) -> List[dict]:
        installed_mods: List[dict] = []
        if not hasattr(self.app_state, 'mods_dir') or not os.path.exists(self.app_state.mods_dir):
            return installed_mods
        mods_metadata = self._read_metadata()
        metadata_updated = False
        found_mod_keys: Set[str] = set()
        for folder_name in os.listdir(self.app_state.mods_dir):
            folder_path = os.path.join(self.app_state.mods_dir, folder_name)
            if not os.path.isdir(folder_path):
                continue
            from utils.file_utils import migrate_mod_config
            migrate_mod_config(folder_path)
            config_path = os.path.join(folder_path, 'mod_config.json')
            if os.path.exists(config_path):
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config_data = json.load(f)
                    if config_data:
                        mod_key = config_data.get('mod_key')
                        if not mod_key:
                            continue
                        found_mod_keys.add(mod_key)
                        mod_meta = mods_metadata.get(mod_key)
                        if not mod_meta:
                            mods_metadata[mod_key] = {'installed_date': time.strftime('%Y-%m-%d %H:%M:%S'), 'is_available_on_server': not config_data.get('is_local_mod', False)}
                            metadata_updated = True
                            mod_meta = mods_metadata[mod_key]
                        config_data['installed_date'] = mod_meta.get('installed_date')
                        config_data['is_available_on_server'] = mod_meta.get('is_available_on_server', False)
                        config_data['is_local_mod'] = config_data.get('is_local_mod', False)
                        config_data['folder_name'] = folder_name
                        installed_mods.append(config_data)
                except Exception as e:
                    logging.warning(f'Failed to read config {config_path}: {e}')
                    continue
        orphaned_keys = set(mods_metadata.keys()) - found_mod_keys
        if orphaned_keys:
            for key in list(orphaned_keys):
                del mods_metadata[key]
            metadata_updated = True
        if metadata_updated:
            self._write_metadata(mods_metadata)
        return installed_mods


def parse_mod_date(date_str: str) -> tuple[int, int, int, int, int]:
    if not date_str or date_str == 'N/A':
        return (0, 0, 0, 0, 0)
    try:
        parts = date_str.split(' ')
        if len(parts) >= 2:
            date_part = parts[0]
            time_part = parts[1]
            day, month, year = map(int, date_part.split('.'))
            hour, minute = map(int, time_part.split(':'))
            if year < 50:
                year += 2000
            else:
                year += 1900
            return (year, month, day, hour, minute)
    except Exception as e:
        logging.debug(f"parse_mod_date failed for '{date_str}': {e}")
    return (0, 0, 0, 0, 0)
