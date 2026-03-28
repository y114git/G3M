"""Mod management and installation."""

import logging
import os
import shutil
import threading
import time
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QDialog, QMessageBox

import models.mod_models as mod_models
from config.config import MOD_CONFIG_FILENAME
from models.exceptions import ModUninstallationError
from models.mod_models import LocalModInfo, ModFileData
from services.localization_service import tr
from services.migration_service import migrate_mod_metadata
from utils.file_utils import (
    get_chapter_folder_name,
    load_json,
    normalize_chapter_id,
    sanitize_filename,
    save_json,
)
from utils.mod_config_parser import (
    normalize_mod_config_data,
    parse_extra_files_raw,
    resolve_chapter_folder,
    resolve_local_icon_path,
)
from utils.mod_scan_utils import (
    ModFolderInfo,
    cleanup_corrupted_mods,
    normalize_mod_cache,
    scan_mods_directory,
)
from utils.mod_utils import (
    get_mod_id,
    get_mod_name,
    resolve_mod_icon,
    sort_gamebanana_files_by_priority,
)
from workers.install.url_install_worker import UrlInstallThread
from workers.mod_scan_worker import ModScanThread


class ModManager(QObject):
    """Manages mod operations including scanning, installation, and caching."""

    _BROWSER_ONLY_DATE_FIELD = "_".join(("created", "date"))

    progress_updated = pyqtSignal(int)
    status_changed = pyqtSignal(str, str)
    mod_list_updated = pyqtSignal()
    url_prompt_required = pyqtSignal(str, str)

    def __init__(
        self, app_state, feedback_service, settings_service=None, parent=None
    ) -> None:
        super().__init__(parent)
        self.app_state = app_state
        self.feedback_service = feedback_service
        self.settings_service = settings_service
        self._cache_lock = threading.RLock()
        self._mods_cache: dict[str, ModFolderInfo] = {}
        self._mods_by_name: dict[str, str] = {}
        self._mods_cache_valid = False
        self._scan_thread: ModScanThread | None = None
        self._scan_in_progress = False

    def cleanup_stale_used_mods(self):
        if not self._mods_cache:
            return
        valid_mod_ids = set(self._mods_cache.keys())
        changes_made = False
        keys_to_check = [
            k for k in self.app_state.local_config if k.startswith("used_mods")
        ]
        for settings_key in keys_to_check:
            used_mods_list = self.app_state.local_config.get(settings_key)
            if not isinstance(used_mods_list, list):
                continue
            new_list = [mod_id for mod_id in used_mods_list if mod_id in valid_mod_ids]
            if len(new_list) != len(used_mods_list):
                extra_ids = set(used_mods_list) - set(new_list)
                logging.info(
                    f"Cleanup: Removing stale mods from {settings_key}: {extra_ids}"
                )
                self.app_state.local_config[settings_key] = new_list
                changes_made = True
        if changes_made:
            if self.settings_service:
                self.settings_service.write_local_config()
            else:
                self._write_local_config_fallback()

    def _write_local_config_fallback(self):
        """Fallback method to write local config when settings_service is None."""
        try:
            from utils.file_utils import save_json

            save_json(self.app_state.config_path, self.app_state.local_config, indent=2)
            logging.warning(
                "Used fallback persistence for settings cleanup (settings_service was None)"
            )
        except Exception as e:
            logging.error(f"Failed to write local config fallback: {e}", exc_info=True)

    def invalidate_mods_cache(self) -> None:
        with self._cache_lock:
            self._mods_cache_valid = False
            self._mods_by_name.clear()

    def _on_scan_completed(self, cache_dict: dict):
        with self._cache_lock:
            cache = {}
            mods_by_name = {}
            for mod_id, mod_info_dict in cache_dict.items():
                try:
                    config_data = mod_info_dict.get("config_data", {})
                    folder_path = mod_info_dict.get("folder_path", "")
                    folder_name = mod_info_dict.get("folder_name", "")
                    config_mtime = mod_info_dict.get("config_mtime", 0.0)
                    effective_id = (
                        mod_info_dict.get("id")
                        or config_data.get("id")
                        or mod_id
                    )
                    if not effective_id:
                        logging.warning(
                            f"_on_scan_completed: Found mod with empty id in {folder_path}, skipping"
                        )
                        continue
                    mod_info = ModFolderInfo(
                        id=effective_id,
                        folder_path=folder_path,
                        folder_name=folder_name,
                        config_data=config_data,
                        config_mtime=config_mtime,
                    )
                    cache[effective_id] = mod_info
                    mod_name = config_data.get("name", "")
                    if mod_name:
                        mods_by_name[mod_name.lower()] = effective_id
                except (KeyError, TypeError) as e:
                    logging.warning(
                        f"_on_scan_completed: Error processing mod {mod_id}: {e}",
                        exc_info=True,
                    )
                    continue
            self._mods_cache = cache
            self._mods_by_name = mods_by_name
            self._mods_cache_valid = True
            self._scan_in_progress = False
            self._scan_thread = None

    @staticmethod
    def _build_safe_mod_info(
        mod_id: str,
        config_data: dict,
        icon_path: str,
        default_name: str = "Installed Mod",
        tags: list | None = None,
    ) -> dict:
        """Build a safe mod info dict from config data with sensible defaults."""
        if tags is None:
            tags = config_data.get("tags", [])
            if not isinstance(tags, list):
                tags = [tags] if tags else []
        return {
            "id": mod_id,
            "name": config_data.get("name", default_name),
            "version": config_data.get("version", "1.0.0"),
            "author": config_data.get("author", tr("defaults.unknown")),
            "description": config_data.get("description", tr("defaults.no_description")),
            "game_version": config_data.get(
                "game_version", tr("defaults.not_specified")
            ),
            "game": config_data.get("game", "deltarune"),
            "icon": icon_path,
            "tags": tags,
            "last_updated": config_data.get("last_updated"),
            "homepage": config_data.get("homepage"),
        }

    def _get_mods_cache(self, use_async: bool = False) -> dict[str, ModFolderInfo]:
        with self._cache_lock:
            if self._mods_cache_valid:
                normalized_cache = normalize_mod_cache(self._mods_cache)
                if len(normalized_cache) != len(self._mods_cache) or any(
                    isinstance(v, dict) for v in self._mods_cache.values()
                ):
                    self._mods_cache = normalized_cache
                return self._mods_cache.copy()
            if (
                use_async
                and not self._scan_in_progress
                and not (self._scan_thread and self._scan_thread.isRunning())
            ):
                self._scan_in_progress = True
                self._scan_thread = ModScanThread(
                    self.app_state.mods_dir, self.parent()
                )
                self._scan_thread.scan_completed.connect(self._on_scan_completed)
                self._scan_thread.start()
                return self._mods_cache.copy()
            cache, mods_by_name = scan_mods_directory(
                self.app_state.mods_dir, self._mods_cache
            )
            self._mods_cache = cache
            self._mods_by_name = mods_by_name
            self._mods_cache_valid = True
            return self._mods_cache.copy()

    def load_local_mods(self):
        if not os.path.exists(self.app_state.mods_dir):
            os.makedirs(self.app_state.mods_dir, exist_ok=True)
            return False
        cleanup_corrupted_mods(self.app_state.mods_dir)
        try:
            cache = self._get_mods_cache(use_async=False)
        except Exception as e:
            logging.error(
                f"load_local_mods: Failed to get mods cache: {e}", exc_info=True
            )
            cache = {}
        from utils.mod_utils import parse_gamebanana_mod_id

        installed_mods = {}
        try:
            for cached_mod_id, mod_info in cache.items():
                try:
                    config_data = mod_info.config_data
                    if not config_data:
                        continue
                    mod_id = config_data.get("id")
                    if not mod_id:
                        logging.warning(
                            "load_local_mods: Found mod with empty id, skipping"
                        )
                        continue
                    installed_mods[mod_id] = config_data
                except Exception as e:
                    logging.warning(
                        f"load_local_mods: Error processing mod info from cache (id={cached_mod_id}): {e}",
                        exc_info=True,
                    )
                    continue
            installed_gamebanana_by_id = {}
            for mod_id, config_data in installed_mods.items():
                if mod_id and mod_id.startswith("gb_"):
                    installed_gamebanana_by_id[mod_id] = config_data

            def _find_mod_by_id(mod_id):
                for mod in self.app_state.all_mods:
                    if get_mod_id(mod) == mod_id:
                        return mod
                return None

            def _sync_mod_icon(existing_mod, config_data, mod_id):
                mod_folder_path = self.get_mod_folder_path(mod_id)
                local_icon = resolve_local_icon_path(config_data, mod_folder_path)
                if local_icon and local_icon != (
                    getattr(existing_mod, "icon", None)
                    or getattr(existing_mod, "icon_path", None)
                ):
                    existing_mod.icon = local_icon
                    existing_mod.icon_path = local_icon
                    if hasattr(existing_mod, "update_metadata"):
                        existing_mod.update_metadata({"icon": local_icon})

            def _try_update_mod_files(
                existing_mod, config_data, mod_id, replace_in_list=False
            ):
                if (
                    not hasattr(existing_mod, "files") or not existing_mod.files
                ) and config_data.get("files"):
                    try:
                        files_data = config_data.get("files", {})
                        if isinstance(files_data, dict) and files_data:
                            new_mod = self.create_mod_object_from_info(
                                config_data, self.app_state.all_mods
                            )
                            if replace_in_list:
                                for i, mod in enumerate(self.app_state.all_mods):
                                    if get_mod_id(mod) == mod_id:
                                        self.app_state.all_mods[i] = new_mod
                                        break
                            elif hasattr(new_mod, "files") and new_mod.files:
                                existing_mod.files = new_mod.files
                        else:
                            logging.debug(
                                f"load_local_mods: Skipping mod {mod_id} with empty/invalid files data"
                            )
                    except Exception as e:
                        logging.warning(
                            f"load_local_mods: Failed to load files for mod {mod_id}: {e}",
                            exc_info=True,
                        )
                for field in (
                    "name",
                    "author",
                    "description",
                    "version",
                    "game",
                    "game_version",
                    "homepage",
                ):
                    val = config_data.get(field)
                    if val:
                        setattr(existing_mod, field, val)
                _sync_mod_icon(existing_mod, config_data, mod_id)

            existing_mod_ids = {
                current_mod_id
                for mod in self.app_state.all_mods
                if (current_mod_id := get_mod_id(mod))
            }
            for mod_id, config_data in list(installed_mods.items()):
                if mod_id and isinstance(mod_id, str) and mod_id.startswith("local_"):
                    continue
                if mod_id and mod_id.startswith("gb_"):
                    if mod_id in existing_mod_ids:
                        existing_mod = _find_mod_by_id(mod_id)
                        if existing_mod:
                            _try_update_mod_files(existing_mod, config_data, mod_id)
                    continue
                if mod_id in existing_mod_ids:
                    existing_mod = _find_mod_by_id(mod_id)
                    if existing_mod:
                        _try_update_mod_files(
                            existing_mod, config_data, mod_id, replace_in_list=True
                        )
                    continue
                try:
                    mod_folder_path = self.get_mod_folder_path(mod_id)
                    icon_path = resolve_local_icon_path(config_data, mod_folder_path)
                    safe_mod_info = self._build_safe_mod_info(
                        mod_id, config_data, icon_path
                    )
                    mod = LocalModInfo(**safe_mod_info)
                    self._parse_chapter_files(mod, config_data, mod_id)
                    self._append_mod_if_valid(mod, mod_id)
                except Exception as e:
                    logging.warning(
                        f"Failed to create LocalModInfo for installed mod {mod_id}: {e}",
                        exc_info=True,
                    )
            self.app_state.all_mods = list(self.app_state.all_mods)
            for mod_id, config_data in list(installed_mods.items()):
                if not (mod_id and isinstance(mod_id, str) and mod_id.startswith("local_")):
                    continue
                if mod_id in existing_mod_ids:
                    existing_mod = _find_mod_by_id(mod_id)
                    if existing_mod:
                        for field in (
                            "name",
                            "author",
                            "description",
                            "version",
                            "game",
                            "game_version",
                            "homepage",
                        ):
                            setattr(
                                existing_mod,
                                field,
                                config_data.get(field, getattr(existing_mod, field)),
                            )
                        _sync_mod_icon(existing_mod, config_data, mod_id)
                        if hasattr(existing_mod, "update_metadata"):
                            existing_mod.update_metadata(config_data)
                    continue
                try:
                    mod_info_from_cache = cache.get(mod_id)
                    mod_folder_path = getattr(
                        mod_info_from_cache, "folder_path", None
                    ) or self.get_mod_folder_path(mod_id)
                    icon_path = resolve_local_icon_path(
                        config_data, mod_folder_path or self.get_mod_folder_path(mod_id)
                    )
                    safe_mod_info = self._build_safe_mod_info(
                        mod_id,
                        config_data,
                        icon_path,
                        default_name=tr("defaults.local_mod"),
                        tags=["local"],
                    )
                    mod = LocalModInfo(**safe_mod_info)
                    self._parse_local_chapter_files(
                        mod, config_data, mod_id, mod_folder_path
                    )
                    self._append_mod_if_valid(mod, mod_id)
                except Exception as e:
                    logging.warning(f"Failed to build LocalModInfo: {e}")
                    continue
            installed_gb_ids = set(installed_gamebanana_by_id)
            for mod in self.app_state.all_mods:
                mod_id_attr = get_mod_id(mod)
                if mod_id_attr and mod_id_attr in installed_gb_ids:
                    gb_type, gb_id = parse_gamebanana_mod_id(mod_id_attr)
                    if gb_type and gb_id and (getattr(mod, "downloads", 0) or 0) <= 0:
                        try:
                            from adapters.gamebanana_adapter import GameBananaAPI

                            api = GameBananaAPI()
                            itemtype = "Wip" if gb_type == "wip" else "Mod"
                            downloaded_count = api.get_mod_downloads_only(
                                int(gb_id), itemtype=itemtype
                            )
                            if downloaded_count is not None:
                                mod.downloads = max(downloaded_count, 0)
                        except Exception as e:
                            logging.debug(
                                f"load_local_mods: Failed to load downloads from API for mod {mod_id_attr}: {e}"
                            )
            metadata = self._read_metadata()
            cleanup_files = metadata.get("mod_files_to_cleanup", [])
            cleanup_dirs = metadata.get("mod_dirs_to_cleanup", [])
            for items, remover, kind in [
                (cleanup_files, os.remove, "file"),
                (cleanup_dirs, shutil.rmtree, "dir"),
            ]:
                for p in items:
                    try:
                        if os.path.exists(p):
                            remover(p)
                    except Exception as e:
                        logging.warning(
                            f"load_local_mods: failed to remove cleanup {kind} {p}: {e}",
                            exc_info=True,
                        )
            if "mod_files_to_cleanup" in metadata or "mod_dirs_to_cleanup" in metadata:
                metadata.pop("mod_files_to_cleanup", None)
                metadata.pop("mod_dirs_to_cleanup", None)
                self._write_metadata(metadata)
            self.cleanup_stale_used_mods()
            return True
        except Exception as e:
            logging.error(f"load_local_mods failed: {e}", exc_info=True)
            return False

    @staticmethod
    def _validate_files_data(config_data: dict, mod_id: str) -> dict:
        files_data = config_data.get("files", {})
        if not isinstance(files_data, dict):
            logging.warning(
                f"load_local_mods: Invalid files_data type for mod {mod_id}, expected dict, got {type(files_data).__name__}"
            )
            return {}
        return files_data

    def _parse_chapter_files(self, mod, config_data: dict, mod_id: str):
        files_data = self._validate_files_data(config_data, mod_id)
        game = config_data.get("game")
        for file_key, ch_info in list(files_data.items()):
            if not isinstance(ch_info, dict):
                logging.debug(
                    f"load_local_mods: Skipping invalid chapter info for mod {mod_id}, file_key={file_key}"
                )
                continue
            try:
                normalized_key = normalize_chapter_id(file_key, game)
                extra_files_list = parse_extra_files_raw(
                    ch_info.get("extra_files", []), ch_info
                )
                mod.files[normalized_key] = ModFileData(
                    description=ch_info.get("description"),
                    data_file_url=ch_info.get("data_file_url"),
                    extra_files=extra_files_list,
                )
            except Exception as e:
                logging.warning(
                    f"load_local_mods: Failed to process chapter data for mod {mod_id}, file_key={file_key}: {e}",
                    exc_info=True,
                )

    def _parse_local_chapter_files(
        self, mod, config_data: dict, mod_id: str, mod_folder_path: str
    ):
        files_data = self._validate_files_data(config_data, mod_id)
        game = config_data.get("game")
        for file_key, ch_info in list(files_data.items()):
            if not isinstance(ch_info, dict):
                logging.warning(
                    f"load_local_mods: ch_info is not a dict for mod {mod_id}, file_key={file_key}, skipping"
                )
                continue
            normalized_key = normalize_chapter_id(file_key, game)
            chapter_folder = resolve_chapter_folder(
                normalized_key, mod_folder_path, game
            )
            if not chapter_folder and mod_folder_path:
                continue
            data_file_url = ""
            if ch_info.get("data_file_url") and mod_folder_path and chapter_folder:
                data_file_url = os.path.join(chapter_folder, ch_info["data_file_url"])
            extra_files = parse_extra_files_raw(
                ch_info.get("extra_files", []),
                ch_info,
                chapter_folder=chapter_folder if mod_folder_path else None,
            )
            mod.files[normalized_key] = ModFileData(
                description=config_data.get("description", ""),
                data_file_url=data_file_url,
                extra_files=extra_files,
            )

    def _append_mod_if_valid(self, mod, mod_id: str):
        if mod.files:
            self.app_state.append_mod(mod)
        else:
            logging.debug(
                f"Skipping mod {mod_id} ({mod.name}): game={mod.game}, has_files={bool(mod.files)}"
            )

    def get_mod_config(self, mod_id: str) -> dict:
        cache = self._get_mods_cache()
        mod_info = cache.get(mod_id)
        if mod_info:
            return mod_info.config_data.copy()
        return {}

    def get_mod_folder_path(self, mod_id: str) -> str:
        if not mod_id:
            return ""
        mod_info = self._get_mods_cache().get(mod_id)
        if mod_info:
            folder_path = (
                mod_info.get("folder_path", "")
                if isinstance(mod_info, dict)
                else mod_info.folder_path
            )
            if folder_path and os.path.isdir(folder_path):
                return folder_path
        for cached_info in self._get_mods_cache().values():
            folder_path = (
                cached_info.get("folder_path", "")
                if isinstance(cached_info, dict)
                else cached_info.folder_path
            )
            config_data = (
                cached_info.get("config_data", {})
                if isinstance(cached_info, dict)
                else cached_info.config_data
            )
            if config_data.get("id") == mod_id and folder_path and os.path.isdir(folder_path):
                return folder_path
        for folder_name, folder_path, _config_path, config_data in self._iter_mod_configs():
            if config_data.get("id") != mod_id:
                continue
            if folder_path and os.path.isdir(folder_path):
                return folder_path
            if folder_name:
                candidate = os.path.join(self.app_state.mods_dir, folder_name)
                if os.path.isdir(candidate):
                    return candidate
        return ""

    @staticmethod
    def resolve_gamebanana_file(mod_info, api, selected_file=None) -> dict | None:
        from utils.mod_utils import get_gamebanana_id, parse_gamebanana_mod_id

        if selected_file:
            return selected_file
        files = sort_gamebanana_files_by_priority(
            getattr(mod_info, "gamebanana_supported_files", []) or []
        )
        if files:
            mod_info.gamebanana_supported_files = files
            return files[0]
        try:
            gb_type, gb_id = parse_gamebanana_mod_id(get_gamebanana_id(mod_info))
            if not gb_id:
                return None
            itemtype = "Wip" if gb_type == "wip" else "Mod"
            compat = api.get_supported_files_for_mod(int(gb_id), itemtype=itemtype)
            files = sort_gamebanana_files_by_priority(
                compat.get("supported_files") or []
            )
            if files:
                mod_info.gamebanana_supported_files = files
                mod_info.gamebanana_compatibility_checked = compat.get(
                    "compatibility_checked", False
                )
                return files[0]
        except Exception as e:
            mod_id = get_mod_id(mod_info) or "unknown"
            logging.warning(
                f"ModManager: Failed to resolve GameBanana file for mod {mod_id}: {e}"
            )
        return None

    def install_from_url(self, url: str):
        if self.app_state.is_installing:
            return
        self.app_state.is_installing = True
        self.status_changed.emit(tr("status.downloading_mod"), "status_info")
        url_install_thread = UrlInstallThread(self.parent(), url)
        url_install_thread.progress.connect(self.progress_updated.emit)
        url_install_thread.status.connect(self.status_changed.emit)
        url_install_thread.finished.connect(self._on_url_install_finished)
        url_install_thread.prompt_required.connect(self.url_prompt_required.emit)
        url_install_thread.manual_install_required.connect(
            self._on_manual_install_required
        )
        self.app_state.current_task = url_install_thread
        url_install_thread.start()

    def _on_manual_install_required(
        self, prepared_path: str, archive_path: str, temp_dir: str
    ):
        try:
            self.app_state.is_installing = False
            self.status_changed.emit(tr("status.ready"), "status_info")
            parent = self.parent()
            msg_box = QMessageBox(parent)
            msg_box.setIcon(QMessageBox.Icon.Information)
            msg_box.setWindowTitle(tr("errors.mod_not_compatible_title"))
            msg_box.setText(tr("errors.mod_requires_manual_installation"))
            msg_box.setInformativeText(tr("dialogs.manual_install_available"))
            manual_install_btn = msg_box.addButton(
                tr("ui.manual_install"), QMessageBox.ButtonRole.AcceptRole
            )
            msg_box.addButton(tr("buttons.close"), QMessageBox.ButtonRole.RejectRole)
            msg_box.setDefaultButton(manual_install_btn)
            msg_box.exec()
            if msg_box.clickedButton() != manual_install_btn:
                shutil.rmtree(temp_dir, ignore_errors=True)
                return
            from services.game_detection_service import get_game_type_string
            from ui.dialogs.manual_install_dialog import ManualModInstallDialog

            initial_game_type = None
            if (
                hasattr(parent, "app_state")
                and parent.app_state
                and hasattr(parent.app_state, "game_mode")
            ):
                initial_game_type = get_game_type_string(parent.app_state.game_mode)
            dialog = ManualModInstallDialog(
                parent,
                prepared_path,
                gamebanana_metadata=None,
                source_file_path=archive_path,
                initial_game_type=initial_game_type,
            )
            dialog.temp_dir_to_cleanup = temp_dir
            if dialog.exec() == QDialog.DialogCode.Accepted:
                from ui.utils.ui_utils import refresh_ui_after_mod_install

                refresh_ui_after_mod_install(parent, self)
                QMessageBox.information(
                    parent,
                    tr("dialogs.success"),
                    tr("dialogs.mod_created_successfully"),
                )
        except Exception as e:
            logging.error(
                f"ModManager: Error handling manual install request: {e}", exc_info=True
            )
            if hasattr(self.parent(), "feedback_service"):
                self.parent().feedback_service.show_message(
                    "error",
                    tr("errors.error"),
                    tr("errors.manual_install_failed", error=str(e)),
                )
            shutil.rmtree(temp_dir, ignore_errors=True)

    _UNINSTALL_ERROR_MAP = {
        PermissionError: (
            "permission_error",
            "Permission denied during uninstallation",
        ),
        OSError: ("io_error", "File operation failed during uninstallation"),
        KeyError: ("missing_data", "Missing required data"),
        AttributeError: ("missing_data", "Missing required data"),
    }

    def uninstall_mod(self, mod):
        try:
            self.delete_mod_files(mod)
            self.app_state.is_installing = False
            self.mod_list_updated.emit()
            self.status_changed.emit(tr("status.mod_uninstalled"), "status_success")
        except Exception as e:
            mod_id = get_mod_id(mod) or "unknown"
            mod_name = get_mod_name(mod, "Unknown Mod")
            reason, prefix = "unknown", "Unexpected error during uninstallation"
            for exc_type, (r, p) in self._UNINSTALL_ERROR_MAP.items():
                if isinstance(e, exc_type):
                    reason, prefix = r, p
                    break
            if isinstance(e, shutil.Error):
                reason, prefix = (
                    "io_error",
                    "File operation failed during uninstallation",
                )
            error = ModUninstallationError(
                f"{prefix}: {e}", mod_id=mod_id, mod_name=mod_name, reason=reason
            )
            logging.error(
                f"uninstall_mod: {reason}: {e}",
                exc_info=True,
                extra={"mod_id": mod_id, "mod_name": mod_name},
            )
            if reason == "permission_error":
                self.feedback_service.show_message(
                    "error", "errors.uninstall_failed", tr("errors.permission_denied")
                )
            elif reason not in ("missing_data",):
                self.feedback_service.show_message(
                    "error", "errors.uninstall_failed", str(e)
                )
            raise error from e

    def update_mod(self, mod_data):
        if self.app_state.is_installing:
            return
        parent = self.parent()
        mod_ops = getattr(parent, "mod_ops", None) if parent else None
        if mod_ops:
            mod_ops.install_mod(mod_data, force=True, is_update=True)

    def _try_delete_folder(self, folder_path: str, label: str) -> bool:
        from utils.file_utils import safe_rmtree

        if not folder_path or not os.path.exists(folder_path):
            return False
        logging.info(f"delete_mod_files: Deleting mod folder by {label}: {folder_path}")
        try:
            if safe_rmtree(folder_path):
                self.invalidate_mods_cache()
                logging.info(
                    f"delete_mod_files: Successfully deleted mod folder by {label}: {folder_path}"
                )
                return True
            logging.warning(
                f"delete_mod_files: safe_rmtree returned False for {folder_path}"
            )
        except Exception as e:
            logging.error(
                f"delete_mod_files: Failed to delete folder {folder_path}: {e}",
                exc_info=True,
            )
            raise
        return False

    def _resolve_mod_info_from_cache(
        self, cache: dict, mod_id: str, mod_name: str | None
    ):
        """Find mod info in cache by id, then by name variants."""
        mod_info = cache.get(mod_id)
        if mod_info:
            return mod_info
        logging.warning(
            f"delete_mod_files: Mod with id {mod_id} not found in cache. Cache has {len(cache)} entries."
        )
        if not mod_name:
            return None
        with self._cache_lock:
            mapped_mod_id = self._mods_by_name.get(mod_name.lower())
            if mapped_mod_id and mapped_mod_id in cache:
                logging.info(
                    f"delete_mod_files: Found mod by name mapping: {mod_name} -> {mapped_mod_id}"
                )
                return cache[mapped_mod_id]
        for cached_mod_id, cached_info in cache.items():
            cached_folder = (
                cached_info.folder_name
                if hasattr(cached_info, "folder_name")
                else cached_info.get("folder_name")
                if isinstance(cached_info, dict)
                else None
            )
            if cached_folder == mod_name:
                logging.info(
                    f"delete_mod_files: Found mod by folder name: {mod_name}, id: {cached_mod_id}"
                )
                return cached_info
        for cached_mod_id, cached_info in cache.items():
            config_data = (
                cached_info.config_data
                if hasattr(cached_info, "config_data")
                else cached_info.get("config_data", {})
                if isinstance(cached_info, dict)
                else {}
            )
            if config_data.get("name", "") == mod_name:
                logging.info(
                    f"delete_mod_files: Found mod by config name: {mod_name}, id: {cached_mod_id}"
                )
                return cached_info
        return None

    def delete_mod_files(self, mod_data):
        try:
            folder_path = (
                mod_data.folder_path
                if hasattr(mod_data, "folder_path")
                else mod_data.get("folder_path")
                if isinstance(mod_data, dict)
                else None
            )
            mod_id = get_mod_id(mod_data)
            mod_name = get_mod_name(mod_data)
            logging.info(
                f"delete_mod_files: id = {mod_id}, mod_name={mod_name}, folder_path={folder_path}, type={type(mod_data)}"
            )
            candidate_paths = [
                (folder_path, "folder_path"),
                (
                    self.get_mod_folder_path(mod_id) if mod_id else None,
                    "get_mod_folder_path",
                ),
                (
                    os.path.join(self.app_state.mods_dir, mod_name)
                    if mod_name
                    else None,
                    "mod_name",
                ),
            ]
            for path, label in candidate_paths:
                if self._try_delete_folder(path, label):
                    return
            if not mod_id:
                logging.error(
                    "delete_mod_files: Cannot determine id or folder_path for mod_data"
                )
                return
            cache = self._get_mods_cache()
            mod_info = self._resolve_mod_info_from_cache(cache, mod_id, mod_name)
            if mod_info:
                self._try_delete_folder(mod_info.folder_path, "cache_info")
                self.invalidate_mods_cache()
                return
            last_resort_paths = [
                (os.path.join(self.app_state.mods_dir, mod_id), "id_as_folder"),
                (
                    os.path.join(self.app_state.mods_dir, mod_name)
                    if mod_name
                    else None,
                    "mod_name_last_resort",
                ),
            ]
            for path, label in last_resort_paths:
                if self._try_delete_folder(path, label):
                    return
            logging.error(
                f"delete_mod_files: Cannot delete mod - not found in cache and folder paths do not exist. id = {mod_id}, mod_name={mod_name or 'None'}"
            )
        except Exception as e:
            logging.error(f"delete_mod_files: cleanup failed: {e}", exc_info=True)
            raise

    def get_mod_status(self, mod: mod_models.AnyModInfo, chapter_id: str) -> str:
        if mod.is_gamebanana_mod():
            return "ready"
        cache = self._get_mods_cache()
        mod_id = get_mod_id(mod)
        mod_info = cache.get(mod_id)
        if not mod_info:
            return "install"
        config_data = mod_info.config_data
        file_key = normalize_chapter_id(chapter_id, config_data.get("game"))
        files_data = config_data.get("files", {})
        if file_key in files_data:
            file_info = files_data[file_key]
            if file_info.get("data_file_url") or file_info.get("extra_files"):
                return "ready"
        return "install"

    def mod_has_update_available(self, mod_data) -> bool:
        try:
            from models.game_modes import get_game

            game_id = getattr(mod_data, "game", "deltarune")
            gm = get_game(game_id)
            tab_ids = [t.tab_id for t in gm.tabs] if gm else [game_id]
            for chapter_id in tab_ids:
                if (
                    self.mod_has_files_for_chapter(mod_data, chapter_id)
                    and self.get_mod_status(mod_data, chapter_id) == "update"
                ):
                    return True
            return False
        except Exception as e:
            logging.warning(f"mod_has_update_available: exception: {e}", exc_info=True)
            return False

    def is_mod_installed(self, mod_id: str) -> bool:
        with self._cache_lock:
            if not self._mods_cache_valid:
                self._get_mods_cache()
            return mod_id in self._mods_cache

    def check_mod_exists(self, mod_info):
        cache = self._get_mods_cache()
        mod_id = mod_info.get("id", "")
        if mod_id and mod_id in cache:
            return True
        folder_name = mod_info.get("folder_name", "")
        if folder_name:
            for mod_info_cached in cache.values():
                if mod_info_cached.folder_name == folder_name:
                    return True
        mod_name = mod_info.get("name", "")
        if mod_name:
            safe_name = sanitize_filename(mod_name)
            for mod_info_cached in cache.values():
                if mod_info_cached.folder_name == safe_name:
                    return True
        return False

    def mod_has_files_for_chapter(self, mod_data, chapter_id):
        try:
            mod_id = get_mod_id(mod_data)
            if not mod_id:
                return True
            cache = self._get_mods_cache()
            mod_info = cache.get(mod_id)
            if not mod_info:
                return False
            files_data = mod_info.config_data.get("files", {})
            if files_data:
                return (
                    normalize_chapter_id(chapter_id, mod_info.config_data.get("game"))
                    in files_data
                )
            folder_name = (
                get_chapter_folder_name(chapter_id)
                if "_" in str(chapter_id)
                else "universal"
            )
            for name in (folder_name, "universal"):
                folder = os.path.join(mod_info.folder_path, name)
                if os.path.exists(folder):
                    return len(os.listdir(folder)) > 0
            return True
        except Exception as e:
            logging.warning(f"mod_has_files_for_chapter: exception: {e}", exc_info=True)
            return True

    def _read_metadata(self) -> dict:
        with self.app_state._mods_metadata_lock:
            if not os.path.exists(self.app_state.mods_metadata_path):
                return {}
            try:
                return load_json(self.app_state.mods_metadata_path) or {}
            except Exception as e:
                logging.warning(f"_read_metadata: failed: {e}", exc_info=True)
                return {}

    def _write_metadata(self, data: dict):
        with self.app_state._mods_metadata_lock:
            try:
                save_json(self.app_state.mods_metadata_path, data, indent=2)
            except Exception as e:
                logging.error(f"_write_metadata: failed: {e}", exc_info=True)

    @staticmethod
    def _normalize_playtime_hours(value: Any) -> float:
        try:
            hours = float(value or 0)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, hours)

    def add_playtime_hours(self, mod_ids: list[str], hours: float) -> None:
        if not mod_ids or hours <= 0:
            return
        with self.app_state._mods_metadata_lock:
            if not os.path.exists(self.app_state.mods_metadata_path):
                metadata = {}
            else:
                try:
                    metadata = load_json(self.app_state.mods_metadata_path) or {}
                except Exception as e:
                    logging.warning(f"add_playtime_hours: failed to read metadata: {e}")
                    metadata = {}
            changed = False
            for mod_id in mod_ids:
                if not mod_id:
                    continue
                entry = metadata.setdefault(mod_id, {})
                current = self._normalize_playtime_hours(entry.get("playtime_hours", 0))
                entry["playtime_hours"] = round(current + hours, 4)
                changed = True
            if changed:
                try:
                    save_json(self.app_state.mods_metadata_path, metadata, indent=2)
                except Exception as e:
                    logging.error(f"add_playtime_hours: failed to write metadata: {e}")

    def get_playtime_hours(self, mod_id: str) -> float:
        metadata = self._read_metadata()
        entry = metadata.get(mod_id, {})
        if not isinstance(entry, dict):
            return 0.0
        return self._normalize_playtime_hours(entry.get("playtime_hours", 0))

    def _on_url_install_finished(self, success: bool, message: str):
        self.app_state.is_installing = False
        finished_task = self.app_state.current_task
        self.app_state.clear_current_task()
        if success:
            self.invalidate_mods_cache()
            self.load_local_mods()
            self.mod_list_updated.emit()
            self.status_changed.emit(tr("status.mod_installed"), "status_success")
        elif finished_task and getattr(finished_task, "_cancelled", False):
            self.status_changed.emit(
                tr("status.install_cancelled_by_user"), "status_info"
            )
        else:
            self.status_changed.emit(tr("status.installation_failed"), "status_error")

    def handle_url_prompt_response(self, response: bool):
        if self.app_state.current_task:
            self.app_state.current_task.prompt_result = response
            self.app_state.current_task.prompt_event.set()

    def create_mod_object_from_info(self, mod_info: dict, all_mods: list | None = None):
        mod_id = mod_info.get("id", "")
        mod_info = dict(mod_info)
        normalize_mod_config_data(mod_info)
        if not (mod_id and isinstance(mod_id, str) and mod_id.startswith("gb_")):
            mod_info.pop(self._BROWSER_ONLY_DATE_FIELD, None)
        files_data = mod_info.get("files", {})
        if files_data:
            from utils.mod_config_parser import normalize_files_data

            mod_info["files"] = normalize_files_data(
                files_data, mod_info.get("game")
            )
        if all_mods:
            for mod in all_mods:
                existing_mod_id = get_mod_id(mod)
                if existing_mod_id == mod_id and hasattr(mod, "files") and mod.files:
                    refreshed_mod = mod_models.LocalModInfo.from_dict(mod_info)
                    for attr in (
                        "name",
                        "version",
                        "author",
                        "description",
                        "game",
                        "game_version",
                        "icon",
                        "tags",
                        "homepage",
                        "files",
                        "added_date",
                        "last_updated",
                    ):
                        if hasattr(refreshed_mod, attr):
                            setattr(mod, attr, getattr(refreshed_mod, attr))
                    mod.playtime_hours = self._normalize_playtime_hours(
                        mod_info.get(
                            "playtime_hours",
                            getattr(mod, "playtime_hours", 0.0),
                        )
                    )
                    return mod
        return mod_models.LocalModInfo.from_dict(mod_info)

    def _iter_mod_configs(self):
        if not os.path.exists(self.app_state.mods_dir):
            return
        for folder_name in os.listdir(self.app_state.mods_dir):
            folder_path = os.path.join(self.app_state.mods_dir, folder_name)
            if not os.path.isdir(folder_path):
                continue
            config_path = os.path.join(folder_path, MOD_CONFIG_FILENAME)
            if not os.path.exists(config_path):
                continue
            try:
                config_data = load_json(config_path)
                if config_data and isinstance(config_data, dict):
                    if normalize_mod_config_data(config_data):
                        save_json(config_path, config_data, indent=4)
                    yield folder_name, folder_path, config_path, config_data
            except Exception as e:
                logging.warning(
                    f"_iter_mod_configs: failed to read {config_path}: {e}",
                    exc_info=True,
                )

    def get_installed_mods_list(self) -> list[dict]:
        installed_mods: list[dict] = []
        if not hasattr(self.app_state, "mods_dir") or not os.path.exists(
            self.app_state.mods_dir
        ):
            return installed_mods
        cache_snapshot: dict[str, ModFolderInfo] | None = None
        with self._cache_lock:
            if self._mods_cache_valid and self._mods_cache:
                cache_snapshot = dict(self._mods_cache)
        mods_metadata = self._read_metadata()
        metadata_updated = False
        found_mod_ids: set[str] = set()
        config_read_errors = False

        def _append_from_config(config_data: dict, folder_name: str) -> None:
            nonlocal metadata_updated
            if not config_data:
                return
            mod_id = config_data.get("id")
            if not mod_id:
                return
            found_mod_ids.add(mod_id)
            mod_meta = mods_metadata.get(mod_id)
            if not mod_meta:
                is_gamebanana = (
                    mod_id and isinstance(mod_id, str) and mod_id.startswith("gb_")
                )
                mods_metadata[mod_id] = {
                    "added_date": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "is_gamebanana": is_gamebanana,
                }
                metadata_updated = True
                mod_meta = mods_metadata[mod_id]
            cfg = dict(config_data)
            normalize_mod_config_data(cfg)
            cfg.pop(self._BROWSER_ONLY_DATE_FIELD, None)
            mod_folder_path = (
                os.path.join(self.app_state.mods_dir, folder_name)
                if folder_name
                else ""
            )
            if mod_folder_path:
                resolved_icon = resolve_mod_icon(cfg, mod_folder_path)
                if resolved_icon:
                    cfg["icon"] = resolved_icon
            cfg["added_date"] = mod_meta.get("added_date")
            cfg["playtime_hours"] = mod_meta.get("playtime_hours", 0.0)
            cfg["folder_name"] = folder_name
            installed_mods.append(cfg)

        if cache_snapshot is not None:
            for cached_mod_id, info in cache_snapshot.items():
                try:
                    if isinstance(info, ModFolderInfo):
                        config_data = info.config_data or {}
                        folder_name = info.folder_name
                    elif isinstance(info, dict):
                        config_data = info.get("config_data", {}) or {}
                        folder_name = info.get("folder_name", "")
                    else:
                        continue
                    _append_from_config(config_data, folder_name)
                except Exception as e:
                    config_read_errors = True
                    config_mod_id = (
                        config_data.get("id", "")
                        if "config_data" in locals()
                        else cached_mod_id
                    )
                    logging.warning(
                        f"Failed to build installed mod from cache for id {config_mod_id}: {e}",
                        exc_info=True,
                    )
        else:
            for (
                folder_name,
                _folder_path,
                _config_path,
                config_data,
            ) in self._iter_mod_configs():
                try:
                    _append_from_config(config_data, folder_name)
                except Exception as e:
                    config_read_errors = True
                    config_mod_id = (
                        config_data.get("id", "")
                        if config_data
                        else folder_name
                    )
                    logging.warning(
                        f"Failed to build installed mod from config for id {config_mod_id}: {e}",
                        exc_info=True,
                    )
        if not config_read_errors:
            orphaned_mod_ids = set(mods_metadata.keys()) - found_mod_ids
            if orphaned_mod_ids:
                for mod_id in list(orphaned_mod_ids):
                    del mods_metadata[mod_id]
                metadata_updated = True
        if metadata_updated:
            self._write_metadata(mods_metadata)
        return installed_mods

    def migrate_metadata_from_local_configs(self) -> bool:
        mods_metadata = self._read_metadata()
        updated = False
        for folder_name, _folder_path, config_path, config_data in self._iter_mod_configs():
            try:
                _mod_id, changed = migrate_mod_metadata(config_data, mods_metadata)
                if changed:
                    save_json(config_path, config_data, indent=4)
                    updated = True
            except Exception as e:
                logging.warning(
                    f"Failed to migrate metadata for mod in {folder_name}: {e}"
                )
        if updated:
            self._write_metadata(mods_metadata)
        return updated


def parse_mod_date(date_str: str) -> tuple[int, int, int, int, int]:
    if not date_str or date_str == "N/A":
        return (0, 0, 0, 0, 0)
    try:
        parts = date_str.split(" ")
        if len(parts) >= 2:
            date_part = parts[0]
            time_part = parts[1]
            day, month, year = map(int, date_part.split("."))
            hour, minute = map(int, time_part.split(":"))
            if year < 50:
                year += 2000
            else:
                year += 1900
            return (year, month, day, hour, minute)
    except Exception as e:
        logging.debug(f"parse_mod_date failed for '{date_str}': {e}")
    return (0, 0, 0, 0, 0)
