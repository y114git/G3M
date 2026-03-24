"""Helpers for Game Versions: base game folder, protected exe, safe archive naming."""

import os
import re

from config.config import CURRENT_PLATFORM

_SAFE_RE = re.compile(r"[^\w\-. ]+")


def get_base_game_folder(game_path: str) -> str | None:
    """Return the base game data folder. On macOS, resolve to Contents/Resources."""
    if not game_path or not os.path.exists(game_path):
        return None
    if CURRENT_PLATFORM == "Darwin":
        if game_path.endswith(".app"):
            resources = os.path.join(game_path, "Contents", "Resources")
        elif os.path.isdir(game_path):
            resources = game_path
            for app_name in os.listdir(game_path):
                if app_name.endswith(".app") and os.path.isdir(
                    os.path.join(game_path, app_name)
                ):
                    candidate = os.path.join(
                        game_path, app_name, "Contents", "Resources"
                    )
                    if os.path.isdir(candidate):
                        resources = candidate
                        break
        else:
            return None
        return resources if os.path.isdir(resources) else None
    return game_path if os.path.isdir(game_path) else None


def get_protected_exe_paths_with_config(
    base_folder: str, game_path: str, game_def, local_config: dict
) -> set[str]:
    """Return set of relative paths (to base_folder) that must never be archived/deleted/overwritten."""
    from utils.path_utils import resolve_game_executable

    protected = set()
    if not base_folder or not os.path.isdir(base_folder):
        return protected
    main_exe = resolve_game_executable(
        game_path, executable_type=game_def.game_id if game_def else "deltarune"
    )
    if main_exe and os.path.isfile(main_exe):
        try:
            rel = os.path.relpath(main_exe, base_folder)
            if not rel.startswith(".."):
                protected.add(rel.replace("\\", "/"))
        except ValueError:
            pass
    if game_def and local_config:
        custom_key = game_def.get_custom_exec_config_key()
        custom_path = local_config.get(custom_key, "") if custom_key else ""
        if custom_path and os.path.isfile(custom_path):
            try:
                rel = os.path.relpath(custom_path, base_folder)
                if not rel.startswith(".."):
                    protected.add(rel.replace("\\", "/"))
            except ValueError:
                pass
    return protected


def safe_archive_name(version_name: str) -> str:
    """Build <safe-name>.zip filename from user's version name."""
    safe = (
        _SAFE_RE.sub("_", version_name.strip()).strip(" .")[:80].strip(" .")
        or "version"
    )
    return f"{safe}.zip"


def unique_archive_path(versions_dir: str, version_name: str) -> str:
    """Return a unique archive path in versions_dir, appending _1, _2... if needed."""
    base_name = safe_archive_name(version_name)
    stem, ext = os.path.splitext(base_name)
    path = os.path.join(versions_dir, base_name)
    counter = 1
    while os.path.exists(path):
        path = os.path.join(versions_dir, f"{stem}_{counter}{ext}")
        counter += 1
    return path
