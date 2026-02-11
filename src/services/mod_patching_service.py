"""Multi-mod patching and application system."""
import os
import platform
import shutil
import tempfile
import subprocess
from typing import Dict, List, Optional, Any
from PyQt6.QtCore import QObject, pyqtSignal
from services.backup_service import BackupManager
from adapters.utmtcli_adapter import UtmtWrapper
from utils.path_utils import get_xdelta_path
from utils.file_utils import ensure_writable, safe_remove, safe_rmtree, safe_copy, get_chapter_folder_name
from services.localization_service import tr
from services.patching_log_service import get_patching_logger
from utils.patching import resource_filter_utils as resource_filter
from utils.patching import mod_content_utils as mod_content
from utils.patching.conflict_tracker_utils import PatchingConflictTracker
from utils.patching.mod_content_utils import (
    has_content as _has_content, get_dir_resources as _get_dir_resources,
    get_file_resources as _get_file_resources, get_font_resources as _get_font_resources,
    get_tileset_config_resource as _get_tileset_config_resource,
    get_gml_resources as _get_gml_resources, no_res as _no_res, json_res as _json_res,
)
from config.patching_config import (
    EXPORT_SCRIPT_CONFIGS, IMPORT_SCRIPT_CONFIGS, SCRIPT_TYPES,
    ASSET_TRACKING_CONFIGS, PATCH_SUBDIRS,
)


class ModPatcher(QObject):
    status_update = pyqtSignal(str, str)
    progress_update = pyqtSignal(int, str)
    warning_confirmation_needed = pyqtSignal(str, str, str)
    _session_manifest_path: Optional[str] = None

    def __init__(self, app_state, mod_service, parent=None):
        super().__init__(parent)
        self.patching_logger = get_patching_logger()
        self.conflict_tracker = PatchingConflictTracker(self.patching_logger)
        self._mod_exported_code_files: Dict[int, set] = {}
        self.app_state = app_state
        self.mod_service = mod_service
        self.utmt_wrapper = UtmtWrapper(patching_logger=self.patching_logger)
        self.xdelta_path = get_xdelta_path()
        self.patching_logger.info(f'[ModPatcher.__init__] xdelta_path initialized: {self.xdelta_path}')
        if self.xdelta_path:
            if platform.system() != 'Windows':
                import stat
                if os.path.exists(self.xdelta_path):
                    file_stat = os.stat(self.xdelta_path)
                    is_executable = bool(file_stat.st_mode & stat.S_IEXEC)
                    self.patching_logger.info(f'[ModPatcher.__init__] xdelta permissions: {oct(file_stat.st_mode)} (executable: {is_executable})')
        self.temp_patch_dir = None
        self.backup_service: Optional[BackupManager] = None
        self._cancelled = False
        self._active_processes: List[subprocess.Popen] = []
        self._temp_files_to_cleanup: List[str] = []
        self.xdelta_modpack = False
        self._warning_callback: Optional[callable] = None
        if hasattr(self.utmt_wrapper, 'set_active_processes_list'):
            self.utmt_wrapper.set_active_processes_list(self._active_processes)

    @staticmethod
    def _safe_tr(key: str, fallback: str, **kwargs) -> str:
        try:
            return tr(key, **kwargs)
        except BaseException:
            return fallback

    @staticmethod
    def _resolve_mod_game(mod_data, source_dir=None):
        from utils.patching.mod_resolve_utils import resolve_mod_game
        return resolve_mod_game(mod_data, source_dir)

    def _run_export_scripts(self, scripts: List[str], data_win: str, objects_dir: str, cwd: str, label: str = '') -> bool:
        all_ok = True
        for script_name, subdir in EXPORT_SCRIPT_CONFIGS:
            if self._cancelled:
                return False
            if script_name not in scripts:
                continue
            out_dir = os.path.join(objects_dir, subdir)
            os.makedirs(out_dir, exist_ok=True)
            returncode, stdout, stderr = self.utmt_wrapper.execute_script(data_win, script_name, output_path=data_win, cwd=cwd, env={'OUTPUT_DIR': out_dir})
            if returncode != 0:
                self.patching_logger.warning(f'[EXPORT] {label}{script_name} failed: {stderr[:300] if stderr else "no error output"}')
                all_ok = False
        return all_ok

    def _run_import_scripts_from_dir(self, scripts_filter: Optional[List[str]], base_file: str, objects_dir: str, cwd: str, label: str = '') -> bool:
        all_ok = True
        for script_name, subdir in IMPORT_SCRIPT_CONFIGS:
            if self._cancelled:
                return False
            if scripts_filter and script_name not in scripts_filter:
                continue
            script_path = self.utmt_wrapper.get_script_path(script_name)
            if not script_path:
                continue
            input_dir = os.path.join(objects_dir, subdir)
            if not os.path.exists(input_dir) or not os.listdir(input_dir):
                continue
            self.patching_logger.info(f'[IMPORT] {label}Running {script_name} with INPUT_DIR={input_dir}')
            returncode, stdout, stderr = self.utmt_wrapper.execute_script(base_file, script_name, output_path=base_file, cwd=cwd, env={'INPUT_DIR': input_dir})
            if returncode != 0:
                self.patching_logger.warning(f'[IMPORT] {label}{script_name} failed: {stderr[:300] if stderr else "no error output"}')
                all_ok = False
            else:
                self.patching_logger.info(f'[IMPORT] {label}{script_name} completed successfully')
        return all_ok

    def _cancelled_restore(self, is_modpack: bool, chapter_id: str) -> bool:
        """Return True (and restore backups) if cancelled, False otherwise."""
        if not self._cancelled:
            return False
        if not is_modpack and self.backup_service:
            self.backup_service.restore_backups(chapter_id)
        return True

    def _fail_restore(self, is_modpack: bool, chapter_id: str) -> None:
        """Restore backups on failure (non-modpack only)."""
        if not is_modpack and self.backup_service:
            self.backup_service.restore_backups(chapter_id)

    def _collect_exported_code_files(self, objects_dir: str, mod_number: int) -> None:
        """Scan CodeEntries dir for .gml files and store in _mod_exported_code_files."""
        code_entries_dir = os.path.join(objects_dir, 'CodeEntries')
        if os.path.exists(code_entries_dir):
            mod_exported_code = {os.path.splitext(f)[0] for f in os.listdir(code_entries_dir) if f.endswith('.gml')}
            self._mod_exported_code_files[mod_number] = mod_exported_code

    def _backup_or_mark_file(self, chapter_id: Optional[int], target_file: str) -> None:
        """Backup existing file or mark new file as added for rollback."""
        if chapter_id is None or not self.backup_service:
            return
        if os.path.exists(target_file):
            self.backup_service.backup_file(chapter_id, target_file)
        else:
            self.backup_service.mark_file_added(chapter_id, target_file)

    @staticmethod
    def _count_items(base, subdir, ext=None, dirs_only=False):
        path = os.path.join(base, subdir)
        if not os.path.exists(path):
            return 0
        if dirs_only:
            return sum(1 for d in os.listdir(path) if os.path.isdir(os.path.join(path, d)))
        if not ext:
            return len(os.listdir(path))
        return sum(1 for f in os.listdir(path) if f.endswith(ext))

    def _log_resource_counts(self, objects_dir: str, label: str) -> tuple:
        code_count = self._count_items(objects_dir, 'CodeEntries', ext='.gml')
        sprite_count = self._count_items(objects_dir, 'Sprites', dirs_only=True)
        shader_count = self._count_items(objects_dir, 'Shaders', dirs_only=True)
        self.patching_logger.info(f'{label}: {code_count} code, {sprite_count} sprites, {shader_count} shaders')
        return code_count, sprite_count, shader_count

    def _cleanup_temp_dir(self, keep_backups: bool = False) -> None:
        if not self.temp_patch_dir or not os.path.exists(self.temp_patch_dir):
            return
        if not keep_backups:
            if safe_rmtree(self.temp_patch_dir):
                self.patching_logger.info(f'Cleaned up temp patch directory: {self.temp_patch_dir}')
            else:
                self.patching_logger.warning(f'Failed to cleanup temp patch dir {self.temp_patch_dir}')
            self.temp_patch_dir = None
        else:
            try:
                for item in os.listdir(self.temp_patch_dir):
                    if item == 'backups':
                        continue
                    item_path = os.path.join(self.temp_patch_dir, item)
                    is_dir = os.path.isdir(item_path)
                    ok = safe_rmtree(item_path) if is_dir else safe_remove(item_path)
                    kind = 'directory' if is_dir else 'file'
                    if ok:
                        self.patching_logger.debug(f'Removed temp {kind}: {item_path}')
                    else:
                        self.patching_logger.warning(f'Failed to remove temp {kind} {item_path}')
                self.patching_logger.info(f'Cleaned up temp files from patch directory, kept backups: {self.temp_patch_dir}')
            except Exception as e:
                self.patching_logger.warning(f'Failed to cleanup temp files from patch dir {self.temp_patch_dir}: {e}')

    def _show_patching_warning(self, warning_type: str, title: str, message: str) -> bool:
        self.patching_logger.warning(f'[PATCHING_WARNING] {warning_type}: {message}')
        if self.app_state.local_config.get('skip_patching_warnings', False):
            self.patching_logger.info(f'[PATCHING_WARNING] Skipping warning (skip_patching_warnings enabled): {warning_type}')
            return True
        if self._warning_callback:
            return self._warning_callback(warning_type, title, message)
        return True

    def _track_exported_assets(self, objects_dir: str, mod_name: str, existing_code_files: Dict, existing_assets: Dict) -> None:
        for subdir, ext, asset_key, is_dir_check in ASSET_TRACKING_CONFIGS:
            path = os.path.join(objects_dir, subdir)
            if not os.path.exists(path):
                continue
            if asset_key == 'code_files':
                for f in os.listdir(path):
                    if f.endswith(ext):
                        name = os.path.splitext(f)[0]
                        if name not in existing_code_files:
                            existing_code_files[name] = mod_name
            elif is_dir_check:
                target = existing_assets.get(asset_key, {})
                for name in os.listdir(path):
                    if os.path.isdir(os.path.join(path, name)) and name not in target:
                        target[name] = mod_name
            else:
                target = existing_assets.get(asset_key, {})
                for f in os.listdir(path):
                    if f.endswith(ext):
                        name = os.path.splitext(f)[0]
                        if name not in target:
                            target[name] = mod_name

    def process_mod_patch(self, chapter_mods: Dict[int, List[Any]], is_modpack: bool, modpack_dir: Optional[str] = None, fast_patch: bool = False, xdelta_modpack: bool = False) -> bool:
        self.xdelta_modpack = xdelta_modpack
        self.patching_logger = get_patching_logger()
        self.conflict_tracker.reset(self.patching_logger)
        op = 'modpack creation' if is_modpack else 'multi-mod patching'
        self.patching_logger.info(f'Starting {op} for {len(chapter_mods)} chapter(s)')
        for chapter_id, mods_list in chapter_mods.items():
            mod_names = [getattr(m, 'name', 'Unknown') for m in mods_list]
            self.patching_logger.info(f'Chapter {chapter_id}: {len(mods_list)} mod(s) - {mod_names}')
        if not self.utmt_wrapper.is_available():
            self.patching_logger.error(f'UTMTCLI not available for platform: {self.utmt_wrapper.get_platform()}')
            self.status_update.emit(tr('errors.utmtcli_not_available', platform=self.utmt_wrapper.get_platform()), 'error')
            return False
        self.patching_logger.info(f'UTMTCLI is available, proceeding with {op}')
        try:
            if is_modpack and modpack_dir:
                os.makedirs(modpack_dir, exist_ok=True)
            total_chapters = len([c for c in chapter_mods.values() if c])
            total_mods = sum((len(mods_list) for mods_list in chapter_mods.values()))
            current_progress = 0
            patch_msg = self._safe_tr('status.preparing_mod_patching', f'Preparing to patch {total_mods} mod(s) for {total_chapters} chapter(s)...', chapters=total_chapters, mods=total_mods)
            self.progress_update.emit(0, patch_msg)
            try:
                prefix = 'deltahub_modpack_' if is_modpack else 'deltahub_multimod_'
                self.temp_patch_dir = tempfile.mkdtemp(prefix=prefix)
                backup_dir = os.path.join(self.temp_patch_dir, 'backups')
                self.backup_service = BackupManager(backup_dir, patching_logger=self.patching_logger)
                self.patching_logger.info(f'Created temp patch directory: {self.temp_patch_dir}')
                current_progress += 5
            except Exception as e:
                self.patching_logger.error(f'Failed to create temp patch directory: {e}', exc_info=True)
                self.status_update.emit(tr('errors.temp_dir_creation_failed'), 'error')
                return False
            patch_msg = self._safe_tr('status.patching_mods', f'Patching mods... {current_progress}%', progress=current_progress)
            self.progress_update.emit(min(current_progress, 95), patch_msg)
            chapter_index = 0
            for chapter_id, mods_list in sorted(chapter_mods.items()):
                if not mods_list:
                    continue
                if is_modpack and '_' not in chapter_id:
                    continue
                if self._cancelled:
                    if not is_modpack:
                        for cid in chapter_mods.keys():
                            self.backup_service.restore_backups(cid)
                    return False
                chapter_index += 1
                chapter_progress_base = (chapter_index - 1) * (100 // total_chapters) if total_chapters > 0 else 0
                self.patching_logger.info(f'Processing chapter {chapter_id} with {len(mods_list)} mod(s)')
                is_actual_chapter = '_' in chapter_id and not chapter_id.endswith('_0')
                if is_actual_chapter:
                    chapter_msg = self._safe_tr('status.patching_chapter', f'Patching chapter {chapter_id} ({chapter_index}/{total_chapters})...', chapter=chapter_id, current=chapter_index, total=total_chapters)
                else:
                    progress_pct = min(chapter_progress_base + 5, 95)
                    chapter_msg = self._safe_tr('status.patching_mods', f'Patching mods... {progress_pct}%', progress=progress_pct)
                self.progress_update.emit(min(chapter_progress_base + 5, 95), chapter_msg)
                if is_modpack and modpack_dir:
                    game = self._resolve_mod_game(mods_list[0]) if mods_list else None
                    chapter_folder_name = get_chapter_folder_name(chapter_id, game=game)
                    chapter_modpack_dir = os.path.join(modpack_dir, chapter_folder_name)
                    if not self._patch_chapter_to_dir(chapter_id, mods_list, chapter_modpack_dir, chapter_progress_base, total_chapters, fast_patch=fast_patch, game=game):
                        self.patching_logger.error(f'Failed to patch mods for chapter {chapter_id} in modpack')
                        failed_msg = self._safe_tr('status.patching_failed', 'Modpack creation failed')
                        self.progress_update.emit(0, failed_msg)
                        return False
                elif not self._patch_chapter(chapter_id, mods_list, chapter_progress_base, total_chapters, fast_patch=fast_patch):
                    target_dir = self._get_target_dir(chapter_id)
                    if not target_dir:
                        self.patching_logger.warning(f'Target directory not found for chapter {chapter_id}, skipping mods for this chapter. The game may not have this chapter installed.')
                        continue
                    self.patching_logger.error(f'Failed to patch mods for chapter {chapter_id}, restoring backups')
                    if self.backup_service:
                        self.backup_service.restore_backups(chapter_id)
                    data_modifying_count = 0
                    for mod_data in mods_list:
                        mod_source_dir = self._get_mod_source_dir(mod_data, chapter_id)
                        if mod_source_dir:
                            mod_type = mod_content.detect_mod_type(mod_source_dir, logger=self.patching_logger)
                            if mod_type.get('has_xdelta_patch') or mod_type.get('has_ready_data_win') or mod_type.get('has_csx_scripts'):
                                data_modifying_count += 1
                    is_fast_path = not is_modpack and data_modifying_count <= 1
                    if is_fast_path and len(mods_list) == 1:
                        mod_name = getattr(mods_list[0], 'name', 'Unknown')
                        failed_msg = self._safe_tr('errors.mod_patch_failed_single', f'Failed to apply mod {mod_name}', mod_name=mod_name)
                    else:
                        failed_msg = self._safe_tr('status.patching_failed', 'Mod patching failed')
                    self.status_update.emit(failed_msg, 'error')
                    self.progress_update.emit(0, failed_msg)
                    return False
                chapter_progress = chapter_index * (100 // total_chapters) if total_chapters > 0 else 100
                patched_msg = self._safe_tr('status.chapter_patched', f'Chapter {chapter_id} patched successfully', chapter=chapter_id)
                self.progress_update.emit(min(chapter_progress, 95), patched_msg)
                self.patching_logger.info(f'Successfully {"processed" if is_modpack else "patched"} mods for chapter {chapter_id}')
                if not is_modpack:
                    if self.backup_service and self._session_manifest_path:
                        self.backup_service.save_backups_to_manifest(self._session_manifest_path)
            completed_msg = self._safe_tr('status.patching_completed', 'Mod patching completed successfully')
            self.progress_update.emit(100, completed_msg)
            self.patching_logger.info(f'{op.capitalize()} completed successfully')
            self._cleanup_temp_dir(keep_backups=not is_modpack)
            return True
        except Exception as e:
            self.patching_logger.error(f'{op.capitalize()} failed: {e}', exc_info=True)
            self.status_update.emit(tr('errors.patching_failed', error=str(e)), 'error')
            if not is_modpack:
                for chapter_id in chapter_mods.keys():
                    if self.backup_service:
                        self.backup_service.restore_backups(chapter_id)
            return False
        finally:
            if hasattr(self, 'temp_patch_dir') and self.temp_patch_dir and os.path.exists(self.temp_patch_dir):
                if is_modpack:
                    if not safe_rmtree(self.temp_patch_dir):
                        self.patching_logger.warning(f'Failed to cleanup temp patch dir in finally block: {self.temp_patch_dir}')
                    self.temp_patch_dir = None

    def _patch_chapter(self, chapter_id: str, mods_list: List[Any], progress_base: int = 0, total_chapters: int = 1, fast_patch: bool = False) -> bool:
        self.patching_logger.debug(f'_patch_chapter: chapter_id={chapter_id}, mods_count={len(mods_list)}')
        target_dir = self._get_target_dir(chapter_id)
        if not target_dir:
            error_msg = tr('errors.target_directory_not_found', chapter=chapter_id)
            self.patching_logger.error(f'Target directory not found for chapter {chapter_id}')
            self.status_update.emit(error_msg, 'error')
            return False
        self.patching_logger.debug(f'Target directory: {target_dir}')
        if not ensure_writable(target_dir):
            self.status_update.emit(tr('errors.no_write_permission_for', path=target_dir), 'error')
            return False
        data_win_path = mod_content.find_data_win(target_dir)
        if not data_win_path:
            expected_path = os.path.join(target_dir, 'data.win')
            warning_msg = tr('dialogs.patching_warning.data_win_not_found', search_path=expected_path)
            if not self._show_patching_warning('data_win_not_found', tr('dialogs.patching_warning.title'), warning_msg):
                self.patching_logger.info(f'[PATCHING_WARNING] User cancelled patching due to missing data.win at: {expected_path}')
                return False
            return self._apply_file_overrides_only(chapter_id, mods_list, target_dir)
        if not self.backup_service.backup_file(chapter_id, data_win_path):
            return False
        return self._perform_chapter_patch(chapter_id, mods_list, data_win_path, target_dir, None, progress_base, total_chapters, is_modpack=False, fast_patch=fast_patch)

    def _fast_path_backup_if_exists(self, output_data_win_path: str, target_dir: str) -> None:
        """Create a backup of the output file if it exists, for fast-path operations."""
        if os.path.exists(output_data_win_path):
            extracted_chapter_id = mod_content.extract_chapter_id_from_path(target_dir)
            if extracted_chapter_id is not None:
                self.backup_service.backup_file(extracted_chapter_id, output_data_win_path)

    def _run_fast_path_operation(self, operation, operation_desc: str, mod_name: str, chapter_id: str, is_modpack: bool) -> bool:
        """Run a fast-path operation with unified error handling.

        Args:
            operation: Callable that returns True on success, False on failure.
            operation_desc: Description for logging (e.g. 'apply xdelta patches').
            mod_name: Name of the mod being processed.
            chapter_id: Current chapter ID.
            is_modpack: Whether this is a modpack operation.
        Returns:
            True if operation succeeded, False otherwise.
        """
        try:
            if not operation():
                self.patching_logger.error(f'[FAST_PATH] Failed to {operation_desc} from {mod_name}')
                if not is_modpack:
                    self.backup_service.restore_backups(chapter_id)
                return False
            return True
        except Exception as e:
            self.patching_logger.error(f'[FAST_PATH] Failed to {operation_desc}: {e}', exc_info=True)
            error_msg = str(e)[:200] if len(str(e)) > 200 else str(e)
            self.status_update.emit(tr('errors.mod_patch_failed', mod_name=mod_name, error=error_msg), 'error')
            if not is_modpack:
                self.backup_service.restore_backups(chapter_id)
            return False

    def _perform_chapter_patch(self, chapter_id: str, mods_list: List[Any], output_data_win_path: str, target_dir: str, modpack_dir: Optional[str], progress_base: int, total_chapters: int, is_modpack: bool, fast_patch: bool = False) -> bool:
        original_data_win = output_data_win_path
        if not mods_list:
            self.patching_logger.info(f'[OPTIMIZATION] No mods to apply for chapter {chapter_id}, skipping')
            return True
        chapter_progress_range = 100 // total_chapters if total_chapters > 0 else 100
        xdelta_progress = chapter_progress_range * 0.3
        export_progress = chapter_progress_range * 0.3
        import_progress = chapter_progress_range * 0.4
        patch_root = self.temp_patch_dir
        if not patch_root:
            self.patching_logger.error('Temp patch directory not set')
            return False
        output_dir = os.path.join(patch_root, 'output')
        os.makedirs(output_dir, exist_ok=True)
        cache_running_dir = os.path.join(output_dir, 'DeltahubCache', 'running')
        os.makedirs(cache_running_dir, exist_ok=True)
        chapter_str = str(chapter_id)
        xdelta_combiner_dir = os.path.join(output_dir, 'DeltahubPatchWorkspace', chapter_str)
        vanilla_dir = os.path.join(xdelta_combiner_dir, '0')
        os.makedirs(vanilla_dir, exist_ok=True)
        original_filename = os.path.basename(original_data_win)
        vanilla_data_win = os.path.join(vanilla_dir, original_filename)
        shutil.copyfile(original_data_win, vanilla_data_win)
        self.patching_logger.info(f'Created vanilla copy at {vanilla_data_win} (from {original_data_win})')
        data_modifying_mods = []
        for mod_data in mods_list:
            mod_source_dir = self._get_mod_source_dir(mod_data, chapter_id)
            if mod_source_dir:
                mod_type = mod_content.detect_mod_type(mod_source_dir, logger=self.patching_logger)
                if mod_type.get('has_xdelta_patch') or mod_type.get('has_ready_data_win') or mod_type.get('has_csx_scripts'):
                    data_modifying_mods.append(mod_data)
        self.patching_logger.info(f'[OPTIMIZATION] Found {len(data_modifying_mods)} mod(s) that modify data.win out of {len(mods_list)} total mod(s)')
        mods_count = len(mods_list)
        if not is_modpack and len(data_modifying_mods) <= 1:
            primary_data_mod = data_modifying_mods[0] if data_modifying_mods else None
            if primary_data_mod:
                mod_name = getattr(primary_data_mod, 'name', 'Unknown')
                mod_source_dir = self._get_mod_source_dir(primary_data_mod, chapter_id)
                if mod_source_dir:
                    ready_data_win_files = mod_content.find_ready_data_win_files(mod_source_dir, logger=self.patching_logger)
                    data_patches = mod_content.find_data_patches(mod_source_dir)
                    csx_scripts = mod_content.find_csx_scripts(mod_source_dir)
                    if ready_data_win_files and (not data_patches) and (not csx_scripts):
                        self.patching_logger.info(f'[FAST_PATH] Mod {mod_name} with only ready data.win/game.ios - copying directly')
                        ready_file = ready_data_win_files[0]
                        self.patching_logger.info(f'[FAST_PATH] Copying ready file: {ready_file} -> {output_data_win_path} (chapter {chapter_id})')

                        def _apply_ready_data_win():
                            extracted_chapter_id = mod_content.extract_chapter_id_from_path(target_dir)
                            if extracted_chapter_id is not None:
                                self.patching_logger.info(f'[FAST_PATH] Creating backup before replacing data.win (chapter {extracted_chapter_id})')
                                if not self.backup_service.backup_file(extracted_chapter_id, output_data_win_path):
                                    self.patching_logger.error(f'[FAST_PATH] Failed to create backup of {output_data_win_path} before replacement')
                                    return False
                            else:
                                self.patching_logger.warning(f'[FAST_PATH] Could not extract chapter ID from path {target_dir}, backup may not work correctly')
                            shutil.copyfile(ready_file, output_data_win_path)
                            file_size = os.path.getsize(output_data_win_path) if os.path.exists(output_data_win_path) else 0
                            self.patching_logger.info(f'[FAST_PATH] Successfully copied ready data.win/game.ios from {mod_name} to {output_data_win_path} (size: {file_size} bytes, chapter {chapter_id})')
                            return True

                        if not self._run_fast_path_operation(_apply_ready_data_win, 'copy ready data.win', mod_name, chapter_id, is_modpack):
                            return False
                    elif data_patches and (not ready_data_win_files) and (not csx_scripts):
                        self.patching_logger.info(f'[FAST_PATH] Mod {mod_name} with only xdelta patch(es) - applying directly')

                        def _apply_xdelta():
                            self._fast_path_backup_if_exists(output_data_win_path, target_dir)
                            if not self._apply_xdelta_patches(output_data_win_path, data_patches, progress_callback=lambda p: self.progress_update.emit(min(int(p * 50), 95), f'Applying patch from {mod_name}...')):
                                return False
                            self.patching_logger.info(f'[FAST_PATH] Successfully applied xdelta patches from {mod_name} to {output_data_win_path}')
                            return True

                        if not self._run_fast_path_operation(_apply_xdelta, 'apply xdelta patches', mod_name, chapter_id, is_modpack):
                            return False
                    elif csx_scripts and (not ready_data_win_files) and (not data_patches):
                        self.patching_logger.info(f'[FAST_PATH] Mod {mod_name} with only CSX script(s) - executing directly without vanilla export')

                        def _apply_csx():
                            self._fast_path_backup_if_exists(output_data_win_path, target_dir)
                            if not self._apply_csx_scripts(output_data_win_path, csx_scripts):
                                return False
                            self.patching_logger.info(f'[FAST_PATH] Successfully executed CSX scripts from {mod_name} on {output_data_win_path}')
                            return True

                        if not self._run_fast_path_operation(_apply_csx, 'execute CSX scripts', mod_name, chapter_id, is_modpack):
                            return False
            else:
                self.patching_logger.info('[FAST_PATH] No mods modify data.win, skipping data.win changes')
            self.patching_logger.info(f'[FAST_PATH] Applying file overrides from all {len(mods_list)} mod(s)')
            for mod_data in mods_list:
                mod_source_dir = self._get_mod_source_dir(mod_data, chapter_id)
                if mod_source_dir:
                    mod_name = getattr(mod_data, 'name', 'Unknown')
                    used_archive_names = set()
                    if self._apply_file_overrides(mod_source_dir, target_dir, used_archive_names, False, chapter_id):
                        self.patching_logger.debug(f'[FAST_PATH] Applied file overrides from {mod_name}')
                    else:
                        self.patching_logger.warning(f'[FAST_PATH] Failed to apply file overrides from {mod_name}')
            self.patching_logger.info('[FAST_PATH] Fast path completed successfully, skipping full export/import cycle')
            return True
        vanilla_objects_dir = os.path.join(vanilla_dir, 'Objects')
        vanilla_already_exported = os.path.exists(vanilla_objects_dir) and bool(os.listdir(vanilla_objects_dir))
        if not vanilla_already_exported:
            self.patching_logger.info('Exporting vanilla mod (mod 0) assets...')
            chapter_file = os.path.join(cache_running_dir, 'chapterNumber.txt')
            mod_file = os.path.join(cache_running_dir, 'modNumbersCache.txt')
            with open(chapter_file, 'w', encoding='utf-8') as f:
                f.write(chapter_str)
            with open(mod_file, 'w', encoding='utf-8') as f:
                f.write('0')
            vanilla_scripts = self._get_available_scripts('Export')
            if vanilla_scripts:
                all_exports_successful = self._run_export_scripts(vanilla_scripts, vanilla_data_win, vanilla_objects_dir, patch_root, label='Vanilla ')
                if not all_exports_successful:
                    self.patching_logger.warning('Some vanilla export scripts failed')
                    warning_msg = tr('dialogs.patching_warning.export_failed', operation=tr('dialogs.patching_warning.export'), resource='vanilla')
                    if not self._show_patching_warning('vanilla_export_failed', tr('dialogs.patching_warning.title'), warning_msg):
                        self.patching_logger.info('[PATCHING_WARNING] User cancelled patching due to vanilla export failure')
                        return False
                    self.patching_logger.info('[PATCHING_WARNING] User chose to continue despite vanilla export failure')
                else:
                    self.patching_logger.info('Successfully exported vanilla assets')
            else:
                self.patching_logger.error('No export scripts found! At least one export script is required.')
                return False
        else:
            self.patching_logger.info('Vanilla mod (mod 0) already exported, skipping')
        max_mods = len(mods_list) + 2
        for mod_num in range(max_mods):
            mod_dir = os.path.join(xdelta_combiner_dir, str(mod_num))
            objects_code_dir = os.path.join(mod_dir, 'Objects', 'CodeEntries')
            os.makedirs(objects_code_dir, exist_ok=True)
        for idx, mod_data in enumerate(mods_list):
            priority = len(mods_list) - idx
            if not hasattr(mod_data, 'priority') or getattr(mod_data, 'priority', None) is None:
                setattr(mod_data, 'priority', priority)
        mods_to_apply = list(mods_list)
        mods_count = len(mods_to_apply)
        self.patching_logger.info(f"Processing {mods_count} mod(s): {[getattr(m, 'name', 'Unknown') for m in mods_to_apply]}")
        highest_priority_mod_name = getattr(mods_list[0], 'name', 'Unknown') if mods_list else 'None'
        self.patching_logger.info(f'Highest priority mod (priority {len(mods_list)}): {highest_priority_mod_name}')
        mod_patched_files = {}
        existing_code_files = {}
        existing_assets = {'sprites': {}, 'backgrounds': {}, 'tilesets': {}, 'shaders': {}}
        mods_already_exported = set()
        mod_types = {}
        for idx, mod_data in enumerate(mods_to_apply):
            if self._cancelled:
                return False
            mod_name = getattr(mod_data, 'name', 'Unknown')
            mod_number = idx + 1
            mod_progress_start = progress_base + int(idx / mods_count * xdelta_progress) if mods_count > 0 else progress_base
            mod_progress_end = progress_base + int((idx + 1) / mods_count * xdelta_progress) if mods_count > 0 else progress_base + xdelta_progress
            mod_progress_range = mod_progress_end - mod_progress_start
            xdelta_msg = self._safe_tr('status.applying_xdelta', f'Applying mod {mod_name} ({idx + 1}/{mods_count})...', mod=mod_name, current=idx + 1, total=mods_count)
            self.progress_update.emit(min(mod_progress_start, 95), xdelta_msg)
            mod_source_dir = self._get_mod_source_dir(mod_data, chapter_id)
            if not mod_source_dir:
                self.patching_logger.warning(f'Mod source directory not found for {mod_name}, skipping')
                continue
            mod_type = mod_content.detect_mod_type(mod_source_dir, logger=self.patching_logger)
            mod_types[mod_number] = mod_type
            mod_dir = os.path.join(xdelta_combiner_dir, str(mod_number))
            os.makedirs(mod_dir, exist_ok=True)
            original_filename = os.path.basename(original_data_win)
            mod_data_win = os.path.join(mod_dir, original_filename)
            shutil.copyfile(original_data_win, mod_data_win)
            ready_data_win_files = mod_content.find_ready_data_win_files(mod_source_dir, logger=self.patching_logger)
            data_patches = mod_content.find_data_patches(mod_source_dir)
            csx_scripts = mod_content.find_csx_scripts(mod_source_dir)
            if ready_data_win_files:
                self.patching_logger.info(f'Found {len(ready_data_win_files)} ready data.win/game.ios file(s) from {mod_name} (mod {mod_number}), merging')
                patch_progress = mod_progress_start + int(mod_progress_range * 0.5)
                self.progress_update.emit(min(patch_progress, 95), f'Applying ready data.win from {mod_name}...')
                if not self._handle_ready_data_win(mod_data_win, ready_data_win_files, mod_dir):
                    self.patching_logger.error(f'Failed to apply ready data.win files from {mod_name}')
                    self._fail_restore(is_modpack, chapter_id)
                    return False
                self.patching_logger.info(f'Successfully applied ready data.win files from {mod_name} (mod {mod_number})')
                target_dir_result = self._get_target_dir(chapter_id)
                if target_dir_result is not None and mod_source_dir:
                    used_archive_names = set()
                    if not self._apply_file_overrides(mod_source_dir, target_dir_result, used_archive_names, False, chapter_id):
                        self.patching_logger.warning(f'Failed to apply file overrides from {mod_name} after ready data.win patching')
                if not data_patches and (not csx_scripts):
                    mods_already_exported.add(mod_number)
                    self.patching_logger.info(f'Mod {mod_name} (number {mod_number}) has only ready data.win, will skip export scripts')
                mod_patched_files[mod_number] = mod_data_win
            if data_patches:
                self.patching_logger.info(f'Found {len(data_patches)} data patch(es) from {mod_name} (mod {mod_number}), applying to original')
                patch_progress = mod_progress_start + int(mod_progress_range * 0.3)
                self.progress_update.emit(min(patch_progress, 95), f'Applying patches from {mod_name}...')
                if not self._apply_xdelta_patches(mod_data_win, data_patches, progress_callback=lambda p: self.progress_update.emit(min(mod_progress_start + int(mod_progress_range * (0.3 + p * 0.4)), 95), f'Applying patches from {mod_name}...')):
                    self.patching_logger.error(f'[PATCH] Failed to apply data patches from {mod_name} (mod {mod_number}). This may be due to incompatibility with previously applied mods. The patch may have been created for the original data.win, but the file has already been modified.')
                    self._fail_restore(is_modpack, chapter_id)
                    return False
                self.patching_logger.info(f'Successfully applied data patches from {mod_name} (mod {mod_number})')
                mod_patched_files[mod_number] = mod_data_win
            if csx_scripts:
                self.patching_logger.info(f'Found {len(csx_scripts)} CSX script(s) from {mod_name} (mod {mod_number}), executing')
                script_progress = mod_progress_start + int(mod_progress_range * 0.7)
                self.progress_update.emit(min(script_progress, 95), f'Executing scripts from {mod_name}...')
                if not self._apply_csx_scripts(mod_data_win, csx_scripts):
                    self.patching_logger.error(f'Failed to execute CSX scripts from {mod_name}')
                    self._fail_restore(is_modpack, chapter_id)
                    return False
                self.patching_logger.info(f'Successfully executed CSX scripts from {mod_name} (mod {mod_number})')
                mod_patched_files[mod_number] = mod_data_win
            if not ready_data_win_files and (not data_patches) and (not csx_scripts):
                target_dir_result = self._get_target_dir(chapter_id)
                if target_dir_result is not None and mod_source_dir:
                    used_archive_names = set()
                    if self._apply_file_overrides(mod_source_dir, target_dir_result, used_archive_names, False, chapter_id):
                        self.patching_logger.info(f'Applied file overrides from {mod_name} (mod {mod_number})')
            if mod_number not in mod_patched_files:
                mod_patched_files[mod_number] = mod_data_win
            self.progress_update.emit(min(mod_progress_end, 95), f'Completed {mod_name}')
        mods_to_export = [m for i, m in enumerate(mods_to_apply) if i + 1 not in mods_already_exported]
        highest_priority_mod_exported_files = set()
        if fast_patch and mods_to_export:

            if not self._perform_parallel_export(mods_to_export, mods_to_apply, mod_patched_files, mod_types, vanilla_data_win, patch_root, cache_running_dir, chapter_str, chapter_id, progress_base + int(xdelta_progress), export_progress, lambda p, msg: self.progress_update.emit(p, msg)):
                self._fail_restore(is_modpack, chapter_id)
                return False
            for mod_data in mods_to_export:
                mod_name = getattr(mod_data, 'name', 'Unknown')
                original_idx = mods_to_apply.index(mod_data)
                mod_number = original_idx + 1
                mod_data_win = mod_patched_files.get(mod_number)
                if not mod_data_win or not os.path.exists(mod_data_win):
                    continue
                mod_dir = os.path.dirname(mod_data_win)
                objects_dir = os.path.join(mod_dir, 'Objects')
                if os.path.exists(objects_dir):
                    self._collect_exported_code_files(objects_dir, mod_number)
                mod_source_dir = self._get_mod_source_dir(mod_data, chapter_id)
                if mod_source_dir:
                    self._track_exported_assets(os.path.join(mod_dir, 'Objects'), mod_name, existing_code_files, existing_assets)
        else:
            for idx, mod_data in enumerate(mods_to_export):
                if self._cancelled:
                    return False
                mod_name = getattr(mod_data, 'name', 'Unknown')
                original_idx = mods_to_apply.index(mod_data)
                mod_number = original_idx + 1
                export_step = idx / len(mods_to_export) * export_progress if mods_to_export else 0
                current_progress = progress_base + int(xdelta_progress + export_step)
                export_msg = self._safe_tr('status.exporting_assets', f'Exporting assets from {mod_name} ({idx + 1}/{len(mods_to_export)})...', mod=mod_name, current=idx + 1, total=len(mods_to_export))
                self.progress_update.emit(min(current_progress, 95), export_msg)
                mod_data_win = mod_patched_files.get(mod_number)
                if not mod_data_win or not os.path.exists(mod_data_win):
                    continue
                mod_dir = os.path.dirname(mod_data_win)
                mod_asset_types = mod_content.detect_mod_asset_types(mod_dir, logger=self.patching_logger)
                mod_type = mod_types.get(mod_number, {})
                has_previous_mod = mod_number > 1 and mod_number - 1 in mod_patched_files
                scripts, comparison_file = self._select_export_strategy(mod_type, mod_asset_types, mod_number, has_previous_mod)
                if not scripts and comparison_file is None:
                    self.patching_logger.info(f'Skipping export for mod {mod_number} ({mod_name}) - already exported')
                    continue
                self.patching_logger.info(f'Exporting assets from mod {mod_number} ({mod_name}) using strategy: {scripts}, comparison: {comparison_file}')
                if not self._export_mod_assets_optimized(mod_data_win, mod_number, scripts, comparison_file, vanilla_data_win, patch_root, cache_running_dir, chapter_str):
                    self.patching_logger.warning(f'Failed to export assets from mod {mod_number} ({mod_name})')
                else:
                    objects_dir = os.path.join(mod_dir, 'Objects')
                    if os.path.exists(objects_dir):
                        code_count, sprite_count, shader_count = self._log_resource_counts(objects_dir, f'[EXPORT] Mod {mod_number} ({mod_name}) exported')
                        self._collect_exported_code_files(objects_dir, mod_number)
                    mod_source_dir = self._get_mod_source_dir(mod_data, chapter_id)
                    if mod_source_dir:
                        self._track_exported_assets(os.path.join(mod_dir, 'Objects'), mod_name, existing_code_files, existing_assets)
        highest_priority_mod = None
        highest_priority_value = -1
        highest_priority_mod_number = None
        for idx, mod_data in enumerate(mods_to_apply):
            mod_number = idx + 1
            mod_priority = getattr(mod_data, 'priority', None)
            if mod_priority is None:
                mod_priority = len(mods_to_apply) - idx
            if mod_priority > highest_priority_value:
                highest_priority_value = mod_priority
                highest_priority_mod = mod_data
                highest_priority_mod_number = mod_number
        if highest_priority_mod_number is None:
            highest_priority_mod_number = 1
        base_mod_number = highest_priority_mod_number
        highest_priority_mod_exported_files = getattr(self, '_mod_exported_code_files', {}).get(base_mod_number, set())
        if highest_priority_mod_exported_files:
            self.patching_logger.info(f"Highest priority mod (mod_number {base_mod_number}): {getattr(highest_priority_mod, 'name', 'Unknown')} (priority {highest_priority_value}) - exported {len(highest_priority_mod_exported_files)} code files in main cycle")
        else:
            self.patching_logger.info(f"Highest priority mod (mod_number {base_mod_number}): {getattr(highest_priority_mod, 'name', 'Unknown')} (priority {highest_priority_value})")
        base_mod_dir = os.path.join(xdelta_combiner_dir, str(base_mod_number))
        base_data_win = mod_patched_files.get(base_mod_number)
        if not base_data_win:
            original_filename = os.path.basename(original_data_win)
            base_data_win = os.path.join(base_mod_dir, original_filename)
            os.makedirs(base_mod_dir, exist_ok=True)
            shutil.copyfile(original_data_win, base_data_win)
            mod_patched_files[base_mod_number] = base_data_win
        self.patching_logger.info(f'Importing all assets into base file (mod {base_mod_number})')
        chapter_file = os.path.join(cache_running_dir, 'chapterNumber.txt')
        with open(chapter_file, 'w', encoding='utf-8') as f:
            f.write(chapter_str)
        objects_dirs_to_import = []
        for idx, mod_data in enumerate(mods_to_apply):
            mod_name = getattr(mod_data, 'name', 'Unknown')
            mod_number = idx + 1
            mod_priority = getattr(mod_data, 'priority', None)
            if mod_priority is None:
                mod_priority = len(mods_to_apply) - idx
            mod_dir = os.path.join(xdelta_combiner_dir, str(mod_number))
            objects_dir = os.path.join(mod_dir, 'Objects')
            if os.path.exists(objects_dir):
                objects_dirs_to_import.append((mod_number, mod_priority, mod_name, objects_dir))
                self.patching_logger.debug(f'Added mod {mod_number} ({mod_name}) with priority {mod_priority} to import list')
            else:
                self.patching_logger.debug(f'Objects directory not found for mod {mod_number} ({mod_name}) - may not have exported assets')
        objects_dirs_to_import.sort(key=lambda x: x[1])
        self.patching_logger.info(f'Patch order (by priority): {[(m[1], m[2]) for m in objects_dirs_to_import]}')
        combined_objects_dir = os.path.join(xdelta_combiner_dir, 'DeltahubCombined')
        target_objects_dir = os.path.join(combined_objects_dir, 'Objects')
        if os.path.exists(combined_objects_dir):
            self.patching_logger.debug(f'Cleaning up previous patch directory: {combined_objects_dir}')
            if not safe_rmtree(combined_objects_dir):
                self.patching_logger.warning(f'Failed to clean up previous patch directory: {combined_objects_dir}')
        os.makedirs(target_objects_dir, exist_ok=True)
        self.patching_logger.info(f'Created clean patch directory: {target_objects_dir}')
        vanilla_objects_dir = os.path.join(xdelta_combiner_dir, '0', 'Objects')
        vanilla_hashes = {}
        if os.path.exists(vanilla_objects_dir):
            self.patching_logger.info('[FILTER] Computing hashes for vanilla resources...')
            vanilla_hashes = resource_filter.compute_resource_hashes(vanilla_objects_dir)
            self.patching_logger.info(f'[FILTER] Computed hashes for {sum((len(v) for v in vanilla_hashes.values()))} vanilla resources')
        filtered_objects_dirs = []
        if fast_patch and objects_dirs_to_import:
            filter_progress = chapter_progress_range * 0.2
            filter_base = progress_base + int(xdelta_progress + export_progress)

            mods_dirs_info = []
            for mod_number, mod_priority, mod_name, objects_dir in objects_dirs_to_import:
                if mod_number == 0:
                    continue
                if os.path.exists(objects_dir):
                    mods_dirs_info.append((mod_number, objects_dir, mod_name))
            if mods_dirs_info:
                filtered_results = self._perform_parallel_filtering(vanilla_hashes, mods_dirs_info, filter_base, filter_progress, lambda p, msg: self.progress_update.emit(p, msg))
                for mod_number, mod_priority, mod_name, objects_dir in objects_dirs_to_import:
                    if mod_number == 0:
                        continue
                    filtered_dir = filtered_results.get(mod_number)
                    if filtered_dir and os.path.exists(filtered_dir):
                        filtered_objects_dirs.append((mod_number, mod_priority, mod_name, filtered_dir))
        else:
            for mod_number, mod_priority, mod_name, objects_dir in objects_dirs_to_import:
                if mod_number == 0:
                    continue
                if os.path.exists(objects_dir):
                    filtered_dir = resource_filter.filter_vanilla_identical_resources(vanilla_hashes, objects_dir, mod_number, mod_name, logger=self.patching_logger)
                    if filtered_dir and os.path.exists(filtered_dir):
                        filtered_objects_dirs.append((mod_number, mod_priority, mod_name, filtered_dir))
        self.patching_logger.info('[PATCH] Combining filtered mods into clean directory (vanilla-identical resources already filtered out)')
        for idx, (mod_number, mod_priority, mod_name, objects_dir) in enumerate(filtered_objects_dirs):
            if self._cancelled_restore(is_modpack, chapter_id):
                return False
            combine_step = idx / len(filtered_objects_dirs) * (import_progress * 0.5) if filtered_objects_dirs else 0
            current_progress = progress_base + int(xdelta_progress + export_progress + combine_step)
            patch_msg = self._safe_tr('status.patching_assets', f'Combining assets from {mod_name} ({idx + 1}/{len(filtered_objects_dirs)})...', mod=mod_name, current=idx + 1, total=len(filtered_objects_dirs))
            self.progress_update.emit(min(current_progress, 90), patch_msg)
            self.patching_logger.info(f'Combining assets from mod {mod_number} ({mod_name}, priority {mod_priority}) into clean patch directory (step {idx + 1}/{len(filtered_objects_dirs)})')
            self._log_resource_counts(objects_dir, f'[PATCH] Mod {mod_number} ({mod_name}) to combine (after filtering)')
            if os.path.exists(objects_dir) and any(True for _, dirs, files in os.walk(objects_dir) if dirs or files):
                self._combine_objects_directories(target_objects_dir, objects_dir, mod_name)
            else:
                self.patching_logger.debug(f'Mod {mod_number} ({mod_name}) has no resources to combine after filtering')
        if os.path.exists(target_objects_dir):
            self._log_resource_counts(target_objects_dir, '[IMPORT] Before import')
            if self._cancelled_restore(is_modpack, chapter_id):
                return False
            import_progress_step = progress_base + int(xdelta_progress + export_progress + import_progress * 0.5)
            self.progress_update.emit(min(import_progress_step, 95), 'Importing combined assets into data.win...')
            self.patching_logger.info('Importing combined Objects directory (contains all exported mods, sorted by priority) into data.win')
            if not self._import_assets_from_objects_dir(base_data_win, target_objects_dir, mods_to_apply, mods_count):
                self.patching_logger.warning('Failed to import combined assets into data.win')
                self._fail_restore(is_modpack, chapter_id)
                return False
            self.patching_logger.info('Successfully imported combined Objects into data.win')
        else:
            self.patching_logger.debug('No Objects directory to import after combining mods (only xdelta changes)')
        if self._cancelled_restore(is_modpack, chapter_id):
            return False
        if is_modpack:
            fname = 'game.ios' if platform.system() == 'Darwin' else 'data.win'
            final_output_path = os.path.join(modpack_dir, fname)
        else:
            final_output_path = output_data_win_path
        if self._cancelled_restore(is_modpack, chapter_id):
            return False
        try:
            shutil.copyfile(base_data_win, final_output_path)
            self.patching_logger.info(f'Copied patched data.win to {final_output_path}')
        except Exception as e:
            self.patching_logger.error(f'Failed to copy patched data.win: {e}')
            self._fail_restore(is_modpack, chapter_id)
            return False
        if self._cancelled_restore(is_modpack, chapter_id):
            return False
        if is_modpack:
            for mod_data in mods_to_apply:
                mod_source_dir = self._get_mod_source_dir(mod_data, chapter_id)
                if mod_source_dir:
                    if not self._apply_file_overrides(mod_source_dir, modpack_dir, set(), True, chapter_id):
                        self.patching_logger.warning(f"Failed to apply file overrides from {getattr(mod_data, 'name', 'Unknown')}")
        else:
            used_archive_names = set()
            for mod_data in mods_to_apply:
                if self._cancelled and self.backup_service:
                    self.backup_service.restore_backups(chapter_id)
                    return False
                mod_source_dir = self._get_mod_source_dir(mod_data, chapter_id)
                if mod_source_dir:
                    if not self._apply_file_overrides(mod_source_dir, target_dir, used_archive_names, False, chapter_id):
                        self.patching_logger.warning(f"Failed to apply file overrides from {getattr(mod_data, 'name', 'Unknown')}")
        self.patching_logger.info('Multi-mod patching completed successfully')
        return True

    def _patch_chapter_to_dir(self, chapter_id: str, mods_list: List[Any], modpack_dir: str, progress_base: int = 0, total_chapters: int = 1, fast_patch: bool = False, game: Optional[str] = None) -> bool:
        self.patching_logger.debug(f'_patch_chapter_to_dir: chapter_id={chapter_id}, mods_count={len(mods_list)}, modpack_dir={modpack_dir}, game={game}')
        os.makedirs(modpack_dir, exist_ok=True)
        target_dir = self._get_target_dir(chapter_id, game=game)
        if not target_dir:
            self.patching_logger.error(f'Target directory not found for chapter {chapter_id} (game={game})')
            return False
        self.patching_logger.debug(f'Target directory: {target_dir}')
        data_win_path = mod_content.find_data_win(target_dir)
        if not data_win_path:
            return self._apply_file_overrides_only(chapter_id, mods_list, modpack_dir, is_modpack=True)
        return self._perform_chapter_patch(chapter_id, mods_list, data_win_path, target_dir, modpack_dir, progress_base, total_chapters, is_modpack=True, fast_patch=fast_patch)

    def _apply_file_overrides_only(self, chapter_id: str, mods_list: List[Any], target_dir: str, is_modpack: bool = False) -> bool:
        mods_to_apply = list(reversed(mods_list))
        used_archive_names = set()
        for mod_data in mods_to_apply:
            mod_source_dir = self._get_mod_source_dir(mod_data, chapter_id)
            if mod_source_dir:
                if not self._apply_file_overrides(mod_source_dir, target_dir, used_archive_names if not is_modpack else set(), is_modpack, chapter_id):
                    return False
        return True

    def _apply_xdelta_patches(self, data_win_path: str, data_patches: List[str], progress_callback=None) -> bool:
        from utils.patching.xdelta_utils import apply_xdelta_patches
        return apply_xdelta_patches(self, data_win_path, data_patches, progress_callback)

    def _apply_csx_scripts(self, data_win_path: str, csx_scripts: List[str]) -> bool:
        if not csx_scripts:
            return True
        if not self.utmt_wrapper.is_available():
            self.patching_logger.error('UTMTCLI not available for executing CSX scripts')
            platform_name = self.utmt_wrapper.get_platform()
            warning_msg = tr('dialogs.patching_warning.utmt_not_available', platform=platform_name)
            if not self._show_patching_warning('utmt_not_available', tr('dialogs.patching_warning.title'), warning_msg):
                self.patching_logger.info('[PATCHING_WARNING] User cancelled patching due to UTMT not available')
                self.status_update.emit(tr('errors.utmtcli_not_available', platform=platform_name), 'error')
                return False
            self.patching_logger.info('[PATCHING_WARNING] User chose to continue despite UTMT not available')
            return True
        env = {}
        if self.temp_patch_dir and os.path.exists(os.path.join(self.temp_patch_dir, 'output')):
            env['DELTAHUB_ROOT'] = self.temp_patch_dir
        for script_path in csx_scripts:
            if self._cancelled:
                return False
            script_name = os.path.basename(script_path)
            try:
                self.patching_logger.info(f'Executing CSX script: {script_name}')
                returncode, stdout, stderr = self.utmt_wrapper.execute_script(data_win_path, script_path, output_path=data_win_path, cwd=self.temp_patch_dir or None, env=env)
                if self._cancelled:
                    return False
                if returncode != 0:
                    error_msg = (stderr or 'Unknown error')[:200]
                    self.patching_logger.error(f'CSX script execution failed: {(stderr or "Unknown error")[:500]}')
                    warning_msg = tr('dialogs.patching_warning.csx_script_failed', script_name=script_name, error=error_msg)
                    if not self._show_patching_warning('csx_script_failed', tr('dialogs.patching_warning.title'), warning_msg):
                        self.patching_logger.info(f'[PATCHING_WARNING] User cancelled patching due to CSX script failure: {script_name}')
                        self.status_update.emit(tr('errors.csx_script_failed', script=script_name), 'error')
                        return False
                    self.patching_logger.info(f'[PATCHING_WARNING] User chose to continue despite CSX script failure: {script_name}')
                    continue
                self.patching_logger.info(f'Successfully executed CSX script: {script_name}')
            except Exception as e:
                error_msg = str(e)[:200]
                self.patching_logger.error(f'CSX script error: {e}')
                warning_msg = tr('dialogs.patching_warning.csx_script_failed', script_name=script_name, error=error_msg)
                if not self._show_patching_warning('csx_script_exception', tr('dialogs.patching_warning.title'), warning_msg):
                    self.patching_logger.info(f'[PATCHING_WARNING] User cancelled patching due to CSX script exception: {script_name}')
                    return False
                self.patching_logger.info(f'[PATCHING_WARNING] User chose to continue despite CSX script exception: {script_name}')
        return True

    def _handle_ready_data_win(self, base_data_win: str, ready_data_win_files: List[str], mod_dir: Optional[str] = None) -> bool:
        if not ready_data_win_files:
            return True
        for ready_file in ready_data_win_files:
            if self._cancelled:
                return False
            try:
                self.patching_logger.info(f'Applying ready data.win file: {os.path.basename(ready_file)}')
                if not self._combine_two_data_win_files(base_data_win, ready_file, mod_dir):
                    self.patching_logger.error(f'Failed to apply ready data.win file: {ready_file}')
                    return False
                self.patching_logger.info(f'Successfully applied ready data.win file: {os.path.basename(ready_file)}')
            except Exception as e:
                self.patching_logger.error(f'Error merging ready data.win file: {e}')
                return False
        return True

    def _import_asset_type(self, asset_config: Dict[str, Any], data_win_path: str, data_win_dir: str, objects_dir: str, mod_name_for_tracking: str) -> bool:
        script_name = asset_config['script_name']
        has_assets = asset_config.get('has_assets', False)
        check_dir_func = asset_config.get('check_dir_func')
        if check_dir_func:
            has_assets = check_dir_func(objects_dir)
        if not has_assets:
            return True
        import_script = self.utmt_wrapper.get_script_path(script_name)
        if not import_script:
            return True
        step_number = asset_config.get('step_number', '?')
        resource_type = asset_config['resource_type']
        resource_action = asset_config.get('resource_action', 'imported')
        get_resources_func = asset_config.get('get_resources_func')
        analyze_errors = asset_config.get('analyze_errors', False)
        extra_resources_func = asset_config.get('extra_resources_func')
        resource_subdir = asset_config.get('resource_subdir')
        self.patching_logger.info(f'[IMPORT] [{step_number}] Importing {resource_type} from {objects_dir}')
        resource_names = []
        if get_resources_func:
            resource_names = get_resources_func(objects_dir)
        extra_resources = []
        if extra_resources_func:
            extra_resources = extra_resources_func(objects_dir)
            for extra_name in extra_resources:
                if extra_name not in resource_names:
                    resource_names.append(extra_name)
        for resource_name in resource_names:
            self.conflict_tracker.track_mod_history(resource_name, resource_type, mod_name_for_tracking, resource_action)
        input_dir = os.path.join(objects_dir, resource_subdir) if resource_subdir else objects_dir
        returncode, stdout, stderr = self.utmt_wrapper.execute_script(data_win_path, script_name, output_path=data_win_path, cwd=data_win_dir, env={'INPUT_DIR': input_dir})
        if self._cancelled:
            self.patching_logger.info(f'{script_name} was cancelled by user, file may be partially modified')
            return False
        if analyze_errors:
            self.conflict_tracker.analyze_compilation_errors(stdout, stderr, script_name, mod_name_for_tracking)
        if returncode != 0:
            error_msg = stderr[:300] if len(stderr) > 300 else stderr
            self.patching_logger.warning(f'{script_name} failed: {error_msg}')
            if len(stderr) > 500:
                self.patching_logger.error(f'[IMPORT] {script_name} failed: {stderr[:500]}')
        else:
            self.patching_logger.info(f'Successfully imported {resource_type} from Objects directory')
        if mod_name_for_tracking not in ('0', 'vanilla', 'unknown_mod', 'patched_mods'):
            for resource_name in resource_names:
                if resource_name in self.conflict_tracker.resource_modification_history:
                    history = self.conflict_tracker.resource_modification_history[resource_name]
                    if returncode != 0 and history:
                        history[-1]['error'] = error_msg
                    if len(history) > 1:
                        prev_mods = [h['mod'] for h in history[:-1]]
                        self.conflict_tracker.log_conflict(resource_type, resource_name, prev_mods, mod_name_for_tracking)
                        prev_filtered = [m for m in prev_mods if m not in ('0', 'vanilla', 'unknown_mod', 'patched_mods', mod_name_for_tracking)]
                        prev_unique = list(dict.fromkeys(prev_filtered))
                        if prev_unique:
                            history[-1]['conflicts_with'] = prev_unique
        return returncode == 0

    def _import_assets_from_objects_dir(self, data_win_path: str, objects_dir: str, mods_to_apply: Optional[List[Any]] = None, mods_count: int = 0) -> bool:
        try:
            if not os.path.exists(objects_dir):
                self.patching_logger.debug(f'Objects directory does not exist: {objects_dir}')
                return False
            data_win_dir = os.path.dirname(data_win_path)
            expected_objects_dir = os.path.join(data_win_dir, 'Objects')
            if objects_dir != expected_objects_dir:
                if 'DeltahubPatchWorkspace' in data_win_dir:
                    self.patching_logger.debug(f'Creating Objects directory link/copy in temporary folder: {expected_objects_dir}')
                    if os.path.exists(expected_objects_dir):
                        if os.path.islink(expected_objects_dir):
                            os.unlink(expected_objects_dir)
                        else:
                            shutil.rmtree(expected_objects_dir)
                    try:
                        os.symlink(objects_dir, expected_objects_dir)
                        self.patching_logger.debug(f'Created symbolic link: {expected_objects_dir} -> {objects_dir}')
                    except (OSError, AttributeError):
                        shutil.copytree(objects_dir, expected_objects_dir, dirs_exist_ok=True)
                        self.patching_logger.debug(f'Copied Objects directory to temporary location: {expected_objects_dir}')
                    objects_dir = expected_objects_dir
                else:
                    self.patching_logger.warning('Objects directory is not next to data.win and we are not in temporary folder. This may cause import issues.')

            _CONTENT_SUBDIRS = ('CodeEntries', 'Shaders', 'Tilesets', 'Fonts', 'Sounds', 'Rooms', 'AudioGroups', 'Paths', 'Timelines', 'Extensions')
            has = {d: _has_content(objects_dir, d) for d in _CONTENT_SUBDIRS}
            has_graphics = os.path.exists(os.path.join(objects_dir, 'Sprites')) or os.path.exists(os.path.join(objects_dir, 'Backgrounds'))
            if not has_graphics and not any(has.values()):
                self.patching_logger.debug(f'Objects directory has no assets to import: {objects_dir}')
                return True
            mod_name_for_tracking = 'patched_mods'
            logger = self.patching_logger
            asset_configs = [
                {'script_name': 'ImportGeneralInfo', 'has_assets': True, 'step_number': '1/15', 'resource_type': 'generalinfo', 'resource_action': 'imported', 'get_resources_func': _no_res, 'resource_subdir': ''},
                {'script_name': 'ImportAudioGroups', 'has_assets': has['AudioGroups'], 'step_number': '2/15', 'resource_type': 'audiogroup', 'resource_action': 'modified', 'get_resources_func': _json_res('AudioGroups'), 'resource_subdir': 'AudioGroups'},
                {'script_name': 'ImportTextureGroupInfo', 'has_assets': True, 'step_number': '3/15', 'resource_type': 'texturegroup', 'resource_action': 'imported', 'get_resources_func': _no_res, 'resource_subdir': ''},
                {'script_name': 'ImportSprites', 'has_assets': has_graphics, 'step_number': '4/15', 'resource_type': 'sprite', 'resource_action': 'imported', 'get_resources_func': lambda obj_dir: _get_dir_resources(obj_dir, 'Sprites'), 'resource_subdir': 'Sprites'},
                {'script_name': 'ImportBackgrounds', 'has_assets': has_graphics, 'step_number': '5/15', 'resource_type': 'background', 'resource_action': 'imported', 'get_resources_func': lambda obj_dir: _get_dir_resources(obj_dir, 'Backgrounds'), 'resource_subdir': 'Backgrounds'},
                {'script_name': 'ImportFonts', 'has_assets': has['Fonts'], 'step_number': '6/15', 'resource_type': 'font', 'resource_action': 'modified', 'get_resources_func': _get_font_resources, 'resource_subdir': 'Fonts'},
                {'script_name': 'ImportSounds', 'has_assets': has['Sounds'], 'step_number': '7/15', 'resource_type': 'sound', 'resource_action': 'modified', 'get_resources_func': lambda obj_dir: _get_file_resources(obj_dir, 'Sounds', ('.ogg', '.wav')), 'resource_subdir': 'Sounds'},
                {'script_name': 'ImportPaths', 'has_assets': has['Paths'], 'step_number': '8/15', 'resource_type': 'path', 'resource_action': 'modified', 'get_resources_func': _json_res('Paths'), 'resource_subdir': 'Paths'},
                {'script_name': 'ImportTilesets', 'has_assets': has['Tilesets'], 'step_number': '9/15', 'resource_type': 'tileset', 'resource_action': 'imported', 'get_resources_func': lambda obj_dir: _get_file_resources(obj_dir, 'Tilesets', '.json', exclude='config.json'), 'extra_resources_func': _get_tileset_config_resource, 'resource_subdir': 'Tilesets'},
                {'script_name': 'ImportShaders', 'has_assets': has['Shaders'], 'step_number': '10/15', 'resource_type': 'shader', 'resource_action': 'imported', 'get_resources_func': lambda obj_dir: _get_dir_resources(obj_dir, 'Shaders'), 'resource_subdir': 'Shaders'},
                {'script_name': 'ImportTimelines', 'has_assets': has['Timelines'], 'step_number': '11/15', 'resource_type': 'timeline', 'resource_action': 'modified', 'get_resources_func': _json_res('Timelines'), 'resource_subdir': 'Timelines'},
                {'script_name': 'ImportGameObjects', 'has_assets': has_graphics, 'step_number': '12/15', 'resource_type': 'object', 'resource_action': 'imported', 'get_resources_func': lambda obj_dir: _get_dir_resources(obj_dir, 'Sprites'), 'resource_subdir': 'Objects'},
                {'script_name': 'ImportRooms', 'has_assets': has['Rooms'], 'step_number': '13/15', 'resource_type': 'room', 'resource_action': 'modified', 'get_resources_func': _json_res('Rooms'), 'check_dir_func': lambda obj_dir: os.path.exists(os.path.join(obj_dir, 'Rooms')), 'resource_subdir': 'Rooms'},
                {'script_name': 'ImportCodeEntries', 'has_assets': has['CodeEntries'], 'step_number': '14/15', 'resource_type': 'code', 'resource_action': 'modified', 'get_resources_func': lambda obj_dir: _get_gml_resources(obj_dir, logger), 'analyze_errors': True, 'resource_subdir': 'CodeEntries'},
                {'script_name': 'ImportExtensions', 'has_assets': has['Extensions'], 'step_number': '15/15', 'resource_type': 'extension', 'resource_action': 'modified', 'get_resources_func': _json_res('Extensions'), 'resource_subdir': 'Extensions'},
            ]
            for asset_config in asset_configs:
                self._import_asset_type(asset_config, data_win_path, data_win_dir, objects_dir, mod_name_for_tracking)
            if 'DeltahubPatchWorkspace' in data_win_dir:
                packager_dir = os.path.join(data_win_dir, 'Packager')
                if os.path.exists(packager_dir):
                    try:
                        shutil.rmtree(packager_dir, ignore_errors=True)
                        self.patching_logger.debug(f'Cleaned up temporary Packager directory: {packager_dir}')
                    except Exception as e:
                        self.patching_logger.debug(f'Failed to clean up Packager directory (non-critical): {e}')
            return True
        except Exception as e:
            self.patching_logger.error(f'Failed to import assets from Objects directory: {e}', exc_info=True)
            return False

    def get_conflicts_summary(self) -> Dict[str, Any]:
        return self.conflict_tracker.get_conflicts_summary()

    def _combine_subdirectory(self, target_base: str, source_base: str, folder_name: str, resource_type: str, source_mod_name: str, track_history: bool = False) -> None:
        source_dir = os.path.join(source_base, folder_name)
        target_dir = os.path.join(target_base, folder_name)
        if not os.path.exists(source_dir):
            return
        if os.path.exists(target_dir):
            conflicts_logged_this_call: set = set()
            history_added_this_call: set = set()
            for root, dirs, files in os.walk(source_dir):
                rel_path = os.path.relpath(root, source_dir)
                target_path = os.path.join(target_dir, rel_path)
                os.makedirs(target_path, exist_ok=True)
                for file in files:
                    src_file = os.path.join(root, file)
                    dst_file = os.path.join(target_path, file)
                    resource_name = rel_path if rel_path != '.' else os.path.splitext(file)[0]
                    if os.path.exists(dst_file) and track_history:
                        try:
                            is_identical = resource_filter.are_files_semantically_equal(src_file, dst_file, resource_type, logger=self.patching_logger)
                        except Exception:
                            is_identical = False
                        if not is_identical and resource_name not in conflicts_logged_this_call:
                            if resource_name in self.conflict_tracker.resource_modification_history:
                                prev_mods = [h['mod'] for h in self.conflict_tracker.resource_modification_history[resource_name]]
                                self.conflict_tracker.log_conflict(resource_type, resource_name, prev_mods, source_mod_name)
                                conflicts_logged_this_call.add(resource_name)
                    safe_copy(src_file, dst_file)
                    if track_history and resource_name not in history_added_this_call:
                        self.conflict_tracker.track_mod_history(resource_name, resource_type, source_mod_name)
                        history_added_this_call.add(resource_name)
        else:
            shutil.copytree(source_dir, target_dir, dirs_exist_ok=True)

    def _combine_objects_directories(self, target_objects_dir: str, source_objects_dir: str, source_mod_name: str = 'unknown') -> None:
        if not os.path.exists(source_objects_dir):
            return
        try:
            if os.path.abspath(source_objects_dir) == os.path.abspath(target_objects_dir):
                self.patching_logger.debug(f'[PATCH] Skipping combine: source and target are the same directory: {source_objects_dir}')
                return
        except Exception:
            pass
        os.makedirs(target_objects_dir, exist_ok=True)
        subdirs_to_combine = PATCH_SUBDIRS
        for folder_name, resource_type, track_history in subdirs_to_combine:
            self._combine_subdirectory(target_objects_dir, source_objects_dir, folder_name, resource_type, source_mod_name, track_history)
        source_code = os.path.join(source_objects_dir, 'CodeEntries')
        target_code = os.path.join(target_objects_dir, 'CodeEntries')
        if os.path.exists(source_code):
            os.makedirs(target_code, exist_ok=True)
            for file in os.listdir(source_code):
                src_file = os.path.join(source_code, file)
                dst_file = os.path.join(target_code, file)
                if os.path.isfile(src_file):
                    code_name = os.path.splitext(file)[0]
                    if os.path.exists(dst_file) and code_name in self.conflict_tracker.resource_modification_history:
                        prev_mods = [h['mod'] for h in self.conflict_tracker.resource_modification_history[code_name]]
                        self.conflict_tracker.log_conflict('code', code_name, prev_mods, source_mod_name)
                    safe_copy(src_file, dst_file)
                    self.conflict_tracker.track_mod_history(code_name, 'code', source_mod_name)
        source_asset_order = os.path.join(source_objects_dir, 'AssetOrder.txt')
        target_asset_order = os.path.join(target_objects_dir, 'AssetOrder.txt')
        if os.path.exists(source_asset_order):
            safe_copy(source_asset_order, target_asset_order)

    def _combine_two_data_win_files(self, base_file: str, other_file: str, mod_dir: Optional[str] = None) -> bool:
        if not self.temp_patch_dir:
            self.patching_logger.error('Temp patch directory not set')
            return False
        try:
            combine_temp_dir = os.path.join(self.temp_patch_dir, 'combine_temp')
            os.makedirs(combine_temp_dir, exist_ok=True)
            if self._cancelled:
                return False
            mod_number = None
            chapter_str = None
            if mod_dir:
                parts = mod_dir.replace('\\', '/').split('/')
                if 'DeltahubPatchWorkspace' in parts:
                    idx = parts.index('DeltahubPatchWorkspace')
                    if idx + 1 < len(parts):
                        chapter_str = parts[idx + 1]
                    if idx + 2 < len(parts):
                        mod_number_str = parts[idx + 2]
                        try:
                            mod_number = int(mod_number_str)
                        except ValueError:
                            pass
            if mod_number is not None and chapter_str is not None:
                output_dir = os.path.join(self.temp_patch_dir, 'output')
                cache_running_dir = os.path.join(output_dir, 'DeltahubCache', 'running')
                os.makedirs(cache_running_dir, exist_ok=True)
                chapter_file = os.path.join(cache_running_dir, 'chapterNumber.txt')
                mod_file = os.path.join(cache_running_dir, 'modNumbersCache.txt')
                with open(chapter_file, 'w', encoding='utf-8') as f:
                    f.write(chapter_str)
                with open(mod_file, 'w', encoding='utf-8') as f:
                    f.write(str(mod_number))
                self.patching_logger.debug(f'Set mod number cache: chapter={chapter_str}, mod={mod_number} for export from ready data.win')
            export_scripts = self._get_available_scripts('Export')
            if not export_scripts:
                self.patching_logger.error('No export scripts found! At least one export script is required.')
                return False
            export_temp = os.path.join(combine_temp_dir, 'other_export')
            os.makedirs(export_temp, exist_ok=True)
            export_objects_dir = os.path.join(export_temp, 'Objects')
            os.makedirs(export_objects_dir, exist_ok=True)
            all_exports_successful = self._run_export_scripts(export_scripts, other_file, export_objects_dir, self.temp_patch_dir)
            if all_exports_successful:
                if mod_dir:
                    mod_objects_dir = os.path.join(mod_dir, 'Objects')
                    if os.path.exists(mod_objects_dir):
                        self._log_resource_counts(mod_objects_dir, f'[EXPORT] Exported from ready data.win in {mod_objects_dir}')
                    else:
                        self.patching_logger.warning(f'Objects directory not found after export: {mod_objects_dir}')
                    export_objects_dir = os.path.join(export_temp, 'Objects')
                    if os.path.exists(export_objects_dir):
                        if os.path.exists(mod_objects_dir):
                            mod_name_from_dir = os.path.basename(mod_dir) if mod_dir else 'unknown_mod'
                            self._combine_objects_directories(mod_objects_dir, export_objects_dir, mod_name_from_dir)
                        else:
                            shutil.copytree(export_objects_dir, mod_objects_dir)
                        self.patching_logger.info(f'Copied exported objects from export_temp to {mod_objects_dir} for later import')
                all_imports_successful = self._run_import_scripts_from_dir(None, base_file, export_objects_dir, export_temp)
                if all_imports_successful:
                    self.patching_logger.info('Successfully combined two data.win files using UTMTCLI scripts')
                else:
                    self.patching_logger.warning('Some import scripts failed during ready data.win patching, but continuing')
                return True
            self.patching_logger.error('UTMTCLI combine failed: Cannot combine data.win files')
            self.patching_logger.error('Fallback copy would overwrite base_file and lose previous mod changes')
            self.patching_logger.error('This mod cannot be combined and will be skipped to prevent data loss')
            return False
        except Exception as e:
            self.patching_logger.error(f'Failed to combine two data.win files: {e}', exc_info=True)
            self.patching_logger.error('Cannot use fallback copy as it would cause irreversible data loss')
            return False

    def _apply_file_overrides(self, mod_source_dir: str, target_dir: str, used_archive_names: set, is_modpack: bool, chapter_id: Optional[int] = None) -> bool:
        from utils.patching.file_override_utils import apply_file_overrides
        return apply_file_overrides(self, mod_source_dir, target_dir, used_archive_names, is_modpack, chapter_id)

    def _get_available_scripts(self, prefix: str) -> List[str]:
        return [f'{prefix}{t}' for t in SCRIPT_TYPES if self.utmt_wrapper.get_script_path(f'{prefix}{t}')]

    def _select_export_strategy(self, mod_type: Dict[str, bool], mod_asset_types: Dict[str, bool], mod_number: int, has_previous_mod: bool) -> tuple[List[str], Optional[str]]:
        if mod_type.get('has_ready_data_win') and not mod_type.get('has_xdelta_patch') and not mod_type.get('has_csx_scripts'):
            return ([], None)
        _ASSET_KEYS = ('has_code', 'has_textures', 'has_shaders', 'has_tilesets', 'has_fonts', 'has_sounds')
        has_any_assets = any(mod_asset_types.get(k, False) for k in _ASSET_KEYS)
        if has_any_assets or mod_type.get('has_xdelta_patch') or mod_type.get('has_csx_scripts'):
            scripts = self._get_available_scripts('Export')
            if not scripts:
                self.patching_logger.error('No export scripts found! At least one export script is required.')
                return ([], None)
            return (scripts, None)
        return ([], None)

    def _export_mod_assets_optimized(self, mod_data_win: str, mod_number: int, scripts: List[str], comparison_file: Optional[str], vanilla_file: str, patch_root: str, cache_running_dir: str, chapter_str: str) -> bool:
        try:
            mod_dir = os.path.dirname(mod_data_win)
            objects_dir = os.path.join(mod_dir, 'Objects')
            for subdir in ('CodeEntries', 'Sprites', 'Backgrounds'):
                os.makedirs(os.path.join(objects_dir, subdir), exist_ok=True)
            chapter_file = os.path.join(cache_running_dir, 'chapterNumber.txt')
            mod_file = os.path.join(cache_running_dir, 'modNumbersCache.txt')
            with open(chapter_file, 'w', encoding='utf-8') as f:
                f.write(chapter_str)
            with open(mod_file, 'w', encoding='utf-8') as f:
                f.write(str(mod_number))
            if scripts:
                if self._cancelled:
                    return False
                all_exports_successful = self._run_export_scripts(scripts, mod_data_win, objects_dir, patch_root, label=f'Mod {mod_number} ')
                if not all_exports_successful:
                    self.patching_logger.warning(f'Some export scripts failed for mod {mod_number}')
                    warning_msg = tr('dialogs.patching_warning.export_failed', operation=tr('dialogs.patching_warning.export'), resource=f'mod {mod_number}')
                    if not self._show_patching_warning('export_failed', tr('dialogs.patching_warning.title'), warning_msg):
                        self.patching_logger.info(f'[PATCHING_WARNING] User cancelled patching due to export failure for mod {mod_number}')
                        return False
                    self.patching_logger.info(f'[PATCHING_WARNING] User chose to continue despite export failure for mod {mod_number}')
                    return False
                self.patching_logger.info(f'Successfully exported assets from mod {mod_number} using {scripts}')
                if os.path.exists(objects_dir):
                    code_count_exported, sprite_count_exported, _ = self._log_resource_counts(objects_dir, f'[EXPORT] Verified after export for mod {mod_number}')
                    if code_count_exported == 0 and sprite_count_exported == 0:
                        self.patching_logger.warning(f'[EXPORT] WARNING: Export scripts exported 0 resources for mod {mod_number}! This may indicate a problem or mod has no changes.')
                return True
            self.patching_logger.debug(f'Skipping export for mod {mod_number} (no scripts needed)')
            return True
        except Exception as e:
            self.patching_logger.error(f'Failed to export mod assets: {e}', exc_info=True)
            return False

    def _perform_parallel_export(self, mods_to_export: List[Any], mods_to_apply: List[Any], mod_patched_files: Dict[int, str], mod_types: Dict[int, Dict], vanilla_data_win: str, patch_root: str, cache_running_dir: str, chapter_str: str, chapter_id: str, progress_base: int, export_progress: int, progress_callback) -> bool:
        from utils.patching.parallel_export_utils import perform_parallel_export
        return perform_parallel_export(self, mods_to_export, mods_to_apply, mod_patched_files, mod_types, vanilla_data_win, patch_root, cache_running_dir, chapter_str, chapter_id, progress_base, export_progress, progress_callback)

    def _perform_parallel_filtering(self, vanilla_hashes: Dict[str, Dict[str, str]], mods_dirs_info: List[tuple], progress_base: int, filter_progress: int, progress_callback) -> Dict[int, Optional[str]]:
        from utils.patching.parallel_export_utils import perform_parallel_filtering
        return perform_parallel_filtering(self, vanilla_hashes, mods_dirs_info, progress_base, filter_progress, progress_callback)

    def _get_mod_source_dir(self, mod_data: Any, chapter_id: str) -> Optional[str]:
        from utils.patching.mod_resolve_utils import get_mod_source_dir
        return get_mod_source_dir(mod_data, chapter_id, self.mod_service, self.app_state, self.patching_logger)

    def _get_target_dir(self, chapter_id: str, game: Optional[str] = None) -> Optional[str]:
        from utils.patching.mod_resolve_utils import get_target_dir
        return get_target_dir(chapter_id, self.app_state, self.patching_logger, game=game)

    def _apply_xdelta_to_file(self, target_file: str, patch_path: str) -> bool:
        from utils.patching.xdelta_utils import apply_xdelta_to_file
        return apply_xdelta_to_file(self, target_file, patch_path)

    def cleanup_processes_and_temp_files(self) -> None:
        processes_to_cleanup = list(self._active_processes)
        for process in processes_to_cleanup:
            try:
                if process.poll() is None:
                    ptype = 'UTMTCLI' if 'UndertaleModCli' in str(process.args) or 'dotnet' in str(process.args) else 'xdelta'
                    self.patching_logger.warning(f'Terminating active {ptype} process (PID: {process.pid})')
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        self.patching_logger.warning(f'Force killing {ptype} process (PID: {process.pid})')
                        process.kill()
                        process.wait()
            except (OSError, Exception) as e:
                self.patching_logger.debug(f'Error terminating process: {e}')
        self._active_processes.clear()
        for temp_file in list(self._temp_files_to_cleanup):
            try:
                if os.path.exists(temp_file):
                    safe_remove(temp_file)
                    self.patching_logger.debug(f'Cleaned up temp file: {temp_file}')
            except Exception as e:
                self.patching_logger.debug(f'Error cleaning up temp file {temp_file}: {e}')
        self._temp_files_to_cleanup.clear()

    def cleanup(self, force: bool = False) -> None:
        self.cleanup_processes_and_temp_files()
        keep_backups = bool(self.backup_service and self.backup_service.original_files)
        self._cleanup_temp_dir(keep_backups=keep_backups)

    def restore_all_backups(self) -> bool:
        if self.backup_service:
            return self.backup_service.restore_all_backups()
        if self._session_manifest_path and os.path.exists(self._session_manifest_path):
            from utils.patching.session_restore_utils import restore_backups_from_manifest
            return restore_backups_from_manifest(
                self._session_manifest_path, self.temp_patch_dir,
                self._cleanup_temp_dir, self.patching_logger)
        self.patching_logger.debug('No backup files found to restore')
        return False
