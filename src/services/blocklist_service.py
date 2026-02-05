"""Mod blocklist management.

This module handles blocking mods by ID, name, or category,
with persistent storage of blocklist data.
"""
import json
import logging
from typing import Dict, List, Optional
from pathlib import Path
from services.localization_service import tr
from utils.path_utils import get_user_data_root
logger = logging.getLogger(__name__)


def _getattr_first(obj, *attrs, default=None):
    """Get first non-None attribute from object."""
    for attr in attrs:
        val = getattr(obj, attr, None)
        if val is not None:
            return val
    return default


class BlocklistManager:
    """Manages mod blocklist for filtering unwanted mods."""
    PREFIX_TYPE_ID, PREFIX_TYPE_NAME, PREFIX_TYPE_CATEGORY = 'id', 'name', 'category'

    def __init__(self, config_path: Optional[Path] = None):
        """Initialize the blocklist manager."""
        self.config_path = config_path or (Path(get_user_data_root()) / 'settings' / 'blocklist.json')
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self._blocklist_data: Dict[str, List[Dict[str, str]]] = {}
        self._load_blocklist()

    def _set_default_blocklist(self) -> None: self._blocklist_data = {'global': []}

    def _load_blocklist(self):
        try:
            self._blocklist_data = json.load(open(self.config_path, 'r', encoding='utf-8')) if self.config_path.exists() else self._set_default_blocklist() or self._blocklist_data
        except Exception as e:
            logger.error(f'BlocklistManager: Error loading blocklist: {e}', exc_info=True)
            self._set_default_blocklist()

    def _save_blocklist(self):
        try:
            json.dump(self._blocklist_data, open(self.config_path, 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f'BlocklistManager: Error saving blocklist: {e}', exc_info=True)

    def get_blocklist_for_game(self, game: str) -> List[Dict[str, str]]:
        return self._blocklist_data.get(game, []) + self._blocklist_data.get('global', [])

    def add_blocklist_entry(self, game: str, prefix_type: str, value: str):
        self._blocklist_data.setdefault(game, [])
        entry = {'prefix_type': prefix_type, 'value': value}
        if not any(e['prefix_type'] == prefix_type and e['value'] == value for e in self._blocklist_data[game]):
            self._blocklist_data[game].append(entry)
            self._save_blocklist()

    def remove_blocklist_entry(self, game: str, prefix_type: str, value: str) -> bool:
        if game not in self._blocklist_data:
            return False
        orig_len = len(self._blocklist_data[game])
        self._blocklist_data[game] = [e for e in self._blocklist_data[game] if not (e['prefix_type'] == prefix_type and e['value'] == value)]
        if not self._blocklist_data[game] and game != 'global':
            del self._blocklist_data[game]
        if len(self._blocklist_data.get(game, [])) != orig_len:
            self._save_blocklist()
            return True
        return False

    def get_all_games(self) -> List[str]:
        games = [g for g in self._blocklist_data.keys() if g != 'global']
        return games + ['global'] if 'global' in self._blocklist_data else games

    def is_mod_blocklisted(self, mod, game: str) -> bool:
        for entry in self.get_blocklist_for_game(game):
            pt, val = entry['prefix_type'], entry['value'].lower()
            if pt == self.PREFIX_TYPE_ID:
                mod_id = _getattr_first(mod, 'id', '_id')
                if mod_id and str(mod_id).lower() == val:
                    return True
                key = _getattr_first(mod, 'key', 'mod_key')
                if key and key.startswith('gb_') and key[3:].lower() == val:
                    return True
            elif pt == self.PREFIX_TYPE_NAME:
                mod_name = _getattr_first(mod, 'name', 'title')
                if mod_name and val in mod_name.lower():
                    return True
            elif pt == self.PREFIX_TYPE_CATEGORY:
                cat = _getattr_first(mod, 'category', 'cat_name', 'gamebanana_category')
                if cat and cat.lower() == val:
                    return True
        return False

    def get_prefix_type_display_name(self, prefix_type: str) -> str:
        return {self.PREFIX_TYPE_ID: tr('blocklist.prefix_type_id'), self.PREFIX_TYPE_NAME: tr('blocklist.prefix_type_name'), self.PREFIX_TYPE_CATEGORY: tr('blocklist.prefix_type_category')}.get(prefix_type, prefix_type)
