"""Patching service using G3MTool CLI."""

import contextlib
import glob
import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import time
import uuid
import zipfile
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal

from adapters.g3mtool_adapter import G3MToolManager
from config.config import (
    ARCHIVE_EXTENSIONS,
    DATA_FILE_EXTENSIONS,
    MAX_PATCHING_ARCHIVES,
    MOD_TYPE_CSX,
    MOD_TYPE_DATAFILE,
    MOD_TYPE_G3MPATCH,
    MOD_TYPE_OVERRIDES_ONLY,
    MOD_TYPE_XDELTA,
    SKIP_FILES,
)
from models.execution_plan import PatchPlan
from services.backup_service import BackupManager
from services.localization_service import tr
from services.warning_service import (
    WarningEvent,
    create_warning_event,
    is_warning_enabled,
)
from utils.file_utils import (
    ensure_writable,
    get_chapter_folder_name,
    safe_remove,
    safe_rmtree,
)
from utils.frickbears3_addons_utils import (
    is_addons_subpath,
    is_top_level_addons_archive,
)
from utils.mod.utils import get_mod_id
from utils.patching import mod_content_utils as mod_content
from utils.patching.file_override_plan import (
    OverrideCandidate,
    apply_override_plan,
    build_override_plan,
    destination_is_case_sensitive,
    discover_directory_candidates,
)
from utils.patching.file_override_utils import iter_configured_override_entries
from utils.patching.mod_resolve_utils import (
    get_mod_configured_data_file,
    get_mod_configured_extra_files,
    get_mod_source_dir,
    get_target_dir,
    has_mod_configured_chapter_entry,
)
from utils.path_utils import get_user_data_root
from utils.pizzatower_afom_utils import (
    is_top_level_towers_archive,
    is_towers_subpath,
)
from utils.process_utils import bounded_output_preview

logger = logging.getLogger(__name__)


def _get_patching_logs_dir() -> str:
    """Return logs/patching/ directory, creating it if needed."""
    d = os.path.join(get_user_data_root(), "logs", "patching")
    os.makedirs(d, exist_ok=True)
    return d


def _get_temp_reports_dir() -> str:
    """Return temp dir for persisted merge reports."""
    d = os.path.join(tempfile.gettempdir(), "g3m_conflict_reports")
    os.makedirs(d, exist_ok=True)
    return d


def _new_g3mtool_log_path() -> str | None:
    """Reserve a log file that no other G3MTool process will share."""
    try:
        archive_dir = _get_patching_logs_dir()
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"g3mtool_{os.getpid()}_{uuid.uuid4().hex[:8]}_{timestamp}.log"
        path = os.path.join(archive_dir, filename)
        with open(path, "x", encoding="utf-8"):
            pass
        return path
    except OSError as error:
        logger.warning("G3MTool file logging is unavailable: %s", error)
        return None


def _rotate_patching_files():
    """Rotate old patching.log and g3mtool.log into logs/patching/ with a timestamp."""
    logs_dir = os.path.join(get_user_data_root(), "logs")
    archive_dir = _get_patching_logs_dir()
    ts = time.strftime("%Y%m%d_%H%M%S")
    for name in ("patching.log", "g3mtool.log"):
        src = os.path.join(logs_dir, name)
        try:
            if os.path.isfile(src) and os.path.getsize(src) > 0:
                if name == "patching.log":
                    normalized_src = os.path.normcase(os.path.abspath(src))
                    patching_logger = logging.getLogger("patching")
                    for handler in list(patching_logger.handlers):
                        if (
                            isinstance(handler, logging.FileHandler)
                            and os.path.normcase(os.path.abspath(handler.baseFilename))
                            == normalized_src
                        ):
                            patching_logger.removeHandler(handler)
                            handler.close()
                base, ext = os.path.splitext(name)
                suffix = f"{os.getpid()}_{uuid.uuid4().hex[:8]}_{ts}"
                dst = os.path.join(archive_dir, f"{base}_{suffix}{ext}")
                shutil.move(src, dst)
        except OSError as error:
            logger.debug("Could not rotate patching log %s: %s", src, error)
    _enforce_archive_limit(archive_dir)


def _enforce_archive_limit(archive_dir: str):
    """Keep at most MAX_PATCHING_ARCHIVES of each file type."""
    for pattern in (
        "patching_*.log",
        "g3mtool_*.log",
        "conflicts_*.log",
    ):
        files = glob.glob(os.path.join(archive_dir, pattern))
        files.sort(key=_log_file_age)
        while len(files) > MAX_PATCHING_ARCHIVES:
            try:
                os.remove(files.pop(0))
            except Exception as e:
                logger.debug(
                    f"_enforce_archive_limit: failed to remove archived file: {e}",
                    exc_info=True,
                )
                break


def _log_file_age(path: str) -> tuple[float, str]:
    try:
        return (os.path.getmtime(path), path)
    except OSError:
        return (0.0, path)


def _get_patching_logger() -> logging.Logger:
    """Get or create a dedicated patching logger that writes to patching.log."""
    logger = logging.getLogger("patching")
    logs_dir = os.path.join(get_user_data_root(), "logs")
    os.makedirs(logs_dir, exist_ok=True)
    log_path = os.path.join(logs_dir, "patching.log")

    normalized_path = os.path.normcase(os.path.abspath(log_path))
    for handler in logger.handlers:
        handler_path = getattr(handler, "baseFilename", None)
        if (
            isinstance(handler, logging.FileHandler)
            and handler_path
            and os.path.normcase(os.path.abspath(handler_path)) == normalized_path
        ):
            try:
                if handler.stream and os.path.samestat(
                    os.fstat(handler.stream.fileno()), os.stat(log_path)
                ):
                    return logger
            except OSError:
                pass

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        with contextlib.suppress(Exception):
            handler.close()
    try:
        handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    except (PermissionError, OSError) as error:
        logger.warning(
            "Failed to initialize patching file logger at %s: %s",
            log_path,
            error,
        )
        logger.setLevel(logging.DEBUG)
        logger.propagate = True
        return logger
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    return logger


class G3MToolPatchingService(QObject):
    status_update = pyqtSignal(str, str)
    progress_update = pyqtSignal(int, str)

    def __init__(self, app_state, mod_service, parent=None) -> None:
        super().__init__(parent)
        self.app_state = app_state
        self.mod_service = mod_service
        self.g3mtool = G3MToolManager(app_state)
        self.backup_service: BackupManager | None = None
        self._cancelled = False
        self._temp_dir: str | None = None
        self._last_report_path: str | None = None
        self._saved_report_path: str | None = None
        self._xdelta_modpack: bool = False
        self._session_manifest_path: str | None = None
        self._override_game_path: str | None = None
        self._backup_root_override: str | None = None
        self._file_hashes: dict[tuple[str, int, int], str | None] = {}
        self.last_restore_external_changes: list[str] = []
        self.last_restore_conflict_archive: str | None = None
        self.warning_handler: Callable[[WarningEvent, str, str | None], bool] | None = (
            None
        )
        self.strict_warning_handler: (
            Callable[[WarningEvent, str, str | None], bool] | None
        ) = None

        _rotate_patching_files()
        self.patching_logger = _get_patching_logger()

    def _emit_progress(self, progress: int, message: str):
        self.progress_update.emit(max(0, min(progress, 100)), message)

    def _emit_chapter_progress(
        self, start: int, end: int, fraction: float, message: str
    ):
        bounded_fraction = max(0.0, min(fraction, 1.0))
        progress = start + int((end - start) * bounded_fraction)
        self._emit_progress(progress, message)

    def _request_warning(
        self,
        message: str,
        details: str = "",
        report_path: str | None = None,
        warning_id: str = "legacy_patching_warning",
        context: dict[str, Any] | None = None,
    ) -> bool:
        self.patching_logger.warning(message)
        if details:
            self.patching_logger.warning(details)
        event = create_warning_event(
            warning_id,
            context=context,
            details=details,
            report_path=report_path,
            fallback_message=message,
        )
        if self.strict_warning_handler:
            return bool(self.strict_warning_handler(event, details, report_path))
        local_config = getattr(self.app_state, "local_config", {}) or {}
        if not is_warning_enabled(warning_id, local_config):
            return True
        if self.warning_handler:
            return bool(self.warning_handler(event, details, report_path))
        return True

    def _continue_without_data_patch(
        self,
        warning_message: str,
        data_win_path: str,
        output_path: str,
        log_error: str,
        warning_id: str = "g3mpatch_apply_failed",
        warning_context: dict[str, Any] | None = None,
    ) -> bool:
        self.patching_logger.error(log_error)
        if not self._request_warning(
            warning_message,
            details=log_error,
            warning_id=warning_id,
            context=warning_context,
        ):
            return False
        try:
            shutil.copy2(data_win_path, output_path)
            self.patching_logger.warning(
                f"Continuing without data patch, copied original file to {output_path}"
            )
            return True
        except Exception as e:
            self.patching_logger.error(
                f"Failed to preserve original data file at {output_path}: {e}",
                exc_info=True,
            )
            self.status_update.emit(tr("errors.patching_failed", error=str(e)), "error")
            return False

    @staticmethod
    def _missing_output_error(output_path: str) -> str:
        return f"Patched output file was not created: {output_path}"

    def _hash_file_md5(self, path: str) -> str | None:
        try:
            stat = os.stat(path)
            cache_key = (os.path.abspath(path), stat.st_size, stat.st_mtime_ns)
            if cache_key in self._file_hashes:
                return self._file_hashes[cache_key]
            digest = hashlib.md5()  # noqa: S324
            with open(path, "rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            result = digest.hexdigest()
            self._file_hashes[cache_key] = result
            return result
        except Exception as e:
            logger.debug("Failed to compute MD5 for %s: %s", path, e)
            return None

    @staticmethod
    def _version_tuple(version: str | None) -> tuple[int, ...] | None:
        if not version:
            return None
        parts = re.findall(r"\d+", str(version))
        if not parts:
            return None
        numbers = [int(part) for part in parts[:4]]
        numbers.extend([0] * (4 - len(numbers)))
        return tuple(numbers)

    def _check_g3mpatch_tool_version_warning(
        self, patch_path: str, manifest: dict
    ) -> bool:
        tool = manifest.get("tool") if isinstance(manifest, dict) else None
        patch_tool_version = tool.get("version") if isinstance(tool, dict) else None
        patch_version_tuple = self._version_tuple(patch_tool_version)
        current_tool_version = self.g3mtool.get_version()
        current_version_tuple = self._version_tuple(current_tool_version)
        if not patch_version_tuple or not current_version_tuple:
            return True
        if patch_version_tuple <= current_version_tuple:
            return True

        should_continue = self._request_warning(
            tr("dialogs.patching_warning.g3mpatch_newer_tool_title"),
            tr(
                "dialogs.patching_warning.g3mpatch_newer_tool_body",
                patch_name=os.path.basename(patch_path),
                patch_tool_version=patch_tool_version,
                current_tool_version=current_tool_version,
            ),
            warning_id="g3mpatch_newer_tool",
            context={
                "patch_name": os.path.basename(patch_path),
                "patch_tool_version": patch_tool_version,
                "current_tool_version": current_tool_version,
            },
        )
        if not should_continue:
            return False
        self.patching_logger.warning(
            "G3MPatch %s was created by newer G3MTool %s; current bundled G3MTool is %s",
            patch_path,
            patch_tool_version,
            current_tool_version,
        )
        return True

    def _check_g3mpatch_validate_warning(
        self, patch_path: str, data_win_path: str
    ) -> bool:
        if not patch_path.lower().endswith((".g3mpatch", ".zip")):
            return True
        try:
            with zipfile.ZipFile(patch_path) as archive:
                manifest_entry = archive.getinfo("g3mpatch.json")
                with archive.open(manifest_entry) as handle:
                    manifest = json.loads(handle.read().decode("utf-8"))
        except Exception as e:
            self.patching_logger.debug(
                "G3MPatch validation skipped for %s: %s", patch_path, e
            )
            return True

        if not self._check_g3mpatch_tool_version_warning(patch_path, manifest):
            return False

        expected_md5 = (
            (manifest.get("original") or {}).get("md5")
            if isinstance(manifest, dict)
            else None
        )
        if not expected_md5:
            return True
        actual_md5 = self._hash_file_md5(data_win_path)
        if not actual_md5 or actual_md5 == expected_md5:
            return True
        expected_name = (
            (manifest.get("original") or {}).get("filename")
            if isinstance(manifest, dict)
            else None
        ) or os.path.basename(data_win_path)
        actual_name = os.path.basename(data_win_path)
        should_continue = self._request_warning(
            tr("dialogs.patching_warning.g3mpatch_validate_title"),
            tr(
                "dialogs.patching_warning.g3mpatch_validate_body",
                patch_name=os.path.basename(patch_path),
                expected_file=expected_name,
                actual_file=actual_name,
                expected_md5=expected_md5,
                actual_md5=actual_md5,
            ),
            warning_id="g3mpatch_original_hash_mismatch",
            context={
                "patch_name": os.path.basename(patch_path),
                "expected_file": expected_name,
                "actual_file": actual_name,
                "expected_md5": expected_md5,
                "actual_md5": actual_md5,
            },
        )
        if not should_continue:
            return False
        self.patching_logger.warning(
            "G3MPatch validate mismatch for %s: expected %s, got %s",
            patch_path,
            expected_md5,
            actual_md5,
        )
        return True

    def set_override_game_path(self, path: str | None) -> None:
        """Set override game path for patching operations."""
        self._override_game_path = path

    def set_backup_root_override(self, path: str | None) -> None:
        """Keep backups inside an isolated caller-owned workspace."""
        self._backup_root_override = path

    def process_sections(
        self,
        section_mods: dict[str, list[Any]],
        is_modpack: bool = False,
        modpack_dir: str | None = None,
    ) -> bool:
        self._cancelled = False
        self._last_report_path = None
        self._file_hashes.clear()

        if not self.g3mtool.is_available():
            reason = self.g3mtool.get_unavailable_reason()
            self.status_update.emit(reason, "error")
            self.patching_logger.error("G3MTool not available: %s", reason)
            return False

        try:
            self._temp_dir = tempfile.mkdtemp(prefix="g3m_patch_")

            if self._backup_root_override:
                backup_dir = self._backup_root_override
            elif is_modpack:
                backup_dir = os.path.join(self._temp_dir, "backups")
            else:
                backup_dir = os.path.join(get_user_data_root(), "patching_backups")
            self.backup_service = BackupManager(
                backup_dir, patching_logger=self.patching_logger
            )

            total_sections = len([mods for mods in section_mods.values() if mods])
            if total_sections == 0:
                self._emit_progress(100, tr("status.patching_completed"))
                return True
            section_index = 0

            for section_id, section_plan in sorted(section_mods.items()):
                if not section_plan or self._cancelled:
                    if self._cancelled:
                        self._restore_all(section_mods)
                        return False
                    continue

                mod_steps = (
                    [list(step) for step in section_plan if step]
                    if section_plan and isinstance(section_plan[0], list)
                    else [list(section_plan)]
                )
                mods_list = [mod for step in mod_steps for mod in step]

                section_index += 1
                display_name = self._get_section_display_name(section_id)
                section_start = min(
                    int((section_index - 1) / max(total_sections, 1) * 90) + 5, 95
                )
                section_end = min(
                    int(section_index / max(total_sections, 1) * 90) + 5, 95
                )
                self._emit_chapter_progress(
                    section_start,
                    section_end,
                    0.0,
                    tr("status.preparing_section", display=display_name),
                )

                success = self._patch_section(
                    section_id,
                    mods_list,
                    is_modpack,
                    modpack_dir,
                    section_start,
                    section_end,
                    display_name,
                    section_index,
                    total_sections,
                    mod_steps,
                )
                if not success:
                    if not is_modpack:
                        self._restore_all(section_mods)
                    return False

            self._emit_progress(
                96 if is_modpack else 100, tr("status.patching_completed")
            )
            return True
        except Exception as e:
            self.patching_logger.error(f"Patching failed: {e}", exc_info=True)
            self.status_update.emit(tr("errors.patching_failed", error=str(e)), "error")
            if not is_modpack:
                self._restore_all(section_mods)
            return False
        finally:
            if self._temp_dir and os.path.exists(self._temp_dir):
                safe_rmtree(self._temp_dir)
                self._temp_dir = None
            with contextlib.suppress(OSError):
                _enforce_archive_limit(_get_patching_logs_dir())

    def process_patch_plan(
        self,
        plan: PatchPlan,
        resolver: Callable[[str], Any | None],
        *,
        is_modpack: bool = False,
        modpack_dir: str | None = None,
    ) -> bool:
        """Resolve and execute a validated plan through the canonical patcher."""
        return self.process_sections(
            plan.resolve(resolver),
            is_modpack=is_modpack,
            modpack_dir=modpack_dir,
        )

    def _get_section_display_name(self, section_id: str) -> str:
        """Return the game-defined display name for a content section."""
        from models.game_modes import get_game

        game_def = (
            get_game(self.app_state.game_mode.game_id)
            if self.app_state and self.app_state.game_mode
            else None
        )
        if game_def:
            return game_def.get_tab_display_name(section_id)
        return section_id

    def _patch_section(
        self,
        chapter_id: str,
        mods_list: list[Any],
        is_modpack: bool,
        modpack_dir: str | None,
        chapter_start: int,
        chapter_end: int,
        display_name: str,
        chapter_index: int,
        total_chapters: int,
        mod_steps: list[list[Any]] | None = None,
    ) -> bool:
        self._emit_chapter_progress(
            chapter_start,
            chapter_end,
            0.03,
            tr(
                "status.processing_section",
                display=display_name,
                current=chapter_index,
                total=total_chapters,
            ),
        )
        if self._override_game_path:
            from utils.path_utils import find_chapter_resource_dir

            gm = self.app_state.game_mode
            mac_names = gm.macos_app_names if gm else ("DELTARUNE.app",)
            target_dir = find_chapter_resource_dir(
                self._override_game_path, chapter_id, mac_names
            )
        else:
            target_dir = get_target_dir(
                chapter_id, self.app_state, self.patching_logger
            )
        if not target_dir:
            self.status_update.emit(
                tr("errors.target_section_directory_not_found", section=chapter_id),
                "error",
            )
            return False
        self._emit_chapter_progress(
            chapter_start,
            chapter_end,
            0.08,
            tr("status.preparing_section", display=display_name),
        )

        if not ensure_writable(target_dir):
            self.status_update.emit(
                tr("errors.no_write_permission_for", path=target_dir), "error"
            )
            return False

        effective_steps = mod_steps or [mods_list]
        override_order = [
            mod_data for step in effective_steps for mod_data in reversed(step)
        ]
        game_mode = self.app_state.game_mode
        data_win_path = mod_content.find_data_win(
            target_dir, game_id=game_mode.game_id if game_mode else ""
        )
        if not data_win_path:
            if not self._request_warning(
                tr(
                    "dialogs.patching_warning.data_win_not_found",
                    search_path=target_dir,
                ),
                warning_id="data_file_missing",
                context={"search_path": target_dir},
            ):
                return False
            self._emit_chapter_progress(
                chapter_start,
                chapter_end,
                0.12,
                tr("status.preparing_section", display=display_name),
            )
            success = self._apply_file_overrides_only(
                override_order,
                target_dir,
                chapter_id,
                chapter_start,
                chapter_end,
                0.12,
                0.98,
            )
            if success:
                self._emit_chapter_progress(
                    chapter_start,
                    chapter_end,
                    1.0,
                    tr("status.section_patched", section=display_name),
                )
            return success

        step_mod_infos = [
            self._collect_mod_infos(step, chapter_id) for step in effective_steps
        ]
        data_steps = [
            [(pf, mt, sd) for pf, mt, sd in infos if mt != MOD_TYPE_OVERRIDES_ONLY]
            for infos in step_mod_infos
        ]
        data_mod_infos = [info for step in data_steps for info in step]

        if not data_mod_infos:
            self.patching_logger.info(
                "No data-modifying patches for content section %s; "
                "applying file overrides only",
                chapter_id,
            )
            success = self._apply_file_overrides_only(
                override_order,
                target_dir,
                chapter_id,
                chapter_start,
                chapter_end,
                0.18,
                0.98,
            )
            if success:
                self._emit_chapter_progress(
                    chapter_start,
                    chapter_end,
                    1.0,
                    tr("status.section_patched", section=display_name),
                )
            return success

        if not is_modpack and not self._backup_or_mark_file(chapter_id, data_win_path):
            return False

        final_output_path = data_win_path
        if is_modpack and modpack_dir:
            game = self._resolve_mod_game(mods_list[0]) if mods_list else None
            chapter_folder_name = get_chapter_folder_name(chapter_id, game=game)
            chapter_modpack_dir = os.path.join(modpack_dir, chapter_folder_name)
            os.makedirs(chapter_modpack_dir, exist_ok=True)
            final_output_path = os.path.join(
                chapter_modpack_dir, os.path.basename(data_win_path)
            )

        log_path = _new_g3mtool_log_path()

        temp_output = os.path.join(
            self._temp_dir or tempfile.gettempdir(),
            f"output_{chapter_id}_{os.path.basename(data_win_path)}",
        )

        success = False
        if not is_modpack:
            self._emit_chapter_progress(
                chapter_start,
                chapter_end,
                0.18,
                tr("status.patching_section", section=display_name, current=1, total=1),
            )
        success = self._apply_data_steps(
            data_win_path,
            data_steps,
            temp_output,
            log_path,
            chapter_id,
            chapter_start,
            chapter_end,
            display_name,
        )

        if not success:
            return False

        self._emit_chapter_progress(
            chapter_start,
            chapter_end,
            0.76,
            tr("status.finalizing_section", display=display_name),
        )
        try:
            shutil.move(temp_output, final_output_path)
            self.patching_logger.info(f"Patched data.win placed at {final_output_path}")
        except Exception as e:
            self.patching_logger.error(
                f"Failed to move patched file to {final_output_path}: {e}",
                exc_info=True,
            )
            return False

        override_target = (
            target_dir if not is_modpack else os.path.dirname(final_output_path)
        )
        override_mods = [
            (mod_data, self._get_mod_source_dir(mod_data, chapter_id))
            for mod_data in override_order
        ]
        override_mods = [(mod_data, path) for mod_data, path in override_mods if path]
        if not self._apply_ordered_file_overrides(
            override_mods,
            override_target,
            chapter_id,
            is_modpack,
            chapter_start,
            chapter_end,
        ):
            return False

        self._emit_chapter_progress(
            chapter_start,
            chapter_end,
            1.0,
            tr("status.section_patched", section=display_name),
        )

        return True

    def _apply_single_mod(
        self,
        data_win_path: str,
        mod_info: tuple,
        output_path: str,
        log_path: str | None,
        chapter_start: int,
        chapter_end: int,
        display_name: str,
    ) -> bool:
        patch_file, mod_type, *_ = mod_info

        if mod_type == MOD_TYPE_DATAFILE:
            self.patching_logger.info("Copying replacement DATA file: %s", patch_file)
            self._emit_chapter_progress(
                chapter_start,
                chapter_end,
                0.35,
                tr("status.patching_section", section=display_name, current=1, total=1),
            )
            try:
                shutil.copy2(patch_file, output_path)
                return True
            except OSError as error:
                self.patching_logger.error(
                    "Failed to copy replacement DATA file: %s", error, exc_info=True
                )
                return False

        if mod_type in {
            MOD_TYPE_CSX,
            MOD_TYPE_XDELTA,
            MOD_TYPE_G3MPATCH,
        }:
            self.patching_logger.info(
                "Applying data input through G3MTool: %s", patch_file
            )
            self._emit_chapter_progress(
                chapter_start,
                chapter_end,
                0.30,
                tr("status.patching_section", section=display_name, current=1, total=1),
            )
            returncode, stdout, stderr = self.g3mtool.apply_patch(
                data_win_path,
                patch_file,
                output_path,
                log_path=log_path,
                progress_callback=lambda progress, _label: self._emit_chapter_progress(
                    chapter_start,
                    chapter_end,
                    0.30 + (progress / 100 * 0.40),
                    tr(
                        "status.patching_section",
                        section=display_name,
                        current=1,
                        total=1,
                    ),
                ),
            )
            if returncode == 0 and os.path.exists(output_path):
                return True
            error_text = (stderr or stdout) or self._missing_output_error(output_path)
            error_preview = bounded_output_preview(error_text)
            warning_id = (
                "xdelta_apply_failed"
                if mod_type == MOD_TYPE_XDELTA
                else "g3mpatch_apply_failed"
            )
            return self._continue_without_data_patch(
                tr(
                    "dialogs.patching_warning.data_patch_failed",
                    patch_name=os.path.basename(patch_file),
                    patch_path=patch_file,
                    data_win_path=data_win_path,
                    error=error_preview,
                ),
                data_win_path,
                output_path,
                f"G3MTool universal apply failed: {error_text}",
                warning_id=warning_id,
                warning_context={
                    "patch_name": os.path.basename(patch_file),
                    "reason": error_preview,
                },
            )

        self.patching_logger.error(f"Unknown mod_type: {mod_type}")
        return False

    def _apply_data_steps(
        self,
        data_win_path: str,
        data_steps: list[list[tuple]],
        output_path: str,
        log_path: str | None,
        chapter_id: str,
        chapter_start: int,
        chapter_end: int,
        display_name: str,
    ) -> bool:
        active_steps = [step for step in data_steps if step]
        if not active_steps:
            shutil.copy2(data_win_path, output_path)
            return True
        current_input = data_win_path
        extension = os.path.splitext(data_win_path)[1]
        for index, step in enumerate(active_steps, start=1):
            if self._cancelled:
                return False
            is_last = index == len(active_steps)
            step_output = (
                output_path
                if is_last
                else os.path.join(
                    self._temp_dir or tempfile.gettempdir(),
                    f"step_{chapter_id}_{index}{extension}",
                )
            )
            data_start = chapter_start + int((chapter_end - chapter_start) * 0.18)
            data_end = chapter_start + int((chapter_end - chapter_start) * 0.76)
            step_start = data_start + int(
                (data_end - data_start) * (index - 1) / len(active_steps)
            )
            step_end = data_start + int(
                (data_end - data_start) * index / len(active_steps)
            )
            for patch_file, mod_type, *_ in step:
                if (
                    mod_type == MOD_TYPE_G3MPATCH
                    and patch_file
                    and os.path.exists(patch_file)
                    and not self._check_g3mpatch_validate_warning(
                        patch_file, current_input
                    )
                ):
                    return False
            if len(step) == 1:
                success = self._apply_single_mod(
                    current_input,
                    step[0],
                    step_output,
                    log_path,
                    step_start,
                    step_end,
                    display_name,
                )
            else:
                success = self._apply_multi_mod(
                    current_input,
                    list(reversed(step)),
                    step_output,
                    log_path,
                    f"{chapter_id}_step_{index}",
                    step_start,
                    step_end,
                    display_name,
                )
            if not success or not os.path.exists(step_output):
                return False
            current_input = step_output
        return True

    def _apply_ordered_file_overrides(
        self,
        override_mods: list[tuple[Any, str]],
        target_dir: str,
        chapter_id: str,
        is_modpack: bool,
        chapter_start: int,
        chapter_end: int,
    ) -> bool:
        """Apply simple overrides once; retain ordered fallback for transforms."""
        can_plan = bool(override_mods) and all(
            os.path.isdir(source) for _mod, source in override_mods
        )
        configured_entries: dict[int, list[dict[str, Any]]] = {}
        configured_mods: set[int] = set()
        transform_extensions = (".xdelta", ".vcdiff", *ARCHIVE_EXTENSIONS)
        if can_plan:
            for mod_data, source in override_mods:
                has_config = has_mod_configured_chapter_entry(
                    mod_data,
                    chapter_id,
                    self.mod_service,
                    self.app_state,
                    self.patching_logger,
                )
                paths = (
                    get_mod_configured_extra_files(
                        mod_data,
                        chapter_id,
                        self.mod_service,
                        self.app_state,
                        self.patching_logger,
                    )
                    if has_config
                    else None
                )
                if has_config:
                    configured_mods.add(id(mod_data))
                entries = (
                    list(
                        iter_configured_override_entries(
                            self.mod_service.get_mod_folder_path(get_mod_id(mod_data)),
                            paths,
                            chapter_id,
                            self._resolve_mod_game(mod_data),
                        )
                    )
                    if paths
                    else []
                )
                configured_entries[id(mod_data)] = entries
                scan_roots = [
                    entry["source"]
                    for entry in entries
                    if entry["is_directory"] and os.path.isdir(entry["source"])
                ] or ([source] if not has_config else [])
                direct_files = [
                    entry["source"] for entry in entries if not entry["is_directory"]
                ]
                if any(
                    path.casefold().endswith(transform_extensions)
                    for path in direct_files
                ):
                    can_plan = False
                    break
                if any(
                    file.casefold().endswith(transform_extensions)
                    for scan_root in scan_roots
                    for _root, _dirs, files in os.walk(scan_root)
                    for file in files
                ):
                    can_plan = False
                    break
        if can_plan:
            candidates = []
            excluded_extensions = tuple(DATA_FILE_EXTENSIONS)
            for priority, (mod_data, source) in enumerate(override_mods):
                entries = configured_entries.get(id(mod_data), [])
                if id(mod_data) in configured_mods:
                    for entry in entries:
                        entry_root = entry.get("target_root") or target_dir
                        target = os.path.join(
                            entry_root, entry["target_relative"].rstrip("/")
                        )
                        if entry["is_directory"]:
                            candidates.extend(
                                discover_directory_candidates(
                                    entry["source"],
                                    target,
                                    priority=priority,
                                    excluded_extensions=excluded_extensions,
                                    follow_symlinks=True,
                                )
                            )
                        elif os.path.isfile(entry["source"]):
                            candidates.append(
                                OverrideCandidate(entry["source"], target, priority)
                            )
                else:
                    candidates.extend(
                        discover_directory_candidates(
                            source,
                            target_dir,
                            priority=priority,
                            excluded_extensions=excluded_extensions,
                            excluded_names=set(SKIP_FILES),
                            exclude_relative=lambda path: (
                                is_addons_subpath(path)
                                or is_top_level_addons_archive(path)
                                or is_towers_subpath(path)
                                or is_top_level_towers_archive(path)
                            ),
                            follow_symlinks=True,
                        )
                    )
            plan = build_override_plan(
                candidates,
                case_sensitive=destination_is_case_sensitive(target_dir),
            )
            return apply_override_plan(
                plan,
                backup_or_mark=lambda target: (
                    None
                    if is_modpack
                    else self._backup_or_mark_file(chapter_id, target)
                ),
                cancelled=lambda: self._cancelled,
            )

        total = len(override_mods)
        for index, (mod_data, source) in enumerate(override_mods, start=1):
            mod_name = (
                getattr(mod_data, "name", None)
                or getattr(mod_data, "mod_name", None)
                or os.path.basename(source)
            )
            start = 0.78 + ((index - 1) / max(total, 1) * 0.20)
            end = 0.78 + (index / max(total, 1) * 0.20)
            if not self._apply_file_overrides(
                source,
                target_dir,
                chapter_id,
                is_modpack,
                chapter_start,
                chapter_end,
                start,
                end,
                mod_name,
                mod_data,
            ):
                return False
        return True

    def _apply_multi_mod(
        self,
        data_win_path: str,
        mod_infos: list[tuple],
        output_path: str,
        log_path: str | None,
        chapter_id: str,
        chapter_start: int,
        chapter_end: int,
        display_name: str,
    ) -> bool:
        patch_files = [patch_file for patch_file, _mod_type, *_ in mod_infos]
        if not patch_files:
            return True
        report_path = (
            os.path.join(self._temp_dir, f"merge_report_{chapter_id}.md")
            if self._temp_dir
            else None
        )

        self.patching_logger.info(
            "Merging %s raw mod inputs through G3MTool for chapter %s: %s",
            len(patch_files),
            chapter_id,
            ", ".join(os.path.basename(path) for path in patch_files),
        )

        merge_code = self.app_state.local_config.get("merge_code", False)
        merge_properties = self.app_state.local_config.get("merge_properties", False)

        returncode, stdout, stderr = self.g3mtool.merge_patches(
            data_win_path,
            patch_files,
            output_path,
            report_path=report_path,
            log_path=log_path,
            merge_code=merge_code,
            merge_properties=merge_properties,
            progress_callback=lambda progress, _label: self._emit_chapter_progress(
                chapter_start,
                chapter_end,
                0.44 + (progress / 100 * 0.28),
                tr(
                    "status.patching_section",
                    section=display_name,
                    current=max(
                        1,
                        min(
                            len(patch_files),
                            progress * len(patch_files) // 100 + 1,
                        ),
                    ),
                    total=len(patch_files),
                ),
            ),
        )
        if returncode != 0:
            error_text = (stderr or stdout) or "Unknown error"
            error_preview = bounded_output_preview(error_text)
            return self._continue_without_data_patch(
                tr(
                    "dialogs.patching_warning.data_patch_failed",
                    patch_name=f"{len(patch_files)} patches",
                    patch_path="\n".join(patch_files),
                    data_win_path=data_win_path,
                    error=error_preview,
                ),
                data_win_path,
                output_path,
                f"G3MTool merge failed for content section {chapter_id}: {error_text}",
                warning_id="merge_failed",
                warning_context={
                    "patch_name": f"{len(patch_files)} patches",
                    "reason": error_preview,
                },
            )
        if not os.path.exists(output_path):
            error_text = self._missing_output_error(output_path)
            return self._continue_without_data_patch(
                tr(
                    "dialogs.patching_warning.data_patch_failed",
                    patch_name=f"{len(patch_files)} patches",
                    patch_path="\n".join(patch_files),
                    data_win_path=data_win_path,
                    error=error_text,
                ),
                data_win_path,
                output_path,
                error_text,
                warning_id="patched_output_missing",
                warning_context={"output_path": output_path},
            )

        if report_path and os.path.exists(report_path):
            self._last_report_path = report_path

            self._saved_report_path = self._persist_conflict_artifacts(
                report_path, chapter_id
            )
            if self.report_has_conflicts():
                total_conflicts = self.get_report_stats()[0]
                if not self._request_warning(
                    tr(
                        "dialogs.patching_warning.conflicts_detected",
                        chapter=display_name,
                        count=total_conflicts,
                    ),
                    details=tr(
                        "dialogs.conflicts.total_conflicts", count=total_conflicts
                    ),
                    report_path=self._saved_report_path or report_path,
                    warning_id="merge_conflicts_detected",
                    context={
                        "chapter": display_name,
                        "count": total_conflicts,
                    },
                ):
                    return False

        return True

    def _persist_conflict_artifacts(
        self, report_path: str, chapter_id: str
    ) -> str | None:
        """Persist temp merge report and write conflict logs without archiving markdown into logs."""
        try:
            archive_dir = _get_patching_logs_dir()
            logs_dir = os.path.join(get_user_data_root(), "logs")
            temp_reports_dir = _get_temp_reports_dir()
            os.makedirs(logs_dir, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            report_dest = os.path.join(
                temp_reports_dir, f"merge_report_{chapter_id}_{ts}.md"
            )
            conflicts_dest = os.path.join(archive_dir, f"conflicts_{ts}.log")
            current_conflicts_log = os.path.join(logs_dir, "conflicts.log")
            shutil.copy2(report_path, report_dest)
            shutil.copy2(report_path, conflicts_dest)
            shutil.copy2(report_path, current_conflicts_log)
            _enforce_archive_limit(archive_dir)
            self.patching_logger.info(
                "Conflict artifacts saved for content section %s", chapter_id
            )
            self._enforce_temp_report_limit(temp_reports_dir)
            return report_dest
        except Exception as e:
            self.patching_logger.warning(f"Failed to persist conflict artifacts: {e}")
            return report_path

    def _enforce_temp_report_limit(self, reports_dir: str) -> None:
        files = sorted(glob.glob(os.path.join(reports_dir, "merge_report_*.md")))
        while len(files) > MAX_PATCHING_ARCHIVES:
            try:
                os.remove(files.pop(0))
            except Exception as e:
                self.patching_logger.debug(
                    "Failed to remove old temp conflict report: %s", e, exc_info=True
                )
                break

    def _collect_mod_infos(
        self, mods_list: list[Any], chapter_id: str
    ) -> list[tuple[str | None, str, str | None]]:
        """Returns list of (patch_file, mod_type, mod_source_dir) for each mod."""
        result = []
        for mod_data in mods_list:
            mod_source_dir = self._get_mod_source_dir(mod_data, chapter_id)
            has_config_entry = has_mod_configured_chapter_entry(
                mod_data,
                chapter_id,
                self.mod_service,
                self.app_state,
                self.patching_logger,
            )
            patch_file = get_mod_configured_data_file(
                mod_data,
                chapter_id,
                self.mod_service,
                self.app_state,
                self.patching_logger,
            )
            if patch_file and os.path.exists(patch_file):
                patch_file, mod_type = mod_content.classify_patch_file(patch_file)
            elif has_config_entry and mod_source_dir:
                if patch_file:
                    self.patching_logger.warning(
                        "Configured data file for chapter %s is missing: %s",
                        chapter_id,
                        patch_file,
                    )
                patch_file, mod_type = None, MOD_TYPE_OVERRIDES_ONLY
            elif mod_source_dir:
                patch_file, mod_type = self._classify_mod(mod_source_dir)
            else:
                if patch_file:
                    self.patching_logger.warning(
                        "Configured data file for chapter %s is missing: %s",
                        chapter_id,
                        patch_file,
                    )
                continue
            result.append((patch_file, mod_type, mod_source_dir))
        return result

    def _classify_mod(self, mod_source_dir: str) -> tuple[str | None, str]:
        """Classify a mod and return (patch_file, mod_type)."""
        return mod_content.classify_mod_directory(mod_source_dir)

    def _apply_file_overrides_only(
        self,
        mods_list: list[Any],
        target_dir: str,
        chapter_id: str,
        chapter_start: int,
        chapter_end: int,
        progress_start: float,
        progress_end: float,
        mod_data: Any | None = None,
    ) -> bool:
        override_mods = [
            (mod_data, self._get_mod_source_dir(mod_data, chapter_id))
            for mod_data in mods_list
        ]
        override_mods = [(mod_data, path) for mod_data, path in override_mods if path]
        for idx, (mod_data, mod_source_dir) in enumerate(override_mods, start=1):
            mod_name = (
                getattr(mod_data, "name", None)
                or getattr(mod_data, "mod_name", None)
                or os.path.basename(mod_source_dir)
            )
            mod_start = progress_start + (
                (idx - 1) / max(len(override_mods), 1) * (progress_end - progress_start)
            )
            mod_end = progress_start + (
                idx / max(len(override_mods), 1) * (progress_end - progress_start)
            )
            if not self._apply_file_overrides(
                mod_source_dir,
                target_dir,
                chapter_id,
                False,
                chapter_start,
                chapter_end,
                mod_start,
                mod_end,
                mod_name,
                mod_data,
            ):
                return False
        return True

    def _apply_file_overrides(
        self,
        mod_source_dir: str,
        target_dir: str,
        chapter_id: str,
        is_modpack: bool,
        chapter_start: int,
        chapter_end: int,
        progress_start: float,
        progress_end: float,
        mod_name: str,
        mod_data=None,
    ) -> bool:
        from utils.mod.utils import get_mod_id
        from utils.patching.file_override_utils import apply_file_overrides

        has_config_entry = (
            has_mod_configured_chapter_entry(
                mod_data,
                chapter_id,
                self.mod_service,
                self.app_state,
                self.patching_logger,
            )
            if mod_data is not None
            else False
        )
        configured_paths = (
            get_mod_configured_extra_files(
                mod_data,
                chapter_id,
                self.mod_service,
                self.app_state,
                self.patching_logger,
            )
            if has_config_entry
            else None
        )
        mod_root_dir = (
            self.mod_service.get_mod_folder_path(get_mod_id(mod_data))
            if mod_data is not None
            else None
        )
        return apply_file_overrides(
            self,
            mod_source_dir,
            target_dir,
            set(),
            is_modpack,
            chapter_id,
            progress_callback=lambda fraction, message: self._emit_chapter_progress(
                chapter_start,
                chapter_end,
                progress_start + ((progress_end - progress_start) * fraction),
                message,
            ),
            mod_name=mod_name,
            game_id=self._resolve_mod_game(mod_data),
            configured_paths=configured_paths,
            mod_root_dir=mod_root_dir,
        )

    def _backup_or_mark_file(self, chapter_id, target_file: str) -> bool:
        if chapter_id is None or not self.backup_service:
            return True
        if os.path.exists(target_file):
            if not self.backup_service.backup_file(chapter_id, target_file):
                self.patching_logger.error(
                    "CRITICAL: Failed to backup %s - aborting to protect game files",
                    target_file,
                )
                self.status_update.emit(tr("errors.backup_failed", path=target_file), "error")
                return False
        else:
            self.backup_service.mark_file_added(chapter_id, target_file)
        if self._write_session_manifest():
            return True
        self.patching_logger.error(
            "Patching aborted because the recovery manifest could not be saved"
        )
        return False

    def _apply_xdelta_to_file(self, target_file: str, patch_path: str) -> bool:
        """Apply xdelta patch to a non-data.win file (used by file_override_utils)."""
        if not self.g3mtool.is_available():
            return False
        try:
            descriptor, temp_output = tempfile.mkstemp(
                prefix=f".{os.path.basename(target_file)}.",
                suffix=".tmp",
                dir=os.path.dirname(target_file) or ".",
            )
        except OSError as error:
            self.patching_logger.debug(
                "_apply_xdelta_to_file: failed to create temporary output: %s", error
            )
            return False
        os.close(descriptor)
        safe_remove(temp_output)
        returncode = self.g3mtool.xpatch_apply(target_file, patch_path, temp_output)[0]
        if returncode == 0 and os.path.isfile(temp_output):
            try:
                os.replace(temp_output, target_file)
                return True
            except Exception as e:
                self.patching_logger.debug(
                    f"_apply_xdelta_to_file: failed to move patched output into place: {e}",
                    exc_info=True,
                )
        safe_remove(temp_output)
        return False

    def _get_mod_source_dir(self, mod_data: Any, chapter_id: str) -> str | None:
        return get_mod_source_dir(
            mod_data, chapter_id, self.mod_service, self.app_state, self.patching_logger
        )

    @staticmethod
    def _resolve_mod_game(mod_data) -> str | None:
        from utils.patching.mod_resolve_utils import resolve_mod_game

        return resolve_mod_game(mod_data)

    def get_report_path(self) -> str | None:
        """Return the saved (permanent) report path if available, else the temp one."""
        return self._saved_report_path or self._last_report_path

    def _read_report_content(self) -> str | None:
        """Read the report content, preferring the saved permanent path."""
        path = self._saved_report_path or self._last_report_path
        if not path or not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as f:
                return f.read()
        except Exception:
            return None

    def report_has_conflicts(self) -> bool:
        content = self._read_report_content()
        if not content:
            return False
        total = self._parse_conflict_counts(content)[0]
        return total > 0

    def get_report_stats(self) -> tuple[int, int]:
        content = self._read_report_content()
        if not content:
            return (0, 0)
        return self._parse_conflict_counts(content)

    @staticmethod
    def _parse_count_field(content: str, field_pattern: str) -> int:
        matches = (
            re.finditer(rf"(?i)(?:total\s+)?{field_pattern}\s*[:=]\s*(\d+)", content),
            re.finditer(rf"(?i)(\d+)[ \t]+{field_pattern}\b", content),
        )
        return max(
            (int(match.group(1)) for group in matches for match in group), default=0
        )

    @classmethod
    def _parse_conflict_counts(cls, content: str) -> tuple[int, int]:
        """Extract actual conflict/auto-resolved counts from the report markdown."""
        total = cls._parse_count_field(content, r"conflicts?")
        auto_resolved = cls._parse_count_field(content, r"auto[- ]?resolved?")

        if total == 0:
            conflict_sections = re.findall(
                r"^#{1,4}\s+.*conflict.*$", content, re.MULTILINE | re.IGNORECASE
            )

            total = len(
                [
                    s
                    for s in conflict_sections
                    if not re.search(r"(?i)summary|total|report|detected", s)
                ]
            )
        return (total, auto_resolved)

    def _write_session_manifest(self) -> bool:
        """Write session manifest so backups can be recovered after a crash."""
        manifest_path = self._session_manifest_path
        if not manifest_path:
            return True
        if not self.backup_service:
            return False
        return self.backup_service.save_backups_to_manifest(manifest_path)

    def _restore_all(self, section_mods: dict) -> None:
        if self.backup_service:
            results = [
                self.backup_service.restore_backups(section_id)
                for section_id in section_mods
            ]
            if all(results):
                self.backup_service.clear_backup_dir()

    def restore_all_backups(self) -> bool:
        if self.backup_service:
            self.last_restore_external_changes = []
            self.last_restore_conflict_archive = None
            result = self.backup_service.restore_all_backups()
            if not result and self.backup_service.external_changes:
                self.last_restore_external_changes = list(
                    self.backup_service.external_changes
                )
                archive = self.backup_service.archive_conflicted_session()
                if archive:
                    self.last_restore_conflict_archive = archive
                    return True
            if result:
                self.backup_service.clear_backup_dir()
            return result
        return False

    def finalize_session_state(self) -> bool:
        if not self.backup_service or (
            not self.backup_service.original_files
            and not self.backup_service.added_files
        ):
            return True
        return self.backup_service.capture_deployed_state()

    def cleanup_processes_and_temp_files(self) -> None:
        """Called from app_cleanup.py on close."""
        self.g3mtool.cancel_active_processes()

    def cleanup(self, force: bool = False) -> None:
        self.g3mtool.cancel_active_processes()
        if force and self._temp_dir and os.path.exists(self._temp_dir):
            safe_rmtree(self._temp_dir)
            self._temp_dir = None

    def cancel(self) -> None:
        self._cancelled = True
        self.g3mtool.cancel_active_processes()

    @property
    def xdelta_modpack(self):
        return self._xdelta_modpack

    @xdelta_modpack.setter
    def xdelta_modpack(self, value: bool):
        self._xdelta_modpack = value
