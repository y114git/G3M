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
from utils.file_utils import sanitize_filename
from utils.mod_utils import get_mod_key, get_mod_name
from config.constants import UI_COLORS
import requests
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
        if not os.path.exists(self.app_state.mods_dir):
            return cache
        try:
            with os.scandir(self.app_state.mods_dir) as entries:
                for entry in entries:
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    folder_name = entry.name
                    folder_path = entry.path
                    config_path = os.path.join(folder_path, 'config.json')
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
                return self._mods_cache.copy()
            if use_async and (not self._scan_in_progress):
                if self._scan_thread and self._scan_thread.isRunning():
                    pass
                else:
                    self._scan_in_progress = True
                    self._scan_thread = ModScanThread(self.app_state.mods_dir, self.parent())
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
                                if '_deltamodInfo.json' in zf.namelist():
                                    is_deltamod_archive = True
                        elif item_name_lower.endswith('.tar.gz'):
                            import tarfile
                            with tarfile.open(item_path, 'r:gz') as tf:
                                if '_deltamodInfo.json' in tf.getnames():
                                    is_deltamod_archive = True
                        elif item_name_lower.endswith('.rar'):
                            try:
                                import rarfile
                                with rarfile.RarFile(item_path, 'r') as rf:
                                    if '_deltamodInfo.json' in rf.namelist():
                                        is_deltamod_archive = True
                            except (OSError, ImportError) as e:
                                logging.warning(f'convert_legacy_mods: failed to check rar archive {item_name}: {e}', exc_info=True)
                        elif item_name_lower.endswith('.7z'):
                            import py7zr
                            try:
                                with py7zr.SevenZipFile(item_path, mode='r') as zf:
                                    if '_deltamodInfo.json' in zf.getnames():
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
                        if '_deltamodInfo.json' in dir_contents and 'config.json' not in dir_contents:
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
                config_path = os.path.join(item_path, 'config.json')
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
                except (OSError, json.JSONDecodeError, KeyError) as e:
                    logging.debug(f'load_local_mods: failed to load mod from {item_path}: {e}')
            for mod in list(self.app_state.all_mods):
                if mod.key in installed_mods:
                    config_data = installed_mods[mod.key]
                    mod_folder_path = self.get_mod_folder_path(mod.key)
                    if mod_folder_path:
                        for ext in ['.png', '.jpg', '.jpeg', '.gif']:
                            potential_icon = os.path.join(mod_folder_path, f'_icon{ext}')
                            if os.path.exists(potential_icon):
                                mod.icon_url = potential_icon
                                break
            existing_keys = {mod.key for mod in self.app_state.all_mods}
            for mod_key, config_data in list(installed_mods.items()):
                if not config_data.get('is_local_mod') and mod_key not in existing_keys:
                    try:
                        mod_folder_path = self.get_mod_folder_path(mod_key)
                        icon_path = ''
                        if mod_folder_path:
                            for ext in ['.png', '.jpg', '.jpeg', '.gif']:
                                potential_icon = os.path.join(mod_folder_path, f'_icon{ext}')
                                if os.path.exists(potential_icon):
                                    icon_path = potential_icon
                                    break
                        safe_mod_info = {'key': mod_key, 'name': config_data.get('name', 'Installed Mod'), 'version': config_data.get('version', '1.0.0'), 'author': config_data.get('author', tr('defaults.unknown')), 'tagline': config_data.get('tagline', tr('defaults.no_description')), 'game_version': config_data.get('game_version', tr('defaults.not_specified')), 'description_url': '', 'downloads': 0, 'modgame': config_data.get('modgame', 'deltarune'), 'is_verified': False, 'icon_url': icon_path, 'tags': [], 'hide_mod': False, 'is_local_mod': False, 'ban_status': False, 'demo_url': None, 'demo_version': '1.0.0', 'created_date': config_data.get('created_date', 'N/A'), 'last_updated': config_data.get('created_date', 'N/A'), 'external_url': config_data.get('external_url')}
                        mod = mod_models.ModInfo(**safe_mod_info)
                        files_data = config_data.get('files', {})
                        for file_key, ch_info in list(files_data.items()):
                            extra_files_list = []
                            for ef_data in ch_info.get('extra_files', []):
                                if isinstance(ef_data, dict):
                                    try:
                                        extra_files_list.append(mod_models.ModExtraFile(key=ef_data.get('key', ''), version=ef_data.get('version', ''), url=ef_data.get('url', '')))
                                    except (KeyError, TypeError, ValueError) as e:
                                        logging.debug(f'load_local_mods: failed to parse extra_file: {e}')
                            valid_chapter_fields = {'description': ch_info.get('description'), 'data_file_url': ch_info.get('data_file_url'), 'data_file_version': ch_info.get('data_file_version'), 'extra_files': extra_files_list}
                            mod.files[file_key] = ModChapterData(**valid_chapter_fields)
                        self.app_state.all_mods.append(mod)
                    except Exception as e:
                        logging.warning(f'Failed to create ModInfo for installed mod {mod_key}: {e}')
            self.app_state.all_mods = [mod for mod in self.app_state.all_mods if not hasattr(mod, 'tags') or 'local' not in mod.tags]
            for mod_key, config_data in list(installed_mods.items()):
                if config_data.get('is_local_mod'):
                    try:
                        mod_folder_for_icon = self.get_mod_folder_path(mod_key)
                        icon_path = ''
                        if mod_folder_for_icon:
                            for ext in ['.png', '.jpg', '.jpeg', '.gif']:
                                potential_icon = os.path.join(mod_folder_for_icon, f'_icon{ext}')
                                if os.path.exists(potential_icon):
                                    icon_path = potential_icon
                                    break
                        safe_mod_info = {'key': mod_key, 'name': config_data.get('name', tr('defaults.local_mod')), 'version': config_data.get('version', '1.0.0'), 'author': config_data.get('author', tr('defaults.unknown')), 'tagline': config_data.get('tagline', tr('defaults.no_description')), 'game_version': config_data.get('game_version', tr('defaults.not_specified')), 'description_url': '', 'downloads': 0, 'modgame': config_data.get('modgame', 'deltarune'), 'is_verified': False, 'icon_url': icon_path, 'tags': ['local'], 'hide_mod': False, 'is_local_mod': config_data.get('is_local_mod', True), 'ban_status': False, 'demo_url': None, 'demo_version': '1.0.0', 'created_date': config_data.get('created_date', 'N/A'), 'last_updated': config_data.get('created_date', 'N/A'), 'external_url': config_data.get('external_url')}
                        mod = mod_models.ModInfo(**safe_mod_info)
                        files_data = config_data.get('files', {})
                        mod_folder_path = None
                        for folder_name in os.listdir(self.app_state.mods_dir):
                            folder_path = os.path.join(self.app_state.mods_dir, folder_name)
                            test_config_path = os.path.join(folder_path, 'config.json')
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
                            self.app_state.all_mods.append(mod)
                    except Exception as e:
                        logging.warning(f'Failed to build local ModInfo: {e}')
                        continue
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
            return mod_info.folder_path
        return ''

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
                    with open(self.app_state.mods_metadata_path, 'w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
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
                    return mod
        return mod_models.ModInfo(key=mod_key, name=mod_info.get('name', mod_key), version=mod_info.get('version', '1.0.0'), author=mod_info.get('author', tr('defaults.unknown')), tagline=mod_info.get('tagline', tr('defaults.no_description')), game_version=mod_info.get('game_version', '1.04'), description_url='', downloads=0, modgame=mod_info.get('modgame', 'deltarune'), is_verified=False, is_local_mod=mod_info.get('is_local_mod', False))

    def fetch_mod_data_by_secret(self, secret_key: str) -> Tuple[Optional[dict], Optional[str], bool]:
        from utils.crypto_utils import possible_secret_hashes
        candidate_hashes = possible_secret_hashes(secret_key.strip())
        mod_data: Optional[dict] = None
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
        try:
            from utils.network_utils import get_session
            resp = get_session().get(f'{CLOUD_FUNCTIONS_BASE_URL}/getPendingChangeData?modId={hashed_key}', timeout=10)
            return bool(resp.status_code == 200 and resp.json())
        except requests.RequestException:
            return False

    def withdraw_pending_mod(self, hashed_key: str) -> None:
        try:
            from utils.network_utils import get_session
            get_session().post(f'{CLOUD_FUNCTIONS_BASE_URL}/withdrawPendingMod', json={'hashedKey': hashed_key}, timeout=10)
        except requests.RequestException:
            raise

    def withdraw_pending_change(self, hashed_key: str) -> None:
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
            config_path = os.path.join(folder_path, 'config.json')
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
            config_path = os.path.join(folder_path, 'config.json')
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
                    with open(config_path, 'w', encoding='utf-8') as f:
                        json.dump(config_data, f, indent=4, ensure_ascii=False)
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
            config_path = os.path.join(folder_path, 'config.json')
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
