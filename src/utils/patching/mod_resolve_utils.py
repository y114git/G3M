"""Path resolution utilities for mod patching - resolves mod source dirs and game target dirs."""

import logging
import os
from typing import Any

from utils.file_utils import get_chapter_folder_name, load_json, sanitize_filename
from utils.mod_utils import get_mod_key, get_mod_name
from utils.patching import mod_content_utils as mod_content
from utils.path_utils import find_chapter_resource_dir

logger = logging.getLogger(__name__)


def resolve_mod_game(mod_data, source_dir=None):
    """Resolve the game type from mod_data attributes and optional source directory."""
    game = getattr(mod_data, "game", None) or getattr(mod_data, "modgame", None)
    if not game and hasattr(mod_data, "config_data"):
        config = mod_data.config_data
        if isinstance(config, dict):
            game = config.get("game") or config.get("modgame")
    if not game and source_dir:
        config_path = os.path.join(source_dir, "mod_config.json")
        if os.path.exists(config_path):
            try:
                config_data = load_json(config_path, migrate_config=True)
                game = config_data.get("game") or config_data.get("modgame")
            except Exception as e:
                logger.debug(
                    f"resolve_mod_game: failed to read config from {config_path}: {e}",
                    exc_info=True,
                )
    return game


def get_mod_source_dir(
    mod_data: Any, chapter_id: str, mod_service, app_state, caller_logger
) -> str | None:
    """Resolve the source directory for a mod's chapter content."""
    key = get_mod_key(mod_data)
    if not key:
        caller_logger.warning("_get_mod_source_dir: mod_data has no key")
        return None
    mod_folder_path = mod_service.get_mod_folder_path(key)
    if mod_folder_path and os.path.isdir(mod_folder_path):
        source_dir = mod_folder_path
    else:
        mod_name = get_mod_name(mod_data, key)
        folder_name = sanitize_filename(mod_name)
        source_dir = os.path.join(app_state.mods_dir, folder_name)
        if not os.path.isdir(source_dir):
            source_dir = None
            if os.path.exists(app_state.mods_dir):
                for folder_name in os.listdir(app_state.mods_dir):
                    folder_path = os.path.join(app_state.mods_dir, folder_name)
                    if not os.path.isdir(folder_path):
                        continue
                    config_path = os.path.join(folder_path, "mod_config.json")
                    if os.path.exists(config_path):
                        try:
                            config_data = load_json(config_path, migrate_config=True)
                            if (
                                config_data.get("key") or config_data.get("mod_key")
                            ) == key:
                                source_dir = folder_path
                                break
                        except Exception as e:
                            caller_logger.debug(
                                f"get_mod_source_dir: failed to inspect {config_path}: {e}",
                                exc_info=True,
                            )
            if not source_dir:
                return None
    game = resolve_mod_game(mod_data, source_dir)
    chapter_folder_name = get_chapter_folder_name(chapter_id, game=game)
    chapter_dir = os.path.join(source_dir, chapter_folder_name)
    if not os.path.isdir(chapter_dir):
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
    return chapter_dir


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
