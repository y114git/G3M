"""Patching service using G3MTool CLI."""
import os
import glob
import logging
import re
import shutil
import tempfile
import time
from typing import Dict, List, Any, Optional, Tuple

from PyQt6.QtCore import QObject, pyqtSignal

from adapters.g3mtool_adapter import G3MToolManager
from config.constants import MAX_PATCHING_ARCHIVES, MOD_TYPE_G3MPATCH, MOD_TYPE_XDELTA, MOD_TYPE_DATAFILE, MOD_TYPE_OVERRIDES_ONLY
from services.backup_service import BackupManager
from services.localization_service import tr
from utils.file_utils import ensure_writable, safe_rmtree, get_chapter_folder_name
from utils.path_utils import get_user_data_root
from utils.patching import mod_content_utils as mod_content
from utils.patching.mod_resolve_utils import get_mod_source_dir, get_target_dir


def _get_patching_logs_dir() -> str:
    """Return logs/patching/ directory, creating it if needed."""
    d = os.path.join(get_user_data_root(), 'logs', 'patching')
    os.makedirs(d, exist_ok=True)
    return d


def _rotate_patching_files():
    """Rotate old patching.log and g3mtool.log into logs/patching/ with a timestamp."""
    logs_dir = os.path.join(get_user_data_root(), 'logs')
    archive_dir = _get_patching_logs_dir()
    ts = time.strftime('%Y%m%d_%H%M%S')
    for name in ('patching.log', 'g3mtool.log'):
        src = os.path.join(logs_dir, name)
        if os.path.isfile(src) and os.path.getsize(src) > 0:
            base, ext = os.path.splitext(name)
            dst = os.path.join(archive_dir, f'{base}_{ts}{ext}')
            try:
                shutil.move(src, dst)
            except Exception:
                pass
    _enforce_archive_limit(archive_dir)


def _enforce_archive_limit(archive_dir: str):
    """Keep at most MAX_PATCHING_ARCHIVES of each file type."""
    for pattern in ('patching_*.log', 'g3mtool_*.log', 'merge_report_*.md'):
        files = sorted(glob.glob(os.path.join(archive_dir, pattern)))
        while len(files) > MAX_PATCHING_ARCHIVES:
            try:
                os.remove(files.pop(0))
            except Exception:
                continue


def _get_patching_logger() -> logging.Logger:
    """Get or create a dedicated patching logger that writes to patching.log."""
    logger = logging.getLogger('patching')

    for h in list(logger.handlers):
        logger.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass
    logs_dir = os.path.join(get_user_data_root(), 'logs')
    os.makedirs(logs_dir, exist_ok=True)
    log_path = os.path.join(logs_dir, 'patching.log')
    handler = logging.FileHandler(log_path, mode='w', encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    return logger


class G3MToolPatchingService(QObject):
    status_update = pyqtSignal(str, str)
    progress_update = pyqtSignal(int, str)

    def __init__(self, app_state, mod_service, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.mod_service = mod_service
        self.g3mtool = G3MToolManager()
        self.backup_service: Optional[BackupManager] = None
        self._cancelled = False
        self._temp_dir: Optional[str] = None
        self._last_report_path: Optional[str] = None
        self._saved_report_path: Optional[str] = None
        self._xdelta_modpack: bool = False
        self._session_manifest_path: Optional[str] = None

        _rotate_patching_files()
        self.patching_logger = _get_patching_logger()

    def process_mod_patch(
        self,
        chapter_mods: Dict[str, List[Any]],
        is_modpack: bool = False,
        modpack_dir: Optional[str] = None,
    ) -> bool:
        self._cancelled = False
        self._last_report_path = None

        if not self.g3mtool.is_available():
            self.status_update.emit(tr('errors.g3mtool_not_available'), 'error')
            self.patching_logger.error('G3MTool not available')
            return False

        try:
            self._temp_dir = tempfile.mkdtemp(prefix='deltahub_patch_')

            if is_modpack:
                backup_dir = os.path.join(self._temp_dir, 'backups')
            else:
                backup_dir = os.path.join(get_user_data_root(), 'patching_backups')
            self.backup_service = BackupManager(backup_dir, patching_logger=self.patching_logger)

            total_chapters = len([c for c in chapter_mods.values() if c])
            chapter_index = 0

            for chapter_id, mods_list in sorted(chapter_mods.items()):
                if not mods_list or self._cancelled:
                    if self._cancelled:
                        self._restore_all(chapter_mods)
                        return False
                    continue

                chapter_index += 1
                progress_pct = min(int((chapter_index - 1) / max(total_chapters, 1) * 90) + 5, 95)
                self.progress_update.emit(progress_pct, f'Processing chapter {chapter_id} ({chapter_index}/{total_chapters})...')

                success = self._patch_chapter(chapter_id, mods_list, is_modpack, modpack_dir)
                if not success:
                    if not is_modpack:
                        self._restore_all(chapter_mods)
                    return False

                if not is_modpack:
                    self._write_session_manifest()

            self.progress_update.emit(100, tr('status.patching_completed') if not is_modpack else 'Modpack created')
            return True
        except Exception as e:
            self.patching_logger.error(f'Patching failed: {e}', exc_info=True)
            self.status_update.emit(tr('errors.patching_failed', error=str(e)), 'error')
            if not is_modpack:
                self._restore_all(chapter_mods)
            return False
        finally:
            if self._temp_dir and os.path.exists(self._temp_dir):
                if is_modpack:
                    safe_rmtree(self._temp_dir)
                    self._temp_dir = None

    def _patch_chapter(self, chapter_id: str, mods_list: List[Any], is_modpack: bool, modpack_dir: Optional[str]) -> bool:
        target_dir = get_target_dir(chapter_id, self.app_state, self.patching_logger)
        if not target_dir:
            self.status_update.emit(tr('errors.target_directory_not_found', chapter=chapter_id), 'error')
            return False

        if not ensure_writable(target_dir):
            self.status_update.emit(tr('errors.no_write_permission_for', path=target_dir), 'error')
            return False

        data_win_path = mod_content.find_data_win(target_dir)
        if not data_win_path:
            self.patching_logger.warning(f'data.win not found for chapter {chapter_id}, applying file overrides only')
            return self._apply_file_overrides_only(mods_list, target_dir, chapter_id)

        mod_infos = self._collect_mod_infos(mods_list, chapter_id)
        data_mod_infos = [(pf, mt, sd) for pf, mt, sd in mod_infos if mt != MOD_TYPE_OVERRIDES_ONLY]

        if not data_mod_infos:
            self.patching_logger.info(f'No data-modifying patches for chapter {chapter_id}, applying file overrides only')
            return self._apply_file_overrides_only(mods_list, target_dir, chapter_id)

        if not is_modpack and self.backup_service:
            if not self.backup_service.backup_file(chapter_id, data_win_path):
                self.patching_logger.error(f'CRITICAL: Failed to backup {data_win_path} — aborting to protect game files')
                self.status_update.emit(tr('errors.backup_failed', path=data_win_path), 'error')
                return False

        final_output_path = data_win_path
        if is_modpack and modpack_dir:
            game = self._resolve_mod_game(mods_list[0]) if mods_list else None
            chapter_folder_name = get_chapter_folder_name(chapter_id, game=game)
            chapter_modpack_dir = os.path.join(modpack_dir, chapter_folder_name)
            os.makedirs(chapter_modpack_dir, exist_ok=True)
            final_output_path = os.path.join(chapter_modpack_dir, os.path.basename(data_win_path))

        logs_dir = os.path.join(get_user_data_root(), 'logs')
        os.makedirs(logs_dir, exist_ok=True)
        log_path = os.path.join(logs_dir, 'g3mtool.log')

        temp_output = os.path.join(self._temp_dir, f'output_{chapter_id}_{os.path.basename(data_win_path)}')

        success = False
        if len(data_mod_infos) == 1:
            success = self._apply_single_mod(data_win_path, data_mod_infos[0], temp_output, log_path)
        else:
            success = self._apply_multi_mod(data_win_path, data_mod_infos, temp_output, log_path, chapter_id)

        if not success:
            return False

        try:
            shutil.move(temp_output, final_output_path)
            self.patching_logger.info(f'Patched data.win placed at {final_output_path}')
        except Exception as e:
            self.patching_logger.error(f'Failed to move patched file to {final_output_path}: {e}', exc_info=True)
            return False

        override_target = target_dir if not is_modpack else os.path.dirname(final_output_path)
        for mod_data in mods_list:
            mod_source_dir = self._get_mod_source_dir(mod_data, chapter_id)
            if mod_source_dir:
                self._apply_file_overrides(mod_source_dir, override_target, chapter_id, is_modpack)

        return True

    def _apply_single_mod(self, data_win_path: str, mod_info: tuple, output_path: str, log_path: str) -> bool:
        patch_file, mod_type, mod_source_dir = mod_info

        if mod_type == MOD_TYPE_XDELTA:

            self.patching_logger.info(f'Applying xdelta patch: {patch_file}')
            returncode, stdout, stderr = self.g3mtool.xpatch_apply(data_win_path, patch_file, output_path)
            if returncode != 0:
                self.patching_logger.error(f'xpatch apply failed: {stderr[:500]}')
                self.status_update.emit(f'xdelta patch failed: {stderr[:200]}', 'error')
                return False
            return True

        if mod_type == MOD_TYPE_DATAFILE:

            self.patching_logger.info(f'Copying replacement data.win: {patch_file}')
            try:
                shutil.copy2(patch_file, output_path)
                return True
            except Exception as e:
                self.patching_logger.error(f'Failed to copy data.win: {e}', exc_info=True)
                return False

        if mod_type == MOD_TYPE_G3MPATCH:

            self.patching_logger.info(f'Applying g3mpatch: {patch_file}')
            returncode, stdout, stderr = self.g3mtool.apply_patch(
                data_win_path, patch_file, output_path, log_path=log_path,
            )
            if returncode != 0:
                self.patching_logger.error(f'patch apply failed: {stderr[:500]}')
                self.status_update.emit(f'G3MTool patch apply failed: {stderr[:200]}', 'error')
                return False
            return True

        self.patching_logger.error(f'Unknown mod_type: {mod_type}')
        return False

    def _apply_multi_mod(self, data_win_path: str, mod_infos: List[tuple], output_path: str, log_path: str, chapter_id: str) -> bool:

        patch_files = [pf for pf, mt, sd in mod_infos]
        report_path = os.path.join(self._temp_dir, f'merge_report_{chapter_id}.md') if self._temp_dir else None

        self.patching_logger.info(f'Merging {len(patch_files)} mods for chapter {chapter_id}')
        returncode, stdout, stderr = self.g3mtool.merge_patches(
            data_win_path, patch_files, output_path,
            report_path=report_path, log_path=log_path,
        )

        if returncode != 0:
            error_msg = stderr[:200] if stderr else 'Unknown error'
            self.status_update.emit(f'G3MTool merge failed: {error_msg}', 'error')
            self.patching_logger.error(f'G3MTool merge failed for chapter {chapter_id}: {stderr[:500]}')
            return False

        if report_path and os.path.exists(report_path):
            self._last_report_path = report_path

            self._saved_report_path = self._save_report_to_archive(report_path, chapter_id)

        return True

    def _save_report_to_archive(self, report_path: str, chapter_id: str) -> Optional[str]:
        """Copy the merge report into logs/patching/ with a timestamp."""
        try:
            archive_dir = _get_patching_logs_dir()
            ts = time.strftime('%Y%m%d_%H%M%S')
            dest = os.path.join(archive_dir, f'merge_report_{chapter_id}_{ts}.md')
            shutil.copy2(report_path, dest)
            _enforce_archive_limit(archive_dir)
            self.patching_logger.info(f'Merge report saved to {dest}')
            return dest
        except Exception as e:
            self.patching_logger.warning(f'Failed to save merge report to archive: {e}')
            return report_path

    def _collect_mod_infos(self, mods_list: List[Any], chapter_id: str) -> List[Tuple[Optional[str], str, Optional[str]]]:
        """Returns list of (patch_file, mod_type, mod_source_dir) for each mod."""
        result = []
        for mod_data in mods_list:
            mod_source_dir = self._get_mod_source_dir(mod_data, chapter_id)
            if not mod_source_dir:
                continue
            patch_file, mod_type = self._classify_mod(mod_source_dir)
            result.append((patch_file, mod_type, mod_source_dir))
        return result

    def _classify_mod(self, mod_source_dir: str) -> Tuple[Optional[str], str]:
        """Classify a mod and return (patch_file, mod_type)."""
        if not os.path.isdir(mod_source_dir):
            return (None, MOD_TYPE_OVERRIDES_ONLY)

        g3m_patches = mod_content.find_g3m_patches(mod_source_dir)
        if g3m_patches:
            return (g3m_patches[0], MOD_TYPE_G3MPATCH)

        for f in os.listdir(mod_source_dir):
            fl = f.lower()
            if fl.endswith(('.xdelta', '.vcdiff')):
                return (os.path.join(mod_source_dir, f), MOD_TYPE_XDELTA)

        ready_files = mod_content.find_ready_data_win_files(mod_source_dir)
        if ready_files:
            return (ready_files[0], MOD_TYPE_DATAFILE)

        return (None, MOD_TYPE_OVERRIDES_ONLY)

    def _apply_file_overrides_only(self, mods_list: List[Any], target_dir: str, chapter_id: str) -> bool:
        for mod_data in mods_list:
            mod_source_dir = self._get_mod_source_dir(mod_data, chapter_id)
            if mod_source_dir:
                self._apply_file_overrides(mod_source_dir, target_dir, chapter_id, False)
        return True

    def _apply_file_overrides(self, mod_source_dir: str, target_dir: str, chapter_id: str, is_modpack: bool) -> bool:
        from utils.patching.file_override_utils import apply_file_overrides
        return apply_file_overrides(self, mod_source_dir, target_dir, set(), is_modpack, chapter_id)

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
        temp_output = target_file + '.tmp'
        returncode, _, _ = self.g3mtool.xpatch_apply(target_file, patch_path, temp_output)
        if returncode == 0 and os.path.exists(temp_output):
            try:
                shutil.move(temp_output, target_file)
                return True
            except Exception:
                pass
        if os.path.exists(temp_output):
            os.remove(temp_output)
        return False

    def _get_mod_source_dir(self, mod_data: Any, chapter_id: str) -> Optional[str]:
        return get_mod_source_dir(mod_data, chapter_id, self.mod_service, self.app_state, self.patching_logger)

    @staticmethod
    def _resolve_mod_game(mod_data):
        from utils.patching.mod_resolve_utils import resolve_mod_game
        return resolve_mod_game(mod_data)

    def get_report_path(self) -> Optional[str]:
        """Return the saved (permanent) report path if available, else the temp one."""
        return self._saved_report_path or self._last_report_path

    def _read_report_content(self) -> Optional[str]:
        """Read the report content, preferring the saved permanent path."""
        path = self._saved_report_path or self._last_report_path
        if not path or not os.path.exists(path):
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception:
            return None

    def report_has_conflicts(self) -> bool:
        content = self._read_report_content()
        if not content:
            return False
        total, _ = self._parse_conflict_counts(content)
        return total > 0

    def get_report_stats(self) -> Tuple[int, int]:
        content = self._read_report_content()
        if not content:
            return (0, 0)
        return self._parse_conflict_counts(content)

    @staticmethod
    def _parse_conflict_counts(content: str) -> Tuple[int, int]:
        """Extract actual conflict/auto-resolved counts from the report markdown."""
        total = 0
        auto_resolved = 0

        for m in re.finditer(r'(?i)(?:total\s+)?conflicts?\s*[:=]\s*(\d+)', content):
            total = max(total, int(m.group(1)))
        for m in re.finditer(r'(?i)auto[- ]?resolved?\s*[:=]\s*(\d+)', content):
            auto_resolved = max(auto_resolved, int(m.group(1)))

        if total == 0:
            conflict_sections = re.findall(r'^#{1,4}\s+.*conflict.*$', content, re.MULTILINE | re.IGNORECASE)

            total = len([s for s in conflict_sections if not re.search(r'(?i)summary|total|report|detected', s)])
        return (total, auto_resolved)

    def _write_session_manifest(self) -> None:
        """Write session manifest so backups can be recovered after a crash."""
        manifest_path = self._session_manifest_path
        if manifest_path and self.backup_service:
            self.backup_service.save_backups_to_manifest(manifest_path)

    def _restore_all(self, chapter_mods: Dict) -> None:
        if self.backup_service:
            for chapter_id in chapter_mods.keys():
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
            self.patching_logger.info('Session cleared: backups and manifest removed')

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
