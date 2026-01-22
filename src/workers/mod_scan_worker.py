import os
import json
import logging
from PyQt6.QtCore import QThread, pyqtSignal
from config.constants import MOD_CONFIG_FILENAME


class ModScanThread(QThread):
    scan_completed = pyqtSignal(dict)

    def __init__(self, mods_dir: str, parent=None, cache_dir: str = None):
        super().__init__(parent)
        self.mods_dir = mods_dir
        self._cancel_flag = False
        self.cache_dir = cache_dir
        self.cache_file = None
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)
            self.cache_file = os.path.join(cache_dir, 'mod_config_cache.json')

    def cancel(self):
        self._cancel_flag = True

    def _load_cache(self) -> dict:
        if not self.cache_file or not os.path.exists(self.cache_file):
            return {}
        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            cache = {}
            for cache_key, info in cache_data.items():
                if isinstance(info, dict) and 'config_mtime' in info and ('config_data' in info):
                    cache[cache_key] = info
            return cache
        except (json.JSONDecodeError, OSError, PermissionError, KeyError) as e:
            logging.debug(f'ModScanThread: Failed to load cache from {self.cache_file}: {e}')
            return {}

    def _save_cache(self, cache: dict):
        if not self.cache_file:
            return
        try:
            cache_to_save = {}
            for cache_key, info in cache.items():
                if isinstance(info, dict):
                    cache_to_save[cache_key] = {'key': info.get('key') or info.get('mod_key', cache_key), 'config_mtime': info.get('config_mtime', 0), 'config_data': info.get('config_data', {}), 'folder_path': info.get('folder_path', ''), 'folder_name': info.get('folder_name', '')}
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_to_save, f, indent=2, ensure_ascii=False)
        except (OSError, PermissionError, TypeError) as e:
            logging.debug(f'ModScanThread: Failed to save cache to {self.cache_file}: {e}')

    def run(self):
        try:
            if self.parent() and hasattr(self.parent(), 'app_state'):
                app_state = self.parent().app_state
                if hasattr(app_state, '_scan_blocked') and app_state._scan_blocked:
                    logging.debug('ModScanThread: Scan blocked during installation, returning empty cache')
                    self.scan_completed.emit({})
                    return
        except Exception as e:
            logging.debug(f'ModScanThread: Could not check scan block status: {e}')
        disk_cache = {}
        cache = {}
        try:
            disk_cache = self._load_cache()
        except Exception as e:
            logging.warning(f'ModScanThread: Failed to load cache: {e}', exc_info=True)
        if not os.path.exists(self.mods_dir):
            self.scan_completed.emit(cache)
            return
        try:
            with os.scandir(self.mods_dir) as entries:
                for entry in entries:
                    if self._cancel_flag:
                        break
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    folder_name = entry.name
                    folder_path = entry.path
                    try:
                        from utils.file_utils import migrate_mod_config
                        migrate_mod_config(folder_path)
                    except Exception:
                        logging.warning(f'ModScanThread: failed to migrate mod config in {folder_path}')
                    config_path = os.path.join(folder_path, MOD_CONFIG_FILENAME)
                    if not os.path.exists(config_path):
                        continue
                    try:
                        config_size = os.path.getsize(config_path)
                        if config_size == 0:
                            logging.warning(f'ModScanThread: Corrupted config detected (0 bytes) in {config_path}, skipping mod')
                            continue
                        config_mtime = os.path.getmtime(config_path)
                        key = None
                        config_data = None
                        if folder_path in [info.get('folder_path') for info in disk_cache.values()]:
                            cached_entry = next((info for info in disk_cache.values() if info.get('folder_path') == folder_path), None)
                            if cached_entry and cached_entry.get('config_mtime', 0) >= config_mtime:
                                key = cached_entry.get('key') or cached_entry.get('mod_key') or cached_entry.get('config_data', {}).get('key') or cached_entry.get('config_data', {}).get('mod_key')
                                if not key:
                                    for cache_key, cache_info in disk_cache.items():
                                        if cache_info.get('folder_path') == folder_path:
                                            key = cache_key
                                            break
                                if key:
                                    if 'key' not in cached_entry:
                                        cached_entry['key'] = key
                                    if 'mod_key' in cached_entry:
                                        del cached_entry['mod_key']
                                    cache[key] = cached_entry
                                    continue
                        with open(config_path, 'r', encoding='utf-8') as f:
                            config_data = json.load(f)
                        key = config_data.get('key') or config_data.get('mod_key')
                        if not key:
                            continue
                        if key in cache:
                            existing_info = cache[key]
                            if config_mtime <= existing_info.get('config_mtime', 0):
                                continue
                        mod_info = {'key': key, 'folder_path': folder_path, 'folder_name': folder_name, 'config_data': config_data, 'config_mtime': config_mtime}
                        cache[key] = mod_info
                    except (OSError, PermissionError):
                        logging.warning(f'ModScanThread: Corrupted config detected (failed to access) in {config_path}')
                        continue
                    except json.JSONDecodeError:
                        logging.warning(f'ModScanThread: Corrupted config detected (invalid JSON) in {config_path}')
                        continue
                    except KeyError:
                        logging.debug(f'ModScanThread: missing key in {config_path}')
                        continue
                    except Exception:
                        logging.error(f'ModScanThread: Corrupted config detected (unexpected error) in {folder_path}')
                        continue
        except OSError:
            logging.error(f'ModScanThread: failed to list directory {self.mods_dir}')
        except Exception:
            pass
        try:
            self._save_cache(cache)
        except Exception as e:
            logging.warning(f'ModScanThread: Failed to save cache: {e}', exc_info=True)
        try:
            self.scan_completed.emit(cache)
        except Exception as e:
            logging.error(f'ModScanThread: Failed to emit scan_completed signal: {e}', exc_info=True)
