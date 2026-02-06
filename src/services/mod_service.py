"""Mod management and installation."""
import os
import json
import logging
import zipfile
import shutil
import tempfile
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Any
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox
from services.localization_service import tr
from models.mod_models import ModChapterData
import models.mod_models as mod_models
from workers.install.url_install_worker import UrlInstallThread
from workers.mod_scan_worker import ModScanThread
from utils.file_utils import sanitize_filename, has_deltamod_info_file
from utils.mod_utils import get_mod_key, get_mod_name, resolve_mod_icon
from config.constants import UI_COLORS, MOD_CONFIG_FILENAME, LEGACY_MOD_CONFIG_FILENAME
import time
from core.exceptions import ModUninstallationError


@dataclass
class ModFolderInfo:
    """Information about a mod folder and its configuration."""
    key: str
    folder_path: str
    folder_name: str
    config_data: Dict
    config_mtime: float


class ModManager(QObject):
    """Manages mod operations including scanning, installation, and caching."""
    progress_updated = pyqtSignal(int)
    status_changed = pyqtSignal(str, str)
    mod_list_updated = pyqtSignal()
    installation_finished = pyqtSignal(bool, str)
    url_prompt_required = pyqtSignal(str, str)

    def __init__(self, app_state, feedback_service, settings_service=None, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.feedback_service = feedback_service
        self.settings_service = settings_service
        self._cache_lock = threading.RLock()
        self._mods_cache: Dict[str, ModFolderInfo] = {}
        self._mods_by_name: Dict[str, str] = {}
        self._mods_cache_valid = False
        self._scan_thread: Optional[ModScanThread] = None
        self._scan_in_progress = False
        self._installed_mods_cache: List[dict] = []
        self._installed_mods_cache_valid: bool = False

    def cleanup_stale_used_mods(self):
        if not self._mods_cache:
            return
        valid_mod_keys = set(self._mods_cache.keys())
        changes_made = False
        keys_to_check = [k for k in self.app_state.local_config.keys() if k.startswith('used_mods')]
        for settings_key in keys_to_check:
            used_mods_list = self.app_state.local_config.get(settings_key)
            if not isinstance(used_mods_list, list):
                continue
            new_list = [mod_id for mod_id in used_mods_list if mod_id in valid_mod_keys]
            if len(new_list) != len(used_mods_list):
                extra_ids = set(used_mods_list) - set(new_list)
                logging.info(f'Cleanup: Removing stale mods from {settings_key}: {extra_ids}')
                self.app_state.local_config[settings_key] = new_list
                changes_made = True
        if changes_made:
            self.app_state.save_config()

    def _normalize_mod_cache(self, cache: Dict[str, Any]) -> Dict[str, ModFolderInfo]:
        normalized_cache: Dict[str, ModFolderInfo] = {}
        for key, value in cache.items():
            if isinstance(value, dict):
                normalized_cache[key] = ModFolderInfo(key=value.get('key') or value.get('mod_key', key), folder_path=value.get('folder_path', ''), folder_name=value.get('folder_name', ''), config_data=value.get('config_data', {}), config_mtime=value.get('config_mtime', 0.0))
            elif isinstance(value, ModFolderInfo):
                normalized_cache[key] = value
        return normalized_cache

    def _scan_mods_directory(self, old_cache: Optional[Dict[str, ModFolderInfo]] = None) -> Dict[str, ModFolderInfo]:
        cache: Dict[str, ModFolderInfo] = {}
        if old_cache is None:
            old_cache = {}

        def record_mod_name(mod_name: str, key_value: str) -> None:
            if not mod_name:
                return
            if not hasattr(self, '_temp_mods_by_name'):
                self._temp_mods_by_name = {}
            self._temp_mods_by_name[mod_name.lower()] = key_value
        old_cache = self._normalize_mod_cache(old_cache)
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
                        found_nested = False
                        try:
                            with os.scandir(folder_path) as sub_entries:
                                for sub in sub_entries:
                                    if sub.is_dir():
                                        nested_config_path = os.path.join(sub.path, MOD_CONFIG_FILENAME)
                                        if os.path.exists(nested_config_path):
                                            config_path = nested_config_path
                                            folder_path = sub.path
                                            found_nested = True
                                            break
                        except (OSError, PermissionError):
                            pass
                        if not found_nested:
                            continue
                    try:
                        config_size = os.path.getsize(config_path)
                        if config_size == 0:
                            logging.warning(f'_scan_mods_directory: Corrupted config detected (0 bytes) in {config_path}, skipping mod', extra={'mod_folder': folder_name, 'config_path': config_path})
                            continue
                        config_mtime = os.path.getmtime(config_path)
                        key = None
                        for old_key, old_info in old_cache.items():
                            if old_info.folder_path == folder_path:
                                key = old_key
                                if config_mtime <= old_info.config_mtime:
                                    cache[key] = old_info
                                    mod_name = old_info.config_data.get('name', '')
                                    record_mod_name(mod_name, key)
                                break
                        if key is None or key not in cache:
                            from utils.file_utils import load_json
                            try:
                                config_data = load_json(config_path, migrate_config=True)
                                if not config_data:
                                    logging.warning(f'_scan_mods_directory: Empty config data in {config_path}, skipping mod', extra={'mod_folder': folder_name, 'config_path': config_path})
                                    continue
                                if not self._validate_mod_config(config_data, config_path, folder_name):
                                    logging.warning(f'_scan_mods_directory: Config validation failed for {folder_name}, marking as corrupted', extra={'mod_folder': folder_name, 'config_path': config_path})
                                    continue
                            except (TypeError, ValueError, AttributeError) as e:
                                logging.warning(f'_scan_mods_directory: Config structure error in {config_path}: {e}, skipping mod', exc_info=True, extra={'mod_folder': folder_name, 'config_path': config_path, 'error_type': type(e).__name__})
                                continue
                            key = config_data.get('key') or config_data.get('mod_key') or ''
                            if not key:
                                cache_key = f'__no_key_{folder_path}'
                            else:
                                cache_key = key
                            mod_info = ModFolderInfo(key=key, folder_path=folder_path, folder_name=folder_name, config_data=config_data, config_mtime=config_mtime)
                            cache[cache_key] = mod_info
                            mod_name = config_data.get('name', '')
                            record_mod_name(mod_name, key)
                    except (OSError, PermissionError) as e:
                        logging.warning(f'_scan_mods_directory: Corrupted config detected (failed to access) in {config_path}: {e}', exc_info=True, extra={'mod_folder': folder_name, 'config_path': config_path})
                        continue
                    except json.JSONDecodeError as e:
                        logging.warning(f'_scan_mods_directory: Corrupted config detected (invalid JSON) in {config_path}: {e}', exc_info=True, extra={'mod_folder': folder_name, 'config_path': config_path, 'json_line': getattr(e, 'lineno', None), 'json_col': getattr(e, 'colno', None)})
                        continue
                    except KeyError as e:
                        logging.debug(f'_scan_mods_directory: missing key in {config_path}: {e}', extra={'mod_folder': folder_name, 'config_path': config_path, 'missing_key': str(e)})
                        continue
        except OSError as e:
            logging.error(f'_scan_mods_directory: failed to list directory {self.app_state.mods_dir}: {e}', exc_info=True, extra={'mods_dir': self.app_state.mods_dir})
        return cache

    def _validate_mod_config(self, config_data: dict, config_path: str, folder_name: str) -> bool:
        if not isinstance(config_data, dict):
            logging.warning(f'_validate_mod_config: Config is not a dictionary in {config_path}, skipping mod', extra={'mod_folder': folder_name, 'config_path': config_path, 'config_type': type(config_data).__name__})
            return False
        has_name = bool(config_data.get('name'))
        has_key = bool(config_data.get('key') or config_data.get('mod_key'))
        if not has_name and (not has_key):
            logging.warning(f'_validate_mod_config: Config missing both name and key in {config_path}, skipping mod', extra={'mod_folder': folder_name, 'config_path': config_path})
            return False
        if 'name' in config_data and (not isinstance(config_data['name'], str)):
            logging.warning(f'_validate_mod_config: Config field "name" has invalid type in {config_path}, expected string', extra={'mod_folder': folder_name, 'config_path': config_path, 'name_type': type(config_data['name']).__name__})
            return False
        key_value = config_data.get('key') or config_data.get('mod_key')
        if key_value and (not isinstance(key_value, str)):
            logging.warning(f'_validate_mod_config: Config field "key" has invalid type in {config_path}, expected string', extra={'mod_folder': folder_name, 'config_path': config_path, 'key_type': type(key_value).__name__})
            return False
        if 'files' in config_data and (not isinstance(config_data['files'], dict)):
            logging.warning(f'_validate_mod_config: Config field "files" has invalid type in {config_path}, expected dict', extra={'mod_folder': folder_name, 'config_path': config_path, 'files_type': type(config_data['files']).__name__})
            return False
        if 'tags' in config_data and (not isinstance(config_data['tags'], (list, type(None)))):
            logging.warning(f'_validate_mod_config: Config field "tags" has invalid type in {config_path}, expected list or None', extra={'mod_folder': folder_name, 'config_path': config_path, 'tags_type': type(config_data['tags']).__name__})
            return False
        return True

    def _cleanup_corrupted_mods(self) -> int:
        if not os.path.exists(self.app_state.mods_dir):
            return 0
        removed_count = 0
        try:
            with os.scandir(self.app_state.mods_dir) as entries:
                for entry in entries:
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    folder_path = entry.path
                    folder_name = entry.name
                    config_path = os.path.join(folder_path, MOD_CONFIG_FILENAME)
                    is_corrupted = False
                    if not os.path.exists(config_path):
                        legacy_config_path = os.path.join(folder_path, LEGACY_MOD_CONFIG_FILENAME)
                        if not os.path.exists(legacy_config_path):
                            is_corrupted = True
                            logging.warning(f'_cleanup_corrupted_mods: Missing mod_config.json in {folder_name}, marking as corrupted')
                    else:
                        try:
                            config_size = os.path.getsize(config_path)
                            if config_size == 0:
                                is_corrupted = True
                                logging.warning(f'_cleanup_corrupted_mods: mod_config.json is 0 bytes in {folder_name}, marking as corrupted')
                            else:
                                try:
                                    with open(config_path, 'r', encoding='utf-8') as f:
                                        json.load(f)
                                except (json.JSONDecodeError, OSError, PermissionError) as e:
                                    is_corrupted = True
                                    logging.warning(f'_cleanup_corrupted_mods: Invalid JSON in mod_config.json for {folder_name}: {e}, marking as corrupted')
                        except (OSError, PermissionError) as e:
                            is_corrupted = True
                            logging.warning(f'_cleanup_corrupted_mods: Cannot access mod_config.json in {folder_name}: {e}, marking as corrupted')
                    if is_corrupted:
                        try:
                            from utils.file_utils import safe_rmtree
                            if safe_rmtree(folder_path):
                                removed_count += 1
                                logging.info(f'_cleanup_corrupted_mods: Removed corrupted mod folder: {folder_name}')
                            else:
                                logging.warning(f'_cleanup_corrupted_mods: Failed to remove corrupted mod folder: {folder_name}')
                        except Exception as e:
                            logging.error(f'_cleanup_corrupted_mods: Error removing corrupted mod folder {folder_name}: {e}', exc_info=True)
        except OSError as e:
            logging.error(f'_cleanup_corrupted_mods: Failed to scan mods directory: {e}', exc_info=True)
        if removed_count > 0:
            logging.info(f'_cleanup_corrupted_mods: Removed {removed_count} corrupted mod(s) during startup cleanup')
        return removed_count

    def invalidate_mods_cache(self) -> None:
        with self._cache_lock:
            self._mods_cache_valid = False
            self._mods_by_name.clear()
            self._installed_mods_cache_valid = False

    def _on_scan_completed(self, cache_dict: Dict):
        with self._cache_lock:
            cache = {}
            mods_by_name = {}
            for key, mod_info_dict in cache_dict.items():
                try:
                    effective_key = mod_info_dict.get('key') or mod_info_dict.get('mod_key', key)
                    config_data = mod_info_dict.get('config_data', {})
                    folder_path = mod_info_dict.get('folder_path', '')
                    folder_name = mod_info_dict.get('folder_name', '')
                    config_mtime = mod_info_dict.get('config_mtime', 0.0)
                    if not effective_key:
                        effective_key = config_data.get('key') or config_data.get('mod_key')
                    if not effective_key and (config_data.get('key') or config_data.get('mod_key')) and (config_data.get('key') or config_data.get('mod_key')).startswith('gb_'):
                        effective_key = config_data.get('key') or config_data.get('mod_key')
                        logging.warning(f'_on_scan_completed: Found GameBanana mod with empty effective_key, using {effective_key}')
                        config_data['key'] = effective_key
                        if 'mod_key' in config_data:
                            del config_data['mod_key']
                    elif not effective_key:
                        logging.warning(f'_on_scan_completed: Found mod with empty key in {folder_path}, skipping')
                        continue
                    mod_info = ModFolderInfo(key=effective_key, folder_path=folder_path, folder_name=folder_name, config_data=config_data, config_mtime=config_mtime)
                    cache[effective_key] = mod_info
                    mod_name = config_data.get('name', '')
                    if mod_name:
                        mods_by_name[mod_name.lower()] = effective_key
                except (KeyError, TypeError) as e:
                    logging.warning(f'_on_scan_completed: Error processing mod {key}: {e}', exc_info=True)
                    continue
            self._mods_cache = cache
            self._mods_by_name = mods_by_name
            self._mods_cache_valid = True
            self._scan_in_progress = False
            self._scan_thread = None
            self._fix_duplicate_mod_keys(cache)

    def _fix_duplicate_mod_keys(self, cache: Dict[str, ModFolderInfo]) -> None:
        mods_by_key: Dict[str, List[ModFolderInfo]] = {}
        mods_without_key: List[ModFolderInfo] = []
        for cache_key, mod_info in cache.items():
            key = mod_info.key
            if not key or cache_key.startswith('__no_key_'):
                mods_without_key.append(mod_info)
            else:
                if key not in mods_by_key:
                    mods_by_key[key] = []
                mods_by_key[key].append(mod_info)
        duplicates_found = False
        key_replacements: Dict[str, str] = {}
        for mod_info in mods_without_key:
            if not mod_info.key:
                mod_name = mod_info.config_data.get('name', 'Unknown Mod')
                from utils.file_utils import sanitize_filename
                base_key = f"local_{sanitize_filename(mod_name).lower().replace(' ', '_')}"
                new_key = self._generate_unique_key(base_key, cache, key_replacements)
                old_cache_key = next((k for k, v in cache.items() if v == mod_info), None)
                if old_cache_key:
                    if old_cache_key in cache:
                        del cache[old_cache_key]
                mod_info.key = new_key
                mod_info.config_data['key'] = new_key
                if 'mod_key' in mod_info.config_data:
                    del mod_info.config_data['mod_key']
                cache[new_key] = mod_info
                logging.info(f'_fix_duplicate_mod_keys: Generated key "{new_key}" for mod without key in folder "{mod_info.folder_path}"')
                self._update_key_in_config(mod_info.folder_path, '', new_key)
        for key, mods_list in mods_by_key.items():
            if len(mods_list) > 1:
                duplicates_found = True
                logging.warning(f'_fix_duplicate_mod_keys: Found {len(mods_list)} mods with duplicate key "{key}"')
                mods_list_sorted = sorted(mods_list, key=lambda m: m.folder_path)
                first_mod = mods_list_sorted[0]
                if key not in cache or cache[key] != first_mod:
                    cache[key] = first_mod
                for i, mod_info in enumerate(mods_list_sorted[1:], start=1):
                    new_key = self._generate_unique_mod_key(key, cache, key_replacements)
                    old_key_for_mod = mod_info.key
                    key_replacements[old_key_for_mod] = new_key
                    logging.info(f'_fix_duplicate_mod_keys: Assigning new key "{new_key}" to mod in folder "{mod_info.folder_path}" (was "{old_key_for_mod}")')
                    self._update_key_in_config(mod_info.folder_path, old_key_for_mod, new_key)
                    if old_key_for_mod in cache and cache[old_key_for_mod] == mod_info:
                        del cache[old_key_for_mod]
                    mod_info.key = new_key
                    mod_info.config_data['key'] = new_key
                    if 'mod_key' in mod_info.config_data:
                        del mod_info.config_data['mod_key']
                    cache[new_key] = mod_info
        if duplicates_found and key_replacements:
            self._replace_keys_everywhere(key_replacements)
            self._mods_cache = cache
            logging.info(f'_fix_duplicate_mod_keys: Fixed {len(key_replacements)} duplicate mod key(s)')

    def _generate_unique_key(self, base_key: str, existing_cache: Dict[str, ModFolderInfo], key_replacements: Dict[str, str]) -> str:
        if not base_key:
            base_key = 'local_mod'
        existing_keys = set(existing_cache.keys())
        existing_keys.update(key_replacements.values())
        existing_keys.update(key_replacements.keys())
        unique_key = base_key
        counter = 1
        while unique_key in existing_keys:
            unique_key = f'{base_key}_{counter}'
            counter += 1
            if counter > 10000:
                unique_key = f'{base_key}_{int(time.time())}'
                break
        return unique_key

    def _update_key_in_config(self, folder_path: str, old_key: str, new_key: str) -> None:
        config_path = os.path.join(folder_path, MOD_CONFIG_FILENAME)
        if not os.path.exists(config_path):
            return
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            config_data['key'] = new_key
            if 'mod_key' in config_data:
                del config_data['mod_key']
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=2, ensure_ascii=False)
            logging.info(f'_update_key_in_config: Updated key in "{config_path}" from "{old_key}" to "{new_key}"')
        except (OSError, json.JSONDecodeError) as e:
            logging.warning(f'_update_key_in_config: Failed to update key in "{config_path}": {e}')

    def _replace_keys_everywhere(self, key_replacements: Dict[str, str]) -> None:
        self._replace_keys_in_metadata(key_replacements)
        self._replace_keys_in_settings(key_replacements)

    def _replace_keys_in_metadata(self, key_replacements: Dict[str, str]) -> None:
        if not key_replacements:
            return
        try:
            mods_metadata = self._read_metadata()
            if not mods_metadata:
                return
            metadata_updated = False
            for old_key, new_key in key_replacements.items():
                if old_key in mods_metadata:
                    mods_metadata[new_key] = mods_metadata[old_key]
                    del mods_metadata[old_key]
                    metadata_updated = True
                    logging.info(f'_replace_keys_in_metadata: Replaced key "{old_key}" with "{new_key}" in metadata')
            if metadata_updated:
                self._write_metadata(mods_metadata)
        except Exception as e:
            logging.warning(f'_replace_keys_in_metadata: Failed to replace keys in metadata: {e}', exc_info=True)

    def _replace_keys_in_settings(self, key_replacements: Dict[str, str]) -> None:
        if not key_replacements or not hasattr(self.app_state, 'local_config'):
            return
        try:
            settings_updated = False
            for config_key in list(self.app_state.local_config.keys()):
                if not config_key.startswith('used_mods_'):
                    continue
                used_mods_data = self.app_state.local_config.get(config_key)
                if not isinstance(used_mods_data, dict):
                    continue
                for chapter_id_str, mod_data in list(used_mods_data.items()):
                    replaced = False
                    if isinstance(mod_data, str):
                        if mod_data in key_replacements:
                            used_mods_data[chapter_id_str] = key_replacements[mod_data]
                            replaced = True
                    elif isinstance(mod_data, list):
                        new_list = []
                        for key in mod_data:
                            if key in key_replacements:
                                new_list.append(key_replacements[key])
                                replaced = True
                            else:
                                new_list.append(key)
                        if replaced:
                            used_mods_data[chapter_id_str] = new_list
                    if replaced:
                        settings_updated = True
                        logging.info(f'_replace_keys_in_settings: Replaced keys in "{config_key}" for chapter "{chapter_id_str}"')
            if settings_updated and self.settings_service:
                self.settings_service.write_local_config()
                logging.info('_replace_keys_in_settings: Saved updated settings')
        except Exception as e:
            logging.warning(f'_replace_keys_in_settings: Failed to replace keys in settings: {e}', exc_info=True)

    def _get_mods_cache(self, use_async: bool = False) -> Dict[str, ModFolderInfo]:
        with self._cache_lock:
            if self._mods_cache_valid:
                normalized_cache = self._normalize_mod_cache(self._mods_cache)
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
            self._fix_duplicate_mod_keys(self._mods_cache)
            if hasattr(self, '_temp_mods_by_name'):
                self._mods_by_name = self._temp_mods_by_name.copy()
                del self._temp_mods_by_name
            else:
                self._mods_by_name = {}
            self._mods_cache_valid = True
            return self._mods_cache.copy()

    @staticmethod
    def _check_archive_is_deltamod(item_path: str, item_name: str) -> bool:
        item_lower = item_name.lower()
        try:
            if item_lower.endswith('.zip'):
                with zipfile.ZipFile(item_path, 'r') as zf:
                    return has_deltamod_info_file(zf.namelist())
            elif item_lower.endswith('.tar.gz'):
                import tarfile
                with tarfile.open(item_path, 'r:gz') as tf:
                    return has_deltamod_info_file(tf.getnames())
            elif item_lower.endswith('.rar'):
                import rarfile
                with rarfile.RarFile(item_path, 'r') as rf:
                    return has_deltamod_info_file(rf.namelist())
            elif item_lower.endswith('.7z'):
                import py7zr
                with py7zr.SevenZipFile(item_path, mode='r') as zf:
                    return has_deltamod_info_file(zf.getnames())
        except (OSError, ImportError) as e:
            logging.warning(f'_check_archive_is_deltamod: failed to check {item_name}: {e}', exc_info=True)
        return False

    def convert_legacy_mods(self) -> bool:
        if not os.path.exists(self.app_state.mods_dir):
            return False
        conversion_happened = False
        try:
            for item_name in os.listdir(self.app_state.mods_dir):
                item_path = os.path.join(self.app_state.mods_dir, item_name)
                if os.path.isfile(item_path) and item_name.lower().endswith(('.zip', '.7z', '.rar', '.tar.gz', '.lzma')):
                    try:
                        is_deltamod_archive = self._check_archive_is_deltamod(item_path, item_name)
                        if is_deltamod_archive:
                            self.status_changed.emit(tr('status.deltamod_archive_detected', name=item_name), UI_COLORS['status_info'])
                            QApplication.processEvents()
                            with tempfile.TemporaryDirectory() as temp_dir:
                                shutil.unpack_archive(item_path, temp_dir)
                                content_path = temp_dir
                                contents = os.listdir(temp_dir)
                                if len(contents) == 1 and os.path.isdir(os.path.join(temp_dir, contents[0])):
                                    content_path = os.path.join(temp_dir, contents[0])
                                from adapters.deltamod_adapter import DeltamodConverter
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
                            from adapters.deltamod_adapter import DeltamodConverter
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
        self._cleanup_corrupted_mods()
        if not _skip_conversion:
            conversion_happened = self.convert_legacy_mods()
            if conversion_happened:
                return self.load_local_mods(_skip_conversion=True)
        try:
            cache = self._get_mods_cache(use_async=False)
        except Exception as e:
            logging.error(f'load_local_mods: Failed to get mods cache: {e}', exc_info=True)
            cache = {}
        installed_mods = {}
        try:
            for cache_key, mod_info in cache.items():
                try:
                    config_data = mod_info.config_data
                    if not config_data:
                        continue
                    key = config_data.get('key') or config_data.get('mod_key')
                    if not key and (config_data.get('key') or config_data.get('mod_key')) and (config_data.get('key') or config_data.get('mod_key')).startswith('gb_'):
                        key = config_data.get('key') or config_data.get('mod_key')
                        logging.warning(f'load_local_mods: Found GameBanana mod with empty key, using {key}')
                        config_data['key'] = key
                        if 'mod_key' in config_data:
                            del config_data['mod_key']
                    elif not key:
                        logging.warning('load_local_mods: Found mod with empty key, skipping')
                        continue
                    installed_mods[key] = config_data
                except Exception as e:
                    logging.warning(f'load_local_mods: Error processing mod info from cache (key={cache_key}): {e}', exc_info=True)
                    continue
            installed_gamebanana_by_key = {}
            for key, config_data in installed_mods.items():
                if key and key.startswith('gb_'):
                    installed_gamebanana_by_key[key] = config_data
                    logging.debug(f'load_local_mods: Registered installed GameBanana mod - key={key}')
            updated_count = 0

            def _update_mod_icon(mod, config_data, key):
                mod_folder_path = self.get_mod_folder_path(key)
                if mod_folder_path:
                    if key in installed_mods:
                        config_data = self.get_mod_config(key)
                    config_icon_url = config_data.get('icon_url', '')
                    resolved_icon = resolve_mod_icon(config_data, mod_folder_path)
                    if resolved_icon:
                        mod.icon_url = resolved_icon
                    elif config_icon_url:
                        mod.icon_url = config_icon_url

            for mod in list(self.app_state.all_mods):
                key = mod.key
                if key in installed_mods:
                    _update_mod_icon(mod, installed_mods[key], key)
                    if key and key.startswith('gb_'):
                        updated_count += 1
                elif key and key.startswith('gb_') and (key in installed_gamebanana_by_key):
                    _update_mod_icon(mod, installed_gamebanana_by_key[key], key)
                    updated_count += 1
            logging.debug(f'load_local_mods: Updated {updated_count} existing GameBanana mods in all_mods')

            def _find_mod_by_key(key):
                for mod in self.app_state.all_mods:
                    if (getattr(mod, 'key', None) or getattr(mod, 'mod_key', None)) == key:
                        return mod
                return None

            def _try_update_mod_files(existing_mod, config_data, key, replace_in_list=False):
                if (not hasattr(existing_mod, 'files') or not existing_mod.files) and config_data.get('files'):
                    try:
                        files_data = config_data.get('files', {})
                        if isinstance(files_data, dict) and files_data:
                            new_mod = self.create_mod_object_from_info(config_data, self.app_state.all_mods)
                            if replace_in_list:
                                for i, mod in enumerate(self.app_state.all_mods):
                                    if (getattr(mod, 'key', None) or getattr(mod, 'mod_key', None)) == key:
                                        self.app_state.all_mods[i] = new_mod
                                        break
                            elif hasattr(new_mod, 'files') and new_mod.files:
                                existing_mod.files = new_mod.files
                        else:
                            logging.debug(f'load_local_mods: Skipping mod {key} with empty/invalid files data')
                    except Exception as e:
                        logging.warning(f'load_local_mods: Failed to load files for mod {key}: {e}', exc_info=True)

            existing_keys = {getattr(mod, 'key', None) or getattr(mod, 'mod_key', None) for mod in self.app_state.all_mods}
            for key, config_data in list(installed_mods.items()):
                if key and isinstance(key, str) and key.startswith('local_'):
                    continue
                if key and key.startswith('gb_'):
                    if key in existing_keys:
                        existing_mod = _find_mod_by_key(key)
                        if existing_mod:
                            _try_update_mod_files(existing_mod, config_data, key)
                    continue
                if key in existing_keys:
                    existing_mod = _find_mod_by_key(key)
                    if existing_mod:
                        _try_update_mod_files(existing_mod, config_data, key, replace_in_list=True)
                    continue
                try:
                    mod_folder_path = self.get_mod_folder_path(key)
                    icon_url = config_data.get('icon_url', '')
                    if icon_url and (not icon_url.startswith(('http://', 'https://'))) and mod_folder_path:
                        if not os.path.isabs(icon_url):
                            resolved_relative = os.path.normpath(os.path.join(mod_folder_path, icon_url))
                            if os.path.exists(resolved_relative) and os.path.isfile(resolved_relative):
                                icon_url = resolved_relative
                    if not icon_url and mod_folder_path:
                        resolved_icon = resolve_mod_icon(config_data, mod_folder_path)
                        if resolved_icon:
                            icon_url = resolved_icon
                    if key and key.startswith('gb_') and (not icon_url):
                        try:
                            from adapters.gamebanana_adapter import GameBananaAPI
                            api = GameBananaAPI()
                            mod_id = int(key.replace('gb_', '', 1))
                            preview_media = api.get_mod_preview_media(mod_id)
                            if preview_media:
                                icon_url_from_api = api.extract_icon_url(preview_media)
                                if icon_url_from_api:
                                    icon_url = icon_url_from_api
                                    logging.debug(f'Loaded icon_url from API for GameBanana mod {mod_id}: {icon_url_from_api}')
                                    config_data['icon_url'] = icon_url
                                    from utils.file_utils import atomic_write_json
                                    config_path = os.path.join(mod_folder_path, MOD_CONFIG_FILENAME)
                                    atomic_write_json(config_path, config_data, indent=2)
                        except Exception as e:
                            key = getattr(mod, 'key', None) or getattr(mod, 'mod_key', None)
                            gb_mod_id = key.replace('gb_', '', 1) if key and key.startswith('gb_') else 'unknown'
                            logging.debug(f'Failed to load icon_url for GameBanana mod {gb_mod_id}: {e}')
                    tags = config_data.get('tags', [])
                    if not isinstance(tags, list):
                        tags = [tags] if tags else []
                    safe_mod_info = {'key': key, 'name': config_data.get('name', 'Installed Mod'), 'version': config_data.get('version', '1.0.0'), 'author': config_data.get('author', tr('defaults.unknown')), 'tagline': config_data.get('tagline', tr('defaults.no_description')), 'game_version': config_data.get('game_version', tr('defaults.not_specified')), 'description_url': '', 'downloads': 0, 'game': config_data.get('game') or config_data.get('modgame', 'deltarune'), 'is_verified': False, 'icon_url': icon_url, 'tags': tags, 'hide_mod': False, 'ban_status': False, 'demo_url': None, 'demo_version': '1.0.0', 'created_date': config_data.get('created_date', 'N/A'), 'last_updated': config_data.get('created_date', 'N/A'), 'external_url': config_data.get('external_url')}
                    mod = mod_models.ModInfo(**safe_mod_info)
                    files_data = config_data.get('files', {})
                    if not isinstance(files_data, dict):
                        logging.warning(f'load_local_mods: Invalid files_data type for mod {key}, expected dict, got {type(files_data).__name__}')
                        files_data = {}
                    try:
                        for file_key, ch_info in list(files_data.items()):
                            if not isinstance(ch_info, dict):
                                logging.debug(f'load_local_mods: Skipping invalid chapter info for mod {key}, file_key={file_key}')
                                continue
                            try:
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
                            except Exception as e:
                                logging.warning(f'load_local_mods: Failed to process chapter data for mod {key}, file_key={file_key}: {e}', exc_info=True)
                                continue
                    except Exception as e:
                        logging.warning(f'load_local_mods: Error processing files_data for mod {key}: {e}', exc_info=True)
                    if mod.files:
                        self.app_state.append_mod(mod)
                    else:
                        logging.debug(f'Skipping mod {key} ({mod.name}): game={mod.game}, has_files={bool(mod.files)}')
                except Exception as e:
                    logging.warning(f'Failed to create ModInfo for installed mod {key}: {e}', exc_info=True)
            all_mods_filtered = []
            for mod in self.app_state.all_mods:
                all_mods_filtered.append(mod)
            self.app_state.all_mods = all_mods_filtered
            existing_gamebanana_ids = set()
            for mod in self.app_state.all_mods:
                mod_key_attr = getattr(mod, 'key', None) or getattr(mod, 'mod_key', None)
                if mod_key_attr and mod_key_attr.startswith('gb_'):
                    gb_id = mod_key_attr.replace('gb_', '', 1)
                    if gb_id:
                        existing_gamebanana_ids.add(str(gb_id))
            for key, config_data in list(installed_mods.items()):
                if config_data.get('is_gamebanana_mod'):
                    gb_id = key.replace('gb_', '', 1) if key and key.startswith('gb_') else None
                    if gb_id:
                        gb_id_str = str(gb_id)
                        if gb_id_str in existing_gamebanana_ids:
                            continue
                    continue
                is_local_key = key and isinstance(key, str) and key.startswith('local_')
                if not is_local_key:
                    continue
                if key in existing_keys:
                    logging.debug(f'load_local_mods: Skipping local mod {key} - already in all_mods')
                    continue
                try:
                    mod_info_from_cache = cache.get(key)
                    if mod_info_from_cache and hasattr(mod_info_from_cache, 'folder_path'):
                        mod_folder_path = mod_info_from_cache.folder_path
                    else:
                        mod_folder_path = self.get_mod_folder_path(key)
                    mod_folder_for_icon = mod_folder_path or self.get_mod_folder_path(key)
                    icon_url_from_config = config_data.get('icon_url', '')
                    icon_url = ''
                    if icon_url_from_config and (not icon_url_from_config.startswith(('http://', 'https://'))) and mod_folder_for_icon:
                        if not os.path.isabs(icon_url_from_config):
                            resolved_relative = os.path.normpath(os.path.join(mod_folder_for_icon, icon_url_from_config))
                            if os.path.exists(resolved_relative) and os.path.isfile(resolved_relative):
                                icon_url = resolved_relative
                        else:
                            icon_url = icon_url_from_config
                    if not icon_url and mod_folder_for_icon:
                        resolved_icon = resolve_mod_icon(config_data, mod_folder_for_icon)
                        if resolved_icon:
                            icon_url = resolved_icon
                    safe_mod_info = {'key': key, 'name': config_data.get('name', tr('defaults.local_mod')), 'version': config_data.get('version', '1.0.0'), 'author': config_data.get('author', tr('defaults.unknown')), 'tagline': config_data.get('tagline', tr('defaults.no_description')), 'game_version': config_data.get('game_version', tr('defaults.not_specified')), 'description_url': '', 'downloads': 0, 'game': config_data.get('game') or config_data.get('modgame', 'deltarune'), 'is_verified': False, 'icon_url': icon_url, 'tags': ['local'], 'hide_mod': False, 'ban_status': False, 'demo_url': None, 'demo_version': '1.0.0', 'created_date': config_data.get('created_date', 'N/A'), 'last_updated': config_data.get('created_date', 'N/A'), 'external_url': config_data.get('external_url')}
                    mod = mod_models.ModInfo(**safe_mod_info)
                    files_data = config_data.get('files', {})
                    if not isinstance(files_data, dict):
                        logging.warning(f'load_local_mods: files_data is not a dict for mod {key}, skipping files processing')
                        files_data = {}
                    for file_key, ch_info in list(files_data.items()):
                        if not isinstance(ch_info, dict):
                            logging.warning(f'load_local_mods: ch_info is not a dict for mod {key}, file_key={file_key}, skipping')
                            continue
                        chapter_files = ch_info
                        chapter_folder = None
                        if mod_folder_path:
                            if file_key == 'demo':
                                chapter_folder = os.path.join(mod_folder_path, 'demo')
                            elif file_key == 'undertale':
                                chapter_folder = os.path.join(mod_folder_path, 'undertale')
                            elif file_key in ['0', '1', '2', '3', '4']:
                                chapter_id = int(file_key)
                                from utils.file_utils import get_chapter_folder_name
                                folder_name = get_chapter_folder_name(chapter_id, config_data.get('game') or config_data.get('modgame'))
                                chapter_folder = os.path.join(mod_folder_path, folder_name)
                            else:
                                try:
                                    ch_id = int(file_key)
                                    from utils.file_utils import get_chapter_folder_name
                                    folder_name = get_chapter_folder_name(ch_id, game=config_data.get('game') or config_data.get('modgame'))
                                    chapter_folder = os.path.join(mod_folder_path, folder_name)
                                except ValueError:
                                    continue
                        data_file_url = ''
                        if chapter_files.get('data_file_url') and mod_folder_path and chapter_folder:
                            data_file_url = os.path.join(chapter_folder, chapter_files['data_file_url'])
                        from models.mod_models import ModExtraFile
                        extra_files = []
                        if chapter_files.get('extra_files') and mod_folder_path:
                            extra_files_data = chapter_files['extra_files']
                            if isinstance(extra_files_data, dict):
                                if chapter_folder:
                                    for group_key, filenames in list(extra_files_data.items()):
                                        if isinstance(filenames, list):
                                            for filename in filenames:
                                                file_path = os.path.join(chapter_folder, filename)
                                                extra_files.append(ModExtraFile(key=group_key, url=file_path, version='1.0.0'))
                            elif isinstance(extra_files_data, list):
                                for ef_data in extra_files_data:
                                    if isinstance(ef_data, dict):
                                        url = ef_data.get('url', '')
                                        if url and (not os.path.isabs(url)) and chapter_folder:
                                            url = os.path.join(chapter_folder, url)
                                        extra_files.append(ModExtraFile(key=ef_data.get('key', ''), url=url, version=ef_data.get('version', '1.0.0')))
                                    elif isinstance(ef_data, ModExtraFile):
                                        extra_files.append(ef_data)
                        mod_chapter = ModChapterData(description=config_data.get('tagline', ''), data_file_url=data_file_url, data_file_version=chapter_files.get('data_file_version', (ch_info.get('versions', {}) or {}).get('data', '1.0.0')), extra_files=extra_files)
                        mod.files[file_key] = mod_chapter
                    if mod.files:
                        self.app_state.append_mod(mod)
                    else:
                        logging.debug(f'Skipping mod {key} ({mod.name}): game={mod.game}, has_files={bool(mod.files)}')
                except Exception as e:
                    logging.warning(f'Failed to build local ModInfo: {e}')
                    continue
            installed_gamebanana_mod_keys = set()
            for key, config_data in installed_mods.items():
                if key and key.startswith('gb_'):
                    installed_gamebanana_mod_keys.add(key)
            for mod in self.app_state.all_mods:
                mod_key_attr = getattr(mod, 'key', None) or getattr(mod, 'mod_key', None)
                if mod_key_attr and mod_key_attr.startswith('gb_') and (mod_key_attr in installed_gamebanana_mod_keys):
                    current_downloads = getattr(mod, 'downloads', 0) or 0
                    if current_downloads <= 0:
                        try:
                            from adapters.gamebanana_adapter import GameBananaAPI
                            api = GameBananaAPI()
                            mod_id = int(mod_key_attr.replace('gb_', '', 1)) if mod_key_attr and mod_key_attr.startswith('gb_') else None
                            if mod_id:
                                downloaded_count = api.get_mod_downloads_only(mod_id)
                                if downloaded_count is not None and downloaded_count > 0:
                                    mod.downloads = downloaded_count
                                elif downloaded_count is not None:
                                    mod.downloads = 0
                        except Exception as e:
                            key_attr = getattr(mod, 'key', None) or getattr(mod, 'mod_key', None)
                            logging.debug(f'load_local_mods: Failed to load downloads from API for mod {key_attr}: {e}')
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
            self.cleanup_stale_used_mods()
            return True
        except Exception as e:
            logging.error(f'load_local_mods failed: {e}', exc_info=True)
            return False

    def get_mod_config(self, key: str) -> dict:
        cache = self._get_mods_cache()
        mod_info = cache.get(key)
        if mod_info:
            return mod_info.config_data.copy()
        return {}

    def get_mod_folder_path(self, key: str) -> str:
        cache = self._get_mods_cache()
        mod_info = cache.get(key)
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
            key = getattr(mod_info, 'key', None) or getattr(mod_info, 'mod_key', None)
            mod_id = int(key.replace('gb_', '', 1)) if key and key.startswith('gb_') else None
            if not mod_id:
                return None
            external_url = getattr(mod_info, 'external_url', None)
            compat = api.get_supported_files_for_mod(int(mod_id), external_url=external_url)
            files = compat.get('supported_files') or []
            if files:
                mod_info.gamebanana_supported_files = files
                mod_info.gamebanana_is_tool_compatible = compat.get('has_supported_files', False)
                mod_info.gamebanana_compatibility_checked = compat.get('compatibility_checked', False)
                return files[0]
        except Exception as e:
            key = getattr(mod_info, 'key', None) or getattr(mod_info, 'mod_key', None) or 'unknown'
            logging.warning(f'ModManager: Failed to resolve GameBanana file for mod {key}: {e}')
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
        url_install_thread.unrar_needed.connect(self._on_unrar_needed)
        url_install_thread.manual_install_required.connect(self._on_manual_install_required)
        self.app_state.current_task = url_install_thread
        url_install_thread.start()

    def _on_unrar_needed(self):
        try:
            from utils.archive_utils import prompt_for_unrar_install
            worker = self.app_state.current_task
            success = prompt_for_unrar_install(parent_widget=self.parent())
            if success:
                logging.info('UnRAR installed successfully from mod manager worker request')
            else:
                logging.info('User declined UnRAR installation from mod manager worker request')
            if worker and hasattr(worker, 'signal_unrar_installed'):
                worker.signal_unrar_installed(success)
        except Exception as e:
            logging.error(f'ModManager: Error handling UnRAR installation request: {e}')
            if self.app_state.current_task and hasattr(self.app_state.current_task, 'signal_unrar_installed'):
                self.app_state.current_task.signal_unrar_installed(False)

    def _on_manual_install_required(self, prepared_path: str, archive_path: str, temp_dir: str):
        try:
            from services.localization_service import tr
            self.app_state.is_installing = False
            self.status_changed.emit(tr('status.ready'), 'status_info')
            parent = self.parent()
            msg_box = QMessageBox(parent)
            msg_box.setIcon(QMessageBox.Icon.Information)
            msg_box.setWindowTitle(tr('errors.mod_not_compatible_title'))
            msg_box.setText(tr('errors.mod_requires_manual_installation'))
            msg_box.setInformativeText(tr('dialogs.manual_install_available'))
            manual_install_btn = msg_box.addButton(tr('ui.manual_install'), QMessageBox.ButtonRole.AcceptRole)
            msg_box.addButton(tr('buttons.close'), QMessageBox.ButtonRole.RejectRole)
            msg_box.setDefaultButton(manual_install_btn)
            msg_box.exec()
            if msg_box.clickedButton() != manual_install_btn:
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except Exception:
                    pass
                return
            from ui.dialogs.manual_install_dialog import ManualModInstallDialog
            from services.game_detection_service import get_game_type_string
            initial_game_type = None
            if hasattr(parent, 'app_state') and parent.app_state and hasattr(parent.app_state, 'game_mode'):
                initial_game_type = get_game_type_string(parent.app_state.game_mode)
            dialog = ManualModInstallDialog(parent, prepared_path, gamebanana_metadata=None, source_file_path=archive_path, initial_game_type=initial_game_type)
            dialog.temp_dir_to_cleanup = temp_dir
            if dialog.exec() == QDialog.DialogCode.Accepted:
                from ui.utils.ui_utils import refresh_ui_after_mod_install
                refresh_ui_after_mod_install(parent, self)
                QMessageBox.information(parent, tr('dialogs.success'), tr('dialogs.mod_created_successfully'))
        except Exception as e:
            logging.error(f'ModManager: Error handling manual install request: {e}', exc_info=True)
            if hasattr(self.parent(), 'feedback_service'):
                self.parent().feedback_service.show_message('error', tr('errors.error'), tr('errors.manual_install_failed', error=str(e)))
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass

    def uninstall_mod(self, mod):
        try:
            self.delete_mod_files(mod)
            self.app_state.is_installing = False
            self.mod_list_updated.emit()
            self.status_changed.emit(tr('status.mod_uninstalled'), 'status_success')
        except PermissionError as e:
            key = get_mod_key(mod) or 'unknown'
            mod_name = get_mod_name(mod, 'Unknown Mod')
            error = ModUninstallationError(f'Permission denied during uninstallation: {e}', key=key, mod_name=mod_name, reason='permission_error')
            logging.error(f'uninstall_mod: permission error: {e}', exc_info=True, extra={'key': key, 'mod_name': mod_name})
            self.feedback_service.show_message('error', 'errors.uninstall_failed', tr('errors.permission_denied'))
            raise error
        except (OSError, shutil.Error) as e:
            key = get_mod_key(mod) or 'unknown'
            mod_name = get_mod_name(mod, 'Unknown Mod')
            error = ModUninstallationError(f'File operation failed during uninstallation: {e}', key=key, mod_name=mod_name, reason='io_error')
            logging.error(f'uninstall_mod: file operation error: {e}', exc_info=True, extra={'key': key, 'mod_name': mod_name})
            self.feedback_service.show_message('error', 'errors.uninstall_failed', tr('errors.file_operation_failed', error=str(e)))
            raise error
        except (KeyError, AttributeError) as e:
            key = get_mod_key(mod) or 'unknown'
            mod_name = get_mod_name(mod, 'Unknown Mod')
            error = ModUninstallationError(f'Missing required data: {e}', key=key, mod_name=mod_name, reason='missing_data')
            logging.error(f'uninstall_mod: data error: {e}', exc_info=True, extra={'key': key, 'mod_name': mod_name})
            raise error
        except Exception as e:
            key = get_mod_key(mod) or 'unknown'
            mod_name = get_mod_name(mod, 'Unknown Mod')
            error = ModUninstallationError(f'Unexpected error during uninstallation: {e}', key=key, mod_name=mod_name, reason='unknown')
            logging.error(f'uninstall_mod: unexpected error: {e}', exc_info=True, extra={'key': key, 'mod_name': mod_name})
            self.feedback_service.show_message('error', 'errors.uninstall_failed', str(e))
            raise error

    def update_mod(self, mod_data):
        if self.app_state.is_installing:
            return
        parent = self.parent()
        mod_ops = getattr(parent, 'mod_ops', None) if parent else None
        if mod_ops:
            mod_ops.install_mod(mod_data, force=True, is_update=True)

    def _try_delete_folder(self, folder_path: str, label: str) -> bool:
        from utils.file_utils import safe_rmtree
        if not folder_path or not os.path.exists(folder_path):
            return False
        logging.info(f'delete_mod_files: Deleting mod folder by {label}: {folder_path}')
        try:
            if safe_rmtree(folder_path):
                self.invalidate_mods_cache()
                logging.info(f'delete_mod_files: Successfully deleted mod folder by {label}: {folder_path}')
                return True
            logging.warning(f'delete_mod_files: safe_rmtree returned False for {folder_path}')
        except Exception as e:
            logging.error(f'delete_mod_files: Failed to delete folder {folder_path}: {e}', exc_info=True)
            raise
        return False

    def delete_mod_files(self, mod_data):
        try:
            from utils.mod_utils import get_mod_key, get_mod_name
            folder_path = None
            if hasattr(mod_data, 'folder_path'):
                folder_path = mod_data.folder_path
            elif isinstance(mod_data, dict) and 'folder_path' in mod_data:
                folder_path = mod_data['folder_path']
            key = get_mod_key(mod_data)
            mod_name = get_mod_name(mod_data)
            logging.info(f'delete_mod_files: key = {key}, mod_name={mod_name}, folder_path={folder_path}, type={type(mod_data)}')
            if self._try_delete_folder(folder_path, 'folder_path'):
                return
            if key and self._try_delete_folder(self.get_mod_folder_path(key), 'get_mod_folder_path'):
                return
            if mod_name and self._try_delete_folder(os.path.join(self.app_state.mods_dir, mod_name), 'mod_name'):
                return
            if not key:
                logging.error('delete_mod_files: Cannot determine key or folder_path for mod_data')
                return
            logging.info(f'delete_mod_files: Attempting to delete mod with key: {key}')
            cache = self._get_mods_cache()
            mod_info = cache.get(key)
            if not mod_info:
                logging.warning(f'delete_mod_files: Mod with key {key} not found in cache. Cache has {len(cache)} entries.')
                cache_keys = list(cache.keys())[:10]
                logging.info(f'delete_mod_files: Cache keys (first 10): {cache_keys}')
                from utils.mod_utils import get_mod_name
                mod_name = get_mod_name(mod_data)
                if mod_name:
                    logging.info(f'delete_mod_files: Trying to find mod by name: {mod_name}')
                    with self._cache_lock:
                        mod_key_from_name = self._mods_by_name.get(mod_name.lower())
                        if mod_key_from_name and mod_key_from_name in cache:
                            mod_info = cache[mod_key_from_name]
                            key = mod_key_from_name
                            logging.info(f'delete_mod_files: Found mod by name mapping: {mod_name} -> {mod_key_from_name}')
                    if not mod_info:
                        for cached_key, cached_info in cache.items():
                            cached_folder_name = cached_info.folder_name if hasattr(cached_info, 'folder_name') else cached_info.get('folder_name') if isinstance(cached_info, dict) else None
                            if cached_folder_name == mod_name:
                                mod_info = cached_info
                                key = cached_key
                                logging.info(f'delete_mod_files: Found mod by folder name: {mod_name}, key: {cached_key}')
                                break
                    if not mod_info:
                        for cached_key, cached_info in cache.items():
                            config_data = cached_info.config_data if hasattr(cached_info, 'config_data') else cached_info.get('config_data', {}) if isinstance(cached_info, dict) else {}
                            config_name = config_data.get('name', '')
                            if config_name == mod_name:
                                mod_info = cached_info
                                key = cached_key
                                logging.info(f'delete_mod_files: Found mod by config name: {mod_name}, key: {cached_key}')
                                break
                    if not mod_info:
                        fallback_path = None
                        if hasattr(mod_data, 'folder_path'):
                            fallback_path = mod_data.folder_path
                        elif isinstance(mod_data, dict) and 'folder_path' in mod_data:
                            fallback_path = mod_data['folder_path']
                        else:
                            fallback_path = os.path.join(self.app_state.mods_dir, mod_name)
                        if self._try_delete_folder(fallback_path, 'fallback_path'):
                            return
                if not mod_info:
                    if self._try_delete_folder(os.path.join(self.app_state.mods_dir, key), 'key_as_folder'):
                        return
                if not mod_info and mod_name:
                    if self._try_delete_folder(os.path.join(self.app_state.mods_dir, mod_name), 'mod_name_last_resort'):
                        return
                if not mod_info:
                    logging.error(f"delete_mod_files: Cannot delete mod - not found in cache and folder paths do not exist. key = {key}, mod_name={(mod_name if mod_name else 'None')}")
                    return
            self._try_delete_folder(mod_info.folder_path, 'cache_info')
            self.invalidate_mods_cache()
        except Exception as e:
            logging.error(f'delete_mod_files: cleanup failed: {e}', exc_info=True)
            raise

    def get_mod_status(self, mod: mod_models.ModInfo, chapter_id: int) -> str:
        if mod.is_gamebanana_mod():
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
        cache = self._get_mods_cache()
        key = getattr(mod, 'key', None) or getattr(mod, 'mod_key', None)
        mod_info = cache.get(key)
        if not mod_info:
            return 'install'
        remote_versions = _collect_remote_versions(mod, chapter_id)
        if not remote_versions:
            return 'n/a'
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
            for chapter_id in range(5):
                if self.mod_has_files_for_chapter(mod_data, chapter_id):
                    if self.get_mod_status(mod_data, chapter_id) == 'update':
                        return True
            return False
        except Exception as e:
            logging.warning(f'mod_has_update_available: exception: {e}', exc_info=True)
            return False

    def is_mod_installed(self, key: str) -> bool:
        with self._cache_lock:
            if not self._mods_cache_valid:
                self._get_mods_cache()
            return key in self._mods_cache

    def check_mod_exists(self, mod_info):
        cache = self._get_mods_cache()
        key = mod_info.get('key') or mod_info.get('mod_key', '')
        if key and key in cache:
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
            key = get_mod_key(mod_data)
            if not key:
                return True
            cache = self._get_mods_cache()
            mod_info = cache.get(key)
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
                from utils.file_utils import load_json
                return load_json(self.app_state.mods_metadata_path, migrate_config=False) or {}
            except Exception as e:
                logging.warning(f'_read_metadata: failed: {e}', exc_info=True)
                return {}

    def _write_metadata(self, data: Dict):
        with self.app_state._mods_metadata_lock:
            try:
                from utils.file_utils import save_json
                save_json(self.app_state.mods_metadata_path, data, indent=2)
            except Exception as e:
                logging.error(f'_write_metadata: failed: {e}', exc_info=True)

    def _on_url_install_finished(self, success: bool, message: str):
        self.app_state.is_installing = False
        self.app_state.clear_current_task()
        if success:
            self.invalidate_mods_cache()
            self.load_local_mods()
            self.mod_list_updated.emit()
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
        key = mod_info.get('key') or mod_info.get('mod_key', '')
        if all_mods:
            for mod in all_mods:
                mod_key_attr = getattr(mod, 'key', None) or getattr(mod, 'mod_key', None)
                if mod_key_attr == key:
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

    def _iter_mod_configs(self):
        from utils.file_utils import migrate_mod_config, load_json
        if not os.path.exists(self.app_state.mods_dir):
            return
        for folder_name in os.listdir(self.app_state.mods_dir):
            folder_path = os.path.join(self.app_state.mods_dir, folder_name)
            if not os.path.isdir(folder_path):
                continue
            migrate_mod_config(folder_path)
            config_path = os.path.join(folder_path, MOD_CONFIG_FILENAME)
            if not os.path.exists(config_path):
                continue
            try:
                config_data = load_json(config_path, migrate_config=True)
                if config_data and isinstance(config_data, dict):
                    yield folder_name, folder_path, config_path, config_data
            except Exception as e:
                logging.warning(f'_iter_mod_configs: failed to read {config_path}: {e}', exc_info=True)

    def migrate_metadata_from_local_configs(self) -> bool:
        mods_metadata = self._read_metadata()
        updated = False
        for folder_name, folder_path, config_path, config_data in self._iter_mod_configs():
            try:
                key = config_data.get('key') or config_data.get('mod_key')
                if not key:
                    continue
                if 'installed_date' in config_data or 'added_date' in config_data or 'is_available_on_server' in config_data:
                    if key not in mods_metadata:
                        mods_metadata[key] = {}
                    if 'installed_date' in config_data:
                        mods_metadata[key]['added_date'] = config_data.pop('installed_date')
                    elif 'added_date' in config_data:
                        mods_metadata[key]['added_date'] = config_data.pop('added_date')
                    if 'is_available_on_server' in config_data:
                        mods_metadata[key]['is_available_on_server'] = config_data.pop('is_available_on_server')
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
        cache_snapshot: Optional[Dict[str, ModFolderInfo]] = None
        with self._cache_lock:
            if self._mods_cache_valid and self._mods_cache:
                cache_snapshot = dict(self._mods_cache)
        mods_metadata = self._read_metadata()
        metadata_updated = False
        found_mod_keys: Set[str] = set()

        def _append_from_config(config_data: dict, folder_name: str) -> None:
            nonlocal metadata_updated
            if not config_data:
                return
            key = config_data.get('key') or config_data.get('mod_key')
            if not key:
                return
            found_mod_keys.add(key)
            mod_meta = mods_metadata.get(key)
            if not mod_meta:
                is_gamebanana = key and isinstance(key, str) and key.startswith('gb_')
                mods_metadata[key] = {'added_date': time.strftime('%Y-%m-%d %H:%M:%S'), 'is_gamebanana': is_gamebanana}
                metadata_updated = True
                mod_meta = mods_metadata[key]
            cfg = dict(config_data)
            mod_folder_path = os.path.join(self.app_state.mods_dir, folder_name) if folder_name else ''
            if mod_folder_path:
                resolved_icon = resolve_mod_icon(cfg, mod_folder_path)
                if resolved_icon:
                    cfg['icon_url'] = resolved_icon
            if 'game' not in cfg and 'modgame' in cfg:
                cfg['game'] = cfg.pop('modgame')
            elif 'game' not in cfg:
                cfg['game'] = 'deltarune'
            if 'key' not in cfg and 'mod_key' in cfg:
                cfg['key'] = cfg.pop('mod_key')
            cfg['added_date'] = mod_meta.get('added_date')
            cfg['folder_name'] = folder_name
            installed_mods.append(cfg)
        if cache_snapshot is not None:
            for cache_key, info in cache_snapshot.items():
                try:
                    if isinstance(info, ModFolderInfo):
                        config_data = info.config_data or {}
                        folder_name = info.folder_name
                    elif isinstance(info, dict):
                        config_data = info.get('config_data', {}) or {}
                        folder_name = info.get('folder_name', '')
                    else:
                        continue
                    _append_from_config(config_data, folder_name)
                except Exception as e:
                    config_key = config_data.get('key') or config_data.get('mod_key', '') if 'config_data' in locals() else cache_key
                    logging.warning(f'Failed to build installed mod from cache for key {config_key}: {e}', exc_info=True)
        else:
            for folder_name, folder_path, config_path, config_data in self._iter_mod_configs():
                _append_from_config(config_data, folder_name)
        orphaned_keys = set(mods_metadata.keys()) - found_mod_keys
        if orphaned_keys:
            for key in list(orphaned_keys):
                del mods_metadata[key]
            metadata_updated = True
        if metadata_updated:
            self._write_metadata(mods_metadata)
        with self._cache_lock:
            self._installed_mods_cache = list(installed_mods)
            self._installed_mods_cache_valid = True
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
