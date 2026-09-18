"""Centralized user-data migrations and legacy field mapping."""

from __future__ import annotations

import contextlib
import json
import logging
import shutil
from pathlib import Path
from typing import Any

from config.settings_schema import DEFAULT_APP_SETTINGS

logger = logging.getLogger(__name__)

LEGACY_DESCRIPTION_KEY = "tagline"
LEGACY_ICON_KEY = "icon_url"
LEGACY_MOD_ID_KEYS = ("key", "mod_key")
LEGACY_HOMEPAGE_KEYS = ("homepage", "external_url", "external_link", "site", "url")
LEGACY_THEME_COLOR_KEYS = {
    "custom_color_background": "custom_background_color",
    "custom_color_elements": "custom_elements_color",
    "custom_color_border": "custom_border_color",
    "custom_color_hover": "custom_hover_color",
    "custom_color_select": "custom_select_color",
    "custom_color_main_text": "custom_main_text_color",
    "custom_color_secondary_text": "custom_secondary_text_color",
    "custom_color_button": "custom_elements_color",
    "custom_color_button_hover": "custom_hover_color",
    "custom_color_button_select": "custom_select_color",
    "custom_color_text": "custom_main_text_color",
    "custom_color_version_text": "custom_secondary_text_color",
}


EXTRA_FILE_TARGET_GAME_FOLDER = "game_folder"
EXTRA_FILE_TARGET_GAME_DATA_FOLDER = "game_data_folder"
EXTRA_FILE_TARGET_NONE = "none"
EXTRA_FILE_TARGET_CUSTOM = "custom"
EXTRA_FILE_TARGETS = frozenset(
    {
        EXTRA_FILE_TARGET_GAME_FOLDER,
        EXTRA_FILE_TARGET_GAME_DATA_FOLDER,
        EXTRA_FILE_TARGET_NONE,
        EXTRA_FILE_TARGET_CUSTOM,
    }
)
_LEGACY_EXTRA_FILE_TARGETS = {
    "install": EXTRA_FILE_TARGET_GAME_FOLDER,
    "data": EXTRA_FILE_TARGET_GAME_DATA_FOLDER,
    "dependency": EXTRA_FILE_TARGET_NONE,
}


def normalize_extra_file_target(value: object) -> str:
    target = str(value or "").strip().lower()
    target = _LEGACY_EXTRA_FILE_TARGETS.get(target, target)
    return target if target in EXTRA_FILE_TARGETS else EXTRA_FILE_TARGET_NONE


def build_extra_file_entry(
    path: str,
    target: str = EXTRA_FILE_TARGET_GAME_FOLDER,
    target_path: str = "",
) -> dict[str, str]:
    entry = {
        "file_path": path,
        "target": normalize_extra_file_target(target),
    }
    if entry["target"] == EXTRA_FILE_TARGET_CUSTOM and target_path.strip():
        entry["target_path"] = target_path.strip()
    return entry


def infer_legacy_extra_file_target(game: str, path: str, target: str) -> str:
    if target != EXTRA_FILE_TARGET_GAME_FOLDER:
        return target
    normalized_path = str(path or "").replace("\\", "/").strip("/").lower()
    special_name = {
        "pizzatower": "towers",
        "frickbears3": "addons",
    }.get(str(game or "").lower())
    if not special_name:
        return target
    if normalized_path == special_name or normalized_path.startswith(
        f"{special_name}/"
    ):
        return EXTRA_FILE_TARGET_GAME_DATA_FOLDER
    archive_stem = (
        normalized_path[:-7]
        if normalized_path.endswith(".tar.gz")
        else normalized_path[:-9]
        if normalized_path.endswith(".tar.lzma")
        else Path(normalized_path).stem
    )
    if "/" not in normalized_path and archive_stem == special_name:
        return EXTRA_FILE_TARGET_GAME_DATA_FOLDER
    return target


LEGACY_CHAPTER_IDS = {
    "-1": "deltarune",
    "0": "deltarune_0",
    "1": "deltarune_1",
    "2": "deltarune_2",
    "3": "deltarune_3",
    "4": "deltarune_4",
    "5": "deltarune_5",
    "-10": "deltarunedemo",
    "-20": "undertale",
    "-30": "undertaleyellow",
    "-40": "pizzatower",
    "-50": "sugaryspire",
}


def migrate_theme_settings(settings: dict[str, Any]) -> bool:
    changed = False
    for legacy_key, current_key in LEGACY_THEME_COLOR_KEYS.items():
        if legacy_key not in settings:
            continue
        legacy_value = settings.pop(legacy_key, "")
        changed = True
        if legacy_value and not settings.get(current_key):
            settings[current_key] = legacy_value
    return changed


def normalize_theme_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of theme settings normalized from legacy keys to current keys."""
    normalized = dict(settings or {})
    migrate_theme_settings(normalized)
    return normalized


def migrate_settings_payload(local_config: dict[str, Any], app_version: str) -> bool:
    changed = False
    if local_config.get("cache_format_version") != app_version:
        local_config["cache_format_version"] = app_version
        changed = True
    if migrate_theme_settings(local_config):
        changed = True
    for key, value in DEFAULT_APP_SETTINGS.items():
        if key not in local_config:
            local_config[key] = value
            changed = True
    return changed


def migrate_legacy_chapter_id(chapter_id: str) -> str:
    return LEGACY_CHAPTER_IDS.get(str(chapter_id), str(chapter_id))


def migrate_mod_config_legacy_fields(config_data: dict[str, Any]) -> bool:
    if not isinstance(config_data, dict):
        return False
    changed = False
    metadata = config_data.get("metadata")
    if isinstance(metadata, dict) and migrate_mod_config_legacy_fields(metadata):
        changed = True

    description_value = config_data.get("description")
    if description_value in (None, "") and LEGACY_DESCRIPTION_KEY in config_data:
        description_value = config_data.get(LEGACY_DESCRIPTION_KEY)
    icon_value = config_data.get("icon")
    if icon_value in (None, "") and LEGACY_ICON_KEY in config_data:
        icon_value = config_data.get(LEGACY_ICON_KEY)
    homepage_value = config_data.get("homepage")
    if homepage_value in (None, ""):
        for legacy_key in LEGACY_HOMEPAGE_KEYS:
            if legacy_key in config_data and config_data.get(legacy_key) not in (
                None,
                "",
            ):
                homepage_value = config_data.get(legacy_key)
                break

    current_id = config_data.get("id")
    if not current_id:
        for legacy_key in LEGACY_MOD_ID_KEYS:
            legacy_id = config_data.get(legacy_key)
            if isinstance(legacy_id, str) and legacy_id.strip():
                config_data["id"] = legacy_id.strip()
                changed = True
                break

    normalized_items: list[tuple[str, Any]] = []
    seen_keys: set[str] = set()
    for key, value in config_data.items():
        if key == LEGACY_DESCRIPTION_KEY:
            key = "description"
            value = description_value
        elif key == LEGACY_ICON_KEY:
            key = "icon"
            value = icon_value
        elif key in LEGACY_MOD_ID_KEYS:
            key = "id"
            value = config_data.get("id", value)
        elif key in LEGACY_HOMEPAGE_KEYS:
            key = "homepage"
            value = homepage_value
        elif key == "description":
            value = description_value
        elif key == "icon":
            value = icon_value
        elif key == "homepage":
            value = homepage_value
        elif key == "files" and isinstance(value, dict):
            migrated_files = {}
            for file_key, file_info in value.items():
                migrated_key = migrate_legacy_chapter_id(file_key)
                migrated_info = file_info
                if isinstance(file_info, dict):
                    migrated_info = dict(file_info)
                    data_file_path = migrated_info.pop("data_file_url", None)
                    if data_file_path not in (None, "") and not migrated_info.get(
                        "data_file_path"
                    ):
                        migrated_info["data_file_path"] = data_file_path
                    extra_files = migrated_info.get("extra_files")
                    normalized_extra_files = []
                    if isinstance(extra_files, list):
                        for extra_file in extra_files:
                            if isinstance(extra_file, str):
                                file_path = extra_file
                            elif isinstance(extra_file, dict):
                                file_path = extra_file.get(
                                    "file_path"
                                ) or extra_file.get("url")
                            else:
                                continue
                            if not file_path:
                                continue
                            if isinstance(extra_file, dict):
                                target = (
                                    extra_file.get("target")
                                    or extra_file.get("status")
                                    or EXTRA_FILE_TARGET_GAME_FOLDER
                                )
                                target_path = str(
                                    extra_file.get("target_path") or ""
                                )
                            else:
                                target = EXTRA_FILE_TARGET_GAME_FOLDER
                                target_path = ""
                            normalized_extra_files.append(
                                build_extra_file_entry(file_path, target, target_path)
                            )
                    elif isinstance(extra_files, dict):
                        for filenames in extra_files.values():
                            if not isinstance(filenames, list):
                                continue
                            for file_path in filenames:
                                if file_path:
                                    normalized_extra_files.append(
                                        build_extra_file_entry(file_path)
                                    )
                    if normalized_extra_files:
                        migrated_info["extra_files"] = normalized_extra_files
                    elif extra_files not in (None, [], {}):
                        migrated_info["extra_files"] = []
                migrated_files[migrated_key] = migrated_info
            if migrated_files != value:
                changed = True
            value = migrated_files
        if key in seen_keys:
            changed = True
            continue
        seen_keys.add(key)
        normalized_items.append((key, value))
    if list(config_data.items()) != normalized_items:
        changed = True
    if changed:
        config_data.clear()
        config_data.update(normalized_items)
    return changed


def migrate_profile_settings(
    local_config: dict[str, Any],
    default_profile_path: Path,
    is_profile_key,
    write_profile,
) -> bool:
    if default_profile_path.exists():
        return False
    profile_data = {}
    for key in list(local_config.keys()):
        if is_profile_key(key):
            profile_data[key] = local_config.pop(key)
    if not profile_data:
        return False
    write_profile(profile_data)
    return True


def merge_dicts(dst: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge source dict into destination dict."""
    result = dst.copy()
    for key, value in src.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_dicts(result[key], value)
        else:
            result[key] = value
    return result


def merge_json_file(
    source: Path,
    target: Path,
    unique_child_path,
    logger: logging.Logger,
) -> None:
    try:
        source_data = json.loads(source.read_text("utf-8")) or {}
        target_data = json.loads(target.read_text("utf-8")) or {}
        if isinstance(source_data, dict) and isinstance(target_data, dict):
            merged_data = merge_dicts(target_data, source_data)
            target.write_text(
                json.dumps(merged_data, indent=2, ensure_ascii=False),
                "utf-8",
            )
            source.unlink(missing_ok=True)
            return
    except Exception as e:
        logger.warning("Profile migration merge failed %s -> %s: %s", source, target, e)
    shutil.move(str(source), unique_child_path(target))


def migrate_legacy_profile_mods(
    legacy_dir: Path,
    target_dir: Path,
    unique_child_path,
    logger: logging.Logger,
) -> bool:
    if not legacy_dir.exists() or not legacy_dir.is_dir():
        return False
    target_dir.mkdir(parents=True, exist_ok=True)
    migrated = False
    for source in list(legacy_dir.iterdir()):
        target = target_dir / source.name
        try:
            if target.exists():
                if source.name == "mods_data.json":
                    merge_json_file(source, target, unique_child_path, logger)
                else:
                    shutil.move(str(source), unique_child_path(target))
            else:
                shutil.move(str(source), str(target))
            migrated = True
        except Exception as e:
            logger.error(
                "Profile migration failed %s -> %s: %s",
                source,
                target,
                e,
            )
    with contextlib.suppress(OSError):
        legacy_dir.rmdir()
    return migrated


def find_imported_profile_json(
    directory: Path,
    ignored_names: set[str],
) -> Path | None:
    return next(
        (
            path
            for path in directory.iterdir()
            if path.is_file()
            and path.suffix.lower() == ".json"
            and path.name.lower() not in ignored_names
        ),
        None,
    )


def migrate_mod_metadata(
    config_data: dict[str, Any],
    mods_metadata: dict[str, dict[str, Any]],
) -> tuple[str | None, bool]:
    mod_id = config_data.get("id")
    if not mod_id:
        return None, False
    if not any(field in config_data for field in ("installed_date", "added_date")):
        return mod_id, False
    mod_metadata = mods_metadata.setdefault(mod_id, {})
    if "installed_date" in config_data:
        mod_metadata["added_date"] = config_data.pop("installed_date")
    elif "added_date" in config_data:
        mod_metadata["added_date"] = config_data.pop("added_date")
    return mod_id, True
