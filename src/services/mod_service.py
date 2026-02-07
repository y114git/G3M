"""Mod management and installation."""
import os
import logging
import zipfile
import shutil
import tempfile
import threading
from typing import Dict, List, Optional, Set
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox
from services.localization_service import tr
from models.mod_models import ModChapterData
import models.mod_models as mod_models
from workers.install.url_install_worker import UrlInstallThread
from workers.mod_scan_worker import ModScanThread
from adapters.deltamod_adapter import DeltamodConverter
from utils.file_utils import load_json, save_json
from utils.file_utils import sanitize_filename, has_deltamod_info_file
from utils.mod_utils import get_mod_key, get_mod_name, resolve_mod_icon
from utils.mod_config_parser import resolve_local_icon_url, parse_extra_files_raw, resolve_data_file_version, resolve_chapter_folder
from config.constants import UI_COLORS, MOD_CONFIG_FILENAME, LEGACY_MOD_CONFIG_FILENAME
import time
from core.exceptions import ModUninstallationError
from utils.mod_key_utils import ModKeyManager
from utils.mod_scan_utils import (
    ModFolderInfo,
    normalize_mod_cache,
    scan_mods_directory,
    cleanup_corrupted_mods,
)


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
        self._key_manager = ModKeyManager(
            app_state=app_state,
            settings_service=settings_service,
            read_metadata=lambda: self._read_metadata(),
            write_metadata=lambda data: self._write_metadata(data),
        )

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
                    config_data = mod_info_dict.get('config_data', {})
                    folder_path = mod_info_dict.get('folder_path', '')
                    folder_name = mod_info_dict.get('folder_name', '')
                    config_mtime = mod_info_dict.get('config_mtime', 0.0)
                    effective_key = mod_info_dict.get('key') or mod_info_dict.get('mod_key', key) or config_data.get('key') or config_data.get('mod_key')
                    if not effective_key:
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
            self._key_manager.fix_duplicate_mod_keys(cache)

    @staticmethod
    def _build_safe_mod_info(key: str, config_data: dict, icon_url: str, default_name: str = 'Installed Mod', tags: Optional[List] = None) -> dict:
        """Build a safe mod info dict from config data with sensible defaults."""
        if tags is None:
            tags = config_data.get('tags', [])
            if not isinstance(tags, list):
                tags = [tags] if tags else []
        return {
            'key': key, 'name': config_data.get('name', default_name),
            'version': config_data.get('version', '1.0.0'),
            'author': config_data.get('author', tr('defaults.unknown')),
            'tagline': config_data.get('tagline', tr('defaults.no_description')),
            'game_version': config_data.get('game_version', tr('defaults.not_specified')),
            'description_url': '', 'downloads': 0,
            'game': config_data.get('game') or config_data.get('modgame', 'deltarune'),
            'is_verified': False, 'icon_url': icon_url, 'tags': tags,
            'hide_mod': False, 'ban_status': False, 'demo_url': None, 'demo_version': '1.0.0',
            'created_date': config_data.get('created_date', 'N/A'),
            'last_updated': config_data.get('created_date', 'N/A'),
            'external_url': config_data.get('external_url'),
        }

    @staticmethod
    def _chapter_id_to_file_key(chapter_id: int) -> str:
        """Convert chapter_id to the file key used in config files data."""
        return 'demo' if chapter_id == -1 else str(chapter_id)

    def _get_mods_cache(self, use_async: bool = False) -> Dict[str, ModFolderInfo]:
        with self._cache_lock:
            if self._mods_cache_valid:
                normalized_cache = normalize_mod_cache(self._mods_cache)
                if len(normalized_cache) != len(self._mods_cache) or any((isinstance(v, dict) for v in self._mods_cache.values())):
                    self._mods_cache = normalized_cache
                return self._mods_cache.copy()
            if use_async and not self._scan_in_progress and not (self._scan_thread and self._scan_thread.isRunning()):
                self._scan_in_progress = True
                from utils.path_utils import get_user_data_root
                cache_dir = os.path.join(get_user_data_root(), 'cache')
                self._scan_thread = ModScanThread(self.app_state.mods_dir, self.parent(), cache_dir=cache_dir)
                self._scan_thread.scan_completed.connect(self._on_scan_completed)
                self._scan_thread.start()
            cache, mods_by_name = scan_mods_directory(self.app_state.mods_dir, self._mods_cache)
            self._mods_cache = cache
            self._key_manager.fix_duplicate_mod_keys(self._mods_cache)
            self._mods_by_name = mods_by_name
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
        cleanup_corrupted_mods(self.app_state.mods_dir)
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
                    if not key:
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

            def _find_mod_by_key(key):
                for mod in self.app_state.all_mods:
                    if get_mod_key(mod) == key:
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
                                    if get_mod_key(mod) == key:
                                        self.app_state.all_mods[i] = new_mod
                                        break
                            elif hasattr(new_mod, 'files') and new_mod.files:
                                existing_mod.files = new_mod.files
                        else:
                            logging.debug(f'load_local_mods: Skipping mod {key} with empty/invalid files data')
                    except Exception as e:
                        logging.warning(f'load_local_mods: Failed to load files for mod {key}: {e}', exc_info=True)

            existing_keys = {k for mod in self.app_state.all_mods if (k := get_mod_key(mod))}
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
                    icon_url = resolve_local_icon_url(config_data, mod_folder_path)
                    safe_mod_info = self._build_safe_mod_info(key, config_data, icon_url)
                    mod = mod_models.ModInfo(**safe_mod_info)
                    self._parse_chapter_files(mod, config_data, key)
                    self._append_mod_if_valid(mod, key)
                except Exception as e:
                    logging.warning(f'Failed to create ModInfo for installed mod {key}: {e}', exc_info=True)
            self.app_state.all_mods = list(self.app_state.all_mods)
            for key, config_data in list(installed_mods.items()):
                if not (key and isinstance(key, str) and key.startswith('local_')):
                    continue
                if key in existing_keys:
                    logging.debug(f'load_local_mods: Skipping local mod {key} - already in all_mods')
                    continue
                try:
                    mod_info_from_cache = cache.get(key)
                    mod_folder_path = getattr(mod_info_from_cache, 'folder_path', None) or self.get_mod_folder_path(key)
                    icon_url = resolve_local_icon_url(config_data, mod_folder_path or self.get_mod_folder_path(key))
                    safe_mod_info = self._build_safe_mod_info(key, config_data, icon_url, default_name=tr('defaults.local_mod'), tags=['local'])
                    mod = mod_models.ModInfo(**safe_mod_info)
                    self._parse_local_chapter_files(mod, config_data, key, mod_folder_path)
                    self._append_mod_if_valid(mod, key)
                except Exception as e:
                    logging.warning(f'Failed to build local ModInfo: {e}')
                    continue
            installed_gb_keys = set(installed_gamebanana_by_key)
            for mod in self.app_state.all_mods:
                mod_key_attr = get_mod_key(mod)
                if mod_key_attr and mod_key_attr.startswith('gb_') and mod_key_attr in installed_gb_keys:
                    if (getattr(mod, 'downloads', 0) or 0) <= 0:
                        try:
                            from adapters.gamebanana_adapter import GameBananaAPI
                            api = GameBananaAPI()
                            mod_id = int(mod_key_attr.replace('gb_', '', 1))
                            downloaded_count = api.get_mod_downloads_only(mod_id)
                            if downloaded_count is not None:
                                mod.downloads = max(downloaded_count, 0)
                        except Exception as e:
                            logging.debug(f'load_local_mods: Failed to load downloads from API for mod {mod_key_attr}: {e}')
            metadata = self._read_metadata()
            cleanup_files = metadata.get('mod_files_to_cleanup', [])
            cleanup_dirs = metadata.get('mod_dirs_to_cleanup', [])
            for items, remover, kind in [(cleanup_files, os.remove, 'file'), (cleanup_dirs, shutil.rmtree, 'dir')]:
                for p in items:
                    try:
                        if os.path.exists(p):
                            remover(p)
                    except Exception as e:
                        logging.warning(f'load_local_mods: failed to remove cleanup {kind} {p}: {e}', exc_info=True)
            self._write_metadata({'mod_files_to_cleanup': [], 'mod_dirs_to_cleanup': []})
            self.cleanup_stale_used_mods()
            return True
        except Exception as e:
            logging.error(f'load_local_mods failed: {e}', exc_info=True)
            return False

    @staticmethod
    def _validate_files_data(config_data: dict, key: str) -> dict:
        files_data = config_data.get('files', {})
        if not isinstance(files_data, dict):
            logging.warning(f'load_local_mods: Invalid files_data type for mod {key}, expected dict, got {type(files_data).__name__}')
            return {}
        return files_data

    def _parse_chapter_files(self, mod, config_data: dict, key: str):
        files_data = self._validate_files_data(config_data, key)
        for file_key, ch_info in list(files_data.items()):
            if not isinstance(ch_info, dict):
                logging.debug(f'load_local_mods: Skipping invalid chapter info for mod {key}, file_key={file_key}')
                continue
            try:
                extra_files_list = parse_extra_files_raw(ch_info.get('extra_files', []), ch_info)
                mod.files[file_key] = ModChapterData(
                    description=ch_info.get('description'),
                    data_file_url=ch_info.get('data_file_url'),
                    data_file_version=resolve_data_file_version(ch_info),
                    extra_files=extra_files_list,
                )
            except Exception as e:
                logging.warning(f'load_local_mods: Failed to process chapter data for mod {key}, file_key={file_key}: {e}', exc_info=True)

    def _parse_local_chapter_files(self, mod, config_data: dict, key: str, mod_folder_path: str):
        files_data = self._validate_files_data(config_data, key)
        game = config_data.get('game') or config_data.get('modgame')
        for file_key, ch_info in list(files_data.items()):
            if not isinstance(ch_info, dict):
                logging.warning(f'load_local_mods: ch_info is not a dict for mod {key}, file_key={file_key}, skipping')
                continue
            chapter_folder = resolve_chapter_folder(file_key, mod_folder_path, game)
            if not chapter_folder and mod_folder_path:
                continue
            data_file_url = ''
            if ch_info.get('data_file_url') and mod_folder_path and chapter_folder:
                data_file_url = os.path.join(chapter_folder, ch_info['data_file_url'])
            extra_files = parse_extra_files_raw(
                ch_info.get('extra_files', []), ch_info,
                chapter_folder=chapter_folder if mod_folder_path else None,
            )
            mod.files[file_key] = ModChapterData(
                description=config_data.get('tagline', ''),
                data_file_url=data_file_url,
                data_file_version=resolve_data_file_version(ch_info),
                extra_files=extra_files,
            )

    def _append_mod_if_valid(self, mod, key: str):
        if mod.files:
            self.app_state.append_mod(mod)
        else:
            logging.debug(f'Skipping mod {key} ({mod.name}): game={mod.game}, has_files={bool(mod.files)}')

    def get_mod_config(self, key: str) -> dict:
        cache = self._get_mods_cache()
        mod_info = cache.get(key)
        if mod_info:
            return mod_info.config_data.copy()
        return {}

    def get_mod_folder_path(self, key: str) -> str:
        mod_info = self._get_mods_cache().get(key)
        if not mod_info:
            return ''
        return mod_info.get('folder_path', '') if isinstance(mod_info, dict) else mod_info.folder_path

    @staticmethod
    def resolve_gamebanana_file(mod_info, api, selected_file=None) -> Optional[Dict]:
        if selected_file:
            return selected_file
        files = getattr(mod_info, 'gamebanana_supported_files', []) or []
        if files:
            return files[0]
        try:
            key = get_mod_key(mod_info)
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
            key = get_mod_key(mod_info) or 'unknown'
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

    _UNINSTALL_ERROR_MAP = {
        PermissionError: ('permission_error', 'Permission denied during uninstallation'),
        OSError: ('io_error', 'File operation failed during uninstallation'),
        KeyError: ('missing_data', 'Missing required data'),
        AttributeError: ('missing_data', 'Missing required data'),
    }

    def uninstall_mod(self, mod):
        try:
            self.delete_mod_files(mod)
            self.app_state.is_installing = False
            self.mod_list_updated.emit()
            self.status_changed.emit(tr('status.mod_uninstalled'), 'status_success')
        except Exception as e:
            key = get_mod_key(mod) or 'unknown'
            mod_name = get_mod_name(mod, 'Unknown Mod')
            reason, prefix = 'unknown', 'Unexpected error during uninstallation'
            for exc_type, (r, p) in self._UNINSTALL_ERROR_MAP.items():
                if isinstance(e, exc_type):
                    reason, prefix = r, p
                    break
            if isinstance(e, shutil.Error):
                reason, prefix = 'io_error', 'File operation failed during uninstallation'
            error = ModUninstallationError(f'{prefix}: {e}', key=key, mod_name=mod_name, reason=reason)
            logging.error(f'uninstall_mod: {reason}: {e}', exc_info=True, extra={'key': key, 'mod_name': mod_name})
            if reason == 'permission_error':
                self.feedback_service.show_message('error', 'errors.uninstall_failed', tr('errors.permission_denied'))
            elif reason not in ('missing_data',):
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

    def _resolve_mod_info_from_cache(self, cache: Dict, key: str, mod_name: Optional[str]):
        """Find mod info in cache by key, then by name variants."""
        mod_info = cache.get(key)
        if mod_info:
            return mod_info
        logging.warning(f'delete_mod_files: Mod with key {key} not found in cache. Cache has {len(cache)} entries.')
        if not mod_name:
            return None
        with self._cache_lock:
            mapped_key = self._mods_by_name.get(mod_name.lower())
            if mapped_key and mapped_key in cache:
                logging.info(f'delete_mod_files: Found mod by name mapping: {mod_name} -> {mapped_key}')
                return cache[mapped_key]
        for cached_key, cached_info in cache.items():
            cached_folder = cached_info.folder_name if hasattr(cached_info, 'folder_name') else cached_info.get('folder_name') if isinstance(cached_info, dict) else None
            if cached_folder == mod_name:
                logging.info(f'delete_mod_files: Found mod by folder name: {mod_name}, key: {cached_key}')
                return cached_info
        for cached_key, cached_info in cache.items():
            config_data = cached_info.config_data if hasattr(cached_info, 'config_data') else cached_info.get('config_data', {}) if isinstance(cached_info, dict) else {}
            if config_data.get('name', '') == mod_name:
                logging.info(f'delete_mod_files: Found mod by config name: {mod_name}, key: {cached_key}')
                return cached_info
        return None

    def delete_mod_files(self, mod_data):
        try:
            folder_path = mod_data.folder_path if hasattr(mod_data, 'folder_path') else mod_data.get('folder_path') if isinstance(mod_data, dict) else None
            key = get_mod_key(mod_data)
            mod_name = get_mod_name(mod_data)
            logging.info(f'delete_mod_files: key = {key}, mod_name={mod_name}, folder_path={folder_path}, type={type(mod_data)}')
            candidate_paths = [
                (folder_path, 'folder_path'),
                (self.get_mod_folder_path(key) if key else None, 'get_mod_folder_path'),
                (os.path.join(self.app_state.mods_dir, mod_name) if mod_name else None, 'mod_name'),
            ]
            for path, label in candidate_paths:
                if self._try_delete_folder(path, label):
                    return
            if not key:
                logging.error('delete_mod_files: Cannot determine key or folder_path for mod_data')
                return
            cache = self._get_mods_cache()
            mod_info = self._resolve_mod_info_from_cache(cache, key, mod_name)
            if mod_info:
                self._try_delete_folder(mod_info.folder_path, 'cache_info')
                self.invalidate_mods_cache()
                return
            last_resort_paths = [
                (os.path.join(self.app_state.mods_dir, key), 'key_as_folder'),
                (os.path.join(self.app_state.mods_dir, mod_name) if mod_name else None, 'mod_name_last_resort'),
            ]
            for path, label in last_resort_paths:
                if self._try_delete_folder(path, label):
                    return
            logging.error(f"delete_mod_files: Cannot delete mod - not found in cache and folder paths do not exist. key = {key}, mod_name={mod_name or 'None'}")
        except Exception as e:
            logging.error(f'delete_mod_files: cleanup failed: {e}', exc_info=True)
            raise

    @staticmethod
    def _collect_remote_versions(mod: mod_models.ModInfo, chapter_id: int) -> dict:
        if chapter_id == -1:
            return {'demo': mod.demo_version} if mod.is_valid_for_demo() and mod.demo_version else {}
        ch = mod.get_chapter_data(chapter_id)
        if not ch:
            return {}
        d = {}
        if ch.data_file_version:
            d['data'] = ch.data_file_version
        for ef in ch.extra_files:
            d[ef.key] = ef.version
        return d

    def get_mod_status(self, mod: mod_models.ModInfo, chapter_id: int) -> str:
        if mod.is_gamebanana_mod():
            return 'ready'
        cache = self._get_mods_cache()
        key = get_mod_key(mod)
        mod_info = cache.get(key)
        if not mod_info:
            return 'install'
        remote_versions = self._collect_remote_versions(mod, chapter_id)
        if not remote_versions:
            return 'n/a'
        config_data = mod_info.config_data
        file_key = self._chapter_id_to_file_key(chapter_id)
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
        from utils.path_utils import version_sort_key
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
                    return 'demo' in files_data or 'undertale' in files_data
                file_key = self._chapter_id_to_file_key(chapter_id)
                return file_key in files_data
            chapter_folders = {-1: 'universal', 0: 'menu', 1: 'chapter1', 2: 'chapter2', 3: 'chapter3', 4: 'chapter4'}
            folder_name = chapter_folders.get(chapter_id, 'universal')
            for name in (folder_name, 'universal'):
                folder = os.path.join(mod_info.folder_path, name)
                if os.path.exists(folder):
                    return len(os.listdir(folder)) > 0
            return True
        except Exception as e:
            logging.warning(f'mod_has_files_for_chapter: exception: {e}', exc_info=True)
            return True

    def _read_metadata(self) -> Dict:
        with self.app_state._mods_metadata_lock:
            if not os.path.exists(self.app_state.mods_metadata_path):
                return {}
            try:
                return load_json(self.app_state.mods_metadata_path, migrate_config=False) or {}
            except Exception as e:
                logging.warning(f'_read_metadata: failed: {e}', exc_info=True)
                return {}

    def _write_metadata(self, data: Dict):
        with self.app_state._mods_metadata_lock:
            try:
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
                mod_key_attr = get_mod_key(mod)
                if mod_key_attr == key:
                    if hasattr(mod, 'files') and mod.files:
                        return mod
        files_data = mod_info.get('files', {})
        if files_data:
            from utils.mod_config_parser import normalize_files_data
            mod_info = mod_info.copy()
            mod_info['files'] = normalize_files_data(files_data)
        return mod_models.ModInfo.from_dict(mod_info)

    def _iter_mod_configs(self):
        from utils.file_utils import migrate_mod_config
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
                    save_json(config_path, config_data, indent=4)
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
            if 'game' not in cfg:
                cfg['game'] = cfg.pop('modgame', 'deltarune')
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
