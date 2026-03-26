"""Mod blocklist management."""

import json
import logging
from pathlib import Path

from services.localization_service import tr
from utils.path_utils import get_user_data_root

logger = logging.getLogger(__name__)


def _getattr_first(obj, *attrs, default=None):
    return next(
        (v for attr in attrs if (v := getattr(obj, attr, None)) is not None), default
    )


class BlocklistManager:
    """Manages mod blocklist for filtering unwanted mods."""

    PREFIX_TYPE_ID, PREFIX_TYPE_NAME, PREFIX_TYPE_CATEGORY = "id", "name", "category"

    def __init__(self, config_path=None) -> None:
        self.config_path = config_path or (
            Path(get_user_data_root()) / "settings" / "blocklist.json"
        )
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self._blocklist_data = {}
        self._load_blocklist()

    def _set_default_blocklist(self):
        self._blocklist_data = {"global": []}

    def _load_blocklist(self):
        try:
            if self.config_path.exists():
                with open(self.config_path, encoding="utf-8") as f:
                    self._blocklist_data = json.load(f)
            else:
                self._set_default_blocklist()
        except Exception as e:
            logger.error(
                f"BlocklistManager: Error loading blocklist: {e}", exc_info=True
            )
            self._set_default_blocklist()

    def _save_blocklist(self):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self._blocklist_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(
                f"BlocklistManager: Error saving blocklist: {e}", exc_info=True
            )

    def get_blocklist_for_game(self, game):
        return self._blocklist_data.get(game, []) + self._blocklist_data.get(
            "global", []
        )

    def add_blocklist_entry(self, game, prefix_type, value):
        self._blocklist_data.setdefault(game, [])
        if not any(
            e["prefix_type"] == prefix_type and e["value"] == value
            for e in self._blocklist_data[game]
        ):
            self._blocklist_data[game].append(
                {"prefix_type": prefix_type, "value": value}
            )
            self._save_blocklist()

    def remove_blocklist_entry(self, game, prefix_type, value):
        if game not in self._blocklist_data:
            return False
        orig_len = len(self._blocklist_data[game])
        self._blocklist_data[game] = [
            e
            for e in self._blocklist_data[game]
            if not (e["prefix_type"] == prefix_type and e["value"] == value)
        ]
        if not self._blocklist_data[game] and game != "global":
            del self._blocklist_data[game]
        if len(self._blocklist_data.get(game, [])) != orig_len:
            self._save_blocklist()
            return True
        return False

    def get_all_games(self):
        games = [g for g in self._blocklist_data if g != "global"]
        return games + (["global"] if "global" in self._blocklist_data else [])

    def is_mod_blocklisted(self, mod, game):
        for entry in self.get_blocklist_for_game(game):
            pt, val = entry["prefix_type"], entry["value"].lower()
            if pt == self.PREFIX_TYPE_ID:
                if (mod_id := _getattr_first(mod, "id", "_id")) and str(
                    mod_id
                ).lower() == val:
                    return True
                if (key := _getattr_first(mod, "id")) and key.startswith("gb_"):
                    from utils.mod_utils import parse_gamebanana_mod_id

                    _, gb_id = parse_gamebanana_mod_id(key)
                    if gb_id and gb_id.lower() == val:
                        return True
            elif pt == self.PREFIX_TYPE_NAME:
                if (n := _getattr_first(mod, "name", "title")) and val in n.lower():
                    return True
            elif pt == self.PREFIX_TYPE_CATEGORY:
                if (
                    c := _getattr_first(
                        mod, "category", "cat_name", "gamebanana_category"
                    )
                ) and c.lower() == val:
                    return True
            else:
                continue
        return False

    def get_prefix_type_display_name(self, prefix_type):
        return {
            self.PREFIX_TYPE_ID: tr("blocklist.prefix_type_id"),
            self.PREFIX_TYPE_NAME: tr("blocklist.prefix_type_name"),
            self.PREFIX_TYPE_CATEGORY: tr("blocklist.prefix_type_category"),
        }.get(prefix_type, prefix_type)
