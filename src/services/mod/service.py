"""Mod management and installation."""

import logging
import os
import shutil
import threading
import time
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal

import models.mod_models as mod_models
from config.config import MOD_CONFIG_FILENAME
from models.exceptions import AppError, ModUninstallationError
from models.mod_models import BrowserModInfo, LocalModInfo, get_mod_authors
from services.localization_service import tr
from services.migration_service import migrate_mod_metadata
from services.mod_config_migration_service import (
    ModConfigMigrationIssue,
    migrate_managed_mods,
)
from services.mod_usage import ModInUseError, is_mod_busy, reserve_for_deletion
from utils.file_utils import (
    load_json,
    save_json,
)
from utils.mod.config import (
    MOD_CONFIG_VERSION,
    config_has_files_for_section,
    load_mod_config,
    write_mod_config,
)
from utils.mod.scan_utils import (
    ModFolderInfo,
    scan_mods_directory,
)
from utils.mod.utils import (
    get_mod_id,
    get_mod_name,
    is_gamebanana_id,
    resolve_mod_icon,
)
from utils.process_utils import format_filesystem_error
from workers.install.url_install_worker import UrlInstallThread
from workers.mod.scan_worker import ModScanThread

logger = logging.getLogger(__name__)


class ModManager(QObject):
    """Manages mod operations including scanning, installation, and caching."""

    _BROWSER_ONLY_DATE_FIELD = "_".join(("created", "date"))

    progress_updated = pyqtSignal(int)
    status_changed = pyqtSignal(str, str)
    mod_list_updated = pyqtSignal()

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
        self.migration_issues: tuple[ModConfigMigrationIssue, ...] = ()

    def _migrate_owned_mods(self) -> None:
        report = migrate_managed_mods(self.app_state.mods_dir)
        if report.configs or report.snapshots:
            self.invalidate_mods_cache()
        if report.issues != self.migration_issues:
            self.migration_issues = report.issues
            if report.issues:
                issue = report.issues[0]
                self.status_changed.emit(
                    tr(
                        "status.mod_migration_failed",
                        count=len(report.issues),
                        details=f"{issue.path.name}: {issue.message}",
                    ),
                    "status_error",
                )
        for issue in report.issues:
            logger.warning("Could not migrate %s: %s", issue.path, issue.message)

    def _safe_show_feedback_message(
        self, level: str, title: str, message: str = ""
    ) -> None:
        try:
            self.feedback_service.show_message(level, title, message)
        except Exception:
            logger.exception("ModManager: failed to show feedback message")

    @staticmethod
    def _safe_parent_show_feedback_message(
        parent, level: str, title: str, message: str = ""
    ) -> None:
        feedback_service = getattr(parent, "feedback_service", None)
        if feedback_service is None:
            return
        try:
            feedback_service.show_message(level, title, message)
        except Exception:
            logger.exception("ModManager: failed to show parent feedback message")

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
                logger.info(
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
            logger.warning(
                "Used fallback persistence for settings cleanup (settings_service was None)"
            )
        except Exception as e:
            logger.error(f"Failed to write local config fallback: {e}", exc_info=True)

    def invalidate_mods_cache(self) -> None:
        with self._cache_lock:
            self._mods_cache_valid = False
            self._mods_by_name.clear()

    def mods_needing_newer_g3m(self) -> list[str]:
        """Names of installed mods whose config format is newer than this G3M reads."""
        names: list[str] = []
        scan_mods_directory(self.app_state.mods_dir, self._mods_cache, newer_config_mods=names)
        return names

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
                    config_digest = mod_info_dict.get("config_digest", "")
                    effective_id = (
                        mod_info_dict.get("id")
                        or config_data.get("id")
                        or mod_id
                    )
                    if not effective_id:
                        logger.warning(
                            f"_on_scan_completed: Found mod with empty id in {folder_path}, skipping"
                        )
                        continue
                    mod_info = ModFolderInfo(
                        id=effective_id,
                        folder_path=folder_path,
                        folder_name=folder_name,
                        config_data=config_data,
                        config_mtime=config_mtime,
                        config_digest=config_digest,
                    )
                    cache[effective_id] = mod_info
                    mod_name = config_data.get("name", "")
                    if mod_name:
                        mods_by_name[mod_name.lower()] = effective_id
                except (KeyError, TypeError) as e:
                    logger.warning(
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
            "authors": get_mod_authors(config_data, tr("defaults.unknown")),
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
        self._migrate_owned_mods()
        try:
            cache = self._get_mods_cache(use_async=False)
        except Exception as e:
            logger.error(
                f"load_local_mods: Failed to get mods cache: {e}", exc_info=True
            )
            cache = {}
        from utils.mod.utils import parse_gamebanana_mod_id

        installed_mods = {}
        try:
            for cached_mod_id, mod_info in cache.items():
                try:
                    config_data = mod_info.config_data
                    if not config_data:
                        continue
                    mod_id = config_data.get("id")
                    if not mod_id:
                        logger.warning(
                            "load_local_mods: Found mod with empty id, skipping"
                        )
                        continue
                    installed_mods[mod_id] = config_data
                except Exception as e:
                    logger.warning(
                        f"load_local_mods: Error processing mod info from cache (id={cached_mod_id}): {e}",
                        exc_info=True,
                    )
                    continue
            installed_gamebanana_by_id = {}
            for mod_id, config_data in installed_mods.items():
                if is_gamebanana_id(mod_id):
                    installed_gamebanana_by_id[mod_id] = config_data

            def _find_mod_by_id(mod_id):
                for mod in self.app_state.all_mods:
                    if get_mod_id(mod) == mod_id:
                        return mod
                return None

            def _sync_mod_icon(existing_mod, config_data, mod_id):
                mod_folder_path = self.get_mod_folder_path(mod_id)
                local_icon = resolve_mod_icon(config_data, mod_folder_path)
                if local_icon and local_icon != (
                    getattr(existing_mod, "icon", None)
                    or getattr(existing_mod, "icon_path", None)
                ):
                    existing_mod.icon = local_icon
                    existing_mod.icon_path = local_icon

            def _refresh_local_mod_sections(existing_mod, config_data):
                existing_mod.sections = self._operation_sections(config_data)

            def _refresh_local_mod(existing_mod, config_data, mod_id):
                if isinstance(existing_mod, LocalModInfo):
                    _refresh_local_mod_sections(existing_mod, config_data)
                metadata = {
                    **config_data,
                    "authors": get_mod_authors(config_data, tr("defaults.unknown")),
                }
                for field in (
                    "name",
                    "authors",
                    "description",
                    "version",
                    "game",
                    "game_version",
                    "homepage",
                ):
                    val = metadata.get(field)
                    if val:
                        setattr(existing_mod, field, val)
                _sync_mod_icon(existing_mod, config_data, mod_id)

            existing_mod_ids = {
                current_mod_id
                for mod in self.app_state.all_mods
                if (current_mod_id := get_mod_id(mod))
            }
            for mod_id, config_data in list(installed_mods.items()):
                if mod_id in existing_mod_ids:
                    existing_mod = _find_mod_by_id(mod_id)
                    if existing_mod:
                        _refresh_local_mod(existing_mod, config_data, mod_id)
                    continue
                if is_gamebanana_id(mod_id):
                    continue  # its card comes from GameBanana
                try:
                    mod_folder_path = self.get_mod_folder_path(mod_id)
                    icon_path = resolve_mod_icon(config_data, mod_folder_path) or ""
                    safe_mod_info = self._build_safe_mod_info(
                        mod_id, config_data, icon_path
                    )
                    mod = LocalModInfo(**safe_mod_info)
                    mod.sections = self._operation_sections(config_data)
                    self._append_mod_if_valid(mod, mod_id, config_data)
                except Exception as e:
                    logger.warning(
                        f"Failed to create LocalModInfo for installed mod {mod_id}: {e}",
                        exc_info=True,
                    )
            self.app_state.all_mods = list(self.app_state.all_mods)
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
                            logger.debug(
                                f"load_local_mods: Failed to load downloads from API for mod {mod_id_attr}: {e}"
                            )
            metadata = self._read_metadata()
            if "mod_files_to_cleanup" in metadata or "mod_dirs_to_cleanup" in metadata:
                metadata.pop("mod_files_to_cleanup", None)
                metadata.pop("mod_dirs_to_cleanup", None)
                self._write_metadata(metadata)
            self.cleanup_stale_used_mods()
            return True
        except Exception as e:
            logger.error(f"load_local_mods failed: {e}", exc_info=True)
            return False

    @staticmethod
    def _operation_sections(config_data: dict) -> frozenset[str]:
        """Expose strict operation targets to library filtering without legacy file data."""
        from models.game_modes import get_game

        game = config_data.get("game")
        game_definition = get_game(game) if isinstance(game, str) else None
        section_ids = (
            [tab.tab_id for tab in game_definition.tabs]
            if game_definition is not None
            else [game]
        )
        return frozenset(
            section_id
            for section_id in section_ids
            if isinstance(section_id, str)
            and config_has_files_for_section(config_data, section_id)
        )

    def _append_mod_if_valid(self, mod, mod_id: str, config_data: dict | None = None):
        if (config_data or {}).get("config_version") == MOD_CONFIG_VERSION:
            self.app_state.append_mod(mod)
        else:
            logger.debug(
                f"Skipping mod {mod_id} ({mod.name}): config is not current"
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
            folder_path = mod_info.folder_path
            if folder_path and os.path.isdir(folder_path):
                return folder_path
        for cached_info in self._get_mods_cache().values():
            if (
                cached_info.config_data.get("id") == mod_id
                and cached_info.folder_path
                and os.path.isdir(cached_info.folder_path)
            ):
                return cached_info.folder_path
        for folder_name, folder_path, _, config_data in self._iter_mod_configs():
            if config_data.get("id") != mod_id:
                continue
            if folder_path and os.path.isdir(folder_path):
                return folder_path
            if folder_name:
                candidate = os.path.join(self.app_state.mods_dir, folder_name)
                if os.path.isdir(candidate):
                    return candidate
        return ""

    def install_from_url(self, url: str):
        if self.app_state.is_installing:
            return
        self.app_state.is_installing = True
        self.status_changed.emit(tr("status.downloading_mod"), "status_info")
        url_install_thread = UrlInstallThread(self.parent(), url)
        url_install_thread.progress.connect(self.progress_updated.emit)
        url_install_thread.status.connect(self.status_changed.emit)
        url_install_thread.result_ready.connect(self._on_url_install_finished)
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
            self.app_state.clear_current_task()
            self.status_changed.emit(tr("status.ready"), "status_info")
            parent = self.parent()
            presenter = getattr(parent, "pizza_oven_conversion_presenter", None)
            if presenter is None:
                shutil.rmtree(temp_dir, ignore_errors=True)
                return
            from ui.utils.ui_utils import refresh_ui_after_mod_install

            presenter.prompt_with_manual_options(
                parent,
                error_title=tr("errors.mod_not_compatible_title"),
                error_text=tr("errors.mod_requires_manual_installation"),
                informative_text=tr("dialogs.manual_install_available"),
                prepared_path=prepared_path,
                source_file_path=archive_path,
                temp_dir=temp_dir,
                on_success=lambda: refresh_ui_after_mod_install(parent, self),
            )
        except Exception as e:
            logger.error(
                f"ModManager: Error handling manual install request: {e}", exc_info=True
            )
            self._safe_parent_show_feedback_message(
                self.parent(),
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

    @staticmethod
    def _describe_uninstall_error(error: Exception) -> str:
        return format_filesystem_error(error)

    def uninstall_mod(self, mod):
        try:
            self.delete_mod_files(mod)
            self.app_state.is_installing = False
            self.mod_list_updated.emit()
            self.status_changed.emit(tr("status.mod_uninstalled"), "status_success")
        except AppError as e:
            self._safe_show_feedback_message("warning", tr("errors.error"), str(e))
            raise
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
            logger.error(
                f"uninstall_mod: {reason}: {e}",
                exc_info=True,
                extra={"mod_id": mod_id, "mod_name": mod_name},
            )
            if reason == "permission_error" or reason not in ("missing_data",):
                self._safe_show_feedback_message(
                    "error",
                    "errors.uninstall_failed",
                    self._describe_uninstall_error(e),
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
        logger.info(f"delete_mod_files: Deleting mod folder by {label}: {folder_path}")
        try:
            # Whatever the descriptor says, a folder an operation is using is never removed,
            # and no operation can start on it until the removal is over.
            try:
                with reserve_for_deletion(self._installed_mod_ids_at(folder_path)):
                    deleted = safe_rmtree(folder_path)
            except ModInUseError as error:
                raise AppError("errors.mod_busy", mod_name=os.path.basename(folder_path)) from error
            if deleted:
                self.invalidate_mods_cache()
                logger.info(
                    f"delete_mod_files: Successfully deleted mod folder by {label}: {folder_path}"
                )
                return True
            logger.warning(
                f"delete_mod_files: safe_rmtree returned False for {folder_path}"
            )
        except Exception as e:
            logger.error(
                f"delete_mod_files: Failed to delete folder {folder_path}: {e}",
                exc_info=True,
            )
            raise
        return False

    def _forget_deleted_mod(self, mod_id: str) -> None:
        """Remove an uninstalled mod from in-memory indexes and local metadata."""
        if not mod_id:
            return
        with self._cache_lock:
            self._mods_cache.pop(mod_id, None)
            self._mods_by_name = {
                name: mapped_id
                for name, mapped_id in self._mods_by_name.items()
                if mapped_id != mod_id
            }
            self._mods_cache_valid = False

        def keep_mod(mod) -> bool:
            return get_mod_id(mod) != mod_id or isinstance(mod, BrowserModInfo)

        self.app_state.all_mods = [
            mod for mod in self.app_state.all_mods if keep_mod(mod)
        ]
        if hasattr(self.app_state, "filtered_mods"):
            self.app_state.filtered_mods = [
                mod for mod in self.app_state.filtered_mods if keep_mod(mod)
            ]

        metadata = self._read_metadata()
        if mod_id in metadata:
            del metadata[mod_id]
            self._write_metadata(metadata)

    def _resolve_mod_info_from_cache(
        self, cache: dict[str, ModFolderInfo], mod_id: str, mod_name: str | None
    ) -> ModFolderInfo | None:
        """Find mod info in cache by id, then by name variants."""
        mod_info = cache.get(mod_id)
        if mod_info:
            return mod_info
        logger.warning(
            f"delete_mod_files: Mod with id {mod_id} not found in cache. Cache has {len(cache)} entries."
        )
        if not mod_name:
            return None
        with self._cache_lock:
            mapped_mod_id = self._mods_by_name.get(mod_name.lower())
            if mapped_mod_id and mapped_mod_id in cache:
                logger.info(
                    f"delete_mod_files: Found mod by name mapping: {mod_name} -> {mapped_mod_id}"
                )
                return cache[mapped_mod_id]
        for cached_mod_id, cached_info in cache.items():
            if cached_info.folder_name == mod_name:
                logger.info(
                    f"delete_mod_files: Found mod by folder name: {mod_name}, id: {cached_mod_id}"
                )
                return cached_info
        for cached_mod_id, cached_info in cache.items():
            if cached_info.config_data.get("name", "") == mod_name:
                logger.info(
                    f"delete_mod_files: Found mod by config name: {mod_name}, id: {cached_mod_id}"
                )
                return cached_info
        return None

    def _installed_mod_ids_at(self, folder_path: str | None) -> list[str]:
        if not folder_path:
            return []
        wanted = os.path.normcase(os.path.abspath(folder_path))
        ids: list[str] = []
        for cached_id, info in self._get_mods_cache().items():
            if os.path.normcase(os.path.abspath(info.folder_path)) == wanted:
                ids.extend((cached_id, str(info.config_data.get("id") or "")))
        return ids

    def ensure_mod_idle(self, mod_data) -> None:
        """Raise AppError while a patch, analysis or export is still using the mod's files."""
        folder = (
            mod_data.get("folder_path")
            if isinstance(mod_data, dict)
            else getattr(mod_data, "folder_path", None)
        )
        if any(is_mod_busy(mod_id) for mod_id in (get_mod_id(mod_data), *self._installed_mod_ids_at(folder))):
            raise AppError("errors.mod_busy", mod_name=get_mod_name(mod_data, ""))

    def delete_mod_files(self, mod_data):
        self.ensure_mod_idle(mod_data)
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
            logger.info(
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
                    if mod_id:
                        self._forget_deleted_mod(mod_id)
                    return
            if not mod_id:
                logger.error(
                    "delete_mod_files: Cannot determine id or folder_path for mod_data"
                )
                return
            cache = self._get_mods_cache()
            mod_info = self._resolve_mod_info_from_cache(cache, mod_id, mod_name)
            if mod_info:
                deleted = self._try_delete_folder(mod_info.folder_path, "cache_info")
                if deleted or not os.path.exists(mod_info.folder_path):
                    self._forget_deleted_mod(mod_id)
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
                    self._forget_deleted_mod(mod_id)
                    return
            logger.error(
                f"delete_mod_files: Cannot delete mod - not found in cache and folder paths do not exist. id = {mod_id}, mod_name={mod_name or 'None'}"
            )
        except Exception as e:
            logger.error(f"delete_mod_files: cleanup failed: {e}", exc_info=True)
            raise

    def get_mod_status(self, mod: mod_models.AnyModInfo, chapter_id: str) -> str:
        if mod.is_gamebanana_mod():
            return "ready"
        cache = self._get_mods_cache()
        mod_id = get_mod_id(mod)
        if not mod_id:
            return "install"
        mod_info = cache.get(mod_id)
        if not mod_info:
            return "install"
        config_data = mod_info.config_data
        return (
            "ready"
            if config_has_files_for_section(config_data, chapter_id)
            else "install"
        )

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
            logger.warning(f"mod_has_update_available: exception: {e}", exc_info=True)
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
            return config_has_files_for_section(mod_info.config_data, chapter_id)
        except Exception as e:
            logger.warning(f"mod_has_files_for_chapter: exception: {e}", exc_info=True)
            return True

    def _read_metadata(self) -> dict:
        with self.app_state._mods_metadata_lock:
            if not os.path.exists(self.app_state.mods_metadata_path):
                return {}
            try:
                return load_json(self.app_state.mods_metadata_path) or {}
            except Exception as e:
                logger.warning(f"_read_metadata: failed: {e}", exc_info=True)
                return {}

    def _write_metadata(self, data: dict):
        with self.app_state._mods_metadata_lock:
            try:
                save_json(self.app_state.mods_metadata_path, data, indent=2)
            except Exception as e:
                logger.error(f"_write_metadata: failed: {e}", exc_info=True)

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
                    metadata = load_json(self.app_state.mods_metadata_path)
                except Exception as e:
                    logger.warning(f"add_playtime_hours: failed to read metadata: {e}")
                    return
            if not isinstance(metadata, dict):
                logger.warning("add_playtime_hours: metadata is not an object")
                return
            changed = False
            for mod_id in mod_ids:
                if not mod_id:
                    continue
                entry = metadata.setdefault(mod_id, {})
                if not isinstance(entry, dict):
                    logger.warning(f"add_playtime_hours: metadata entry for {mod_id!r} is not an object, skipping it")
                    continue
                current = self._normalize_playtime_hours(entry.get("playtime_hours", 0))
                entry["playtime_hours"] = round(current + hours, 4)
                changed = True
            if changed:
                try:
                    save_json(self.app_state.mods_metadata_path, metadata, indent=2)
                except Exception as e:
                    logger.error(f"add_playtime_hours: failed to write metadata: {e}")

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

    def create_mod_object_from_info(self, mod_info: dict, all_mods: list | None = None):
        mod_id = mod_info.get("id", "")
        mod_info = dict(mod_info)
        transient_fields = {
            "playtime_hours": mod_info.get("playtime_hours", 0.0),
            "added_date": mod_info.get("added_date"),
            "last_updated": mod_info.get("last_updated"),
        }
        if mod_info.get("config_version") != MOD_CONFIG_VERSION:
            return None
        mod_info.update(
            {
                key: value
                for key, value in transient_fields.items()
                if value not in (None, "")
            }
        )
        if not is_gamebanana_id(mod_id):
            mod_info.pop(self._BROWSER_ONLY_DATE_FIELD, None)
        if all_mods:
            for mod in all_mods:
                existing_mod_id = get_mod_id(mod)
                if (
                    existing_mod_id == mod_id
                    and isinstance(mod, mod_models.LocalModInfo)
                ):
                    refreshed_mod = mod_models.LocalModInfo.from_dict(mod_info)
                    for attr in (
                        "name",
                        "version",
                        "authors",
                        "description",
                        "game",
                        "game_version",
                        "icon",
                        "tags",
                        "homepage",
                        "sections",
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
            if folder_name.startswith(".") or not os.path.isdir(folder_path):
                continue
            config_path = os.path.join(folder_path, MOD_CONFIG_FILENAME)
            if not os.path.exists(config_path):
                continue
            try:
                yield folder_name, folder_path, config_path, load_mod_config(config_path)
            except Exception as e:
                logger.warning(
                    f"_iter_mod_configs: failed to read {config_path}: {e}",
                    exc_info=True,
                )

    def get_installed_mods_list(self) -> list[dict]:
        installed_mods: list[dict] = []
        if not hasattr(self.app_state, "mods_dir") or not os.path.exists(
            self.app_state.mods_dir
        ):
            return installed_mods
        with self._cache_lock:
            needs_migration = not self._mods_cache_valid
        if needs_migration:
            self._migrate_owned_mods()
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
                is_gamebanana = is_gamebanana_id(mod_id)
                mods_metadata[mod_id] = {
                    "added_date": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "is_gamebanana": is_gamebanana,
                }
                metadata_updated = True
                mod_meta = mods_metadata[mod_id]
            mod_folder_path = (
                os.path.join(self.app_state.mods_dir, folder_name)
                if folder_name
                else ""
            )
            cfg = dict(config_data)
            cfg.pop(self._BROWSER_ONLY_DATE_FIELD, None)
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
                config_data = {}
                try:
                    config_data = info.config_data or {}
                    folder_name = info.folder_name
                    _append_from_config(config_data, folder_name)
                except Exception as e:
                    config_read_errors = True
                    config_mod_id = config_data.get("id", "") or cached_mod_id
                    logger.warning(
                        f"Failed to build installed mod from cache for id {config_mod_id}: {e}",
                        exc_info=True,
                    )
        else:
            for folder_name, _, _, config_data in self._iter_mod_configs():
                try:
                    _append_from_config(config_data, folder_name)
                except Exception as e:
                    config_read_errors = True
                    config_mod_id = (
                        config_data.get("id", "")
                        if config_data
                        else folder_name
                    )
                    logger.warning(
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
                changed = migrate_mod_metadata(config_data, mods_metadata)[1]
                if changed:
                    write_mod_config(config_path, config_data)
                    updated = True
            except Exception as e:
                logger.warning(
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
        logger.debug(f"parse_mod_date failed for '{date_str}': {e}")
    return (0, 0, 0, 0, 0)
