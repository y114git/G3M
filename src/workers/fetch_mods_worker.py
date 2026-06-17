"""Worker thread for fetching mod lists from remote sources."""

import json
import logging
import os
from typing import Any

from PyQt6.QtCore import QThread, pyqtSignal

from config.config import GAMEBANANA_PER_PAGE, UI_COLORS
from models.game_modes import get_gamebanana_game_ids
from models.mod_models import AnyModInfo, BrowserModInfo
from services.localization_service import tr
from utils.mod.utils import get_mod_id

logger = logging.getLogger(__name__)


def _safe_emit(owner: str, signal, *args) -> None:
    try:
        signal.emit(*args)
    except Exception as e:
        logger.warning("%s: failed to emit signal: %s", owner, e, exc_info=True)


class FetchModsThread(QThread):
    """Background thread for fetching mod lists from remote sources."""

    result = pyqtSignal(bool)
    status = pyqtSignal(str, str)

    def __init__(self, main_window_or_context, force_update=False, parent=None) -> None:
        super().__init__(parent)
        if hasattr(main_window_or_context, "app_state"):
            self.main_window = main_window_or_context
        else:
            self.main_window = type(
                "MainWindowProxy",
                (),
                {
                    "app_state": main_window_or_context.app_state,
                    "settings_service": main_window_or_context.settings_service,
                },
            )()
        self.force_update = force_update

    def run(self):
        try:
            logger.info("FetchModsThread: Starting mod fetch")
            all_mods = []
            try:
                logger.info("FetchModsThread: Starting GameBanana fetch")
                sort_param = "relevant"
                app_state = getattr(self.main_window, "app_state", None)
                if app_state:
                    sort_index = (
                        app_state.local_config.get("search_sort_index", 0)
                        if hasattr(app_state, "local_config")
                        else 0
                    )
                    sort_param = (
                        ["relevant", "new", "updated"][sort_index]
                        if sort_index in (0, 1, 2)
                        else "relevant"
                    )

                class GameBananaFetcher:
                    def __init__(self, sort_param="relevant", app_state=None) -> None:
                        self.all_mods = []
                        self.api = None
                        self.sort_param = sort_param
                        self.app_state = app_state
                        self.status: Any | None = None

                    def fetch_mods(self, initial_pages: int = 3):
                        from adapters.gamebanana_adapter import GameBananaAPI

                        self.api = GameBananaAPI()
                        selected_game = "deltarune"
                        if self.app_state and hasattr(self.app_state, "local_config"):
                            selected_game = self.app_state.local_config.get(
                                "selected_search_game", "deltarune"
                            )
                        gamebanana_game = selected_game
                        gamebanana_ids = get_gamebanana_game_ids()
                        if not gamebanana_ids:
                            return self.all_mods
                        if gamebanana_game not in gamebanana_ids:
                            logger.warning(
                                f"GameBananaFetcher: Unknown game {gamebanana_game}, defaulting to first searchable game"
                            )
                            gamebanana_game = next(iter(gamebanana_ids))
                        game_id = gamebanana_ids[gamebanana_game]
                        logger.info(
                            f"GameBananaFetcher.fetch_mods: Starting fetch for {selected_game} (GameBanana: {gamebanana_game}) with sort={self.sort_param}, initial_pages={initial_pages}"
                        )
                        if hasattr(self, "status") and self.status:
                            self.status(
                                tr(
                                    "status.fetching_gamebanana_mods",
                                    game=gamebanana_game.upper(),
                                ),
                                UI_COLORS["status_info"],
                            )
                        game_mods = self._fetch_game_mods(
                            game_id,
                            start_page=1,
                            num_pages=initial_pages,
                            sort=self.sort_param,
                        )
                        if game_mods:
                            self.all_mods.extend(game_mods)
                            logger.info(
                                f"GameBananaFetcher: Fetched {len(game_mods)} mods for {gamebanana_game} (pages 1-{initial_pages})"
                            )
                        logger.info(
                            f"GameBananaFetcher.fetch_mods: Total fetched {len(self.all_mods)} mods"
                        )
                        return self.all_mods

                    def _fetch_game_mods(
                        self,
                        game_id: int,
                        start_page: int = 1,
                        num_pages: int = 3,
                        sort: str = "relevant",
                    ) -> list[BrowserModInfo]:
                        mods = []
                        try:
                            if not self.api:
                                return mods
                            for page in range(start_page, start_page + num_pages):
                                mods_data, _ = self.api.get_game_mods(
                                    game_id,
                                    page=page,
                                    per_page=GAMEBANANA_PER_PAGE,
                                    sort=sort,
                                    app_state=self.app_state,
                                )
                                if not mods_data:
                                    break
                                for mod_info in mods_data:
                                    if mod_info:
                                        mods.append(mod_info)
                                if len(mods_data) < GAMEBANANA_PER_PAGE:
                                    break
                        except Exception as e:
                            logger.error(
                                f"Error fetching GameBanana mods: {e}", exc_info=True
                            )
                        return mods

                fetcher = GameBananaFetcher(sort_param=sort_param, app_state=app_state)

                fetcher.status = lambda msg, color: _safe_emit(
                    self.__class__.__name__, self.status, msg, color
                )
                initial_pages = 3
                gamebanana_mods = fetcher.fetch_mods(initial_pages=initial_pages)
                if gamebanana_mods:
                    all_mods.extend(gamebanana_mods)
                    logger.info(
                        f"FetchModsThread: Added {len(gamebanana_mods)} GameBanana mods to list"
                    )
                    app_state = getattr(self.main_window, "app_state", None)
                    if app_state:
                        selected_game = (
                            app_state.local_config.get(
                                "selected_search_game", "deltarune"
                            )
                            if hasattr(app_state, "local_config")
                            else "deltarune"
                        )
                        gamebanana_game = selected_game
                        gamebanana_ids = get_gamebanana_game_ids()
                        if gamebanana_game in gamebanana_ids:
                            game_id = gamebanana_ids[gamebanana_game]
                            game_mods_count = len(gamebanana_mods)
                            pages_loaded = (
                                (game_mods_count - 1) // GAMEBANANA_PER_PAGE + 1
                                if game_mods_count > 0
                                else initial_pages
                            )
                            app_state.gamebanana_loaded_pages[game_id] = pages_loaded
            except Exception as e:
                logger.error(
                    f"FetchModsThread: Failed to fetch GameBanana mods: {e}",
                    exc_info=True,
                )
            local_mods = self._get_local_mods()
            mod_service = getattr(self.main_window, "mod_service", None)
            installed_mods_with_files = {}
            if mod_service:
                try:
                    for installed_mod in mod_service.get_installed_mods_list():
                        mod_id = installed_mod.get("id")
                        if mod_id and installed_mod.get("files"):
                            installed_mods_with_files[mod_id] = installed_mod
                except Exception as e:
                    logger.warning(
                        f"FetchModsThread: Error getting installed mods: {e}"
                    )
            existing_mods_with_files = {}
            app_state = getattr(self.main_window, "app_state", None)
            if app_state and hasattr(app_state, "all_mods"):
                for mod in app_state.all_mods:
                    mod_id = get_mod_id(mod)
                    if mod_id and hasattr(mod, "files") and mod.files:
                        existing_mods_with_files[mod_id] = mod
            all_mods_filtered = []
            for mod in all_mods:
                mod_id = get_mod_id(mod)
                is_local_mod_id = (
                    mod_id and isinstance(mod_id, str) and mod_id.startswith("local_")
                )
                if is_local_mod_id:
                    continue
                is_gamebanana_mod = mod_id and mod_id.startswith("gb_")
                if is_gamebanana_mod and (
                    mod_id in existing_mods_with_files
                    or mod_id in installed_mods_with_files
                ):
                    if mod_id in existing_mods_with_files:
                        existing_mod = existing_mods_with_files[mod_id]
                        if hasattr(existing_mod, "files") and existing_mod.files:
                            mod.files = existing_mod.files
                    elif mod_id in installed_mods_with_files:
                        installed_mod_config = installed_mods_with_files[mod_id]
                        if installed_mod_config.get("files"):
                            mod_service = getattr(self.main_window, "mod_service", None)
                            if mod_service:
                                try:
                                    temp_mod = mod_service.create_mod_object_from_info(
                                        installed_mod_config, []
                                    )
                                    if hasattr(temp_mod, "files") and temp_mod.files:
                                        mod.files = temp_mod.files
                                except Exception as e:
                                    logger.debug(
                                        f"Failed to load files for installed mod {mod_id}: {e}"
                                    )
                    all_mods_filtered.append(mod)
                elif mod_id and mod_id in existing_mods_with_files:
                    existing_mod = existing_mods_with_files[mod_id]
                    if hasattr(existing_mod, "files") and existing_mod.files:
                        mod.files = existing_mod.files
                    all_mods_filtered.append(mod)
                elif mod_id and mod_id in installed_mods_with_files:
                    installed_mod_config = installed_mods_with_files[mod_id]
                    mod_service = getattr(self.main_window, "mod_service", None)
                    if mod_service:
                        temp_mod = mod_service.create_mod_object_from_info(
                            installed_mod_config, []
                        )
                        if hasattr(temp_mod, "files") and temp_mod.files:
                            mod.files = temp_mod.files
                        all_mods_filtered.append(mod)
                    else:
                        all_mods_filtered.append(mod)
                else:
                    all_mods_filtered.append(mod)
            for local_mod in local_mods:
                mod_id = get_mod_id(local_mod)
                if mod_id and mod_id not in {get_mod_id(m) for m in all_mods_filtered}:
                    all_mods_filtered.append(local_mod)
            app_state = getattr(self.main_window, "app_state", None)
            if app_state:
                _safe_emit(
                    self.__class__.__name__,
                    app_state.all_mods_updated,
                    all_mods_filtered,
                )
            self._update_remote_exists_flags(all_mods)
            logger.info("FetchModsThread: Mod fetch completed successfully")
            _safe_emit(self.__class__.__name__, self.result, True)
        except Exception as e:
            logger.error(f"FetchModsThread: Error in run: {e}", exc_info=True)
            _safe_emit(self.__class__.__name__, self.status, str(e), UI_COLORS["status_error"])
            _safe_emit(self.__class__.__name__, self.result, False)

    def _get_local_mods(self) -> list[AnyModInfo]:
        local_mods = []
        app_state = getattr(self.main_window, "app_state", None)
        if app_state and hasattr(app_state, "all_mods"):
            for mod in app_state.all_mods:
                mod_id = get_mod_id(mod)
                is_local_mod_id = (
                    mod_id and isinstance(mod_id, str) and mod_id.startswith("local_")
                )
                if is_local_mod_id:
                    local_mods.append(mod)
            logger.debug(
                f"_get_local_mods: Found {len(local_mods)} local mods in app_state"
            )
        return local_mods

    def _update_remote_exists_flags(self, all_mods: list[BrowserModInfo]):
        app_state = getattr(self.main_window, "app_state", None)
        mod_service = getattr(self.main_window, "mod_service", None)
        settings_service = getattr(self.main_window, "settings_service", None)
        if (
            not app_state
            or not hasattr(app_state, "mods_dir")
            or (not os.path.exists(app_state.mods_dir))
        ):
            return
        if not mod_service:
            return
        try:
            for folder_name in os.listdir(app_state.mods_dir):
                folder_path = os.path.join(app_state.mods_dir, folder_name)
                if not os.path.isdir(folder_path):
                    continue
                config_path = os.path.join(folder_path, "mod_config.json")
                if not os.path.exists(config_path):
                    continue
                try:
                    if settings_service:
                        config_data = settings_service.read_json(config_path)
                    else:
                        with open(config_path, encoding="utf-8") as f:
                            config_data = json.load(f)
                    if not config_data:
                        continue
                    mod_id = config_data.get("id")
                    is_local_mod_id = (
                        mod_id and isinstance(mod_id, str) and mod_id.startswith("local_")
                    )
                    if not mod_id or is_local_mod_id:
                        continue
                except (OSError, json.JSONDecodeError):
                    continue
        except Exception as e:
            logger.warning(f"Failed to update remote exists flags in metadata: {e}")
