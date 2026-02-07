"""Mod key deduplication and management utilities."""
import json
import logging
import os
import time
from typing import Callable, Dict, List, Optional

from config.constants import MOD_CONFIG_FILENAME


class ModKeyManager:
    """Handles detection and resolution of duplicate mod keys."""

    def __init__(self, app_state, settings_service=None,
                 read_metadata: Optional[Callable] = None,
                 write_metadata: Optional[Callable] = None):
        self.app_state = app_state
        self.settings_service = settings_service
        self._read_metadata = read_metadata or (lambda: {})
        self._write_metadata = write_metadata or (lambda data: None)

    def fix_duplicate_mod_keys(self, cache: Dict) -> None:
        mods_by_key: Dict[str, List] = {}
        mods_without_key: List = []
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
                new_key = self.generate_unique_key(base_key, cache, key_replacements)
                old_cache_key = next((k for k, v in cache.items() if v == mod_info), None)
                if old_cache_key:
                    if old_cache_key in cache:
                        del cache[old_cache_key]
                mod_info.key = new_key
                mod_info.config_data['key'] = new_key
                if 'mod_key' in mod_info.config_data:
                    del mod_info.config_data['mod_key']
                cache[new_key] = mod_info
                logging.info(f'fix_duplicate_mod_keys: Generated key "{new_key}" for mod without key in folder "{mod_info.folder_path}"')
                self.update_key_in_config(mod_info.folder_path, '', new_key)
        for key, mods_list in mods_by_key.items():
            if len(mods_list) > 1:
                duplicates_found = True
                logging.warning(f'fix_duplicate_mod_keys: Found {len(mods_list)} mods with duplicate key "{key}"')
                mods_list_sorted = sorted(mods_list, key=lambda m: m.folder_path)
                first_mod = mods_list_sorted[0]
                if key not in cache or cache[key] != first_mod:
                    cache[key] = first_mod
                for i, mod_info in enumerate(mods_list_sorted[1:], start=1):
                    new_key = self.generate_unique_key(key, cache, key_replacements)
                    old_key_for_mod = mod_info.key
                    key_replacements[old_key_for_mod] = new_key
                    logging.info(f'fix_duplicate_mod_keys: Assigning new key "{new_key}" to mod in folder "{mod_info.folder_path}" (was "{old_key_for_mod}")')
                    self.update_key_in_config(mod_info.folder_path, old_key_for_mod, new_key)
                    if old_key_for_mod in cache and cache[old_key_for_mod] == mod_info:
                        del cache[old_key_for_mod]
                    mod_info.key = new_key
                    mod_info.config_data['key'] = new_key
                    if 'mod_key' in mod_info.config_data:
                        del mod_info.config_data['mod_key']
                    cache[new_key] = mod_info
        if duplicates_found and key_replacements:
            self.replace_keys_everywhere(key_replacements)
            logging.info(f'fix_duplicate_mod_keys: Fixed {len(key_replacements)} duplicate mod key(s)')
        return cache

    @staticmethod
    def generate_unique_key(base_key: str, existing_cache: Dict, key_replacements: Dict[str, str]) -> str:
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

    @staticmethod
    def update_key_in_config(folder_path: str, old_key: str, new_key: str) -> None:
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
            logging.info(f'update_key_in_config: Updated key in "{config_path}" from "{old_key}" to "{new_key}"')
        except (OSError, json.JSONDecodeError) as e:
            logging.warning(f'update_key_in_config: Failed to update key in "{config_path}": {e}')

    def replace_keys_everywhere(self, key_replacements: Dict[str, str]) -> None:
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
