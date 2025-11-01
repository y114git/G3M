import json
import os
import re
from typing import Any, Dict, List, Optional
import requests
from utils.network_utils import get_session
import logging
from PyQt6.QtCore import QThread, pyqtSignal
from config.constants import CLOUD_FUNCTIONS_BASE_URL, UI_COLORS
from managers.localization_manager import tr
from models.mod_models import ModChapterData, ModExtraFile, ModInfo
from utils.file_utils import version_sort_key


class FetchModsThread(QThread):
    result = pyqtSignal(bool)
    status = pyqtSignal(str, str)

    def __init__(self, main_window, force_update=False):
        super().__init__(main_window)
        self.main_window = main_window
        self.force_update = force_update

    def run(self):
        try:
            if not CLOUD_FUNCTIONS_BASE_URL:
                self.status.emit('Cloud Functions URL not configured', 'red')
                self.result.emit(False)
                return
            session = get_session()
            response = session.get(f'{CLOUD_FUNCTIONS_BASE_URL}/getMods', timeout=15)
            response.raise_for_status()
            mods_json = response.json() or {}
            all_mods = self._parse_mods(mods_json)
            local_mods = self._get_local_mods()
            self.main_window.app_state.all_mods = all_mods + local_mods
            self._update_remote_exists_flags(all_mods)
            self.result.emit(True)
        except requests.RequestException as e:
            error_msg = tr('errors.update_list_failed').format(str(e))
            self.status.emit(error_msg, UI_COLORS['status_error'])
            self.result.emit(False)
        except Exception as e:
            self.status.emit(str(e), UI_COLORS['status_error'])
            self.result.emit(False)

    def _parse_mods(self, mods_json: Dict[str, Any]) -> List[ModInfo]:
        all_mods = []
        for key, data in mods_json.items():
            if not isinstance(data, dict):
                continue
            mod = self._parse_single_mod(key, data)
            if mod:
                all_mods.append(mod)
        return all_mods

    def _parse_single_mod(self, key: str, data: Dict[str, Any]) -> Optional[ModInfo]:
        files_data = self._extract_files_data(data)
        composite_version = self._aggregate_versions(files_data)
        base_version = data.get('version')
        modgame = data.get('modgame', 'deltarune')
        if modgame == 'deltarune' and data.get('is_demo_mod', False):
            modgame = 'deltarunedemo'
        screens_list = data.get('screenshots_url', [])
        if isinstance(screens_list, str):
            screens_list = [s.strip() for s in screens_list.split(',') if s.strip()]
        elif not isinstance(screens_list, list):
            screens_list = []
        mod = ModInfo(key=key, name=data.get('name', tr('status.unknown_mod')), author=data.get('author', tr('defaults.unknown')), version=f'{base_version}|{composite_version}' if base_version else composite_version, tagline=data.get('tagline', tr('status.no_description_status')), game_version=data.get('game_version', tr('defaults.not_specified')), description_url=data.get('description_url', ''), downloads=data.get('downloads', 0), modgame=modgame, is_verified=data.get('is_verified', False), icon_url=data.get('icon_url'), tags=data.get('tags', []), hide_mod=data.get('hide_mod', False), is_xdelta=data.get('is_xdelta', False), ban_status=data.get('ban_status', False), demo_url=files_data.get('demo', {}).get('url') if files_data else None, demo_version=files_data.get('demo', {}).get('version', '1.0.0') if files_data else '1.0.0', created_date=data.get('created_date'), last_updated=data.get('last_updated'), external_url=data.get('external_url'), screenshots_url=screens_list)
        if self._process_mod_chapters(mod, files_data):
            return mod
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
        if not hasattr(self.main_window.app_state, 'mods_dir') or not os.path.exists(self.main_window.app_state.mods_dir):
            return local_mods
        existing_local_keys = set()
        for folder_name in os.listdir(self.main_window.app_state.mods_dir):
            folder_path = os.path.join(self.main_window.app_state.mods_dir, folder_name)
            if not os.path.isdir(folder_path):
                continue
            config_path = os.path.join(folder_path, 'config.json')
            if os.path.exists(config_path):
                try:
                    config_data = self.main_window.settings_manager.read_json(config_path)
                    if config_data and config_data.get('is_local_mod'):
                        key = config_data.get('mod_key')
                        if key:
                            existing_local_keys.add(key)
                except (IOError, json.JSONDecodeError):
                    continue
        for mod in self.main_window.app_state.all_mods:
            if hasattr(mod, 'key') and mod.key.startswith('local_') and (mod.key in existing_local_keys):
                local_mods.append(mod)
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
            if chapter_data.get('description_url'):
                pass
            if mod_chapter.is_valid():
                mod.files[file_key] = mod_chapter
        return True

    def _update_remote_exists_flags(self, all_mods: List[ModInfo]):
        remote_mod_keys = {mod.key for mod in all_mods}
        if not hasattr(self.main_window.app_state, 'mods_dir') or not os.path.exists(self.main_window.app_state.mods_dir):
            return
        try:
            mods_metadata = self.main_window.mod_manager._read_metadata()
            metadata_updated = False
            for folder_name in os.listdir(self.main_window.app_state.mods_dir):
                folder_path = os.path.join(self.main_window.app_state.mods_dir, folder_name)
                if not os.path.isdir(folder_path):
                    continue
                config_path = os.path.join(folder_path, 'config.json')
                if not os.path.exists(config_path):
                    continue
                try:
                    config_data = self.main_window.settings_manager.read_json(config_path)
                    if not config_data:
                        continue
                    mod_key = config_data.get('mod_key')
                    if not mod_key or config_data.get('is_local_mod', False):
                        continue
                    is_available_now = mod_key in remote_mod_keys
                    mod_meta = mods_metadata.get(mod_key, {})
                    if mod_meta.get('is_available_on_server') != is_available_now:
                        mod_meta['is_available_on_server'] = is_available_now
                        mods_metadata[mod_key] = mod_meta
                        metadata_updated = True
                except (IOError, json.JSONDecodeError):
                    continue
            if metadata_updated:
                self.main_window.mod_manager._write_metadata(mods_metadata)
        except Exception as e:
            logging.warning(f'Failed to update remote exists flags in metadata: {e}')
