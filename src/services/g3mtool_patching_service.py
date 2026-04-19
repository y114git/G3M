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
import zipfile
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal

from adapters.g3mtool_adapter import G3MToolManager
from config.config import (
    MAX_PATCHING_ARCHIVES,
    MOD_TYPE_CSX,
    MOD_TYPE_DATAFILE,
    MOD_TYPE_G3MPATCH,
    MOD_TYPE_OVERRIDES_ONLY,
    MOD_TYPE_XDELTA,
)
from services.backup_service import BackupManager
from services.localization_service import tr
from utils.file_utils import ensure_writable, get_chapter_folder_name, safe_rmtree
from utils.patching import mod_content_utils as mod_content
from utils.patching.mod_resolve_utils import (
    get_mod_configured_data_file,
    get_mod_configured_extra_files,
    get_mod_source_dir,
    get_target_dir,
    has_mod_configured_chapter_entry,
)
from utils.path_utils import get_user_data_root


def _get_patching_logs_dir() -> str:
    """Return logs/patching/ directory, creating it if needed."""
    d = os.path.join(get_user_data_root(), "logs", "patching")
    os.makedirs(d, exist_ok=True)
    return d


def _rotate_patching_files():
    """Rotate old patching.log and g3mtool.log into logs/patching/ with a timestamp."""
    logs_dir = os.path.join(get_user_data_root(), "logs")
    archive_dir = _get_patching_logs_dir()
    ts = time.strftime("%Y%m%d_%H%M%S")
    for name in ("patching.log", "g3mtool.log"):
        src = os.path.join(logs_dir, name)
        if os.path.isfile(src) and os.path.getsize(src) > 0:
            base, ext = os.path.splitext(name)
            dst = os.path.join(archive_dir, f"{base}_{ts}{ext}")
            with contextlib.suppress(Exception):
                shutil.move(src, dst)
    _enforce_archive_limit(archive_dir)


def _enforce_archive_limit(archive_dir: str):
    """Keep at most MAX_PATCHING_ARCHIVES of each file type."""
    for pattern in ("patching_*.log", "g3mtool_*.log", "merge_report_*.md"):
        files = sorted(glob.glob(os.path.join(archive_dir, pattern)))
        while len(files) > MAX_PATCHING_ARCHIVES:
            try:
                os.remove(files.pop(0))
            except Exception as e:
                logging.debug(
                    f"_enforce_archive_limit: failed to remove archived file: {e}",
                    exc_info=True,
                )
                break


def _get_patching_logger() -> logging.Logger:
    """Get or create a dedicated patching logger that writes to patching.log."""
    logger = logging.getLogger("patching")

    for h in list(logger.handlers):
        logger.removeHandler(h)
        with contextlib.suppress(Exception):
            h.close()
    logs_dir = os.path.join(get_user_data_root(), "logs")
    os.makedirs(logs_dir, exist_ok=True)
    log_path = os.path.join(logs_dir, "patching.log")
    try:
        handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    except (PermissionError, OSError) as error:
        logging.warning(
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
        self.g3mtool = G3MToolManager()
        self.backup_service: BackupManager | None = None
        self._cancelled = False
        self._temp_dir: str | None = None
        self._last_report_path: str | None = None
        self._saved_report_path: str | None = None
        self._xdelta_modpack: bool = False
        self._session_manifest_path: str | None = None
        self._override_game_path: str | None = None
        self.warning_handler: Callable[[str, str, str | None], bool] | None = None

        _rotate_patching_files()
        self.patching_logger = _get_patching_logger()
        self._g3mtool_version: str | None = None

    def _emit_progress(self, progress: int, message: str):
        self.progress_update.emit(max(0, min(progress, 100)), message)

    def _emit_chapter_progress(
        self, start: int, end: int, fraction: float, message: str
    ):
        bounded_fraction = max(0.0, min(fraction, 1.0))
        progress = start + int((end - start) * bounded_fraction)
        self._emit_progress(progress, message)

    def _request_warning(
        self, message: str, details: str = "", report_path: str | None = None
    ) -> bool:
        self.patching_logger.warning(message)
        if details:
            self.patching_logger.warning(details)
        local_config = getattr(self.app_state, "local_config", {}) or {}
        if local_config.get("skip_patching_warnings", False):
            return True
        if self.warning_handler:
            return bool(self.warning_handler(message, details, report_path))
        return True

    def _continue_without_data_patch(
        self,
        warning_message: str,
        data_win_path: str,
        output_path: str,
        log_error: str,
    ) -> bool:
        self.patching_logger.error(log_error)
        if not self._request_warning(warning_message):
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

    @staticmethod
    def _hash_file_md5(path: str) -> str | None:
        try:
            digest = hashlib.md5()  # noqa: S324
            with open(path, "rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            return digest.hexdigest()
        except Exception as e:
            logging.debug("Failed to compute MD5 for %s: %s", path, e)
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

    def _get_g3mtool_version(self) -> str | None:
        if self._g3mtool_version is None:
            self._g3mtool_version = self.g3mtool.get_version() or ""
        return self._g3mtool_version or None

    def _check_g3mpatch_tool_version_warning(
        self, patch_path: str, manifest: dict
    ) -> bool:
        tool = manifest.get("tool") if isinstance(manifest, dict) else None
        patch_tool_version = tool.get("version") if isinstance(tool, dict) else None
        patch_version_tuple = self._version_tuple(patch_tool_version)
        current_tool_version = self._get_g3mtool_version()
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

    def process_mod_patch(
        self,
        chapter_mods: dict[str, list[Any]],
        is_modpack: bool = False,
        modpack_dir: str | None = None,
    ) -> bool:
        self._cancelled = False
        self._last_report_path = None

        if not self.g3mtool.is_available():
            self.status_update.emit(tr("errors.g3mtool_not_available"), "error")
            self.patching_logger.error("G3MTool not available")
            return False

        try:
            self._temp_dir = tempfile.mkdtemp(prefix="g3m_patch_")

            if is_modpack:
                backup_dir = os.path.join(self._temp_dir, "backups")
            else:
                backup_dir = os.path.join(get_user_data_root(), "patching_backups")
            self.backup_service = BackupManager(
                backup_dir, patching_logger=self.patching_logger
            )

            total_chapters = len([c for c in chapter_mods.values() if c])
            if total_chapters == 0:
                self._emit_progress(100, tr("status.patching_completed"))
                return True
            chapter_index = 0

            for chapter_id, mods_list in sorted(chapter_mods.items()):
                if not mods_list or self._cancelled:
                    if self._cancelled:
                        self._restore_all(chapter_mods)
                        return False
                    continue

                chapter_index += 1
                display_name = self._get_chapter_display_name(chapter_id)
                chapter_start = min(
                    int((chapter_index - 1) / max(total_chapters, 1) * 90) + 5, 95
                )
                chapter_end = min(
                    int(chapter_index / max(total_chapters, 1) * 90) + 5, 95
                )
                self._emit_chapter_progress(
                    chapter_start,
                    chapter_end,
                    0.0,
                    tr("status.preparing_chapter", display=display_name),
                )

                success = self._patch_chapter(
                    chapter_id,
                    mods_list,
                    is_modpack,
                    modpack_dir,
                    chapter_start,
                    chapter_end,
                    display_name,
                    chapter_index,
                    total_chapters,
                )
                if not success:
                    if not is_modpack:
                        self._restore_all(chapter_mods)
                    return False

                if not is_modpack:
                    self._write_session_manifest()

            self._emit_progress(
                96 if is_modpack else 100, tr("status.patching_completed")
            )
            return True
        except Exception as e:
            self.patching_logger.error(f"Patching failed: {e}", exc_info=True)
            self.status_update.emit(tr("errors.patching_failed", error=str(e)), "error")
            if not is_modpack:
                self._restore_all(chapter_mods)
            return False
        finally:
            if self._temp_dir and os.path.exists(self._temp_dir):
                safe_rmtree(self._temp_dir)
                self._temp_dir = None

    def _get_chapter_display_name(self, chapter_id: str) -> str:
        """Human-readable name like 'DELTARUNE Chapter 1' or 'Pizza Tower'."""
        from models.game_modes import get_game

        game_def = (
            get_game(self.app_state.game_mode.game_id)
            if self.app_state and self.app_state.game_mode
            else None
        )
        if game_def:
            return game_def.get_tab_display_name(chapter_id)
        return chapter_id

    def _patch_chapter(
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
    ) -> bool:
        self._emit_chapter_progress(
            chapter_start,
            chapter_end,
            0.03,
            tr(
                "status.processing_chapter",
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
                tr("errors.target_directory_not_found", chapter=chapter_id), "error"
            )
            return False
        self._emit_chapter_progress(
            chapter_start,
            chapter_end,
            0.08,
            tr("status.preparing_chapter", display=display_name),
        )

        if not ensure_writable(target_dir):
            self.status_update.emit(
                tr("errors.no_write_permission_for", path=target_dir), "error"
            )
            return False

        game_mode = self.app_state.game_mode
        data_win_path = mod_content.find_data_win(
            target_dir, game_id=game_mode.game_id if game_mode else None
        )
        if not data_win_path:
            if not self._request_warning(
                tr(
                    "dialogs.patching_warning.data_win_not_found",
                    search_path=target_dir,
                )
            ):
                return False
            self._emit_chapter_progress(
                chapter_start,
                chapter_end,
                0.12,
                tr("status.preparing_chapter", display=display_name),
            )
            success = self._apply_file_overrides_only(
                mods_list,
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
                    tr("status.chapter_patched", chapter=display_name),
                )
            return success

        mod_infos = self._collect_mod_infos(mods_list, chapter_id)
        data_mod_infos = [
            (pf, mt, sd) for pf, mt, sd in mod_infos if mt != MOD_TYPE_OVERRIDES_ONLY
        ]

        if not data_mod_infos:
            self.patching_logger.info(
                f"No data-modifying patches for chapter {chapter_id}, applying file overrides only"
            )
            success = self._apply_file_overrides_only(
                mods_list,
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
                    tr("status.chapter_patched", chapter=display_name),
                )
            return success

        if (
            not is_modpack
            and self.backup_service
            and not self.backup_service.backup_file(chapter_id, data_win_path)
        ):
            self.patching_logger.error(
                f"CRITICAL: Failed to backup {data_win_path} - aborting to protect game files"
            )
            self.status_update.emit(
                tr("errors.backup_failed", path=data_win_path), "error"
            )
            return False

        for patch_file, mod_type, _mod_source_dir in data_mod_infos:
            if mod_type == MOD_TYPE_G3MPATCH and not self._check_g3mpatch_validate_warning(
                patch_file or "", data_win_path
            ):
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

        logs_dir = os.path.join(get_user_data_root(), "logs")
        os.makedirs(logs_dir, exist_ok=True)
        log_path = os.path.join(logs_dir, "g3mtool.log")

        temp_output = os.path.join(
            self._temp_dir, f"output_{chapter_id}_{os.path.basename(data_win_path)}"
        )

        success = False
        if not is_modpack:
            self._emit_chapter_progress(
                chapter_start,
                chapter_end,
                0.18,
                tr("status.patching_chapter", chapter=display_name, current=1, total=1),
            )
        if len(data_mod_infos) == 1:
            success = self._apply_single_mod(
                data_win_path,
                data_mod_infos[0],
                temp_output,
                log_path,
                chapter_start,
                chapter_end,
                display_name,
            )
        else:
            success = self._apply_multi_mod(
                data_win_path,
                data_mod_infos,
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
            tr("status.finalizing_chapter", display=display_name),
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
            for mod_data in mods_list
        ]
        override_mods = [(mod_data, path) for mod_data, path in override_mods if path]
        total_override_mods = len(override_mods)
        for idx, (mod_data, mod_source_dir) in enumerate(override_mods, start=1):
            mod_start = 0.78 + ((idx - 1) / max(total_override_mods, 1) * 0.20)
            mod_end = 0.78 + (idx / max(total_override_mods, 1) * 0.20)
            mod_name = (
                getattr(mod_data, "name", None)
                or getattr(mod_data, "mod_name", None)
                or os.path.basename(mod_source_dir)
            )
            if not self._apply_file_overrides(
                mod_source_dir,
                override_target,
                chapter_id,
                is_modpack,
                chapter_start,
                chapter_end,
                mod_start,
                mod_end,
                mod_name,
                mod_data,
            ):
                return False

        self._emit_chapter_progress(
            chapter_start,
            chapter_end,
            1.0,
            tr("status.chapter_patched", chapter=display_name),
        )

        return True

    def _apply_single_mod(
        self,
        data_win_path: str,
        mod_info: tuple,
        output_path: str,
        log_path: str,
        chapter_start: int,
        chapter_end: int,
        display_name: str,
    ) -> bool:
        patch_file, mod_type, _mod_source_dir = mod_info

        if mod_type == MOD_TYPE_CSX:
            self.patching_logger.info(f"Executing csx script: {patch_file}")
            self._emit_chapter_progress(
                chapter_start,
                chapter_end,
                0.35,
                tr("status.patching_chapter", chapter=display_name, current=1, total=1),
            )
            returncode, _stdout, stderr = self.g3mtool.execute(
                patch_file,
                data_file=data_win_path,
                output_path=output_path,
            )
            if returncode != 0:
                error_text = stderr[:200] or "Unknown error"
                return self._continue_without_data_patch(
                    tr(
                        "dialogs.patching_warning.data_patch_failed",
                        patch_name=os.path.basename(patch_file),
                        patch_path=patch_file,
                        data_win_path=data_win_path,
                        error=error_text,
                    ),
                    data_win_path,
                    output_path,
                    f"csx execute failed: {stderr[:500]}",
                )
            if not os.path.exists(output_path):
                error_text = self._missing_output_error(output_path)
                return self._continue_without_data_patch(
                    tr(
                        "dialogs.patching_warning.data_patch_failed",
                        patch_name=os.path.basename(patch_file),
                        patch_path=patch_file,
                        data_win_path=data_win_path,
                        error=error_text,
                    ),
                    data_win_path,
                    output_path,
                    error_text,
                )
            self._emit_chapter_progress(
                chapter_start,
                chapter_end,
                0.70,
                tr("status.finalizing_chapter", display=display_name),
            )
            return True

        if mod_type == MOD_TYPE_XDELTA:
            self.patching_logger.info(f"Applying xdelta patch: {patch_file}")
            self._emit_chapter_progress(
                chapter_start,
                chapter_end,
                0.30,
                tr(
                    "status.applying_xdelta",
                    mod=os.path.basename(patch_file),
                    current=1,
                    total=1,
                ),
            )
            returncode, _stdout, stderr = self.g3mtool.xpatch_apply(
                data_win_path,
                patch_file,
                output_path,
                progress_callback=lambda progress, _label: self._emit_chapter_progress(
                    chapter_start,
                    chapter_end,
                    0.30 + (progress / 100 * 0.40),
                    tr(
                        "status.applying_xdelta",
                        mod=os.path.basename(patch_file),
                        current=1,
                        total=1,
                    ),
                ),
            )
            if returncode != 0:
                error_text = stderr[:200] or "Unknown error"
                return self._continue_without_data_patch(
                    tr(
                        "dialogs.patching_warning.xdelta_patch_failed",
                        patch_name=os.path.basename(patch_file),
                        patch_path=patch_file,
                        data_win_path=data_win_path,
                        error=error_text,
                    ),
                    data_win_path,
                    output_path,
                    f"xpatch apply failed: {stderr[:500]}",
                )
            if not os.path.exists(output_path):
                error_text = self._missing_output_error(output_path)
                return self._continue_without_data_patch(
                    tr(
                        "dialogs.patching_warning.xdelta_patch_failed",
                        patch_name=os.path.basename(patch_file),
                        patch_path=patch_file,
                        data_win_path=data_win_path,
                        error=error_text,
                    ),
                    data_win_path,
                    output_path,
                    error_text,
                )
            self._emit_chapter_progress(
                chapter_start,
                chapter_end,
                0.70,
                tr("status.finalizing_chapter", display=display_name),
            )
            return True

        if mod_type == MOD_TYPE_DATAFILE:
            self.patching_logger.info(f"Copying replacement data.win: {patch_file}")
            self._emit_chapter_progress(
                chapter_start,
                chapter_end,
                0.35,
                tr("status.patching_chapter", chapter=display_name, current=1, total=1),
            )
            try:
                shutil.copy2(patch_file, output_path)
                self._emit_chapter_progress(
                    chapter_start,
                    chapter_end,
                    0.70,
                    tr("status.finalizing_chapter", display=display_name),
                )
                return True
            except Exception as e:
                self.patching_logger.error(
                    f"Failed to copy data.win: {e}", exc_info=True
                )
                return False

        if mod_type == MOD_TYPE_G3MPATCH:
            self.patching_logger.info(f"Applying g3mpatch: {patch_file}")
            self._emit_chapter_progress(
                chapter_start,
                chapter_end,
                0.30,
                tr("status.applying_g3mpatch", display=display_name),
            )
            returncode, _stdout, stderr = self.g3mtool.apply_patch(
                data_win_path,
                patch_file,
                output_path,
                log_path=log_path,
                progress_callback=lambda progress, _label: self._emit_chapter_progress(
                    chapter_start,
                    chapter_end,
                    0.30 + (progress / 100 * 0.40),
                    tr("status.applying_g3mpatch", display=display_name),
                ),
            )
            if returncode != 0:
                error_text = stderr[:200] or "Unknown error"
                return self._continue_without_data_patch(
                    tr(
                        "dialogs.patching_warning.data_patch_failed",
                        patch_name=os.path.basename(patch_file),
                        patch_path=patch_file,
                        data_win_path=data_win_path,
                        error=error_text,
                    ),
                    data_win_path,
                    output_path,
                    f"patch apply failed: {stderr[:500]}",
                )
            if not os.path.exists(output_path):
                error_text = self._missing_output_error(output_path)
                return self._continue_without_data_patch(
                    tr(
                        "dialogs.patching_warning.data_patch_failed",
                        patch_name=os.path.basename(patch_file),
                        patch_path=patch_file,
                        data_win_path=data_win_path,
                        error=error_text,
                    ),
                    data_win_path,
                    output_path,
                    error_text,
                )
            self._emit_chapter_progress(
                chapter_start,
                chapter_end,
                0.70,
                tr("status.finalizing_chapter", display=display_name),
            )
            return True

        self.patching_logger.error(f"Unknown mod_type: {mod_type}")
        return False

    def _apply_multi_mod(
        self,
        data_win_path: str,
        mod_infos: list[tuple],
        output_path: str,
        log_path: str,
        chapter_id: str,
        chapter_start: int,
        chapter_end: int,
        display_name: str,
    ) -> bool:
        if any(mod_type == MOD_TYPE_CSX for _patch_file, mod_type, _source_dir in mod_infos):
            current_input = data_win_path
            temp_inputs_to_cleanup: list[str] = []
            total_mods = len(mod_infos)
            for index, mod_info in enumerate(mod_infos, start=1):
                temp_output = (
                    output_path
                    if index == total_mods
                    else os.path.join(
                        self._temp_dir or tempfile.gettempdir(),
                        f"seq_{chapter_id}_{index}_{os.path.basename(data_win_path)}",
                    )
                )
                if not self._apply_single_mod(
                    current_input,
                    mod_info,
                    temp_output,
                    log_path,
                    chapter_start,
                    chapter_end,
                    display_name,
                ):
                    return False
                if current_input != data_win_path:
                    temp_inputs_to_cleanup.append(current_input)
                current_input = temp_output
            for temp_input in temp_inputs_to_cleanup:
                if os.path.exists(temp_input):
                    with contextlib.suppress(Exception):
                        os.remove(temp_input)
            return True

        patch_files: list[str] = []
        for patch_file, _mod_type, _source_dir in mod_infos:
            if patch_file:
                patch_files.append(patch_file)
        if not patch_files:
            return True
        report_path = (
            os.path.join(self._temp_dir, f"merge_report_{chapter_id}.md")
            if self._temp_dir
            else None
        )

        self.patching_logger.info(
            "Merging %s mods for chapter %s using direct inputs: %s",
            len(patch_files),
            chapter_id,
            ", ".join(os.path.basename(path) for path in patch_files),
        )

        merge_code = self.app_state.local_config.get("merge_code", False)
        merge_properties = self.app_state.local_config.get("merge_properties", False)

        returncode, _stdout, stderr = self.g3mtool.merge_patches(
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
                0.20 + (progress / 100 * 0.52),
                tr(
                    "status.patching_chapter",
                    chapter=display_name,
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
            error_text = stderr[:200] or "Unknown error"
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
                f"G3MTool merge failed for chapter {chapter_id}: {stderr[:500]}",
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
            )

        if report_path and os.path.exists(report_path):
            self._last_report_path = report_path

            self._saved_report_path = self._save_report_to_archive(
                report_path, chapter_id
            )
            if self.report_has_conflicts():
                total_conflicts, _auto_resolved = self.get_report_stats()
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
                ):
                    return False

        return True

    def _materialize_merge_patch(
        self,
        data_win_path: str,
        mod_info: tuple,
        chapter_id: str,
        index: int,
        total_mods: int,
        chapter_start: int,
        chapter_end: int,
        display_name: str,
    ) -> str | None:
        patch_file, mod_type, _mod_source_dir = mod_info
        materialize_window_start = 0.20
        materialize_window_end = 0.44
        per_mod_span = (materialize_window_end - materialize_window_start) / max(
            total_mods, 1
        )
        mod_start = materialize_window_start + ((index - 1) * per_mod_span)
        mod_end = mod_start + per_mod_span
        create_start = mod_start + (per_mod_span * 0.25)

        def emit_materialize_progress(fraction: float) -> None:
            self._emit_chapter_progress(
                chapter_start,
                chapter_end,
                mod_start + ((mod_end - mod_start) * fraction),
                tr(
                    "status.patching_chapter",
                    chapter=display_name,
                    current=index,
                    total=total_mods,
                ),
            )

        if mod_type == MOD_TYPE_G3MPATCH:
            emit_materialize_progress(1.0)
            return patch_file

        temp_root = self._temp_dir or tempfile.gettempdir()
        modified_output = os.path.join(
            temp_root,
            f"merge_src_{chapter_id}_{index}.win",
        )
        generated_patch = os.path.join(
            temp_root,
            f"merge_src_{chapter_id}_{index}.g3mpatch",
        )

        if mod_type == MOD_TYPE_XDELTA:
            returncode, _stdout, stderr = self.g3mtool.xpatch_apply(
                data_win_path,
                patch_file,
                modified_output,
                progress_callback=lambda progress, _label: emit_materialize_progress(
                    (progress / 100) * 0.25
                ),
            )
            if returncode != 0 or not os.path.exists(modified_output):
                error_text = stderr[:200] or "Unknown error"
                self.patching_logger.error(
                    "Failed to materialize xdelta merge patch %s: %s",
                    patch_file,
                    stderr[:500],
                )
                self.status_update.emit(
                    tr("errors.patching_failed", error=error_text), "error"
                )
                return None
        elif mod_type == MOD_TYPE_DATAFILE:
            emit_materialize_progress(0.25)
            try:
                shutil.copy2(patch_file, modified_output)
            except Exception as e:
                self.patching_logger.error(
                    "Failed to materialize data replacement merge patch %s: %s",
                    patch_file,
                    e,
                    exc_info=True,
                )
                self.status_update.emit(
                    tr("errors.patching_failed", error=str(e)), "error"
                )
                return None
        else:
            return patch_file

        returncode, _stdout, stderr = self.g3mtool.patch_create(
            data_win_path,
            modified_output,
            generated_patch,
            progress_callback=lambda progress, _label: self._emit_chapter_progress(
                chapter_start,
                chapter_end,
                create_start + ((mod_end - create_start) * (progress / 100)),
                tr(
                    "status.patching_chapter",
                    chapter=display_name,
                    current=index,
                    total=total_mods,
                ),
            ),
        )
        if returncode != 0 or not os.path.exists(generated_patch):
            error_text = stderr[:200] or "Unknown error"
            self.patching_logger.error(
                "Failed to create mergeable g3mpatch from %s: %s",
                patch_file,
                stderr[:500],
            )
            self.status_update.emit(
                tr("errors.patching_failed", error=error_text), "error"
            )
            return None
        emit_materialize_progress(1.0)
        return generated_patch

    def _save_report_to_archive(self, report_path: str, chapter_id: str) -> str | None:
        """Copy the merge report into logs/patching/ with a timestamp."""
        try:
            archive_dir = _get_patching_logs_dir()
            ts = time.strftime("%Y%m%d_%H%M%S")
            dest = os.path.join(archive_dir, f"merge_report_{chapter_id}_{ts}.md")
            shutil.copy2(report_path, dest)
            _enforce_archive_limit(archive_dir)
            self.patching_logger.info(f"Merge report saved to {dest}")
            return dest
        except Exception as e:
            self.patching_logger.warning(f"Failed to save merge report to archive: {e}")
            return report_path

    def _collect_mod_infos(
        self, mods_list: list[Any], chapter_id: str
    ) -> list[tuple[str | None, str, str | None]]:
        """Returns list of (patch_file, mod_type, mod_source_dir) for each mod."""
        result = []
        for mod_data in mods_list:
            mod_source_dir = self._get_mod_source_dir(mod_data, chapter_id)
            patch_file = get_mod_configured_data_file(
                mod_data,
                chapter_id,
                self.mod_service,
                self.app_state,
                self.patching_logger,
            )
            if patch_file and os.path.exists(patch_file):
                patch_file, mod_type = mod_content.classify_patch_file(patch_file)
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
        if not os.path.isdir(mod_source_dir):
            return (None, MOD_TYPE_OVERRIDES_ONLY)

        g3m_patches = mod_content.find_g3m_patches(mod_source_dir)
        if g3m_patches:
            return (g3m_patches[0], MOD_TYPE_G3MPATCH)

        for f in os.listdir(mod_source_dir):
            fl = f.lower()
            if fl.endswith((".xdelta", ".vcdiff")):
                return (os.path.join(mod_source_dir, f), MOD_TYPE_XDELTA)

        csx_scripts = mod_content.find_csx_scripts(mod_source_dir)
        if csx_scripts:
            return (csx_scripts[0], MOD_TYPE_CSX)

        ready_files = mod_content.find_ready_data_win_files(mod_source_dir)
        if ready_files:
            return (ready_files[0], MOD_TYPE_DATAFILE)

        return (None, MOD_TYPE_OVERRIDES_ONLY)

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
        from utils.mod_utils import get_mod_id
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

    def _backup_or_mark_file(self, chapter_id, target_file: str) -> None:
        if chapter_id is None or not self.backup_service:
            return
        if os.path.exists(target_file):
            self.backup_service.backup_file(chapter_id, target_file)
        else:
            self.backup_service.mark_file_added(chapter_id, target_file)

    def _apply_xdelta_to_file(self, target_file: str, patch_path: str) -> bool:
        """Apply xdelta patch to a non-data.win file (used by file_override_utils)."""
        if not self.g3mtool.is_available():
            return False
        temp_output = target_file + ".tmp"
        returncode, _, _ = self.g3mtool.xpatch_apply(
            target_file, patch_path, temp_output
        )
        if returncode == 0 and os.path.exists(temp_output):
            try:
                shutil.move(temp_output, target_file)
                return True
            except Exception as e:
                self.patching_logger.debug(
                    f"_apply_xdelta_to_file: failed to move patched output into place: {e}",
                    exc_info=True,
                )
        if os.path.exists(temp_output):
            os.remove(temp_output)
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
        total, _ = self._parse_conflict_counts(content)
        return total > 0

    def get_report_stats(self) -> tuple[int, int]:
        content = self._read_report_content()
        if not content:
            return (0, 0)
        return self._parse_conflict_counts(content)

    @staticmethod
    def _parse_conflict_counts(content: str) -> tuple[int, int]:
        """Extract actual conflict/auto-resolved counts from the report markdown."""
        total = 0
        auto_resolved = 0

        for m in re.finditer(r"(?i)(?:total\s+)?conflicts?\s*[:=]\s*(\d+)", content):
            total = max(total, int(m.group(1)))
        for m in re.finditer(r"(?i)auto[- ]?resolved?\s*[:=]\s*(\d+)", content):
            auto_resolved = max(auto_resolved, int(m.group(1)))

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

    def _write_session_manifest(self) -> None:
        """Write session manifest so backups can be recovered after a crash."""
        manifest_path = self._session_manifest_path
        if manifest_path and self.backup_service:
            self.backup_service.save_backups_to_manifest(manifest_path)

    def _restore_all(self, chapter_mods: dict) -> None:
        if self.backup_service:
            for chapter_id in chapter_mods:
                self.backup_service.restore_backups(chapter_id)
            self.backup_service.clear_backup_dir()

    def restore_all_backups(self) -> bool:
        if self.backup_service:
            result = self.backup_service.restore_all_backups()
            self.backup_service.clear_backup_dir()
            return result
        return False

    def clear_session(self) -> None:
        """Remove persistent backups and session manifest (call after successful game close)."""
        if self.backup_service:
            self.backup_service.clear_backup_dir()
            self.patching_logger.info("Session cleared: backups and manifest removed")

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
