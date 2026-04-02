"""Settings defaults and theme-key helpers."""

from __future__ import annotations

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

THEME_COLOR_NAME_ALIASES = {
    "text": "main_text",
    "version_text": "secondary_text",
}

DEFAULT_APP_SETTINGS = {
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
    "pause_background_music_unfocused": False,
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
    "analytics_opt_in_enabled": False,
    "downloads_no_auto_use": False,
    "downloads_delete_after_use": False,
    "downloads_save_local_imports": False,
}


def get_theme_color_key(color_name: str) -> str:
    normalized_name = THEME_COLOR_NAME_ALIASES.get(color_name, color_name)
    return THEME_COLOR_SETTING_KEYS.get(
        normalized_name,
        f"custom_{normalized_name}_color",
    )


def apply_settings_defaults(local_config: dict[str, Any], app_version: str) -> None:
    local_config["cache_format_version"] = app_version
    for key, value in DEFAULT_APP_SETTINGS.items():
        local_config.setdefault(key, value)
