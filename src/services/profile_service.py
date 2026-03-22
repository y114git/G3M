"""Library profiles management — stores per-profile library state in profiles/*.json."""

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal

from utils.path_utils import get_user_data_root

logger = logging.getLogger(__name__)


_SAFE_RE = re.compile(r"[^\w\- ]+")
DEFAULT_PROFILE = "Default"

PROFILE_STATIC_KEYS = frozenset(
    {
        "selected_game_type",
        "chapter_mode_enabled",
        "full_install_enabled",
        "direct_launch_chapter",
    }
)


def is_profile_key(key: str) -> bool:
    return key in PROFILE_STATIC_KEYS or key.startswith("used_mods_")


def _safe_filename(name: str) -> str:
    return _SAFE_RE.sub("_", name).strip()[:80] or DEFAULT_PROFILE


def _has_safe_profile_name(name: str) -> bool:
    return bool(_SAFE_RE.sub("_", name).strip()[:80])


class ProfileService(QObject):
    """Manages library profiles stored as JSON files in {user_data_root}/profiles/."""

    profile_switched = pyqtSignal(str)

    def __init__(self, app_state, settings_service, parent=None) -> None:
        super().__init__(parent)
        self.app_state = app_state
        self.settings_service = settings_service
        self.profiles_dir = os.path.join(get_user_data_root(), "profiles")
        self._active_name: str = DEFAULT_PROFILE

    def initialize(self):
        """Call after local_config is loaded and migrate_config_if_needed ran."""
        os.makedirs(self.profiles_dir, exist_ok=True)
        self._migrate_from_settings()
        self._ensure_default_exists()
        self._active_name = self.app_state.local_config.get(
            "active_profile", DEFAULT_PROFILE
        )
        if not self._profile_path(self._active_name).exists():
            self._active_name = DEFAULT_PROFILE
            self.app_state.local_config["active_profile"] = DEFAULT_PROFILE
        self._load_into_config(self._active_name)

    def _migrate_from_settings(self):
        """One-time: move profile keys from settings.json → default.json."""
        if self._profile_path(DEFAULT_PROFILE).exists():
            return
        profile_data: dict[str, Any] = {}
        for key in list(self.app_state.local_config.keys()):
            if is_profile_key(key):
                profile_data[key] = self.app_state.local_config.pop(key)
        self._write_profile(DEFAULT_PROFILE, profile_data)

    def _ensure_default_exists(self):
        if not self._profile_path(DEFAULT_PROFILE).exists():
            self._write_profile(DEFAULT_PROFILE, {"selected_game_type": "deltarune"})

    def _profile_path(self, name: str) -> Path:
        return Path(self.profiles_dir) / f"{_safe_filename(name)}.json"

    def _read_profile(self, name: str) -> dict[str, Any]:
        path = self._profile_path(name)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text("utf-8")) or {}
        except Exception as e:
            logger.error("ProfileService: failed to read %s: %s", path, e)
            return {}

    def _write_profile(self, name: str, data: dict[str, Any]):
        path = self._profile_path(name)
        try:
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")
        except Exception as e:
            logger.error("ProfileService: failed to write %s: %s", path, e)

    def _load_into_config(self, name: str):
        data = self._read_profile(name)
        for key, value in data.items():
            self.app_state.local_config[key] = value
        self.app_state.local_config.setdefault("selected_game_type", "deltarune")

    def _extract_profile_data_from_config(self) -> dict[str, Any]:
        result = {}
        for k, v in self.app_state.local_config.items():
            if not is_profile_key(k):
                continue
            if k.startswith("used_mods_") and isinstance(v, dict) and not v:
                continue
            result[k] = v
        return result

    def _strip_profile_keys_from_config(self):
        for key in [k for k in self.app_state.local_config if is_profile_key(k)]:
            del self.app_state.local_config[key]

    @property
    def active_name(self) -> str:
        return self._active_name

    def save_active(self):
        """Persist current profile keys from local_config to the active profile file."""
        existing = self._read_profile(self._active_name)
        extracted = self._extract_profile_data_from_config()
        existing.update(extracted)
        self._write_profile(self._active_name, existing)

    def save_settings_only(self):
        """Write local_config minus profile keys to settings.json."""
        data = {
            k: v
            for k, v in self.app_state.local_config.items()
            if not is_profile_key(k)
        }
        self.settings_service.write_json(self.app_state.config_path, data)

    def write_local_config(self):
        """Replacement for settings_service.write_local_config — splits data."""
        self.save_active()
        self.save_settings_only()

    def switch(self, name: str):
        """Save current, load new profile, emit signal."""
        if name == self._active_name:
            return
        self.save_active()
        self._strip_profile_keys_from_config()
        self._active_name = name
        self.app_state.local_config["active_profile"] = name
        self._load_into_config(name)
        self.save_settings_only()
        self.profile_switched.emit(name)

    def list_profiles(self) -> list[str]:
        """Return profile names in stored order."""
        order = self.app_state.local_config.get("profile_order", [])
        existing = {p.stem for p in Path(self.profiles_dir).glob("*.json")}
        result = []
        for name in order:
            if name in existing and name not in result:
                result.append(name)
        for name in sorted(existing):
            if name not in result:
                result.append(name)
        return result

    def get_profile_summary(self, name: str) -> dict[str, Any]:
        """Return a lightweight summary dict for display in the profile manager."""
        from models.game_modes import get_game

        data = self._read_profile(name)
        game = data.get("selected_game_type", "deltarune")
        game_def = get_game(game)
        display_name = game_def.display_name if game_def else game.upper()
        game_count = self._count_mods_for_game(data, game)
        total_count = self._count_all_mods(data)
        return {
            "name": name,
            "game": game,
            "game_display_name": display_name,
            "game_mod_count": game_count,
            "total_mod_count": total_count,
            "chapter_mode": data.get("chapter_mode_enabled", False),
            "direct_launch": data.get("direct_launch_chapter", ""),
        }

    def create(self, name: str) -> bool:
        name = name.strip()
        if (
            not name
            or not _has_safe_profile_name(name)
            or self._profile_path(name).exists()
        ):
            return False
        self._write_profile(name, {"selected_game_type": "deltarune"})
        self._append_to_order(name)
        return True

    def duplicate(self, source_name: str, new_name: str) -> bool:
        new_name = new_name.strip()
        if (
            not new_name
            or not _has_safe_profile_name(new_name)
            or self._profile_path(new_name).exists()
        ):
            return False
        data = self._read_profile(source_name)
        self._write_profile(new_name, data)
        self._append_to_order(new_name)
        return True

    def rename(self, old_name: str, new_name: str) -> bool:
        new_name = new_name.strip()
        if (
            old_name == DEFAULT_PROFILE
            or not new_name
            or not _has_safe_profile_name(new_name)
            or self._profile_path(new_name).exists()
        ):
            return False
        old_path = self._profile_path(old_name)
        if not old_path.exists():
            return False
        data = self._read_profile(old_name)
        self._write_profile(new_name, data)
        old_path.unlink(missing_ok=True)
        order = self.app_state.local_config.get("profile_order", [])
        self.app_state.local_config["profile_order"] = [
            new_name if n == old_name else n for n in order
        ]
        if self._active_name == old_name:
            self._active_name = new_name
            self.app_state.local_config["active_profile"] = new_name
        self.save_settings_only()
        return True

    def delete(self, name: str) -> bool:
        if name == DEFAULT_PROFILE:
            return False
        path = self._profile_path(name)
        if not path.exists():
            return False
        was_active = self._active_name == name
        path.unlink(missing_ok=True)
        order = self.app_state.local_config.get("profile_order", [])
        self.app_state.local_config["profile_order"] = [n for n in order if n != name]
        if was_active:
            self._strip_profile_keys_from_config()
            self._active_name = DEFAULT_PROFILE
            self.app_state.local_config["active_profile"] = DEFAULT_PROFILE
            self._load_into_config(DEFAULT_PROFILE)
            self.profile_switched.emit(DEFAULT_PROFILE)
        self.save_settings_only()
        return True

    def reorder(self, names: list[str]):
        """Set display order."""
        self.app_state.local_config["profile_order"] = list(names)
        self.save_settings_only()

    @staticmethod
    def _count_all_mods(data: dict[str, Any], prefix: str = "used_mods_") -> int:
        return sum(
            len(val) if isinstance(val, list) else 1
            for k, v in data.items()
            if k.startswith(prefix) and isinstance(v, dict)
            for val in v.values()
            if val
        )

    @staticmethod
    def _count_mods_for_game(data: dict[str, Any], game: str) -> int:
        return ProfileService._count_all_mods(data, f"used_mods_{game}")

    def _append_to_order(self, name: str):
        order = self.app_state.local_config.get("profile_order", [])
        if name not in order:
            order.append(name)
            self.app_state.local_config["profile_order"] = order
        self.save_settings_only()
