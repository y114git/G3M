"""Path resolution utilities for mod patching - resolves mod source dirs and game target dirs."""

import logging
import os
from typing import Any

from utils.file_utils import get_chapter_folder_name, load_json, normalize_chapter_id
from utils.mod_config_parser import normalize_mod_config_data, resolve_mod_file_path
from utils.mod_utils import get_mod_id, get_mod_name
from utils.patching import mod_content_utils as mod_content
from utils.path_utils import find_chapter_resource_dir

logger = logging.getLogger(__name__)


def resolve_mod_game(mod_data, source_dir=None):
    """Resolve the game type from mod_data attributes and optional source directory."""
    game = getattr(mod_data, "game", None)
    if not game and hasattr(mod_data, "config_data"):
        config = mod_data.config_data
        if isinstance(config, dict):
            game = config.get("game")
    if not game and source_dir:
        config_path = os.path.join(source_dir, "mod_config.json")
        if os.path.exists(config_path):
            try:
                config_data = load_json(config_path)
                game = config_data.get("game")
            except Exception as e:
                logger.debug(
                    f"resolve_mod_game: failed to read config from {config_path}: {e}",
                    exc_info=True,
                )
    return game


def _resolve_mod_root_dir(
    mod_data: Any, mod_service, app_state, caller_logger
) -> tuple[str | None, str | None]:
    mod_id = get_mod_id(mod_data)
    if not mod_id:
        caller_logger.warning("_get_mod_source_dir: mod_data has no id")
        return None, None
    mod_folder_path = mod_service.get_mod_folder_path(mod_id)
    if mod_folder_path and os.path.isdir(mod_folder_path):
        return mod_id, mod_folder_path
    if os.path.isdir(app_state.mods_dir):
        for folder_name in os.listdir(app_state.mods_dir):
            folder_path = os.path.join(app_state.mods_dir, folder_name)
            if not os.path.isdir(folder_path):
                continue
            config_path = os.path.join(folder_path, "mod_config.json")
            if os.path.exists(config_path):
                try:
                    config_data = load_json(config_path)
                    if config_data.get("id") == mod_id:
                        return mod_id, folder_path
                except Exception as e:
                    caller_logger.debug(
                        f"get_mod_source_dir: failed to inspect {config_path}: {e}",
                        exc_info=True,
                    )
    caller_logger.warning(
        "_get_mod_source_dir: source dir not found for mod_id=%s mod_name=%s",
        mod_id,
        get_mod_name(mod_data, mod_id),
    )
    return mod_id, None


def _load_chapter_config_entry(source_dir: str, mod_data: Any, chapter_id: str) -> dict:
    config_path = os.path.join(source_dir, "mod_config.json")
    if not os.path.exists(config_path):
        return {}
    try:
        config_data = load_json(config_path)
        normalize_mod_config_data(config_data, mod_root_path=source_dir)
        game = resolve_mod_game(mod_data, source_dir)
        normalized_id = normalize_chapter_id(chapter_id, game)
        files_data = config_data.get("files", {})
        chapter_info = files_data.get(normalized_id) or files_data.get(chapter_id)
        return chapter_info if isinstance(chapter_info, dict) else {}
    except Exception as e:
        logger.debug(
            "Failed to load chapter config entry for %s from %s: %s",
            chapter_id,
            config_path,
            e,
            exc_info=True,
        )
        return {}


def _get_configured_chapter_dir(source_dir: str, mod_data: Any, chapter_id: str) -> str | None:
    chapter_info = _load_chapter_config_entry(source_dir, mod_data, chapter_id)
    if not chapter_info:
        return None

    candidate_dirs: list[str] = []
    configured_paths = []
    data_file_path = chapter_info.get("data_file_path") or chapter_info.get("data_file_url")
    if isinstance(data_file_path, str) and data_file_path.strip():
        configured_paths.append(data_file_path)
    extra_files = chapter_info.get("extra_files")
    if isinstance(extra_files, list):
        configured_paths.extend(
            path for path in extra_files if isinstance(path, str) and path.strip()
        )

    for rel_path in configured_paths:
        resolved_path = resolve_mod_file_path(source_dir, rel_path)
        if not resolved_path:
            continue
        candidate_dir = (
            resolved_path
            if os.path.isdir(resolved_path)
            else os.path.dirname(resolved_path)
        )
        if candidate_dir:
            candidate_dirs.append(os.path.normpath(candidate_dir))

    if not candidate_dirs:
        return None

    try:
        common_dir = os.path.commonpath(candidate_dirs)
        return common_dir if os.path.isdir(common_dir) else None
    except ValueError:
        return None


def get_mod_configured_data_file(
    mod_data: Any, chapter_id: str, mod_service, app_state, caller_logger
) -> str | None:
    mod_id, source_dir = _resolve_mod_root_dir(
        mod_data, mod_service, app_state, caller_logger
    )
    if not mod_id or not source_dir:
        return None
    configured_path = None
    if hasattr(mod_data, "get_chapter_data"):
        try:
            chapter_data = mod_data.get_chapter_data(chapter_id)
        except Exception as e:
            caller_logger.debug(
                f"get_mod_configured_data_file: get_chapter_data failed for {mod_id}: {e}",
                exc_info=True,
            )
            chapter_data = None
        if chapter_data:
            configured_path = getattr(chapter_data, "data_file_path", None) or getattr(
                chapter_data, "data_file_url", None
            )
    if not configured_path:
        chapter_info = _load_chapter_config_entry(source_dir, mod_data, chapter_id)
        configured_path = chapter_info.get("data_file_path") or chapter_info.get(
            "data_file_url"
        )
    resolved_path = resolve_mod_file_path(source_dir, configured_path)
    return resolved_path or None


def get_mod_configured_extra_files(
    mod_data: Any, chapter_id: str, mod_service, app_state, caller_logger
) -> list[str]:
    source_dir = _resolve_mod_root_dir(
        mod_data, mod_service, app_state, caller_logger
    )[1]
    if not source_dir:
        return []

    configured_paths: list[str] = []
    if hasattr(mod_data, "get_chapter_data"):
        try:
            chapter_data = mod_data.get_chapter_data(chapter_id)
        except Exception as e:
            caller_logger.debug(
                "get_mod_configured_extra_files: get_chapter_data failed for %s: %s",
                chapter_id,
                e,
                exc_info=True,
            )
            chapter_data = None
        if chapter_data:
            configured_paths.extend(
                str(path)
                for path in getattr(chapter_data, "extra_files", []) or []
                if isinstance(path, str) and path.strip()
            )
    if not configured_paths:
        chapter_info = _load_chapter_config_entry(source_dir, mod_data, chapter_id)
        configured_paths.extend(
            str(path)
            for path in chapter_info.get("extra_files", []) or []
            if isinstance(path, str) and path.strip()
        )
    return configured_paths


def has_mod_configured_chapter_entry(
    mod_data: Any, chapter_id: str, mod_service, app_state, caller_logger
) -> bool:
    source_dir = _resolve_mod_root_dir(
        mod_data, mod_service, app_state, caller_logger
    )[1]
    if not source_dir:
        return False
    return bool(_load_chapter_config_entry(source_dir, mod_data, chapter_id))


def get_mod_source_dir(
    mod_data: Any, chapter_id: str, mod_service, app_state, caller_logger
) -> str | None:
    """Resolve the source directory for a mod's chapter content."""
    source_dir = _resolve_mod_root_dir(
        mod_data, mod_service, app_state, caller_logger
    )[1]
    if not source_dir:
        return None
    game = resolve_mod_game(mod_data, source_dir)
    chapter_folder_name = get_chapter_folder_name(chapter_id, game=game)
    chapter_dir = os.path.join(source_dir, chapter_folder_name)
    if os.path.isdir(chapter_dir):
        return chapter_dir

    alt_dirs = []
    if chapter_folder_name.startswith("chapter_"):
        alt_dirs.append(os.path.join(source_dir, chapter_folder_name.replace("chapter_", "chapter", 1)))
    alt_dirs.append(_get_configured_chapter_dir(source_dir, mod_data, chapter_id))

    for alt_dir in alt_dirs:
        if alt_dir and os.path.isdir(alt_dir):
            return alt_dir

    if chapter_id.endswith("_0"):
        if game == "pizzatower":
            pizzatower_dir = os.path.join(source_dir, "pizzatower")
            if os.path.isdir(pizzatower_dir):
                return pizzatower_dir
        alt_menu_dir = os.path.join(source_dir, "menu")
        if os.path.isdir(alt_menu_dir):
            return alt_menu_dir
    elif "_" not in str(chapter_id):
        return source_dir
    return None


def get_target_dir(
    chapter_id: str, app_state, logger, game: str | None = None
) -> str | None:
    """Resolve the target directory (game install path) for a chapter."""
    from models.game_modes import get_game

    def _try_macos_resolve(gm, base_path):
        """For non-multi-tab games, resolve macOS .app path if chapter matches."""
        if not gm or gm.is_multi_tab or not gm.macos_app_names:
            return None
        match_ids = {gm.default_tab_id} | {t.tab_id for t in gm.tabs}
        if chapter_id in match_ids:
            return mod_content.resolve_macos_path(base_path, gm.macos_app_names[0])
        return None

    if game:
        game_id = game.replace("_", "") if "_" in game else game
        gm = get_game(game_id)
        if gm:
            base_path = gm.get_game_path(app_state.local_config)
            if not base_path:
                logger.warning(
                    f"{game} game path not found in config for chapter {chapter_id}"
                )
                return None
            resolved = _try_macos_resolve(gm, base_path)
            if resolved:
                return resolved
        else:
            base_path = app_state.game_path
            if not base_path:
                return None
    else:
        gm = app_state.game_mode
        base_path = gm.get_game_path(app_state.local_config)
        if not base_path:
            return None
        resolved = _try_macos_resolve(gm, base_path)
        if resolved:
            return resolved
    mac_names = gm.macos_app_names if gm else ("DELTARUNE.app", "DELTARUNEdemo.app")
    return find_chapter_resource_dir(base_path, chapter_id, mac_names)
