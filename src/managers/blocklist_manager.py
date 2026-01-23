"""Mod blocklist management.

This module handles blocking mods by ID, name, or category,
with persistent storage of blocklist data.
"""
import json
import logging
from typing import Dict, List, Optional
from pathlib import Path
from managers.localization_manager import tr
from utils.path_utils import get_user_data_root
logger = logging.getLogger(__name__)


class BlocklistManager:
    """Manages mod blocklist for filtering unwanted mods."""
    PREFIX_TYPE_ID = 'id'
    PREFIX_TYPE_NAME = 'name'
    PREFIX_TYPE_CATEGORY = 'category'

    def __init__(self, config_path: Optional[Path] = None):
        """Initialize the blocklist manager.

        Args:
            config_path: Path to blocklist config file (optional).
        """
        if config_path:
            self.config_path = config_path
        else:
            user_root = get_user_data_root()
            settings_dir = Path(user_root) / 'settings'
            settings_dir.mkdir(parents=True, exist_ok=True)
            self.config_path = settings_dir / 'blocklist.json'
        self._blocklist_data: Dict[str, List[Dict[str, str]]] = {}
        self._load_blocklist()

    def _set_default_blocklist(self) -> None:
        """Set default empty blocklist."""
        self._blocklist_data = {'global': []}

    def _load_blocklist(self):
        """Load blocklist from disk."""
        try:
            if self.config_path.exists():
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    self._blocklist_data = json.load(f)
            else:
                self._set_default_blocklist()
        except Exception as e:
            logger.error(f'BlocklistManager: Error loading blocklist: {e}', exc_info=True)
            self._set_default_blocklist()

    def _save_blocklist(self):
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self._blocklist_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f'BlocklistManager: Error saving blocklist: {e}', exc_info=True)

    def get_blocklist_for_game(self, game: str) -> List[Dict[str, str]]:
        return self._blocklist_data.get(game, []) + self._blocklist_data.get('global', [])

    def add_blocklist_entry(self, game: str, prefix_type: str, value: str):
        self._blocklist_data.setdefault(game, [])
        entry = {'prefix_type': prefix_type, 'value': value}
        for existing_entry in self._blocklist_data[game]:
            if existing_entry['prefix_type'] == prefix_type and existing_entry['value'] == value:
                return
        self._blocklist_data[game].append(entry)
        self._save_blocklist()

    def remove_blocklist_entry(self, game: str, prefix_type: str, value: str) -> bool:
        try:
            if game not in self._blocklist_data:
                return False
            original_length = len(self._blocklist_data[game])
            self._blocklist_data[game] = [entry for entry in self._blocklist_data[game] if not (entry['prefix_type'] == prefix_type and entry['value'] == value)]
            if len(self._blocklist_data[game]) == 0 and game != 'global':
                del self._blocklist_data[game]
            if len(self._blocklist_data.get(game, [])) != original_length:
                self._save_blocklist()
                return True
            return False
        except KeyError as e:
            logger.error(f'BlocklistManager: KeyError in remove_blocklist_entry: {e}', exc_info=True)
            return False

    def get_all_games(self) -> List[str]:
        games = list(self._blocklist_data.keys())
        if 'global' in games:
            games.remove('global')
            games.append('global')
        return games

    def is_mod_blocklisted(self, mod, game: str) -> bool:
        blocklist_entries = self.get_blocklist_for_game(game)
        for entry in blocklist_entries:
            prefix_type = entry['prefix_type']
            value = entry['value'].lower()
            if prefix_type == self.PREFIX_TYPE_ID:
                mod_id = getattr(mod, 'id', None) or getattr(mod, '_id', None)
                key = getattr(mod, 'key', None) or getattr(mod, 'mod_key', None)
                if mod_id and str(mod_id).lower() == value:
                    return True
                if key and key.startswith('gb_'):
                    key_id = key.replace('gb_', '', 1)
                    if key_id and key_id.lower() == value:
                        return True
            elif prefix_type == self.PREFIX_TYPE_NAME:
                mod_name = getattr(mod, 'name', None) or getattr(mod, 'title', None)
                if mod_name and value in mod_name.lower():
                    return True
            elif prefix_type == self.PREFIX_TYPE_CATEGORY:
                mod_category = getattr(mod, 'category', None) or getattr(mod, 'cat_name', None) or getattr(mod, 'gamebanana_category', None)
                if mod_category and mod_category.lower() == value:
                    return True
        return False

    def get_prefix_type_display_name(self, prefix_type: str) -> str:
        display_names = {self.PREFIX_TYPE_ID: tr('blocklist.prefix_type_id'), self.PREFIX_TYPE_NAME: tr('blocklist.prefix_type_name'), self.PREFIX_TYPE_CATEGORY: tr('blocklist.prefix_type_category')}
        return display_names.get(prefix_type, prefix_type)
