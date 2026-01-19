import os
import json
import zipfile
import shutil
import logging
import tempfile
from typing import Optional, Dict, Any
from utils.deltamod_converter import DeltamodConverter
from utils.file_utils import find_deltamod_info_file, check_filename_is_deltamod_info, normalize_mod_package
logger = logging.getLogger(__name__)


class GameBananaConverter:

    def __init__(self, archive_path: str, mods_dir: str, gamebanana_metadata: Dict[str, Any] = None):
        self.archive_path = archive_path
        self.mods_dir = mods_dir
        self.gamebanana_metadata = gamebanana_metadata or {}
        self.temp_extract_dir = None

    def convert(self) -> Optional[str]:
        try:
            self.temp_extract_dir = tempfile.mkdtemp(prefix='gb_convert_')
            if not self._check_compatibility():
                logger.error(f'Archive {self.archive_path} does not contain deltamod info file')
                return None
            self._extract_archive()
            normalize_mod_package(self.temp_extract_dir, require_manifest=True)
            target_mod_key = None
            if self.gamebanana_metadata.get('mod_id'):
                target_mod_key = f"gb_{self.gamebanana_metadata['mod_id']}"
            if target_mod_key:
                self._update_deltamod_info_mod_key(target_mod_key)
                self._remove_existing_mod_folder(target_mod_key)
            deltamod_converter = DeltamodConverter(self.temp_extract_dir, self.mods_dir)
            result_path = deltamod_converter.convert()
            if result_path:
                result_path = self._update_config_with_gb_metadata(result_path)
            return result_path
        except Exception as e:
            logger.error(f'GameBanana conversion failed: {e}', exc_info=True)
            return None
        finally:
            if self.temp_extract_dir and os.path.exists(self.temp_extract_dir):
                try:
                    shutil.rmtree(self.temp_extract_dir)
                except Exception as e:
                    logger.warning(f'Failed to cleanup temp directory: {e}')

    def _check_compatibility(self) -> bool:
        try:
            if not os.path.exists(self.archive_path):
                return False
            with zipfile.ZipFile(self.archive_path, 'r') as zf:
                namelist = zf.namelist()
                for name in namelist:
                    if check_filename_is_deltamod_info(name):
                        return True
                return False
        except zipfile.BadZipFile:
            logger.debug(f'Archive is not a valid zip file: {self.archive_path}')
            return False
        except Exception as e:
            logger.error(f'Error checking archive compatibility: {e}')
            return False

    def _extract_archive(self) -> None:
        try:
            from utils.archive_utils import extract_with_unrar_retry
            extract_with_unrar_retry(self.archive_path, self.temp_extract_dir)
            extracted_items = os.listdir(self.temp_extract_dir)
            if len(extracted_items) == 1:
                single_item = os.path.join(self.temp_extract_dir, extracted_items[0])
                if os.path.isdir(single_item):
                    for item in os.listdir(single_item):
                        shutil.move(os.path.join(single_item, item), os.path.join(self.temp_extract_dir, item))
                    os.rmdir(single_item)
        except Exception as e:
            logger.error(f'Error extracting archive: {e}')
            raise

    def _update_deltamod_info_mod_key(self, target_mod_key: str) -> None:
        deltamod_info_path = find_deltamod_info_file(self.temp_extract_dir)
        if not deltamod_info_path:
            return
        try:
            with open(deltamod_info_path, 'r', encoding='utf-8') as f:
                deltamod_info = json.load(f)
            package_id = target_mod_key.replace('_', '.')
            if 'metadata' not in deltamod_info:
                deltamod_info['metadata'] = {}
            deltamod_info['metadata']['packageID'] = package_id
            with open(deltamod_info_path, 'w', encoding='utf-8') as f:
                json.dump(deltamod_info, f, indent=4, ensure_ascii=False)
            logger.info(f'GameBananaConverter: Updated packageID in deltamod info file to {package_id} (target_mod_key: {target_mod_key})')
        except Exception as e:
            logger.warning(f'Failed to update packageID in deltamod info file: {e}')

    def _remove_existing_mod_folder(self, key: str) -> None:
        if not os.path.exists(self.mods_dir):
            return
        try:
            for folder_name in os.listdir(self.mods_dir):
                folder_path = os.path.join(self.mods_dir, folder_name)
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
                    if (config_data.get('key') or config_data.get('mod_key')) == key:
                        logger.info(f'GameBananaConverter: Removing existing mod folder {folder_path} with key {key}')
                        shutil.rmtree(folder_path)
                        break
                except Exception as e:
                    logger.debug(f'GameBananaConverter: Error checking config in {folder_path}: {e}')
                    continue
        except Exception as e:
            logger.warning(f'GameBananaConverter: Error checking for existing mod folder: {e}')

    def _update_config_with_gb_metadata(self, mod_dir: str) -> str:
        config_path = os.path.join(mod_dir, 'mod_config.json')
        if not os.path.exists(config_path):
            logger.warning(f'GameBananaConverter: Config file not found at {config_path}')
            return mod_dir
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            if not isinstance(config_data, dict):
                logger.warning(f'GameBananaConverter: Config data is not a dict at {config_path}')
                return mod_dir
            config_data['is_local_mod'] = False
            if self.gamebanana_metadata.get('mod_id'):
                mod_id = str(self.gamebanana_metadata['mod_id'])
                expected_mod_key = f'gb_{mod_id}'
                config_data['key'] = expected_mod_key
                if 'mod_key' in config_data:
                    del config_data['mod_key']
                logger.info(f'GameBananaConverter: Updated config - key={expected_mod_key}, mod_dir={mod_dir} (folder name based on mod name)')
            if not config_data.get('external_url') and self.gamebanana_metadata.get('profile_url'):
                config_data['external_url'] = self.gamebanana_metadata['profile_url']
            if self.gamebanana_metadata.get('icon_url'):
                config_data['icon_url'] = self.gamebanana_metadata['icon_url']
            tags = []
            if self.gamebanana_metadata.get('tags'):
                tags = self.gamebanana_metadata['tags']
                if not isinstance(tags, list):
                    tags = [tags] if tags else []
            elif self.gamebanana_metadata.get('category'):
                from utils.gamebanana_api import GameBananaAPI
                category_tag = GameBananaAPI.category_to_tag(self.gamebanana_metadata['category'])
                if category_tag:
                    tags = [category_tag]
            if tags:
                existing_tags = config_data.get('tags', [])
                if not isinstance(existing_tags, list):
                    existing_tags = [existing_tags] if existing_tags else []
                for tag in tags:
                    if tag and tag not in existing_tags:
                        existing_tags.append(tag)
                config_data['tags'] = existing_tags
            from utils.file_utils import atomic_write_json
            atomic_write_json(config_path, config_data, indent=4)
            logger.info(f"GameBananaConverter: Updated config for GameBanana mod: key={config_data.get('key') or config_data.get('mod_key')}, mod_dir={mod_dir}")
            return mod_dir
        except (IOError, json.JSONDecodeError, TypeError, KeyError) as e:
            logger.error(f'GameBananaConverter: Failed to update config with GameBanana metadata: {e}', exc_info=True)
            return mod_dir
        except Exception as e:
            logger.error(f'GameBananaConverter: Unexpected error updating config: {e}', exc_info=True)
            return mod_dir
