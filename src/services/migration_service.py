"""Centralized migration helpers."""

from __future__ import annotations

import contextlib
import json
import logging
import shutil
from pathlib import Path
from typing import Any

THEME_COLOR_SETTING_KEYS = {
    "background": "custom_background_color",
    "elements": "custom_elements_color",
    "border": "custom_border_color",
    "hover": "custom_hover_color",
    "select": "custom_select_color",
    "main_text": "custom_main_text_color",
    "secondary_text": "custom_secondary_text_color",
}
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
LEGACY_CHAPTER_IDS = {
    "-1": "deltarune",
    "0": "deltarune_0",
    "1": "deltarune_1",
    "2": "deltarune_2",
    "3": "deltarune_3",
    "4": "deltarune_4",
    "-10": "deltarunedemo",
    "-20": "undertale",
    "-30": "undertaleyellow",
    "-40": "pizzatower",
    "-50": "sugaryspire",
}
THEME_COLOR_KEY_ALIASES = {
    "text": "main_text",
    "version_text": "secondary_text",
}


def get_theme_color_setting(color_name: str) -> str:
    normalized_name = THEME_COLOR_KEY_ALIASES.get(color_name, color_name)
    return THEME_COLOR_SETTING_KEYS.get(
        normalized_name,
        f"custom_{normalized_name}_color",
    )


def migrate_theme_settings(settings: dict[str, Any]) -> bool:
    changed = False
    for legacy_key, key in LEGACY_THEME_COLOR_KEYS.items():
        if legacy_key not in settings:
            continue
        legacy_value = settings.pop(legacy_key, "")
        changed = True
        if legacy_value and not settings.get(key):
            settings[key] = legacy_value
    return changed


def migrate_settings_payload(
    local_config: dict[str, Any],
    app_version: str,
) -> None:
    local_config["cache_format_version"] = app_version
    migrate_theme_settings(local_config)
    defaults = {
        "game_path": "",
        "last_selected": {},
        "use_custom_executable": False,
        "demo_game_path": "",
        "launch_via_steam": False,
        "use_portproton": False,
        "portproton_path": "",
        "demo_mode_enabled": False,
        "custom_background_path": "",
        "custom_executable_path": "",
        "background_disabled": False,
        "disable_startup_sound": False,
        "custom_background_color": "",
        "custom_elements_color": "",
        "custom_border_color": "",
        "custom_hover_color": "",
        "custom_select_color": "",
        "custom_main_text_color": "",
        "custom_secondary_text_color": "",
        "beta_updates_enabled": False,
        "pizzatower_game_path": "",
        "pizzatower_custom_executable_path": "",
        "skip_patching_warnings": False,
        "merge_properties": False,
        "merge_code": False,
        "hide_mods_browser_tab": False,
        "hide_library_tab": False,
        "hide_library_filters": False,
        "show_reset_buttons": False,
        "custom_border_radius": 7,
        "downloads_no_auto_use": False,
        "downloads_delete_after_use": False,
        "downloads_save_local_imports": False,
    }
    for key, value in defaults.items():
        local_config.setdefault(key, value)


def migrate_profile_settings(
    local_config: dict[str, Any],
    default_profile_path: Path,
    is_profile_key,
    write_profile,
) -> None:
    if default_profile_path.exists():
        return
    profile_data = {}
    for key in list(local_config.keys()):
        if is_profile_key(key):
            profile_data[key] = local_config.pop(key)
    write_profile(profile_data)


def migrate_legacy_profile_mods(
    legacy_dir: Path,
    target_dir: Path,
    unique_child_path,
    logger: logging.Logger,
) -> None:
    if not legacy_dir.exists() or not legacy_dir.is_dir():
        return
    target_dir.mkdir(parents=True, exist_ok=True)
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
        except Exception as e:
            logger.error(
                "Profile migration failed %s -> %s: %s",
                source,
                target,
                e,
            )
    with contextlib.suppress(OSError):
        legacy_dir.rmdir()


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
            target.write_text(
                json.dumps(target_data | source_data, indent=2, ensure_ascii=False),
                "utf-8",
            )
            source.unlink(missing_ok=True)
            return
    except Exception as e:
        logger.warning("Profile migration merge failed %s -> %s: %s", source, target, e)
    shutil.move(str(source), unique_child_path(target))


def migrate_legacy_chapter_id(chapter_id: str) -> str:
    return LEGACY_CHAPTER_IDS.get(chapter_id, chapter_id)


def migrate_mod_metadata(
    config_data: dict[str, Any],
    mods_metadata: dict[str, dict[str, Any]],
) -> tuple[str | None, bool]:
    mod_id = config_data.get("id")
    if not mod_id:
        return None, False
    if not any(
        field in config_data
        for field in ("installed_date", "added_date")
    ):
        return mod_id, False
    mod_metadata = mods_metadata.setdefault(mod_id, {})
    if "installed_date" in config_data:
        mod_metadata["added_date"] = config_data.pop("installed_date")
    elif "added_date" in config_data:
        mod_metadata["added_date"] = config_data.pop("added_date")
    return mod_id, True
