"""Target resolution helpers for manual install flows."""

import logging
import os
from collections.abc import Callable

from utils.path_utils import find_chapter_resource_dir

logger = logging.getLogger(__name__)


def resolve_target_root_for_chapter(
    game_root: str,
    chapter_id: str,
    game_def,
    *,
    find_chapter_resource_dir_fn: Callable[..., str | None] = find_chapter_resource_dir,
) -> str | None:
    if not game_def or not game_def.is_multi_tab:
        return game_root
    chapter_root = find_chapter_resource_dir_fn(
        game_root,
        chapter_id,
        getattr(game_def, "macos_app_names", ("DELTARUNE.app", "DELTARUNEdemo.app")),
    )
    return chapter_root or game_root


def read_configured_game_root(game_def, local_config: dict | None) -> str | None:
    if not game_def or local_config is None:
        return None
    try:
        return game_def.get_game_path(local_config)
    except Exception:
        return None


def get_or_prompt_game_folder(
    *,
    app_state,
    game_def,
    settings_service,
    path_exists: Callable[[str], bool] = os.path.exists,
    logger: logging.Logger | None = None,
) -> str | None:
    game_root = None
    local_config = getattr(app_state, "local_config", None)
    if game_def:
        try:
            game_root = game_def.get_game_path(local_config)
        except Exception as e:
            if logger is not None:
                logger.debug(
                    f"ManualInstallDialog: Failed to get game path: {e}",
                    exc_info=True,
                )
    if game_root and path_exists(game_root):
        return game_root
    if not settings_service or not game_def or app_state is None:
        return None

    old_game_mode = getattr(app_state, "game_mode", None)
    app_state.game_mode = game_def
    try:
        prompted = settings_service.prompt_for_game_path(is_initial=False)
    finally:
        app_state.game_mode = old_game_mode
    if not prompted:
        return None

    try:
        game_root = game_def.get_game_path(local_config)
    except Exception as e:
        if logger is not None:
            logger.debug(
                f"ManualInstallDialog: Failed to get game path after prompt: {e}",
                exc_info=True,
            )
        return None
    return game_root if game_root and path_exists(game_root) else None
