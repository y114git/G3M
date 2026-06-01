"""Modpack creation worker thread."""

import contextlib
import json
import logging
import os
import shutil
import threading
import uuid
from typing import Any

from PyQt6.QtCore import QThread, pyqtSignal

from adapters.g3mtool_adapter import G3MToolManager
from services.g3mtool_patching_service import G3MToolPatchingService
from services.localization_service import tr
from utils.file_utils import get_chapter_folder_name, normalize_chapter_id
from utils.mod_config_parser import build_mod_config_data
from utils.patching.mod_content_utils import find_data_win
from utils.patching.mod_resolve_utils import get_mod_configured_extra_files


class CreateModpackThread(QThread):
    progress_update = pyqtSignal(int, str)
    status_update = pyqtSignal(str, str)
    warning_confirmation_needed = pyqtSignal(object, str, object)
    finished = pyqtSignal(bool)

    def __init__(
        self,
        chapter_mods: dict[int, list[Any]],
        modpack_name: str,
        modpack_dir: str,
        app_state,
        mod_service,
        parent=None,
        xdelta_modpack: bool = False,
    ) -> None:
        super().__init__(parent)
        self.chapter_mods = chapter_mods
        self.modpack_name = modpack_name
        self.modpack_dir = modpack_dir
        self.app_state = app_state
        self.mod_service = mod_service
        self.xdelta_modpack = xdelta_modpack
        self.patcher = None
        self._cancelled = False
        self._warning_event = threading.Event()
        self._warning_result = True

    def cancel(self):
        self._cancelled = True
        self.requestInterruption()
        self._warning_event.set()
        if self.patcher:
            self.patcher._cancelled = True
        self.status_update.emit("Operation cancelled", "error")

    def confirm_warning(self, accepted: bool):
        self._warning_result = accepted
        self._warning_event.set()

    def _request_warning_confirmation(
        self, message: object, details: str = "", report_path: str | None = None
    ) -> bool:
        self._warning_result = True
        self._warning_event.clear()
        self.warning_confirmation_needed.emit(message, details, report_path)
        while not self._warning_event.wait(0.1):
            if self.isInterruptionRequested() or self._cancelled:
                return False
        return self._warning_result and not (
            self.isInterruptionRequested() or self._cancelled
        )

    def _get_mod_game(self, mods_list: list[Any]):
        game = None
        if mods_list:
            first_mod = mods_list[0]
            game = first_mod.game if hasattr(first_mod, "game") else None
            if not game:
                game = None
            if not game and hasattr(first_mod, "config_data"):
                config = first_mod.config_data
                if isinstance(config, dict):
                    game = config.get("game")
        return game

    def run(self):
        success = False
        try:
            if self.isInterruptionRequested() or self._cancelled:
                return
            self.patcher = G3MToolPatchingService(
                self.app_state, self.mod_service, None
            )
            self.patcher.xdelta_modpack = self.xdelta_modpack
            self.patcher.progress_update.connect(self.progress_update.emit)
            self.patcher.status_update.connect(self.status_update.emit)
            self.patcher.warning_handler = self._request_warning_confirmation
            if self.isInterruptionRequested() or self._cancelled:
                return
            success = self.patcher.process_mod_patch(
                self.chapter_mods, is_modpack=True, modpack_dir=self.modpack_dir
            )
            if self.isInterruptionRequested() or self._cancelled:
                self.patcher.cancel()
                success = False
                if os.path.exists(self.modpack_dir):
                    try:
                        shutil.rmtree(self.modpack_dir, ignore_errors=True)
                        logging.info(
                            f"Cancelled modpack creation, removed directory: {self.modpack_dir}"
                        )
                    except Exception as e:
                        logging.error(
                            f"Failed to remove cancelled modpack directory: {e}"
                        )
            if success and (not (self.isInterruptionRequested() or self._cancelled)):
                if self.xdelta_modpack:
                    self._create_xdelta_patches()
                self._create_config_json()
                self.progress_update.emit(100, tr("status.patching_completed"))
        except Exception as e:
            logging.error(f"CreateModpackThread failed: {e}", exc_info=True)
            self.status_update.emit(f"Modpack creation failed: {e!s}", "error")
            success = False
        finally:
            if self.patcher:
                try:
                    for sig in (
                        self.patcher.progress_update,
                        self.patcher.status_update,
                    ):
                        with contextlib.suppress(TypeError, RuntimeError):
                            sig.disconnect()
                    self.patcher.cleanup(force=True)
                except Exception as cleanup_error:
                    logging.warning(
                        f"Error during patcher cleanup: {cleanup_error}", exc_info=True
                    )
                finally:
                    self.patcher = None
            self.finished.emit(success)

    def _create_xdelta_patches(self):
        try:
            g3mtool = G3MToolManager(self.app_state)
            if not g3mtool.is_available():
                logging.error("G3MTool not found, cannot create xdelta patches")
                self.status_update.emit(tr("errors.g3mtool_not_available"), "error")
                return
            total_chapters = max(len(self.chapter_mods), 1)
            for index, (chapter_id, mods_list) in enumerate(
                self.chapter_mods.items(), start=1
            ):
                if self.isInterruptionRequested() or self._cancelled:
                    return
                game = self._get_mod_game(mods_list)
                chapter_folder_name = get_chapter_folder_name(chapter_id, game=game)
                chapter_modpack_dir = os.path.join(
                    self.modpack_dir, chapter_folder_name
                )
                if not os.path.exists(chapter_modpack_dir):
                    continue
                modified_data_file = find_data_win(chapter_modpack_dir, game_id=game)
                if not modified_data_file:
                    continue
                data_filename = os.path.basename(modified_data_file)
                original_data_file = self._find_original_data_file(
                    chapter_id, game, data_filename
                )
                if not original_data_file or not os.path.exists(original_data_file):
                    logging.warning(
                        f"Original data file not found for chapter {chapter_id}, skipping xdelta creation"
                    )
                    continue
                patch_filename = f"{os.path.splitext(data_filename)[0]}.xdelta"
                patch_path = os.path.join(chapter_modpack_dir, patch_filename)
                self.status_update.emit(
                    tr("status.creating_xdelta_patch", chapter=chapter_id), "info"
                )
                range_start = 96 + int((index - 1) / total_chapters * 3)
                range_end = 96 + int(index / total_chapters * 3)
                returncode, _stdout, stderr = g3mtool.xpatch_create(
                    original_data_file,
                    modified_data_file,
                    patch_path,
                    progress_callback=lambda progress, chapter=chapter_id, start=range_start, end=range_end: (
                        self.progress_update.emit(
                            start + int((end - start) * progress / 100),
                            tr("status.creating_xdelta_patch", chapter=chapter),
                        )
                    ),
                )
                if returncode != 0:
                    logging.error(
                        f"Failed to create xdelta patch for chapter {chapter_id}: {stderr}"
                    )
                    self.status_update.emit(
                        tr("errors.xdelta_patch_creation_failed", chapter=chapter_id),
                        "error",
                    )
                    continue
                if os.path.exists(patch_path):
                    try:
                        os.remove(modified_data_file)
                        logging.info(
                            f"Created xdelta patch for chapter {chapter_id}: {patch_path}"
                        )
                    except Exception as e:
                        logging.warning(
                            f"Failed to remove data file after creating xdelta patch: {e}"
                        )
        except Exception as e:
            logging.error(f"Failed to create xdelta patches: {e}", exc_info=True)
            self.status_update.emit(
                tr("errors.xdelta_patch_creation_failed_general"), "error"
            )

    def _determine_primary_game_type(self, detected_games: list[str]) -> str:
        if not detected_games:
            from services.game_detection_service import get_game_type_string

            return get_game_type_string(self.app_state.game_mode)
        unique_games = set(detected_games)
        if len(unique_games) == 1:
            return unique_games.pop()
        return max(unique_games, key=detected_games.count)

    def _find_original_data_file(
        self, chapter_id: str, game: str, data_filename: str
    ) -> str:
        try:
            from models.game_modes import get_game
            from utils.path_utils import find_chapter_resource_dir

            game_mode = (
                get_game(game)
                or get_game(self.app_state.game_mode.game_id)
                or self.app_state.game_mode
            )
            base_game_path = game_mode.get_game_path(self.app_state.local_config)
            if not base_game_path or not os.path.exists(base_game_path):
                logging.warning(f"Base game path not found: {base_game_path}")
                return None
            chapter_dir = find_chapter_resource_dir(
                base_game_path, chapter_id, game_mode.macos_app_names
            )
            if not chapter_dir or not os.path.exists(chapter_dir):
                logging.warning(
                    f"Chapter directory not found for chapter {chapter_id} in {base_game_path}"
                )
                return None
            original_data_file = find_data_win(chapter_dir, data_filename, game)
            if original_data_file and os.path.exists(original_data_file):
                logging.info(f"Found original data file: {original_data_file}")
                return original_data_file
            logging.warning(
                f"Original data file not found for expected name {data_filename} in {chapter_dir}"
            )
            return None
        except Exception as e:
            logging.error(f"Error finding original data file: {e}", exc_info=True)
            return None

    def _create_config_json(self):
        try:
            files_data = {}
            detected_games = []
            for chapter_id, mods_list in self.chapter_mods.items():
                chapter_key = normalize_chapter_id(chapter_id)
                game = self._get_mod_game(mods_list)
                if game:
                    detected_games.append(game)
                chapter_folder_name = get_chapter_folder_name(chapter_id, game=game)
                chapter_modpack_dir = os.path.join(
                    self.modpack_dir, chapter_folder_name
                )
                if not os.path.exists(chapter_modpack_dir):
                    continue
                file_info = {}
                if self.xdelta_modpack:
                    xdelta_files = [
                        f
                        for f in os.listdir(chapter_modpack_dir)
                        if f.lower().endswith(".xdelta")
                    ]
                    xdelta_files.sort()
                    xdelta_patch = (
                        os.path.join(chapter_modpack_dir, xdelta_files[0])
                        if xdelta_files
                        else ""
                    )
                    if xdelta_patch and os.path.exists(xdelta_patch):
                        file_info["data_file_path"] = (
                            f"{chapter_folder_name}/{os.path.basename(xdelta_patch)}"
                        )
                        files_data[chapter_key] = file_info
                        continue
                    logging.warning(
                        f"xdelta_modpack enabled but xdelta patch not found for chapter {chapter_id}, skipping in config"
                    )
                    continue
                if data_file := find_data_win(chapter_modpack_dir, game_id=game):
                    file_info["data_file_path"] = (
                        f"{chapter_folder_name}/{os.path.basename(data_file)}"
                    )
                extra_files = self._get_modpack_extra_files(
                    mods_list, chapter_id, chapter_modpack_dir
                )
                if extra_files:
                    file_info["extra_files"] = extra_files
                if file_info:
                    files_data[chapter_key] = file_info
            mod_id = f"local_{uuid.uuid4().hex[:12]}"
            detected_game = self._determine_primary_game_type(detected_games)
            config_data = {
                "id": mod_id,
                "version": "1.0.0",
                "name": self.modpack_name,
                "description": tr("defaults.no_description"),
                "author": tr("defaults.multiple_authors"),
                "game": detected_game,
                "game_version": tr("defaults.not_specified"),
                "files": files_data,
                "tags": [],
            }
            config_path = os.path.join(self.modpack_dir, "mod_config.json")
            self.progress_update.emit(
                99, tr("status.finalizing_chapter", display=self.modpack_name)
            )
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(build_mod_config_data(config_data), f, indent=4, ensure_ascii=False)
            logging.info(f"Created mod_config.json for modpack: {self.modpack_name}")
        except Exception as e:
            logging.error(f"Failed to create mod_config.json: {e}", exc_info=True)
            raise

    def _get_modpack_extra_files(
        self, mods_list: list[Any], chapter_id: str, chapter_modpack_dir: str
    ) -> list[str]:
        extra_files: list[str] = []
        seen = set()
        for mod_data in mods_list:
            for rel_path in get_mod_configured_extra_files(
                mod_data, chapter_id, self.mod_service, self.app_state, logging
            ):
                normalized = rel_path.replace("\\", "/").strip()
                if not normalized or normalized in seen:
                    continue
                if os.path.exists(os.path.join(chapter_modpack_dir, normalized.rstrip("/"))):
                    seen.add(normalized)
                    extra_files.append(
                        os.path.relpath(
                            os.path.join(chapter_modpack_dir, normalized.rstrip("/")),
                            self.modpack_dir,
                        ).replace("\\", "/")
                    )
        return extra_files
