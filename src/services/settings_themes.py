"""Theme archive helpers for settings workflows."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile

from config.config import THEME_CONFIG_FILENAME, THEME_CONFIG_FILENAMES
from services.migration_service import normalize_theme_settings
from utils.path_utils import find_theme_config_path, get_user_themes_dir, resource_path


def theme_archive_contains_config(theme_file_path: str) -> bool:
    with zipfile.ZipFile(theme_file_path, "r") as zipf:
        archive_names = set(zipf.namelist())
        return any(
            name in archive_names
            or any(archived_name.endswith(f"/{name}") for archived_name in archive_names)
            for name in THEME_CONFIG_FILENAMES
        )


def maybe_copy_theme_archive(theme_file_path: str, parent_widget) -> None:
    theme_dir_abs = os.path.normcase(
        os.path.normpath(os.path.dirname(os.path.abspath(theme_file_path)))
    )
    bundled_dirs = (
        os.path.normcase(os.path.normpath(os.path.abspath(d)))
        for d in (resource_path("assets/themes"), get_user_themes_dir())
    )
    if theme_dir_abs in bundled_dirs:
        return
    checkbox = getattr(parent_widget, "do_not_save_theme_checkbox", None)
    if checkbox and checkbox.isChecked():
        return
    destination = os.path.join(get_user_themes_dir(), os.path.basename(theme_file_path))
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    shutil.copy2(theme_file_path, destination)
    if hasattr(parent_widget, "theme"):
        parent_widget.theme.init_theme_list()


def apply_theme_archive(
    *,
    app_state,
    theme_file_path: str,
    remove_files,
    get_audio_paths,
    remove_logo_files,
    remove_font_files,
) -> None:
    from utils.archive_utils import extract_any_archive, unwrap_single_directory_chain

    with tempfile.TemporaryDirectory() as temp_dir:
        extract_any_archive(theme_file_path, temp_dir)
        content_root = unwrap_single_directory_chain(temp_dir)
        theme_json_path = find_theme_config_path(content_root)
        if not theme_json_path:
            raise FileNotFoundError(
                f"{THEME_CONFIG_FILENAME} not found in extracted archive"
            )
        with open(theme_json_path, encoding="utf-8") as handle:
            theme_settings = normalize_theme_settings(json.load(handle))
        for key, value in theme_settings.items():
            if key != "config_version":
                app_state.local_config[key] = value
        app_state.local_config["active_theme_name"] = os.path.splitext(
            os.path.basename(theme_file_path)
        )[0]

        for base in ("background_music", "startup_sound"):
            remove_files(get_audio_paths(base))
        remove_logo_files()
        remove_font_files()
        app_state.local_config["custom_background_path"] = ""

        asset_prefixes = {
            "background.": "custom_background",
            "background_music.": "custom_background_music",
            "startup_sound.": "custom_startup_sound",
            "custom_logo.": "custom_logo",
            "custom_font.": "custom_font",
        }

        for filename in os.listdir(content_root):
            for prefix, dest_name in asset_prefixes.items():
                if filename.startswith(prefix):
                    extension = os.path.splitext(filename)[1]
                    destination = os.path.join(
                        app_state.config_dir, f"{dest_name}{extension}"
                    )
                    shutil.copy2(os.path.join(content_root, filename), destination)
                    if prefix == "background.":
                        app_state.local_config["custom_background_path"] = destination
                    break
