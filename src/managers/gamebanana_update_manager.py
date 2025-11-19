import os
import json
import logging
from typing import Dict, List
from utils.gamebanana_api import GameBananaAPI
from models.mod_models import ModInfo
logger = logging.getLogger(__name__)


class GameBananaUpdateManager:

    def __init__(self, mods_dir: str):
        self.mods_dir = mods_dir
        self.api = GameBananaAPI()
        self._update_cache: Dict[str, int] = {}

    def check_mod_for_updates(self, mod_info: ModInfo) -> bool:
        if not mod_info.is_gamebanana_mod or not mod_info.gamebanana_mod_id:
            return False
        try:
            mod_id = int(mod_info.gamebanana_mod_id)
            current_timestamp = mod_info.gamebanana_last_update_timestamp
            latest_data = self.api.get_mod_details(mod_id)
            if not latest_data:
                return False
            latest_timestamp = latest_data.get('_tsDateModified')
            if not latest_timestamp:
                return False
            if current_timestamp and latest_timestamp > current_timestamp:
                return True
            return False
        except Exception as e:
            logger.error(f'Error checking updates for mod {mod_info.name}: {e}')
            return False

    def get_installed_gamebanana_mods(self) -> List[ModInfo]:
        installed_mods = []
        if not os.path.exists(self.mods_dir):
            return installed_mods
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
                    if not isinstance(config_data, dict):
                        logger.debug(f'Config data is not a dict for {folder_name}')
                        continue
                    if config_data.get('is_gamebanana_mod'):
                        mod_id = config_data.get('gamebanana_mod_id')
                        if mod_id:
                            try:
                                mod_info = ModInfo(key=config_data.get('mod_key') or folder_name, name=config_data.get('name') or folder_name, version=config_data.get('version') or '1.0.0', author=config_data.get('author') or 'Unknown', tagline=config_data.get('tagline') or '', game_version=config_data.get('game_version') or '', description_url=config_data.get('description_url') or '', downloads=0, modgame=config_data.get('modgame') or 'deltarune', is_verified=False, is_gamebanana_mod=True, gamebanana_mod_id=str(mod_id), gamebanana_mod_type=config_data.get('gamebanana_mod_type') or 'Mod', gamebanana_last_update_timestamp=config_data.get('gamebanana_last_update_timestamp'))
                                installed_mods.append(mod_info)
                            except (TypeError, ValueError) as e:
                                logger.warning(f'Error creating ModInfo for {folder_name}: {e}')
                                continue
                except (IOError, json.JSONDecodeError, KeyError, TypeError) as e:
                    logger.debug(f'Error reading config for {folder_name}: {e}')
                    continue
        except Exception as e:
            logger.error(f'Error scanning mods directory: {e}')
        return installed_mods

    def check_all_mods_for_updates(self) -> Dict[str, bool]:
        updates = {}
        installed_mods = self.get_installed_gamebanana_mods()
        for mod_info in installed_mods:
            mod_id = mod_info.gamebanana_mod_id
            if mod_id:
                has_update = self.check_mod_for_updates(mod_info)
                updates[mod_id] = has_update
        return updates

    def get_mods_with_updates(self) -> List[ModInfo]:
        mods_with_updates = []
        installed_mods = self.get_installed_gamebanana_mods()
        for mod_info in installed_mods:
            if self.check_mod_for_updates(mod_info):
                mods_with_updates.append(mod_info)
        return mods_with_updates
