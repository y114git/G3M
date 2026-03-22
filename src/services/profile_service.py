"""Library profiles management with per-profile mod storage."""

import contextlib
import json
import logging
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal

from config.constants import LEGACY_MOD_CONFIG_FILENAME, MOD_CONFIG_FILENAME
from utils.path_utils import (
    get_profile_mods_root,
    get_user_mods_dir,
    get_user_profiles_dir,
    safe_profile_name,
)

logger = logging.getLogger(__name__)

_SAFE_RE = re.compile(r"[^\w\- ]+")
DEFAULT_PROFILE = "Default"
UNNAMED_PROFILE = "Unnamed"

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


def _has_safe_profile_name(name: str) -> bool:
    return bool((name or "").strip()) and bool(_SAFE_RE.sub("_", name).strip()[:80])


class ProfileService(QObject):
    """Manages library profiles stored as folders in {user_data_root}/profiles/."""

    profile_switched = pyqtSignal(str)

    def __init__(self, app_state, settings_service, parent=None) -> None:
        super().__init__(parent)
        self.app_state = app_state
        self.settings_service = settings_service
        self.profiles_dir = get_user_profiles_dir()
        self._active_name = DEFAULT_PROFILE

    def initialize(self):
        """Call after local_config is loaded and migrate_config_if_needed ran."""
        os.makedirs(self.profiles_dir, exist_ok=True)
        self._migrate_from_settings()
        self._ensure_default_exists()
        self._active_name = safe_profile_name(
            self.app_state.local_config.get("active_profile", DEFAULT_PROFILE)
        )
        if not self._profile_path(self._active_name).exists():
            self._active_name = DEFAULT_PROFILE
            self.app_state.local_config["active_profile"] = DEFAULT_PROFILE
        self._apply_profile_paths(self._active_name)
        self._load_into_config(self._active_name)

    def _migrate_from_settings(self):
        """One-time: move profile keys from settings.json and legacy mods to Default."""
        if not self._profile_path(DEFAULT_PROFILE).exists():
            profile_data = {}
            for key in list(self.app_state.local_config.keys()):
                if is_profile_key(key):
                    profile_data[key] = self.app_state.local_config.pop(key)
            self._write_profile(DEFAULT_PROFILE, profile_data)
        self._migrate_legacy_mods()

    def _migrate_legacy_mods(self):
        legacy_dir = Path(get_user_mods_dir())
        if not legacy_dir.exists() or not legacy_dir.is_dir():
            return
        target_dir = self._profile_dir(DEFAULT_PROFILE)
        target_dir.mkdir(parents=True, exist_ok=True)
        for source in list(legacy_dir.iterdir()):
            target = target_dir / source.name
            try:
                if target.exists():
                    if source.name == "metadata.json":
                        self._merge_json_file(source, target)
                    else:
                        shutil.move(str(source), self._unique_child_path(target))
                else:
                    shutil.move(str(source), str(target))
            except Exception as e:
                logger.error(
                    "ProfileService: failed to migrate %s -> %s: %s",
                    source,
                    target,
                    e,
                )
        with contextlib.suppress(OSError):
            legacy_dir.rmdir()

    def _ensure_default_exists(self):
        if not self._profile_path(DEFAULT_PROFILE).exists():
            self._write_profile(DEFAULT_PROFILE, {"selected_game_type": "deltarune"})

    def _apply_profile_paths(self, name: str):
        profile_dir = self._profile_dir(name)
        profile_dir.mkdir(parents=True, exist_ok=True)
        self.app_state.mods_dir = get_profile_mods_root(name)
        self.app_state.mods_metadata_path = os.path.join(profile_dir, "metadata.json")

    def _profile_dir(self, name: str) -> Path:
        return Path(self.profiles_dir) / safe_profile_name(name)

    def _profile_path(self, name: str) -> Path:
        safe_name = safe_profile_name(name)
        return self._profile_dir(safe_name) / f"{safe_name}.json"

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
            path.parent.mkdir(parents=True, exist_ok=True)
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
        existing.update(self._extract_profile_data_from_config())
        self._write_profile(self._active_name, existing)

    def save_settings_only(self):
        """Write local_config minus profile keys to settings.json."""
        self.settings_service.write_json(
            self.app_state.config_path,
            {
                k: v
                for k, v in self.app_state.local_config.items()
                if not is_profile_key(k)
            },
        )

    def write_local_config(self):
        """Replacement for settings_service.write_local_config — splits data."""
        self.save_active()
        self.save_settings_only()

    def switch(self, name: str):
        """Save current, load new profile, emit signal."""
        name = safe_profile_name(name)
        if name == self._active_name or not self._profile_path(name).exists():
            return
        self.save_active()
        self._strip_profile_keys_from_config()
        self._active_name = name
        self.app_state.local_config["active_profile"] = name
        self._apply_profile_paths(name)
        self._load_into_config(name)
        self.save_settings_only()
        self.profile_switched.emit(name)

    def list_profiles(self) -> list[str]:
        """Return profile names in stored order."""
        order = self.app_state.local_config.get("profile_order", [])
        existing = {
            path.name
            for path in Path(self.profiles_dir).iterdir()
            if path.is_dir() and self._profile_path(path.name).exists()
        }
        result = []
        for name in map(safe_profile_name, order):
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
        return {
            "name": safe_profile_name(name),
            "game": game,
            "game_display_name": display_name,
            "game_mod_count": self._count_mods_for_game(data, game),
            "total_mod_count": self._count_all_mods(data),
            "profile_mod_count": self._count_profile_mods(name),
            "chapter_mode": data.get("chapter_mode_enabled", False),
            "direct_launch": data.get("direct_launch_chapter", ""),
        }

    def create(self, name: str) -> bool:
        name = safe_profile_name(name)
        if not _has_safe_profile_name(name) or self._profile_path(name).exists():
            return False
        self._write_profile(name, {"selected_game_type": "deltarune"})
        self._append_to_order(name)
        return True

    def duplicate(self, source_name: str, new_name: str) -> bool:
        new_name = safe_profile_name(new_name)
        source_name = safe_profile_name(source_name)
        source_dir = self._profile_dir(source_name)
        if (
            not _has_safe_profile_name(new_name)
            or self._profile_path(new_name).exists()
            or not source_dir.exists()
        ):
            return False
        try:
            if source_name == self._active_name:
                self.save_active()
            shutil.copytree(source_dir, self._profile_dir(new_name))
            source_path = self._profile_path(source_name)
            new_path = self._profile_path(new_name)
            if source_path.name != new_path.name:
                copied = new_path.parent / source_path.name
                if copied.exists():
                    copied.replace(new_path)
            if not new_path.exists():
                self._write_profile(new_name, self._read_profile(source_name))
            self._append_to_order(new_name)
            return True
        except Exception as e:
            logger.error("ProfileService: failed to duplicate %s: %s", source_name, e)
            return False

    def rename(self, old_name: str, new_name: str) -> bool:
        new_name = safe_profile_name(new_name)
        old_name = safe_profile_name(old_name)
        if (
            old_name == DEFAULT_PROFILE
            or not _has_safe_profile_name(new_name)
            or self._profile_path(new_name).exists()
        ):
            return False
        old_dir = self._profile_dir(old_name)
        if not old_dir.exists():
            return False
        try:
            if old_name == self._active_name:
                self.save_active()
            old_dir.replace(self._profile_dir(new_name))
            old_path = self._profile_path(new_name).parent / f"{old_name}.json"
            new_path = self._profile_path(new_name)
            if old_path.exists() and old_path != new_path:
                old_path.replace(new_path)
        except Exception as e:
            logger.error("ProfileService: failed to rename %s: %s", old_name, e)
            return False
        order = self.app_state.local_config.get("profile_order", [])
        self.app_state.local_config["profile_order"] = [
            new_name if safe_profile_name(n) == old_name else n for n in order
        ]
        if self._active_name == old_name:
            self._active_name = new_name
            self.app_state.local_config["active_profile"] = new_name
            self._apply_profile_paths(new_name)
        self.save_settings_only()
        return True

    def delete(self, name: str) -> bool:
        name = safe_profile_name(name)
        if name == DEFAULT_PROFILE:
            return False
        path = self._profile_dir(name)
        if not path.exists():
            return False
        was_active = self._active_name == name

        def _on_rm_error(func, path, exc_info):
            logger.warning("ProfileService: failed to remove %s: %s", path, exc_info[1])

        shutil.rmtree(path, onerror=_on_rm_error)
        self.app_state.local_config["profile_order"] = [
            n
            for n in self.app_state.local_config.get("profile_order", [])
            if safe_profile_name(n) != name
        ]
        if was_active:
            self._strip_profile_keys_from_config()
            self._active_name = DEFAULT_PROFILE
            self.app_state.local_config["active_profile"] = DEFAULT_PROFILE
            self._apply_profile_paths(DEFAULT_PROFILE)
            self._load_into_config(DEFAULT_PROFILE)
            self.profile_switched.emit(DEFAULT_PROFILE)
        self.save_settings_only()
        return True

    def reorder(self, names: list[str]):
        """Set display order."""
        self.app_state.local_config["profile_order"] = [
            safe_profile_name(n) for n in names
        ]
        self.save_settings_only()

    def export(self, name: str, target_path: str) -> bool:
        name = safe_profile_name(name)
        profile_dir = self._profile_dir(name)
        if not profile_dir.exists():
            return False
        if name == self._active_name:
            self.save_active()
        with zipfile.ZipFile(
            target_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9
        ) as zf:
            for root, _dirs, files in os.walk(profile_dir):
                for file_name in files:
                    file_path = os.path.join(root, file_name)
                    zf.write(file_path, os.path.relpath(file_path, profile_dir))
        return True

    def import_profile(self, archive_path: str) -> str:
        with tempfile.TemporaryDirectory(prefix="deltahub_profile_import_") as temp_dir:
            with zipfile.ZipFile(archive_path, "r") as zf:
                zf.extractall(temp_dir)
            import_root = self._resolve_import_root(Path(temp_dir))
            profile_json = self._find_profile_json(import_root)
            imported_name = profile_json.stem if profile_json else UNNAMED_PROFILE
            imported_name = self._next_available_name(imported_name)
            target_dir = self._profile_dir(imported_name)
            shutil.copytree(import_root, target_dir)
            target_json = self._profile_path(imported_name)
            if profile_json:
                copied_json = target_dir / profile_json.name
                if copied_json != target_json:
                    copied_json.replace(target_json)
            if not target_json.exists():
                self._write_profile(imported_name, {})
            self._append_to_order(imported_name)
            return imported_name

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

    def _count_profile_mods(self, name: str) -> int:
        profile_dir = self._profile_dir(name)
        if not profile_dir.exists():
            return 0
        return sum(
            1
            for child in profile_dir.iterdir()
            if child.is_dir()
            and (
                (child / MOD_CONFIG_FILENAME).exists()
                or (child / LEGACY_MOD_CONFIG_FILENAME).exists()
            )
        )

    def _append_to_order(self, name: str):
        order = [
            safe_profile_name(n)
            for n in self.app_state.local_config.get("profile_order", [])
        ]
        if name not in order:
            order.append(name)
            self.app_state.local_config["profile_order"] = order
        self.save_settings_only()

    def _next_available_name(self, name: str) -> str:
        base = safe_profile_name(name)
        candidate = base
        counter = 1
        while self._profile_dir(candidate).exists():
            candidate = f"{base}_{counter}"
            counter += 1
        return candidate

    @staticmethod
    def _find_profile_json(directory: Path) -> Path | None:
        return next(
            (
                path
                for path in directory.iterdir()
                if path.is_file()
                and path.suffix.lower() == ".json"
                and path.name.lower()
                not in {
                    "metadata.json",
                    MOD_CONFIG_FILENAME.lower(),
                    LEGACY_MOD_CONFIG_FILENAME.lower(),
                }
            ),
            None,
        )

    @staticmethod
    def _resolve_import_root(directory: Path) -> Path:
        entries = list(directory.iterdir())
        if len(entries) == 1 and entries[0].is_dir():
            return entries[0]
        return directory

    @staticmethod
    def _unique_child_path(path: Path) -> str:
        stem, suffix = path.stem, path.suffix
        counter = 1
        candidate = path
        while candidate.exists():
            candidate = path.with_name(f"{stem}_{counter}{suffix}")
            counter += 1
        return str(candidate)

    @staticmethod
    def _merge_json_file(source: Path, target: Path):
        try:
            source_data = json.loads(source.read_text("utf-8")) or {}
            target_data = json.loads(target.read_text("utf-8")) or {}
            if isinstance(source_data, dict) and isinstance(target_data, dict):
                target.write_text(
                    json.dumps(target_data | source_data, indent=2, ensure_ascii=False),
                    "utf-8",
                )
                source.unlink(missing_ok=True)
                return
        except Exception as e:
            logger.warning(
                "ProfileService: failed to merge %s into %s: %s", source, target, e
            )
        shutil.move(str(source), ProfileService._unique_child_path(target))
