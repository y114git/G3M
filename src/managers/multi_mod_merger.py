import os
import shutil
import tempfile
import subprocess
import time
import re
from typing import Dict, List, Optional, Any
from PyQt6.QtCore import QObject, pyqtSignal
from managers.utmtcli_manager import UTMTCLIManager
from managers.backup_manager import BackupManager
from managers.utmt_wrapper import UtmtWrapper
from utils.path_utils import get_xdelta_path, find_chapter_resource_dir
from utils.file_utils import ensure_writable, sanitize_filename, safe_remove, safe_move, safe_rmtree
from config.constants import DATA_WIN_FILENAME
from managers.localization_manager import tr
from utils.mod_utils import get_mod_key, get_mod_name
from utils.patching_logger import get_patching_logger, get_conflicts_logger, clear_patching_logs


class MultiModMerger(QObject):
    status_update = pyqtSignal(str, str)
    progress_update = pyqtSignal(int, str)
    _session_manifest_path: Optional[str] = None

    def __init__(self, app_state, mod_manager, parent=None):
        super().__init__(parent)
        self.patching_logger = get_patching_logger()
        self.conflicts_logger = get_conflicts_logger()
        self.detected_conflicts: List[Dict[str, Any]] = []
        self._mod_exported_code_files: Dict[int, set] = {}
        self.app_state = app_state
        self.mod_manager = mod_manager
        self.utmt_wrapper = UtmtWrapper(patching_logger=self.patching_logger)
        self.xdelta_path = get_xdelta_path()
        self.patching_logger.info(f'[MultiModMerger.__init__] xdelta_path initialized: {self.xdelta_path}')
        if self.xdelta_path:
            import platform
            if platform.system() != 'Windows':
                import stat
                if os.path.exists(self.xdelta_path):
                    file_stat = os.stat(self.xdelta_path)
                    is_executable = bool(file_stat.st_mode & stat.S_IEXEC)
                    self.patching_logger.info(f'[MultiModMerger.__init__] xdelta permissions: {oct(file_stat.st_mode)} (executable: {is_executable})')
        self.temp_merge_dir = None
        self.backup_manager: Optional[BackupManager] = None
        self._cancelled = False
        self.resource_modification_history: Dict[str, List[Dict[str, Any]]] = {}

    def process_mod_merge(self, chapter_mods: Dict[int, List[Any]], is_modpack: bool, modpack_dir: Optional[str] = None) -> bool:
        clear_logs_enabled = self.app_state.local_config.get('clear_logs_on_startup', False)
        if clear_logs_enabled:
            clear_patching_logs()
        self.patching_logger = get_patching_logger()
        self.conflicts_logger = get_conflicts_logger()
        self.detected_conflicts = []
        if is_modpack:
            self.patching_logger.info(f'Starting modpack creation for {len(chapter_mods)} chapter(s)')
        else:
            self.patching_logger.info(f'Starting multi-mod merge for {len(chapter_mods)} chapter(s)')
        for chapter_id, mods_list in chapter_mods.items():
            mod_names = [getattr(m, 'name', 'Unknown') for m in mods_list]
            self.patching_logger.info(f'Chapter {chapter_id}: {len(mods_list)} mod(s) - {mod_names}')
        if not self.utmt_wrapper.is_available():
            self.patching_logger.error(f'UTMTCLI not available for platform: {self.utmt_wrapper.get_platform()}')
            self.status_update.emit(tr('errors.utmtcli_not_available', platform=self.utmt_wrapper.get_platform()), 'error')
            return False
        if is_modpack:
            self.patching_logger.info('UTMTCLI is available, proceeding with modpack creation')
        else:
            self.patching_logger.info('UTMTCLI is available, proceeding with merge')
        try:
            if is_modpack and modpack_dir:
                os.makedirs(modpack_dir, exist_ok=True)
            total_chapters = len([c for c in chapter_mods.values() if c])
            total_mods = sum((len(mods_list) for mods_list in chapter_mods.values()))
            current_progress = 0
            try:
                if is_modpack:
                    merge_msg = tr('status.preparing_mod_merge', chapters=total_chapters, mods=total_mods)
                else:
                    merge_msg = tr('status.preparing_mod_merge', chapters=total_chapters, mods=total_mods)
            except BaseException:
                if is_modpack:
                    merge_msg = f'Preparing to create modpack with {total_mods} mod(s) for {total_chapters} chapter(s)...'
                else:
                    merge_msg = f'Preparing to merge {total_mods} mod(s) for {total_chapters} chapter(s)...'
            self.progress_update.emit(0, merge_msg)
            temp_merge_dir_created = False
            try:
                if is_modpack:
                    self.temp_merge_dir = tempfile.mkdtemp(prefix='deltahub_modpack_')
                else:
                    self.temp_merge_dir = tempfile.mkdtemp(prefix='deltahub_multimod_')
                temp_merge_dir_created = True
                backup_dir = os.path.join(self.temp_merge_dir, 'backups')
                self.backup_manager = BackupManager(backup_dir, patching_logger=self.patching_logger)
                self.patching_logger.info(f'Created temp merge directory: {self.temp_merge_dir}')
                current_progress += 5
            except Exception as e:
                self.patching_logger.error(f'Failed to create temp merge directory: {e}', exc_info=True)
                self.status_update.emit(tr('errors.temp_dir_creation_failed'), 'error')
                return False
            try:
                if is_modpack:
                    merge_msg = tr('status.merging_mods', progress=current_progress)
                else:
                    merge_msg = tr('status.merging_mods', progress=current_progress)
            except BaseException:
                if is_modpack:
                    merge_msg = f'Creating modpack... {current_progress}%'
                else:
                    merge_msg = f'Merging mods... {current_progress}%'
            self.progress_update.emit(min(current_progress, 95), merge_msg)
            chapter_index = 0
            for chapter_id, mods_list in chapter_mods.items():
                if not mods_list:
                    continue
                if is_modpack and chapter_id == -1:
                    continue
                if self._cancelled:
                    if not is_modpack:
                        for cid in chapter_mods.keys():
                            self.backup_manager.restore_backups(cid)
                    return False
                chapter_index += 1
                chapter_progress_base = (chapter_index - 1) * (100 // total_chapters) if total_chapters > 0 else 0
                self.patching_logger.info(f'Processing chapter {chapter_id} with {len(mods_list)} mod(s)')
                try:
                    chapter_msg = tr('status.merging_chapter', chapter=chapter_id, current=chapter_index, total=total_chapters)
                except BaseException:
                    if is_modpack:
                        chapter_msg = f'Processing chapter {chapter_id} ({chapter_index}/{total_chapters})...'
                    else:
                        chapter_msg = f'Merging chapter {chapter_id} ({chapter_index}/{total_chapters})...'
                self.progress_update.emit(min(chapter_progress_base + 5, 95), chapter_msg)
                if is_modpack and modpack_dir:
                    chapter_folder_name = {-1: 'demo', 0: 'chapter_0'}.get(chapter_id, f'chapter_{chapter_id}')
                    chapter_modpack_dir = os.path.join(modpack_dir, chapter_folder_name)
                    target_dir = self._get_target_dir(chapter_id)
                    if not target_dir:
                        self.patching_logger.warning(f'Target directory not found for chapter {chapter_id}, skipping mods for this chapter in modpack')
                        continue
                    if not self._merge_mods_for_chapter_to_dir(chapter_id, mods_list, chapter_modpack_dir, chapter_progress_base, total_chapters):
                        self.patching_logger.error(f'Failed to merge mods for chapter {chapter_id} in modpack')
                        try:
                            failed_msg = tr('status.merge_failed')
                        except BaseException:
                            failed_msg = 'Modpack creation failed'
                        self.progress_update.emit(0, failed_msg)
                        return False
                elif not self._merge_mods_for_chapter(chapter_id, mods_list, chapter_progress_base, total_chapters):
                    target_dir = self._get_target_dir(chapter_id)
                    if not target_dir:
                        self.patching_logger.warning(f'Target directory not found for chapter {chapter_id}, skipping mods for this chapter. The game may not have this chapter installed.')
                        continue
                    self.patching_logger.error(f'Failed to merge mods for chapter {chapter_id}, restoring backups')
                    if self.backup_manager:
                        self.backup_manager.restore_backups(chapter_id)
                    try:
                        failed_msg = tr('status.merge_failed')
                    except BaseException:
                        failed_msg = 'Mod merge failed'
                    self.progress_update.emit(0, failed_msg)
                    return False
                chapter_progress = chapter_index * (100 // total_chapters) if total_chapters > 0 else 100
                try:
                    merged_msg = tr('status.chapter_merged', chapter=chapter_id)
                except BaseException:
                    if is_modpack:
                        merged_msg = f'Chapter {chapter_id} processed successfully'
                    else:
                        merged_msg = f'Chapter {chapter_id} merged successfully'
                self.progress_update.emit(min(chapter_progress, 95), merged_msg)
                if is_modpack:
                    self.patching_logger.info(f'Successfully processed mods for chapter {chapter_id}')
                else:
                    self.patching_logger.info(f'Successfully merged mods for chapter {chapter_id}')
            try:
                completed_msg = tr('status.merge_completed')
            except BaseException:
                if is_modpack:
                    completed_msg = 'Modpack creation completed successfully'
                else:
                    completed_msg = 'Mod merge completed successfully'
            self.progress_update.emit(100, completed_msg)
            if is_modpack:
                self.patching_logger.info('Modpack creation completed successfully')
                if self.temp_merge_dir and os.path.exists(self.temp_merge_dir):
                    if safe_rmtree(self.temp_merge_dir):
                        self.patching_logger.info(f'Cleaned up temp merge directory for modpack: {self.temp_merge_dir}')
                    else:
                        self.patching_logger.warning(f'Failed to cleanup temp merge dir for modpack {self.temp_merge_dir}')
                self.temp_merge_dir = None
            else:
                self.patching_logger.info('Multi-mod merge completed successfully')
                if self.temp_merge_dir and os.path.exists(self.temp_merge_dir):
                    try:
                        for item in os.listdir(self.temp_merge_dir):
                            item_path = os.path.join(self.temp_merge_dir, item)
                            if item != 'backups':
                                if os.path.isdir(item_path):
                                    if safe_rmtree(item_path):
                                        self.patching_logger.debug(f'Removed temp directory: {item_path}')
                                    else:
                                        self.patching_logger.warning(f'Failed to remove temp directory {item_path}')
                                elif safe_remove(item_path):
                                    self.patching_logger.debug(f'Removed temp file: {item_path}')
                                else:
                                    self.patching_logger.warning(f'Failed to remove temp file {item_path}')
                        self.patching_logger.info(f'Cleaned up temp files from merge directory, kept backups: {self.temp_merge_dir}')
                    except Exception as e:
                        self.patching_logger.warning(f'Failed to cleanup temp files from merge dir {self.temp_merge_dir}: {e}')
            return True
        except Exception as e:
            if is_modpack:
                self.patching_logger.error(f'Modpack creation failed: {e}', exc_info=True)
            else:
                self.patching_logger.error(f'Multi-mod merge failed: {e}', exc_info=True)
            self.status_update.emit(tr('errors.merge_failed', error=str(e)), 'error')
            if not is_modpack:
                for chapter_id in chapter_mods.keys():
                    if self.backup_manager:
                        self.backup_manager.restore_backups(chapter_id)
            return False
        finally:
            if hasattr(self, 'temp_merge_dir') and self.temp_merge_dir and os.path.exists(self.temp_merge_dir):
                if is_modpack:
                    if not safe_rmtree(self.temp_merge_dir):
                        self.patching_logger.warning(f'Failed to cleanup temp merge dir in finally block: {self.temp_merge_dir}')
                    self.temp_merge_dir = None

    def _merge_mods_for_chapter(self, chapter_id: int, mods_list: List[Any], progress_base: int = 0, total_chapters: int = 1) -> bool:
        self.patching_logger.debug(f'_merge_mods_for_chapter: chapter_id={chapter_id}, mods_count={len(mods_list)}')
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
        data_win_path = self._find_data_win(target_dir)
        if not data_win_path:
            return self._apply_file_overrides_only(chapter_id, mods_list, target_dir)
        if not self.backup_manager.backup_file(chapter_id, data_win_path):
            return False
        return self._perform_chapter_merge(chapter_id, mods_list, data_win_path, target_dir, None, progress_base, total_chapters, is_modpack=False)

    def _perform_chapter_merge(self, chapter_id: int, mods_list: List[Any], output_data_win_path: str, target_dir: str, modpack_dir: Optional[str], progress_base: int, total_chapters: int, is_modpack: bool) -> bool:
        import platform
        original_data_win = output_data_win_path
        chapter_progress_range = 100 // total_chapters if total_chapters > 0 else 100
        xdelta_progress = chapter_progress_range * 0.3
        export_progress = chapter_progress_range * 0.3
        import_progress = chapter_progress_range * 0.4
        merge_root = self.temp_merge_dir
        if not merge_root:
            self.patching_logger.error('Temp merge directory not set')
            return False
        output_dir = os.path.join(merge_root, 'output')
        os.makedirs(output_dir, exist_ok=True)
        cache_running_dir = os.path.join(output_dir, 'Cache', 'running')
        os.makedirs(cache_running_dir, exist_ok=True)
        chapter_str = str(chapter_id)
        xdelta_combiner_dir = os.path.join(output_dir, 'xDeltaCombiner', chapter_str)
        vanilla_dir = os.path.join(xdelta_combiner_dir, '0')
        os.makedirs(vanilla_dir, exist_ok=True)
        original_filename = os.path.basename(original_data_win)
        vanilla_data_win = os.path.join(vanilla_dir, original_filename)
        shutil.copy2(original_data_win, vanilla_data_win)
        self.patching_logger.info(f'Created vanilla copy at {vanilla_data_win} (from {original_data_win})')
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
        existing_assets = {'sprites': {}, 'backgrounds': {}, 'rooms': {}, 'tilesets': {}, 'shaders': {}}
        if not is_modpack and mods_count == 1:
            mod_data = mods_to_apply[0]
            mod_name = getattr(mod_data, 'name', 'Unknown')
            mod_source_dir = self._get_mod_source_dir(mod_data, chapter_id)
            if mod_source_dir:
                ready_data_win_files = self._find_ready_data_win_files(mod_source_dir)
                data_patches = self._find_data_patches(mod_source_dir)
                csx_scripts = self._find_csx_scripts(mod_source_dir)
                if ready_data_win_files and (not data_patches) and (not csx_scripts):
                    self.patching_logger.info(f'[SINGLE_MOD] Single mod {mod_name} with only ready data.win/game.ios - copying directly')
                    ready_file = ready_data_win_files[0]
                    self.patching_logger.info(f'[SINGLE_MOD] Copying ready file: {ready_file} -> {output_data_win_path} (chapter {chapter_id})')
                    try:
                        extracted_chapter_id = self._extract_chapter_id_from_path(target_dir)
                        if extracted_chapter_id is not None:
                            self.patching_logger.info(f'[SINGLE_MOD] Creating backup before replacing data.win (chapter {extracted_chapter_id})')
                            if not self.backup_manager.backup_file(extracted_chapter_id, output_data_win_path):
                                self.patching_logger.error(f'[SINGLE_MOD] Failed to create backup of {output_data_win_path} before replacement')
                                if not is_modpack:
                                    self.backup_manager.restore_backups(chapter_id)
                                return False
                        else:
                            self.patching_logger.warning(f'[SINGLE_MOD] Could not extract chapter ID from path {target_dir}, backup may not work correctly')
                        shutil.copy2(ready_file, output_data_win_path)
                        file_size = os.path.getsize(output_data_win_path) if os.path.exists(output_data_win_path) else 0
                        self.patching_logger.info(f'[SINGLE_MOD] Successfully copied ready data.win/game.ios from {mod_name} to {output_data_win_path} (size: {file_size} bytes, chapter {chapter_id})')
                        used_archive_names = set()
                        if not self._apply_file_overrides(mod_source_dir, target_dir, used_archive_names, False):
                            self.patching_logger.warning(f'[SINGLE_MOD] Failed to apply file overrides from {mod_name}')
                        return True
                    except Exception as e:
                        self.patching_logger.error(f'[SINGLE_MOD] Failed to copy ready data.win file from {mod_name}: {e}', exc_info=True)
                        if not is_modpack:
                            self.backup_manager.restore_backups(chapter_id)
                        return False
                if data_patches and (not ready_data_win_files) and (not csx_scripts):
                    self.patching_logger.info(f'Single mod {mod_name} with only xdelta patch(es) - applying directly')
                    try:
                        if os.path.exists(output_data_win_path):
                            extracted_chapter_id = self._extract_chapter_id_from_path(target_dir)
                            if extracted_chapter_id is not None:
                                self.backup_manager.backup_file(extracted_chapter_id, output_data_win_path)
                        if not self._apply_xdelta_patches(output_data_win_path, data_patches, progress_callback=lambda p: self.progress_update.emit(min(int(p * 50), 95), f'Applying patch from {mod_name}...')):
                            self.patching_logger.error(f'Failed to apply xdelta patches from {mod_name}')
                            if not is_modpack:
                                self.backup_manager.restore_backups(chapter_id)
                            return False
                        self.patching_logger.info(f'Successfully applied xdelta patches from {mod_name} to {output_data_win_path}')
                        used_archive_names = set()
                        if not self._apply_file_overrides(mod_source_dir, target_dir, used_archive_names, False):
                            self.patching_logger.warning(f'Failed to apply file overrides from {mod_name}')
                        return True
                    except Exception as e:
                        self.patching_logger.error(f'Failed to apply xdelta patches: {e}', exc_info=True)
                        if not is_modpack:
                            self.backup_manager.restore_backups(chapter_id)
                        return False
                if csx_scripts and (not ready_data_win_files) and (not data_patches):
                    self.patching_logger.info(f'Single mod {mod_name} with only CSX script(s) - executing directly')
                    try:
                        if os.path.exists(output_data_win_path):
                            extracted_chapter_id = self._extract_chapter_id_from_path(target_dir)
                            if extracted_chapter_id is not None:
                                self.backup_manager.backup_file(extracted_chapter_id, output_data_win_path)
                        if not self._apply_csx_scripts(output_data_win_path, csx_scripts):
                            self.patching_logger.error(f'Failed to execute CSX scripts from {mod_name}')
                            if not is_modpack:
                                self.backup_manager.restore_backups(chapter_id)
                            return False
                        self.patching_logger.info(f'Successfully executed CSX scripts from {mod_name} on {output_data_win_path}')
                        used_archive_names = set()
                        if not self._apply_file_overrides(mod_source_dir, target_dir, used_archive_names, False):
                            self.patching_logger.warning(f'Failed to apply file overrides from {mod_name}')
                        return True
                    except Exception as e:
                        self.patching_logger.error(f'Failed to execute CSX scripts: {e}', exc_info=True)
                        if not is_modpack:
                            self.backup_manager.restore_backups(chapter_id)
                        return False
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
            try:
                xdelta_msg = tr('status.applying_xdelta', mod=mod_name, current=idx + 1, total=mods_count)
            except BaseException:
                xdelta_msg = f'Applying mod {mod_name} ({idx + 1}/{mods_count})...'
            self.progress_update.emit(min(mod_progress_start, 95), xdelta_msg)
            mod_source_dir = self._get_mod_source_dir(mod_data, chapter_id)
            if not mod_source_dir:
                self.patching_logger.warning(f'Mod source directory not found for {mod_name}, skipping')
                continue
            mod_type = self._detect_mod_type(mod_source_dir)
            mod_types[mod_number] = mod_type
            mod_dir = os.path.join(xdelta_combiner_dir, str(mod_number))
            os.makedirs(mod_dir, exist_ok=True)
            original_filename = os.path.basename(original_data_win)
            mod_data_win = os.path.join(mod_dir, original_filename)
            shutil.copy2(original_data_win, mod_data_win)
            ready_data_win_files = self._find_ready_data_win_files(mod_source_dir)
            data_patches = self._find_data_patches(mod_source_dir)
            csx_scripts = self._find_csx_scripts(mod_source_dir)
            if ready_data_win_files:
                self.patching_logger.info(f'Found {len(ready_data_win_files)} ready data.win/game.ios file(s) from {mod_name} (mod {mod_number}), merging')
                patch_progress = mod_progress_start + int(mod_progress_range * 0.5)
                self.progress_update.emit(min(patch_progress, 95), f'Merging ready data.win from {mod_name}...')
                if not self._handle_ready_data_win(mod_data_win, ready_data_win_files, mod_dir):
                    self.patching_logger.error(f'Failed to merge ready data.win files from {mod_name}')
                    if not is_modpack and self.backup_manager:
                        self.backup_manager.restore_backups(chapter_id)
                    return False
                self.patching_logger.info(f'Successfully merged ready data.win files from {mod_name} (mod {mod_number})')
                target_dir_result = self._get_target_dir(chapter_id)
                if target_dir_result is not None and mod_source_dir:
                    used_archive_names = set()
                    if not self._apply_file_overrides(mod_source_dir, target_dir_result, used_archive_names, False):
                        self.patching_logger.warning(f'Failed to apply file overrides from {mod_name} after ready data.win merge')
                if not data_patches and (not csx_scripts):
                    mods_already_exported.add(mod_number)
                    self.patching_logger.info(f'Mod {mod_name} (number {mod_number}) has only ready data.win, will skip SmartExport')
                mod_patched_files[mod_number] = mod_data_win
            if data_patches:
                self.patching_logger.info(f'Found {len(data_patches)} data patch(es) from {mod_name} (mod {mod_number}), applying to original')
                patch_progress = mod_progress_start + int(mod_progress_range * 0.3)
                self.progress_update.emit(min(patch_progress, 95), f'Applying patches from {mod_name}...')
                if not self._apply_xdelta_patches(mod_data_win, data_patches, progress_callback=lambda p: self.progress_update.emit(min(mod_progress_start + int(mod_progress_range * (0.3 + p * 0.4)), 95), f'Applying patches from {mod_name}...')):
                    self.patching_logger.error(f'[MERGE] Failed to apply data patches from {mod_name} (mod {mod_number}). This may be due to incompatibility with previously applied mods. The patch may have been created for the original data.win, but the file has already been modified.')
                    if not is_modpack and self.backup_manager:
                        self.backup_manager.restore_backups(chapter_id)
                    return False
                self.patching_logger.info(f'Successfully applied data patches from {mod_name} (mod {mod_number})')
                mod_patched_files[mod_number] = mod_data_win
            if csx_scripts:
                self.patching_logger.info(f'Found {len(csx_scripts)} CSX script(s) from {mod_name} (mod {mod_number}), executing')
                script_progress = mod_progress_start + int(mod_progress_range * 0.7)
                self.progress_update.emit(min(script_progress, 95), f'Executing scripts from {mod_name}...')
                if not self._apply_csx_scripts(mod_data_win, csx_scripts):
                    self.patching_logger.error(f'Failed to execute CSX scripts from {mod_name}')
                    if not is_modpack and self.backup_manager:
                        self.backup_manager.restore_backups(chapter_id)
                    return False
                self.patching_logger.info(f'Successfully executed CSX scripts from {mod_name} (mod {mod_number})')
                mod_patched_files[mod_number] = mod_data_win
            if not ready_data_win_files and (not data_patches) and (not csx_scripts):
                target_dir_result = self._get_target_dir(chapter_id)
                if target_dir_result is not None and mod_source_dir:
                    used_archive_names = set()
                    if self._apply_file_overrides(mod_source_dir, target_dir_result, used_archive_names, False):
                        self.patching_logger.info(f'Applied file overrides from {mod_name} (mod {mod_number})')
            if mod_number not in mod_patched_files:
                mod_patched_files[mod_number] = mod_data_win
            self.progress_update.emit(min(mod_progress_end, 95), f'Completed {mod_name}')
        mods_to_export = [m for i, m in enumerate(mods_to_apply) if i + 1 not in mods_already_exported]
        highest_priority_mod_exported_files = set()
        for idx, mod_data in enumerate(mods_to_export):
            if self._cancelled:
                return False
            mod_name = getattr(mod_data, 'name', 'Unknown')
            original_idx = mods_to_apply.index(mod_data)
            mod_number = original_idx + 1
            export_step = idx / len(mods_to_export) * export_progress if mods_to_export else 0
            current_progress = progress_base + int(xdelta_progress + export_step)
            try:
                export_msg = tr('status.exporting_assets', mod=mod_name, current=idx + 1, total=len(mods_to_export))
            except BaseException:
                export_msg = f'Exporting assets from {mod_name} ({idx + 1}/{len(mods_to_export)})...'
            self.progress_update.emit(min(current_progress, 95), export_msg)
            mod_data_win = mod_patched_files.get(mod_number)
            if not mod_data_win or not os.path.exists(mod_data_win):
                continue
            mod_dir = os.path.dirname(mod_data_win)
            mod_asset_types = self._detect_mod_asset_types(mod_dir)
            mod_type = mod_types.get(mod_number, {})
            has_previous_mod = mod_number > 1 and mod_number - 1 in mod_patched_files
            scripts, comparison_file = self._select_export_strategy(mod_type, mod_asset_types, mod_number, has_previous_mod)
            if not scripts and comparison_file is None:
                self.patching_logger.info(f'Skipping export for mod {mod_number} ({mod_name}) - already exported')
                continue
            self.patching_logger.info(f'Exporting assets from mod {mod_number} ({mod_name}) using strategy: {scripts}, comparison: {comparison_file}')
            if not self._export_mod_assets_optimized(mod_data_win, mod_number, scripts, comparison_file, vanilla_data_win, merge_root, cache_running_dir, chapter_str):
                self.patching_logger.warning(f'Failed to export assets from mod {mod_number} ({mod_name})')
            else:
                objects_dir = os.path.join(mod_dir, 'Objects')
                if os.path.exists(objects_dir):
                    code_entries_dir = os.path.join(objects_dir, 'CodeEntries')
                    sprites_dir = os.path.join(objects_dir, 'Sprites')
                    rooms_dir = os.path.join(objects_dir, 'Rooms')
                    shaders_dir = os.path.join(objects_dir, 'Shaders')
                    code_count = len([f for f in os.listdir(code_entries_dir) if f.endswith('.gml')]) if os.path.exists(code_entries_dir) else 0
                    sprite_count = len([d for d in os.listdir(sprites_dir) if os.path.isdir(os.path.join(sprites_dir, d))]) if os.path.exists(sprites_dir) else 0
                    room_count = len([f for f in os.listdir(rooms_dir) if f.endswith('.json')]) if os.path.exists(rooms_dir) else 0
                    shader_count = len([d for d in os.listdir(shaders_dir) if os.path.isdir(os.path.join(shaders_dir, d))]) if os.path.exists(shaders_dir) else 0
                    self.patching_logger.info(f'[EXPORT] Mod {mod_number} ({mod_name}) exported: {code_count} code, {sprite_count} sprites, {room_count} rooms, {shader_count} shaders')
                    if os.path.exists(code_entries_dir):
                        mod_exported_code = set()
                        for code_file in os.listdir(code_entries_dir):
                            if code_file.endswith('.gml'):
                                code_name = os.path.splitext(code_file)[0]
                                mod_exported_code.add(code_name)
                        self._mod_exported_code_files[mod_number] = mod_exported_code
                        self.patching_logger.debug(f'[EXPORT] Tracked {len(mod_exported_code)} code files exported by mod {mod_number} ({mod_name})')
                    if os.path.exists(sprites_dir):
                        ramb_sprites = [d for d in os.listdir(sprites_dir) if 'ramb' in d.lower()]
                        if ramb_sprites:
                            self.patching_logger.debug(f'[EXPORT] Found ramb sprites: {ramb_sprites}')
                    if os.path.exists(code_entries_dir):
                        ramb_code = [f for f in os.listdir(code_entries_dir) if 'ramb' in f.lower()]
                        if ramb_code:
                            self.patching_logger.debug(f'[EXPORT] Found ramb code: {ramb_code}')
                mod_source_dir = self._get_mod_source_dir(mod_data, chapter_id)
                if mod_source_dir:
                    objects_dir = os.path.join(mod_dir, 'Objects')
                    code_entries_dir = os.path.join(objects_dir, 'CodeEntries')
                    if os.path.exists(code_entries_dir):
                        for code_file in os.listdir(code_entries_dir):
                            if code_file.endswith('.gml'):
                                code_name = os.path.splitext(code_file)[0]
                                if code_name not in existing_code_files:
                                    existing_code_files[code_name] = mod_name
                    sprites_dir = os.path.join(objects_dir, 'Sprites')
                    if os.path.exists(sprites_dir):
                        for sprite_name in os.listdir(sprites_dir):
                            if os.path.isdir(os.path.join(sprites_dir, sprite_name)):
                                if sprite_name not in existing_assets['sprites']:
                                    existing_assets['sprites'][sprite_name] = mod_name
                    backgrounds_dir = os.path.join(objects_dir, 'Backgrounds')
                    if os.path.exists(backgrounds_dir):
                        for bg_file in os.listdir(backgrounds_dir):
                            if bg_file.endswith('.png'):
                                bg_name = os.path.splitext(bg_file)[0]
                                if bg_name not in existing_assets['backgrounds']:
                                    existing_assets['backgrounds'][bg_name] = mod_name
                    rooms_dir = os.path.join(objects_dir, 'Rooms')
                    if os.path.exists(rooms_dir):
                        for room_file in os.listdir(rooms_dir):
                            if room_file.endswith('.json'):
                                room_name = os.path.splitext(room_file)[0]
                                if room_name not in existing_assets['rooms']:
                                    existing_assets['rooms'][room_name] = mod_name
                    tilesets_dir = os.path.join(objects_dir, 'Tilesets')
                    if os.path.exists(tilesets_dir):
                        for tileset_file in os.listdir(tilesets_dir):
                            if tileset_file.endswith('.json'):
                                tileset_name = os.path.splitext(tileset_file)[0]
                                if tileset_name not in existing_assets['tilesets']:
                                    existing_assets['tilesets'][tileset_name] = mod_name
                    shaders_dir = os.path.join(objects_dir, 'Shaders')
                    if os.path.exists(shaders_dir):
                        for shader_name in os.listdir(shaders_dir):
                            if os.path.isdir(os.path.join(shaders_dir, shader_name)):
                                if shader_name not in existing_assets['shaders']:
                                    existing_assets['shaders'][shader_name] = mod_name
                    code_conflicts = self.detect_code_conflicts(mod_source_dir, mod_name, existing_code_files)
                    asset_conflicts = self.detect_asset_conflicts(mod_source_dir, mod_name, existing_assets)
                    if code_conflicts or any(asset_conflicts.values()):
                        self.patching_logger.warning(f'[CONFLICTS] Mod {mod_name} has conflicts: {len(code_conflicts)} code, {sum((len(v) for v in asset_conflicts.values()))} assets')
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
            shutil.copy2(original_data_win, base_data_win)
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
        base_mod_dir = os.path.join(xdelta_combiner_dir, str(base_mod_number))
        base_objects_dir = os.path.join(base_mod_dir, 'Objects')
        objects_dirs_to_import.sort(key=lambda x: x[1])
        self.patching_logger.info(f'Merge order (by priority): {[(m[1], m[2]) for m in objects_dirs_to_import]}')
        data_win_dir = os.path.dirname(base_data_win)
        expected_objects_dir = os.path.join(data_win_dir, 'Objects')
        for idx, (mod_number, mod_priority, mod_name, objects_dir) in enumerate(objects_dirs_to_import):
            if self._cancelled:
                if not is_modpack and self.backup_manager:
                    self.backup_manager.restore_backups(chapter_id)
                return False
            merge_step = idx / len(objects_dirs_to_import) * (import_progress * 0.5) if objects_dirs_to_import else 0
            current_progress = progress_base + int(xdelta_progress + export_progress + merge_step)
            try:
                merge_msg = tr('status.merging_assets', mod=mod_name, current=idx + 1, total=len(objects_dirs_to_import))
            except BaseException:
                merge_msg = f'Merging assets from {mod_name} ({idx + 1}/{len(objects_dirs_to_import)})...'
            self.progress_update.emit(min(current_progress, 90), merge_msg)
            self.patching_logger.info(f'Merging Objects from mod {mod_number} ({mod_name}, priority {mod_priority}) into Objects directory (step {idx + 1}/{len(objects_dirs_to_import)})')
            code_entries_dir = os.path.join(objects_dir, 'CodeEntries')
            sprites_dir = os.path.join(objects_dir, 'Sprites')
            code_count = len([f for f in os.listdir(code_entries_dir) if f.endswith('.gml')]) if os.path.exists(code_entries_dir) else 0
            sprite_count = len([d for d in os.listdir(sprites_dir) if os.path.isdir(os.path.join(sprites_dir, d))]) if os.path.exists(sprites_dir) else 0
            self.patching_logger.debug(f'[MERGE] Mod {mod_number} ({mod_name}) has {code_count} code files, {sprite_count} sprites to merge')
            if os.path.exists(expected_objects_dir):
                self.patching_logger.debug(f'Merging Objects from mod {mod_number} ({mod_name}, priority {mod_priority}) into existing Objects directory (will overwrite conflicting files)')
                self._merge_objects_directories(expected_objects_dir, objects_dir, mod_name)
            elif os.path.exists(objects_dir):
                self.patching_logger.debug(f'Copying Objects from mod {mod_number} ({mod_name}, priority {mod_priority}) to expected location (first mod)')
                shutil.copytree(objects_dir, expected_objects_dir, dirs_exist_ok=True)
        mod_1_patched_backup = None
        if base_mod_number in mod_patched_files:
            mod_1_patched = mod_patched_files.get(base_mod_number)
            if mod_1_patched and os.path.exists(mod_1_patched):
                mod_1_patched_backup = mod_1_patched + '.backup_for_export'
                if os.path.exists(mod_1_patched_backup):
                    safe_remove(mod_1_patched_backup)
                shutil.copy2(mod_1_patched, mod_1_patched_backup)
                self.patching_logger.info(f'Created backup of highest priority mod file: {mod_1_patched_backup}')
        if os.path.exists(expected_objects_dir):
            code_entries_before = os.path.join(expected_objects_dir, 'CodeEntries')
            sprites_before = os.path.join(expected_objects_dir, 'Sprites')
            code_files_before = [f for f in os.listdir(code_entries_before) if f.endswith('.gml')] if os.path.exists(code_entries_before) else []
            sprite_dirs_before = [d for d in os.listdir(sprites_before) if os.path.isdir(os.path.join(sprites_before, d))] if os.path.exists(sprites_before) else []
            self.patching_logger.info(f'[IMPORT] Before import: {len(code_files_before)} code files, {len(sprite_dirs_before)} sprites in Objects directory')
            if code_files_before:
                ramb_code_before = [f for f in code_files_before if 'ramb' in f.lower()]
                if ramb_code_before:
                    self.patching_logger.info(f'[IMPORT] Found ramb code files before import: {ramb_code_before}')
            if sprite_dirs_before:
                ramb_sprites_before = [d for d in sprite_dirs_before if 'ramb' in d.lower()]
                if ramb_sprites_before:
                    self.patching_logger.info(f'[IMPORT] Found ramb sprites before import: {ramb_sprites_before}')
            if self._cancelled:
                if not is_modpack and self.backup_manager:
                    self.backup_manager.restore_backups(chapter_id)
                return False
            import_progress_step = progress_base + int(xdelta_progress + export_progress + import_progress * 0.5)
            self.progress_update.emit(min(import_progress_step, 95), 'Importing merged assets into data.win...')
            self.patching_logger.info('Importing merged Objects directory (contains all exported mods, sorted by priority) into data.win')
            if not self._import_assets_from_objects_dir(base_data_win, expected_objects_dir, mods_to_apply, mods_count):
                self.patching_logger.warning('Failed to import merged assets into data.win')
                if not is_modpack and self.backup_manager:
                    self.backup_manager.restore_backups(chapter_id)
                return False
            self.patching_logger.info('Successfully imported merged Objects into data.win')
            code_files_after = [f for f in os.listdir(code_entries_before) if f.endswith('.gml')] if os.path.exists(code_entries_before) else []
            sprite_dirs_after = [d for d in os.listdir(sprites_before) if os.path.isdir(os.path.join(sprites_before, d))] if os.path.exists(sprites_before) else []
            self.patching_logger.info(f'[IMPORT] After import: {len(code_files_after)} code files, {len(sprite_dirs_after)} sprites still in Objects directory')
        else:
            self.patching_logger.debug('No Objects directory to import after merging mods (only xdelta changes)')
        self.patching_logger.info('Applying highest priority mod (mod_number=1) changes AFTER importing Objects')
        if mod_1_patched_backup and os.path.exists(mod_1_patched_backup):
            self.patching_logger.info('Exporting GML code from highest priority mod to apply over imported Objects')
            try:
                mod_1_export_dir = tempfile.mkdtemp(prefix='mod_1_export_')
                mod_1_objects_dir = os.path.join(mod_1_export_dir, 'Objects')
                os.makedirs(mod_1_objects_dir, exist_ok=True)
                mod_1_data_win_dir = os.path.dirname(mod_1_patched_backup)
                if self._cancelled:
                    return False
                export_script = self.utmt_wrapper.get_script_path('SmartExport')
                returncode = 1
                stderr = ''
                if export_script:
                    self.patching_logger.debug('Exporting modified GML code from highest priority mod using SmartExport')
                    env = os.environ.copy()
                    env['SMARTEXPORT_VANILLA_PATH'] = original_data_win
                    returncode, stdout, stderr = self.utmt_wrapper.execute_scripts(mod_1_patched_backup, ['SmartExport'], cwd=mod_1_data_win_dir, env=env)
                    try:
                        self._check_critical_script_errors(stderr, 'SmartExport', 'highest priority mod')
                    except RuntimeError:
                        self.patching_logger.error('Процесс слияния прерван из-за критической ошибки в SmartExport для highest priority mod')
                        raise
                else:
                    export_script = self.utmt_wrapper.get_script_path('ExportAllCode')
                    if export_script:
                        self.patching_logger.warning('SmartExport not found, falling back to ExportAllCode (may overwrite unmodified code)')
                        self.patching_logger.debug('Exporting all GML code from highest priority mod using ExportAllCode')
                        returncode, stdout, stderr = self.utmt_wrapper.execute_scripts(mod_1_patched_backup, ['ExportAllCode'], cwd=mod_1_data_win_dir)
                    else:
                        self.patching_logger.warning('SmartExport and ExportAllCode scripts not found, cannot export from highest priority mod')
                if returncode == 0:
                    mod_1_exported_objects = os.path.join(mod_1_data_win_dir, 'Objects')
                    if os.path.exists(mod_1_exported_objects):
                        self.patching_logger.info('Copying all resources from highest priority mod export (including sprites, rooms, shaders, etc.)')
                        for item in os.listdir(mod_1_exported_objects):
                            src_item = os.path.join(mod_1_exported_objects, item)
                            dst_item = os.path.join(mod_1_objects_dir, item)
                            if os.path.isdir(src_item):
                                if os.path.exists(dst_item) and os.path.isdir(dst_item):
                                    highest_priority_mod_name = getattr(highest_priority_mod, 'name', 'highest_priority_mod') if highest_priority_mod else 'highest_priority_mod'
                                    self._merge_objects_directories(dst_item, src_item, highest_priority_mod_name)
                                else:
                                    shutil.copytree(src_item, dst_item, dirs_exist_ok=True)
                            elif os.path.isfile(src_item):
                                self._safe_copy2(src_item, dst_item)
                        mod_1_code_entries = os.path.join(mod_1_exported_objects, 'CodeEntries')
                        mod_1_temp_code_entries = os.path.join(mod_1_objects_dir, 'CodeEntries')
                        if os.path.exists(mod_1_code_entries):
                            self.patching_logger.info('Successfully exported all resources from highest priority mod (including CodeEntries)')
                            if os.path.exists(mod_1_temp_code_entries):
                                exported_files = [f for f in os.listdir(mod_1_temp_code_entries) if f.endswith('.gml')]
                                self.patching_logger.info(f'Exported {len(exported_files)} GML file(s) from highest priority mod')
                                if exported_files:
                                    for f in exported_files[:5]:
                                        file_path = os.path.join(mod_1_temp_code_entries, f)
                                        with open(file_path, 'r', encoding='utf-8') as code_file:
                                            content = code_file.read()
                                            self.patching_logger.debug(f'  File {f}: {len(content)} chars, preview: {content[:50]}...')
                            else:
                                self.patching_logger.debug('No CodeEntries directory found in exported Objects from highest priority mod')
                        else:
                            self.patching_logger.info('Successfully exported resources from highest priority mod (no CodeEntries found)')
                        self.patching_logger.info('Importing GML code from highest priority mod to resolve conflicts')
                        base_data_win_dir = os.path.dirname(base_data_win)
                        target_objects_dir = os.path.join(base_data_win_dir, 'Objects')
                        mod_1_code_entries = os.path.join(mod_1_objects_dir, 'CodeEntries')
                        target_code_entries = os.path.join(target_objects_dir, 'CodeEntries')
                        if os.path.exists(mod_1_code_entries):
                            if os.path.exists(target_code_entries):
                                self.patching_logger.debug(f'Merging highest priority mod CodeEntries into existing CodeEntries directory: {target_code_entries}')
                                files_to_copy = []
                                all_files = [f for f in os.listdir(mod_1_code_entries) if f.endswith('.gml')]
                                for file in all_files:
                                    code_name = os.path.splitext(file)[0]
                                    if code_name in highest_priority_mod_exported_files:
                                        files_to_copy.append(file)
                                self.patching_logger.info(f'[IMPORT] Copying {len(files_to_copy)} code file(s) from highest priority mod (only files exported in main cycle, out of {len(all_files)} total)')
                                for file in files_to_copy:
                                    src_file = os.path.join(mod_1_code_entries, file)
                                    dst_file = os.path.join(target_code_entries, file)
                                    if os.path.isfile(src_file):
                                        self._safe_copy2(src_file, dst_file)
                                if len(files_to_copy) < len(all_files):
                                    skipped = len(all_files) - len(files_to_copy)
                                    self.patching_logger.info(f'[IMPORT] Skipped {skipped} code file(s) from highest priority mod (not exported in main cycle, likely not modified by this mod)')
                            else:
                                self.patching_logger.debug(f'Copying highest priority mod CodeEntries to: {target_code_entries}')
                                shutil.copytree(mod_1_code_entries, target_code_entries, dirs_exist_ok=True)
                            if self._import_assets_from_objects_dir(base_data_win, target_objects_dir, mods_to_apply, mods_count):
                                self.patching_logger.info('Successfully applied highest priority mod GML code over imported Objects')
                            else:
                                self.patching_logger.warning('Failed to import GML code from highest priority mod')
                        else:
                            self.patching_logger.debug('No CodeEntries from highest priority mod to import - all resources already merged from main export')
                    else:
                        self.patching_logger.debug('Objects directory not created by SmartExport/ExportAllCode for highest priority mod')
                else:
                    self.patching_logger.warning(f'SmartExport/ExportAllCode failed for highest priority mod: {stderr[:300]}')
                if not safe_rmtree(mod_1_export_dir):
                    self.patching_logger.warning(f'Failed to clean up temporary export directory: {mod_1_export_dir}')
                if mod_1_patched_backup and os.path.exists(mod_1_patched_backup):
                    if not safe_remove(mod_1_patched_backup):
                        self.patching_logger.warning(f'Failed to clean up backup file: {mod_1_patched_backup}')
            except Exception as e:
                self.patching_logger.error(f'Failed to export/import from highest priority mod: {e}', exc_info=True)
                if mod_1_patched_backup and os.path.exists(mod_1_patched_backup):
                    if not safe_remove(mod_1_patched_backup):
                        self.patching_logger.warning(f'Failed to clean up backup file after error: {mod_1_patched_backup}')
        else:
            self.patching_logger.debug('No highest priority mod changes to apply (no backup file created)')
        if self._cancelled:
            if not is_modpack and self.backup_manager:
                self.backup_manager.restore_backups(chapter_id)
            return False
        if os.path.exists(base_objects_dir):
            self.patching_logger.debug(f'Final Objects directory in base: {base_objects_dir}')
        if is_modpack:
            if modpack_dir is None:
                self.patching_logger.error('modpack_dir is None but is_modpack is True')
                return False
            system = platform.system()
            if system == 'Darwin':
                final_output_path = os.path.join(modpack_dir, 'game.ios')
            else:
                final_output_path = os.path.join(modpack_dir, 'data.win')
        else:
            final_output_path = output_data_win_path
        try:
            shutil.copy2(base_data_win, final_output_path)
            self.patching_logger.info(f'Copied merged data.win to {final_output_path}')
        except Exception as e:
            self.patching_logger.error(f'Failed to copy merged data.win: {e}')
            if not is_modpack and self.backup_manager:
                self.backup_manager.restore_backups(chapter_id)
            return False
        if self._cancelled:
            if not is_modpack and self.backup_manager:
                self.backup_manager.restore_backups(chapter_id)
            return False
        if is_modpack:
            if modpack_dir is None:
                self.patching_logger.error('modpack_dir is None but is_modpack is True')
                return False
            for mod_data in mods_to_apply:
                mod_source_dir = self._get_mod_source_dir(mod_data, chapter_id)
                if mod_source_dir:
                    if not self._apply_file_overrides(mod_source_dir, modpack_dir, set(), True):
                        self.patching_logger.warning(f"Failed to apply file overrides from {getattr(mod_data, 'name', 'Unknown')}")
        else:
            used_archive_names = set()
            for mod_data in mods_to_apply:
                if self._cancelled and self.backup_manager:
                    self.backup_manager.restore_backups(chapter_id)
                    return False
                mod_source_dir = self._get_mod_source_dir(mod_data, chapter_id)
                if mod_source_dir:
                    if not self._apply_file_overrides(mod_source_dir, target_dir, used_archive_names, False):
                        self.patching_logger.warning(f"Failed to apply file overrides from {getattr(mod_data, 'name', 'Unknown')}")
        self.patching_logger.info('Multi-mod merge completed successfully')
        return True

    def _merge_mods_for_chapter_to_dir(self, chapter_id: int, mods_list: List[Any], modpack_dir: str, progress_base: int = 0, total_chapters: int = 1) -> bool:
        self.patching_logger.debug(f'_merge_mods_for_chapter_to_dir: chapter_id={chapter_id}, mods_count={len(mods_list)}, modpack_dir={modpack_dir}')
        os.makedirs(modpack_dir, exist_ok=True)
        target_dir = self._get_target_dir(chapter_id)
        if not target_dir:
            self.patching_logger.error(f'Target directory not found for chapter {chapter_id}')
            return False
        self.patching_logger.debug(f'Target directory: {target_dir}')
        data_win_path = self._find_data_win(target_dir)
        if not data_win_path:
            return self._apply_file_overrides_only_to_dir(chapter_id, mods_list, modpack_dir)
        return self._perform_chapter_merge(chapter_id, mods_list, data_win_path, target_dir, modpack_dir, progress_base, total_chapters, is_modpack=True)

    def _apply_file_overrides_only_to_dir(self, chapter_id: int, mods_list: List[Any], modpack_dir: str) -> bool:
        mods_to_apply = list(reversed(mods_list))
        for mod_data in mods_to_apply:
            mod_source_dir = self._get_mod_source_dir(mod_data, chapter_id)
            if mod_source_dir:
                if not self._apply_file_overrides(mod_source_dir, modpack_dir, set(), True):
                    return False
        return True

    def _apply_file_overrides_only(self, chapter_id: int, mods_list: List[Any], target_dir: str) -> bool:
        mods_to_apply = list(reversed(mods_list))
        used_archive_names = set()
        for mod_data in mods_to_apply:
            mod_source_dir = self._get_mod_source_dir(mod_data, chapter_id)
            if mod_source_dir:
                if not self._apply_file_overrides(mod_source_dir, target_dir, used_archive_names, False):
                    return False
        return True

    def _apply_xdelta_patches(self, data_win_path: str, data_patches: List[str], progress_callback=None) -> bool:
        import platform
        import stat
        if not self.xdelta_path:
            self.patching_logger.error('xdelta executable not found')
            self.status_update.emit(tr('errors.xdelta_not_found'), 'error')
            return False
        if not os.path.exists(self.xdelta_path):
            self.patching_logger.error(f'xdelta path does not exist: {self.xdelta_path}')
            self.status_update.emit(tr('errors.xdelta_not_found'), 'error')
            return False
        if platform.system() != 'Windows':
            try:
                file_stat = os.stat(self.xdelta_path)
                is_executable = bool(file_stat.st_mode & stat.S_IEXEC)
                if not is_executable:
                    os.chmod(self.xdelta_path, 493)
            except Exception as e:
                self.patching_logger.error(f'Failed to check/set xdelta permissions: {e}', exc_info=True)
        if not os.path.exists(data_win_path):
            self.patching_logger.error(f'Input file does not exist: {data_win_path}')
            return False
        total_patches = len(data_patches)
        for idx, patch_path in enumerate(data_patches):
            if self._cancelled:
                return False
            patch_name = os.path.basename(patch_path)
            self.patching_logger.info(f'[XDELTA] Applying patch {idx + 1}/{total_patches}: {patch_name} to {os.path.basename(data_win_path)}')
            if progress_callback:
                progress_callback(idx / total_patches if total_patches > 0 else 0)
            if not os.path.exists(patch_path):
                self.patching_logger.error(f'Patch file does not exist: {patch_path}')
                self.status_update.emit(tr('errors.xdelta_patch_failed', patch=os.path.basename(patch_path)), 'error')
                return False
            try:
                temp_output = data_win_path + '.tmp'
                temp_dir = os.path.dirname(temp_output)
                if not os.access(temp_dir, os.W_OK):
                    self.patching_logger.error(f'Temp directory is not writable: {temp_dir}')
                    self.status_update.emit(tr('errors.xdelta_patch_failed', patch=os.path.basename(patch_path)), 'error')
                    return False
                cmd = [self.xdelta_path, '-d', '-s', data_win_path, patch_path, temp_output]
                startupinfo = None
                creationflags = 0
                if platform.system() == 'Windows':
                    import subprocess as sp
                    startupinfo = sp.STARTUPINFO()
                    startupinfo.dwFlags |= sp.STARTF_USESHOWWINDOW
                    startupinfo.wShowWindow = sp.SW_HIDE
                    creationflags = sp.CREATE_NO_WINDOW
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL, startupinfo=startupinfo, creationflags=creationflags)
                if progress_callback:
                    progress_callback((idx + 1) / total_patches if total_patches > 0 else 1.0)
                if result.returncode != 0:
                    error_msg = result.stderr.strip() if result.stderr else 'Unknown error'
                    if 'checksum mismatch' in error_msg.lower() or 'XD3_INVALID_INPUT' in error_msg:
                        detailed_error = f'[XDELTA] Patch "{os.path.basename(patch_path)}" failed: checksum mismatch. This usually means the patch was created for the original data.win, but the file has already been modified by previous mods. The patch cannot be applied to a modified file.\nError details: {error_msg}'
                        self.patching_logger.error(detailed_error)
                        self.status_update.emit(tr('errors.xdelta_patch_checksum_mismatch', patch=os.path.basename(patch_path), error=error_msg[:100]), 'error')
                    else:
                        detailed_error = f'[XDELTA] Patch "{os.path.basename(patch_path)}" failed: {error_msg}'
                        self.patching_logger.error(detailed_error)
                        self.status_update.emit(tr('errors.xdelta_patch_failed', patch=os.path.basename(patch_path)), 'error')
                    return False
                if not os.path.exists(temp_output):
                    self.patching_logger.error(f'Temp output file was not created: {temp_output}')
                    self.status_update.emit(tr('errors.xdelta_patch_failed', patch=os.path.basename(patch_path)), 'error')
                    return False
                if not safe_move(temp_output, data_win_path):
                    raise OSError(f'Failed to move patched file from {temp_output} to {data_win_path}')
                self.patching_logger.info(f'Patch {idx + 1}/{total_patches} applied successfully')
            except subprocess.TimeoutExpired:
                self.patching_logger.error(f'xdelta patch timed out after 300 seconds: {patch_path}')
                return False
            except Exception as e:
                self.patching_logger.error(f'xdelta patch error: {e}', exc_info=True)
                return False
        self.patching_logger.info('All patches applied successfully')
        return True

    def _apply_csx_scripts(self, data_win_path: str, csx_scripts: List[str]) -> bool:
        if not csx_scripts:
            return True
        if not self.utmt_wrapper.is_available():
            self.patching_logger.error('UTMTCLI not available for executing CSX scripts')
            self.status_update.emit(tr('errors.utmtcli_not_available', platform=self.utmt_wrapper.get_platform()), 'error')
            return False
        env = {}
        if self.temp_merge_dir and os.path.exists(os.path.join(self.temp_merge_dir, 'output')):
            env['DELTAHUB_ROOT'] = self.temp_merge_dir
        for script_path in csx_scripts:
            if self._cancelled:
                return False
            try:
                self.patching_logger.info(f'Executing CSX script: {os.path.basename(script_path)}')
                returncode, stdout, stderr = self.utmt_wrapper.execute_script(data_win_path, script_path, output_path=data_win_path, cwd=self.temp_merge_dir if self.temp_merge_dir else None, env=env)
                if returncode != 0:
                    self.patching_logger.error(f'CSX script execution failed: {stderr[:500]}')
                    self.status_update.emit(tr('errors.csx_script_failed', script=os.path.basename(script_path)), 'error')
                    return False
                self.patching_logger.info(f'Successfully executed CSX script: {os.path.basename(script_path)}')
            except Exception as e:
                self.patching_logger.error(f'CSX script error: {e}')
                return False
        return True

    def _handle_ready_data_win(self, base_data_win: str, ready_data_win_files: List[str], mod_dir: Optional[str] = None) -> bool:
        if not ready_data_win_files:
            return True
        for ready_file in ready_data_win_files:
            if self._cancelled:
                return False
            try:
                self.patching_logger.info(f'Merging ready data.win file: {os.path.basename(ready_file)}')
                if not self._merge_two_data_win_files(base_data_win, ready_file, mod_dir):
                    self.patching_logger.error(f'Failed to merge ready data.win file: {ready_file}')
                    return False
                self.patching_logger.info(f'Successfully merged ready data.win file: {os.path.basename(ready_file)}')
            except Exception as e:
                self.patching_logger.error(f'Error merging ready data.win file: {e}')
                return False
        return True

    def _merge_assets_with_utmtcli(self, data_win_path: str, mod_source_dir: str) -> bool:
        if not self.temp_merge_dir:
            self.patching_logger.error('Temp merge directory not set')
            return False
        try:
            asset_temp_dir = os.path.join(self.temp_merge_dir, 'assets_temp')
            os.makedirs(asset_temp_dir, exist_ok=True)
            has_assets = self._mod_has_assets(mod_source_dir)
            if not has_assets:
                return True
            return self.utmt_wrapper.merge_assets(data_win_path, mod_source_dir)
            return True
        except Exception as e:
            self.patching_logger.error(f'UTMTCLI asset merge failed: {e}', exc_info=True)
            return False

    def _import_asset_type(self, asset_config: Dict[str, Any], data_win_path: str, data_win_dir: str, objects_dir: str, mod_name_for_tracking: str) -> bool:
        script_name = asset_config['script_name']
        has_assets = asset_config.get('has_assets', False)
        check_dir_func = asset_config.get('check_dir_func')
        if check_dir_func and (not check_dir_func(objects_dir)):
            has_assets = False
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
            if resource_name not in self.resource_modification_history:
                self.resource_modification_history[resource_name] = []
            self.resource_modification_history[resource_name].append({'type': resource_type, 'mod': mod_name_for_tracking, 'action': resource_action, 'timestamp': time.time()})
        returncode, stdout, stderr = self.utmt_wrapper.execute_script(data_win_path, script_name, output_path=data_win_path, cwd=data_win_dir)
        if analyze_errors:
            self._analyze_compilation_errors(stdout, stderr, script_name, mod_name_for_tracking)
        if returncode != 0:
            error_msg = stderr[:300] if len(stderr) > 300 else stderr
            self.patching_logger.warning(f'{script_name} failed: {error_msg}')
            if len(stderr) > 500:
                self.patching_logger.error(f'[IMPORT] {script_name} failed: {stderr[:500]}')
            for resource_name in resource_names:
                if resource_name in self.resource_modification_history:
                    history = self.resource_modification_history[resource_name]
                    if history:
                        history[-1]['error'] = error_msg
                        if len(history) > 1:
                            prev_mods = [h['mod'] for h in history[:-1]]
                            prev_mods_unique = [m for m in prev_mods if m != mod_name_for_tracking]
                            if prev_mods_unique:
                                conflict_msg = f'''{resource_type.capitalize()} "{resource_name}" was modified by: {', '.join(prev_mods_unique)} before "{mod_name_for_tracking}". Higher priority mod ({mod_name_for_tracking}) will be used.'''
                                self.patching_logger.warning(f'[CONFLICT] {conflict_msg}')
                                self.conflicts_logger.info(f'''Resource: {resource_type.capitalize()} "{resource_name}" | Conflict between: {', '.join(prev_mods_unique)} vs "{mod_name_for_tracking}" | Resolution: Using "{mod_name_for_tracking}" (higher priority)''')
                                self.detected_conflicts.append({'resource_type': resource_type, 'resource_name': resource_name, 'mods': prev_mods_unique + [mod_name_for_tracking], 'resolution': mod_name_for_tracking})
                                history[-1]['conflicts_with'] = prev_mods_unique
        else:
            for resource_name in resource_names:
                if resource_name in self.resource_modification_history:
                    history = self.resource_modification_history[resource_name]
                    if len(history) > 1:
                        prev_mods = [h['mod'] for h in history[:-1]]
                        prev_mods_unique = [m for m in prev_mods if m != mod_name_for_tracking]
                        if prev_mods_unique:
                            conflict_msg = f'''{resource_type.capitalize()} "{resource_name}" was modified by: {', '.join(prev_mods_unique)} before "{mod_name_for_tracking}". Higher priority mod ({mod_name_for_tracking}) will be used.'''
                            self.patching_logger.warning(f'[CONFLICT] {conflict_msg}')
                            self.conflicts_logger.info(f'''Resource: {resource_type.capitalize()} "{resource_name}" | Conflict between: {', '.join(prev_mods_unique)} vs "{mod_name_for_tracking}" | Resolution: Using "{mod_name_for_tracking}" (higher priority)''')
                            self.detected_conflicts.append({'resource_type': resource_type, 'resource_name': resource_name, 'mods': prev_mods_unique + [mod_name_for_tracking], 'resolution': mod_name_for_tracking})
                            history[-1]['conflicts_with'] = prev_mods_unique
            self.patching_logger.info(f'Successfully imported {resource_type} from Objects directory')
        return returncode == 0

    def _import_assets_from_objects_dir(self, data_win_path: str, objects_dir: str, mods_to_apply: Optional[List[Any]] = None, mods_count: int = 0) -> bool:
        try:
            if not os.path.exists(objects_dir):
                self.patching_logger.debug(f'Objects directory does not exist: {objects_dir}')
                return False
            data_win_dir = os.path.dirname(data_win_path)
            expected_objects_dir = os.path.join(data_win_dir, 'Objects')
            if objects_dir != expected_objects_dir:
                self.patching_logger.warning(f'Objects directory is not next to data.win! Expected: {expected_objects_dir}, Got: {objects_dir}')
                if os.path.exists(expected_objects_dir):
                    mod_name_from_path = 'unknown_mod'
                    try:
                        if 'xDeltaCombiner' in objects_dir:
                            parts = objects_dir.split(os.sep)
                            if 'xDeltaCombiner' in parts:
                                idx = parts.index('xDeltaCombiner')
                                if idx + 2 < len(parts):
                                    mod_name_from_path = parts[idx + 2]
                    except BaseException:
                        pass
                    self._merge_objects_directories(expected_objects_dir, objects_dir, mod_name_from_path)
                else:
                    shutil.copytree(objects_dir, expected_objects_dir, dirs_exist_ok=True)
                objects_dir = expected_objects_dir
            sprites_dir = os.path.join(objects_dir, 'Sprites')
            backgrounds_dir = os.path.join(objects_dir, 'Backgrounds')
            has_graphics = os.path.exists(sprites_dir) or os.path.exists(backgrounds_dir)
            code_entries_dir = os.path.join(objects_dir, 'CodeEntries')
            append_code_dir = os.path.join(objects_dir, 'AppendCode')
            prepend_code_dir = os.path.join(objects_dir, 'PrependCode')
            code_patches_file = os.path.join(objects_dir, 'CodePatches.json')
            has_gml = bool(os.path.exists(code_entries_dir) and os.listdir(code_entries_dir) or (os.path.exists(append_code_dir) and os.listdir(append_code_dir)) or (os.path.exists(prepend_code_dir) and os.listdir(prepend_code_dir)) or os.path.exists(code_patches_file))
            shaders_dir = os.path.join(objects_dir, 'Shaders')
            has_shaders = bool(os.path.exists(shaders_dir) and os.listdir(shaders_dir))
            new_objects_dir = os.path.join(objects_dir, 'NewObjects')
            has_new_objects = bool(os.path.exists(new_objects_dir) and os.listdir(new_objects_dir))
            existing_objects_dir = os.path.join(objects_dir, 'ExistingObjects')
            has_existing_objects = bool(os.path.exists(existing_objects_dir) and os.listdir(existing_objects_dir))
            rooms_dir = os.path.join(objects_dir, 'Rooms')
            has_rooms = bool(os.path.exists(rooms_dir) and os.listdir(rooms_dir))
            tilesets_dir = os.path.join(objects_dir, 'Tilesets')
            has_tilesets = bool(os.path.exists(tilesets_dir) and os.listdir(tilesets_dir))
            asset_order_path = os.path.join(objects_dir, 'AssetOrder.txt')
            has_asset_order = os.path.exists(asset_order_path)
            if not (has_graphics or has_gml or has_shaders or has_new_objects or has_existing_objects or has_rooms or has_tilesets or has_asset_order):
                self.patching_logger.debug(f'Objects directory has no assets to import: {objects_dir}')
                return True
            mod_name_for_tracking = 'unknown_mod'
            try:
                if 'xDeltaCombiner' in objects_dir:
                    parts = objects_dir.split(os.sep)
                    if 'xDeltaCombiner' in parts:
                        idx = parts.index('xDeltaCombiner')
                        if idx + 2 < len(parts):
                            mod_number_str = parts[idx + 2]
                            try:
                                mod_number = int(mod_number_str)
                                if mods_to_apply and mods_count > 0:
                                    for mod_idx, mod_data in enumerate(mods_to_apply):
                                        actual_mod_number = mod_idx + 1
                                        if actual_mod_number == mod_number:
                                            mod_name_for_tracking = getattr(mod_data, 'name', f'mod_{mod_number}')
                                            break
                            except (ValueError, TypeError):
                                pass
            except BaseException:
                pass

            def get_sprite_resources(obj_dir):
                sprites_path = os.path.join(obj_dir, 'Sprites')
                if os.path.exists(sprites_path):
                    sprite_dirs = [d for d in os.listdir(sprites_path) if os.path.isdir(os.path.join(sprites_path, d))]
                    self.patching_logger.info(f'[IMPORT] Will import {len(sprite_dirs)} sprite directories')
                    return sprite_dirs
                return []

            def get_shader_resources(obj_dir):
                shaders_path = os.path.join(obj_dir, 'Shaders')
                if os.path.exists(shaders_path):
                    return [d for d in os.listdir(shaders_path) if os.path.isdir(os.path.join(shaders_path, d))]
                return []

            def get_new_object_resources(obj_dir):
                new_objects_path = os.path.join(obj_dir, 'NewObjects')
                if os.path.exists(new_objects_path):
                    return [os.path.splitext(f)[0] for f in os.listdir(new_objects_path) if f.endswith('.json')]
                return []

            def get_gml_resources(obj_dir):
                code_entries_path = os.path.join(obj_dir, 'CodeEntries')
                append_code_path = os.path.join(obj_dir, 'AppendCode')
                prepend_code_path = os.path.join(obj_dir, 'PrependCode')
                all_code_names = set()
                if os.path.exists(code_entries_path):
                    for f in os.listdir(code_entries_path):
                        if f.endswith('.gml'):
                            all_code_names.add(os.path.splitext(f)[0])
                if os.path.exists(append_code_path):
                    for f in os.listdir(append_code_path):
                        if f.endswith('.gml'):
                            all_code_names.add(os.path.splitext(f)[0])
                if os.path.exists(prepend_code_path):
                    for f in os.listdir(prepend_code_path):
                        if f.endswith('.gml'):
                            all_code_names.add(os.path.splitext(f)[0])
                code_files = list(all_code_names)
                if code_files:
                    self.patching_logger.debug(f'[IMPORT] Code files to import: {code_files[:10]}...' if len(code_files) > 10 else f'[IMPORT] Code files to import: {code_files}')
                return code_files

            def get_existing_object_resources(obj_dir):
                existing_objects_path = os.path.join(obj_dir, 'ExistingObjects')
                if os.path.exists(existing_objects_path):
                    return [os.path.splitext(f)[0] for f in os.listdir(existing_objects_path) if f.endswith('.json')]
                return []

            def get_room_resources(obj_dir):
                rooms_path = os.path.join(obj_dir, 'Rooms')
                if os.path.exists(rooms_path):
                    return [os.path.splitext(f)[0] for f in os.listdir(rooms_path) if f.endswith('.json')]
                return []

            def get_tileset_resources(obj_dir):
                tilesets_path = os.path.join(obj_dir, 'Tilesets')
                if os.path.exists(tilesets_path):
                    return [os.path.splitext(f)[0] for f in os.listdir(tilesets_path) if f.endswith('.json') and (not f.endswith('config.json'))]
                return []

            def get_tileset_config_resource(obj_dir):
                tilesets_path = os.path.join(obj_dir, 'Tilesets')
                if os.path.exists(tilesets_path) and os.path.exists(os.path.join(tilesets_path, 'config.json')):
                    return ['tilesets_config']
                return []

            def get_font_resources(obj_dir):
                fonts_path = os.path.join(obj_dir, 'Fonts')
                if os.path.exists(fonts_path):
                    return [os.path.splitext(f)[0] for f in os.listdir(fonts_path) if f.endswith('.png')]
                return []

            def get_sound_resources(obj_dir):
                sounds_path = os.path.join(obj_dir, 'Sounds')
                if os.path.exists(sounds_path):
                    return [os.path.splitext(f)[0] for f in os.listdir(sounds_path) if f.endswith(('.ogg', '.wav'))]
                return []
            asset_configs = [{'script_name': 'ImportGraphics', 'has_assets': has_graphics, 'step_number': '1/12', 'resource_type': 'sprite', 'resource_action': 'imported', 'get_resources_func': get_sprite_resources}, {'script_name': 'ImportShaders', 'has_assets': has_shaders, 'step_number': '2/12', 'resource_type': 'shader', 'resource_action': 'imported', 'get_resources_func': get_shader_resources}, {'script_name': 'ImportNewObjects', 'has_assets': has_new_objects, 'step_number': '3/12', 'resource_type': 'new_object', 'resource_action': 'created', 'get_resources_func': get_new_object_resources}, {'script_name': 'ImportGML', 'has_assets': has_gml, 'step_number': '5/12', 'resource_type': 'code', 'resource_action': 'modified', 'get_resources_func': get_gml_resources, 'analyze_errors': True}, {'script_name': 'ImportExistingObjects', 'has_assets': has_existing_objects, 'step_number': '9/12', 'resource_type': 'existing_object', 'resource_action': 'modified', 'get_resources_func': get_existing_object_resources}, {'script_name': 'ImportRooms', 'has_assets': has_rooms, 'step_number': '10/12', 'resource_type': 'room', 'resource_action': 'imported', 'get_resources_func': get_room_resources}, {'script_name': 'ImportTilesets', 'has_assets': has_tilesets, 'step_number': '10/14', 'resource_type': 'tileset', 'resource_action': 'imported', 'get_resources_func': get_tileset_resources, 'extra_resources_func': get_tileset_config_resource}, {'script_name': 'ImportFonts', 'has_assets': False, 'check_dir_func': lambda obj_dir: os.path.exists(os.path.join(obj_dir, 'Fonts')), 'step_number': '11/14', 'resource_type': 'font', 'resource_action': 'modified', 'get_resources_func': get_font_resources}, {'script_name': 'ImportSounds', 'has_assets': False, 'check_dir_func': lambda obj_dir: os.path.exists(os.path.join(obj_dir, 'Sounds')), 'step_number': '12/14', 'resource_type': 'sound', 'resource_action': 'modified', 'get_resources_func': get_sound_resources}]
            for asset_config in asset_configs:
                self._import_asset_type(asset_config, data_win_path, data_win_dir, objects_dir, mod_name_for_tracking)
            import_asset_order_script = self.utmt_wrapper.get_script_path('ImportAssetOrder')
            if import_asset_order_script and has_asset_order:
                self.patching_logger.info(f'[IMPORT] [14/14] Importing asset order from {objects_dir}')
                returncode, stdout, stderr = self.utmt_wrapper.execute_scripts(data_win_path, ['ImportAssetOrder'], output_path=data_win_path, cwd=data_win_dir)
                if returncode != 0:
                    self.patching_logger.warning(f'ImportAssetOrder failed: {stderr[:300]}')
                else:
                    self.patching_logger.info('Successfully imported asset order from Objects directory')
            return True
        except Exception as e:
            self.patching_logger.error(f'Failed to import assets from Objects directory: {e}', exc_info=True)
            return False

    def detect_file_conflicts(self, mod_source_dir: str, target_dir: str, mod_name: str) -> List[str]:
        conflicts = []
        if not os.path.isdir(mod_source_dir):
            return conflicts
        from config.constants import DATA_FILE_EXTENSIONS
        xdelta_extensions = DATA_FILE_EXTENSIONS
        archive_extensions = ('.zip', '.7z', '.rar', '.tar.gz', '.lzma')
        for root, dirs, files in os.walk(mod_source_dir):
            for file in files:
                if file.lower() in ('config.json', '_icon.png'):
                    continue
                if file.lower().endswith(xdelta_extensions):
                    continue
                source_path = os.path.join(root, file)
                if file.lower().endswith(archive_extensions):
                    continue
                rel_path = os.path.relpath(source_path, mod_source_dir)
                target_path = os.path.join(target_dir, rel_path)
                if os.path.exists(target_path):
                    conflicts.append(rel_path)
                    self.patching_logger.warning(f'[CONFLICT] File override conflict detected: {rel_path} from mod {mod_name}')
                    self.conflicts_logger.info(f'Resource: File "{rel_path}" | Conflict: File already exists | Resolution: Using file from "{mod_name}" (higher priority)')
                    self.detected_conflicts.append({'resource_type': 'file', 'resource_name': rel_path, 'mods': [mod_name], 'resolution': mod_name})
        return conflicts

    def detect_code_conflicts(self, mod_source_dir: str, mod_name: str, existing_code_files: Dict[str, str]) -> List[str]:
        conflicts = []
        objects_dir = os.path.join(mod_source_dir, 'Objects')
        code_entries_dir = os.path.join(objects_dir, 'CodeEntries')
        if not os.path.exists(code_entries_dir):
            return conflicts
        for file in os.listdir(code_entries_dir):
            if file.endswith('.gml'):
                code_name = os.path.splitext(file)[0]
                if code_name in existing_code_files:
                    prev_mod = existing_code_files[code_name]
                    if prev_mod != mod_name:
                        conflicts.append(code_name)
                        self.patching_logger.warning(f'[CONFLICT] Code conflict detected: {code_name} from mod {mod_name} (already modified by {prev_mod})')
                        self.conflicts_logger.info(f'Resource: GML Code "{code_name}" | Conflict between: "{prev_mod}" vs "{mod_name}" | Resolution: Using "{mod_name}" (higher priority)')
                        self.detected_conflicts.append({'resource_type': 'code', 'resource_name': code_name, 'mods': [prev_mod, mod_name], 'resolution': mod_name})
        return conflicts

    def _check_dir_conflicts(self, base_dir: str, subfolder: str, resource_type: str, existing_assets: Dict[str, Dict[str, str]], mod_name: str, extension: str = None) -> List[str]:
        conflicts = []
        resource_dir = os.path.join(base_dir, subfolder)
        if not os.path.exists(resource_dir):
            return conflicts
        for item_name in os.listdir(resource_dir):
            item_path = os.path.join(resource_dir, item_name)
            if extension:
                if not item_name.endswith(extension):
                    continue
                resource_name = os.path.splitext(item_name)[0]
            else:
                if not os.path.isdir(item_path):
                    continue
                resource_name = item_name
            if resource_name in existing_assets.get(resource_type, {}):
                prev_mod = existing_assets[resource_type][resource_name]
                if prev_mod != mod_name:
                    conflicts.append(resource_name)
                    self.patching_logger.warning(f'[CONFLICT] {resource_type.capitalize()} conflict detected: {resource_name} from mod {mod_name}')
                    self.conflicts_logger.info(f'Resource: {resource_type.capitalize()} "{resource_name}" | Conflict between: "{prev_mod}" vs "{mod_name}" | Resolution: Using "{mod_name}" (higher priority)')
                    self.detected_conflicts.append({'resource_type': resource_type.rstrip('s'), 'resource_name': resource_name, 'mods': [prev_mod, mod_name], 'resolution': mod_name})
        return conflicts

    def detect_asset_conflicts(self, mod_source_dir: str, mod_name: str, existing_assets: Dict[str, Dict[str, str]]) -> Dict[str, List[str]]:
        conflicts = {'sprites': [], 'backgrounds': [], 'rooms': [], 'tilesets': [], 'shaders': []}
        objects_dir = os.path.join(mod_source_dir, 'Objects')
        if not os.path.exists(objects_dir):
            return conflicts
        resource_configs = [('Sprites', 'sprites', None), ('Backgrounds', 'backgrounds', '.png'), ('Rooms', 'rooms', '.json'), ('Tilesets', 'tilesets', '.json'), ('Shaders', 'shaders', None)]
        for subfolder, resource_type, extension in resource_configs:
            conflicts[resource_type] = self._check_dir_conflicts(objects_dir, subfolder, resource_type, existing_assets, mod_name, extension)
        return conflicts

    def _analyze_compilation_errors(self, stdout: str, stderr: str, script_name: str, mod_name: str) -> List[Dict[str, Any]]:
        errors_found = []
        combined_output = (stdout or '') + '\n' + (stderr or '')
        error_patterns = [('variable\\s+name\\s+[\\\'"]?(\\w+)[\\\'"]?\\s+index\\s+\\([^)]+\\)\\s+not\\s+set\\s+before\\s+reading', 'variable_not_set'), ('global\\s+variable\\s+name\\s+[\\\'"]?(\\w+)[\\\'"]?\\s+index\\s+\\([^)]+\\)\\s+not\\s+set', 'global_variable_not_set'), ('ERROR\\s+in\\s+action\\s+number\\s+\\d+\\s+of\\s+(\\w+)\\s+Event\\d+\\s+for\\s+object\\s+(\\w+):', 'runtime_error'), ('undefined\\s+variable\\s+[\\\'"]?(\\w+)[\\\'"]?', 'undefined_variable'), ('compilation\\s+error', 'compilation_error'), ('compilation\\s+failed', 'compilation_failed'), ('failed\\s+to\\s+compile', 'compilation_failed'), ('variable\\s+[\\\'"]?(\\w+)[\\\'"]?\\s+is\\s+not\\s+defined', 'variable_not_defined')]
        for pattern, error_type in error_patterns:
            matches = re.finditer(pattern, combined_output, re.IGNORECASE | re.MULTILINE)
            for match in matches:
                error_context = match.group(0)
                variable_name = match.group(1) if len(match.groups()) > 0 else None
                object_name = match.group(2) if len(match.groups()) > 1 else None
                error_start = match.start()
                error_end = min(error_start + 500, len(combined_output))
                context = combined_output[error_start:error_end].split('\n')[:5]
                context_str = '\n'.join(context)
                error_info = {'type': error_type, 'script': script_name, 'mod': mod_name, 'error_message': error_context, 'context': context_str, 'variable_name': variable_name, 'object_name': object_name}
                errors_found.append(error_info)
                error_desc = f'Code Error: {error_type}'
                if variable_name:
                    error_desc += f' (variable: {variable_name})'
                if object_name:
                    error_desc += f' (object: {object_name})'
                self.conflicts_logger.info(f'Resource: GML Code | Error Type: {error_desc} | Script: {script_name} | Mod: {mod_name} | Error: {error_context[:200]}')
                self.detected_conflicts.append({'resource_type': 'code_error', 'resource_name': variable_name or object_name or 'unknown', 'mods': [mod_name], 'error_type': error_type, 'error_message': error_context[:300], 'script': script_name})
        return errors_found

    def get_conflicts_summary(self) -> Dict[str, Any]:
        if not self.detected_conflicts:
            return {'has_conflicts': False, 'conflicting_mods': set(), 'conflicts': []}
        all_mods = set()
        mod_pairs = set()
        unique_resources = set()
        for conflict in self.detected_conflicts:
            mods = conflict['mods']
            seen = set()
            unique_mods = [m for m in mods if not (m in seen or seen.add(m))]
            if len(unique_mods) < 2:
                continue
            all_mods.update(unique_mods)
            for i in range(len(unique_mods)):
                for j in range(i + 1, len(unique_mods)):
                    if unique_mods[i] != unique_mods[j]:
                        mod_pairs.add(tuple(sorted([unique_mods[i], unique_mods[j]])))
            resource_key = (conflict.get('resource_type'), conflict.get('resource_name'))
            unique_resources.add(resource_key)
        total_unique_conflicts = len(unique_resources)
        return {'has_conflicts': True, 'conflicting_mods': sorted(all_mods), 'mod_pairs': [list(pair) for pair in sorted(mod_pairs)], 'conflicts': self.detected_conflicts, 'total_conflicts': total_unique_conflicts}

    def _safe_copy2(self, src: str, dst: str, max_retries: int = 5) -> None:
        try:
            if os.path.abspath(src) == os.path.abspath(dst):
                self.patching_logger.debug(f'Skipping copy: source and destination are the same file: {src}')
                return
        except Exception:
            pass
        for attempt in range(max_retries):
            try:
                shutil.copy2(src, dst)
                return
            except PermissionError as e:
                if attempt < max_retries - 1:
                    time.sleep(0.1 * (attempt + 1))
                else:
                    self.patching_logger.error(f'Failed to copy {src} to {dst} after {max_retries} attempts: {e}')
                    raise
            except OSError as e:
                if attempt < max_retries - 1:
                    time.sleep(0.1 * (attempt + 1))
                else:
                    self.patching_logger.error(f'Failed to copy {src} to {dst} after {max_retries} attempts: {e}')
                    raise

    def _merge_subdirectory(self, target_base: str, source_base: str, folder_name: str, resource_type: str, source_mod_name: str, track_history: bool = False) -> None:
        source_dir = os.path.join(source_base, folder_name)
        target_dir = os.path.join(target_base, folder_name)
        if not os.path.exists(source_dir):
            return
        if os.path.exists(target_dir):
            for root, dirs, files in os.walk(source_dir):
                rel_path = os.path.relpath(root, source_dir)
                target_path = os.path.join(target_dir, rel_path)
                os.makedirs(target_path, exist_ok=True)
                for file in files:
                    src_file = os.path.join(root, file)
                    dst_file = os.path.join(target_path, file)
                    if os.path.exists(dst_file) and track_history:
                        resource_name = rel_path if rel_path != '.' else os.path.splitext(file)[0]
                        if resource_name in self.resource_modification_history:
                            prev_mods = [h['mod'] for h in self.resource_modification_history[resource_name]]
                            if prev_mods and source_mod_name not in prev_mods:
                                conflict_msg = f'''{resource_type.capitalize()} "{resource_name}" was modified by: {', '.join(prev_mods)} before "{source_mod_name}". Higher priority mod ({source_mod_name}) will overwrite.'''
                                self.patching_logger.warning(f'[CONFLICT] {conflict_msg}')
                                self.conflicts_logger.info(f'''Resource: {resource_type.capitalize()} "{resource_name}" | Conflict between: {', '.join(prev_mods)} vs "{source_mod_name}" | Resolution: Using "{source_mod_name}" (higher priority)''')
                                self.detected_conflicts.append({'resource_type': resource_type, 'resource_name': resource_name, 'mods': prev_mods + [source_mod_name], 'resolution': source_mod_name})
                    self._safe_copy2(src_file, dst_file)
                    if track_history:
                        resource_name = rel_path if rel_path != '.' else os.path.splitext(file)[0]
                        if resource_name not in self.resource_modification_history:
                            self.resource_modification_history[resource_name] = []
                        self.resource_modification_history[resource_name].append({'type': resource_type, 'mod': source_mod_name, 'action': 'merged', 'timestamp': time.time()})
        else:
            shutil.copytree(source_dir, target_dir, dirs_exist_ok=True)

    def _merge_objects_directories(self, target_objects_dir: str, source_objects_dir: str, source_mod_name: str = 'unknown') -> None:
        if not os.path.exists(source_objects_dir):
            return
        try:
            if os.path.abspath(source_objects_dir) == os.path.abspath(target_objects_dir):
                self.patching_logger.debug(f'[MERGE] Skipping merge: source and target are the same directory: {source_objects_dir}')
                return
        except Exception:
            pass
        os.makedirs(target_objects_dir, exist_ok=True)
        subdirs_to_merge = [('Sprites', 'sprite', True), ('Backgrounds', 'background', False), ('Rooms', 'room', False), ('Tilesets', 'tileset', False), ('Shaders', 'shader', False), ('Fonts', 'font', False), ('Sounds', 'sound', False), ('NewObjects', 'new_object', False), ('ExistingObjects', 'existing_object', False)]
        for folder_name, resource_type, track_history in subdirs_to_merge:
            self._merge_subdirectory(target_objects_dir, source_objects_dir, folder_name, resource_type, source_mod_name, track_history)
        source_code = os.path.join(source_objects_dir, 'CodeEntries')
        target_code = os.path.join(target_objects_dir, 'CodeEntries')
        if os.path.exists(source_code):
            os.makedirs(target_code, exist_ok=True)
            for file in os.listdir(source_code):
                src_file = os.path.join(source_code, file)
                dst_file = os.path.join(target_code, file)
                if os.path.isfile(src_file):
                    if os.path.exists(dst_file):
                        code_name = os.path.splitext(file)[0]
                        if code_name in self.resource_modification_history:
                            prev_mods = [h['mod'] for h in self.resource_modification_history[code_name]]
                            if prev_mods and source_mod_name not in prev_mods:
                                conflict_msg = f'''Code "{code_name}" was modified by: {', '.join(prev_mods)} before "{source_mod_name}". Higher priority mod ({source_mod_name}) will overwrite.'''
                                self.patching_logger.warning(f'[CONFLICT] {conflict_msg}')
                                self.conflicts_logger.info(f'''Resource: GML Code "{code_name}" | Conflict between: {', '.join(prev_mods)} vs "{source_mod_name}" | Resolution: Using "{source_mod_name}" (higher priority)''')
                                self.detected_conflicts.append({'resource_type': 'code', 'resource_name': code_name, 'mods': prev_mods + [source_mod_name], 'resolution': source_mod_name})
                    self._safe_copy2(src_file, dst_file)
                    code_name = os.path.splitext(file)[0]
                    if code_name not in self.resource_modification_history:
                        self.resource_modification_history[code_name] = []
                    self.resource_modification_history[code_name].append({'type': 'code', 'mod': source_mod_name, 'action': 'merged', 'timestamp': time.time()})
        for code_folder in ['AppendCode', 'PrependCode']:
            self._merge_subdirectory(target_objects_dir, source_objects_dir, code_folder, 'code_injection', source_mod_name, track_history=False)
        source_patches = os.path.join(source_objects_dir, 'CodePatches.json')
        target_patches = os.path.join(target_objects_dir, 'CodePatches.json')
        if os.path.exists(source_patches):
            if os.path.exists(target_patches):
                try:
                    import json
                    with open(target_patches, 'r', encoding='utf-8') as f_t:
                        target_json = json.load(f_t)
                    with open(source_patches, 'r', encoding='utf-8') as f_s:
                        source_json = json.load(f_s)
                    if isinstance(target_json, dict) and isinstance(source_json, dict):
                        target_json.update(source_json)
                        with open(target_patches, 'w', encoding='utf-8') as f_out:
                            json.dump(target_json, f_out, indent=2)
                except Exception as e:
                    self.patching_logger.warning(f'Failed to merge CodePatches.json: {e}')
                    self._safe_copy2(source_patches, target_patches)
            else:
                self._safe_copy2(source_patches, target_patches)
        source_asset_order = os.path.join(source_objects_dir, 'AssetOrder.txt')
        target_asset_order = os.path.join(target_objects_dir, 'AssetOrder.txt')
        if os.path.exists(source_asset_order):
            self._safe_copy2(source_asset_order, target_asset_order)

    def _merge_two_data_win_files(self, base_file: str, other_file: str, mod_dir: Optional[str] = None) -> bool:
        if not self.temp_merge_dir:
            self.patching_logger.error('Temp merge directory not set')
            return False
        try:
            merge_temp_dir = os.path.join(self.temp_merge_dir, 'merge_temp')
            os.makedirs(merge_temp_dir, exist_ok=True)
            if self._cancelled:
                return False
            export_script = self.utmt_wrapper.get_script_path('SmartExport')
            if export_script:
                export_temp = os.path.join(merge_temp_dir, 'other_export')
                os.makedirs(export_temp, exist_ok=True)
                returncode, stdout, stderr = self.utmt_wrapper.execute_scripts(other_file, ['SmartExport'], cwd=export_temp)
                try:
                    self._check_critical_script_errors(stderr, 'SmartExport', 'other files export')
                except RuntimeError:
                    self.patching_logger.error('Процесс слияния прерван из-за критической ошибки в SmartExport для других файлов')
                    raise
                if returncode == 0:
                    if mod_dir:
                        export_objects_dir = os.path.join(export_temp, 'Objects')
                        mod_objects_dir = os.path.join(mod_dir, 'Objects')
                        if os.path.exists(export_objects_dir):
                            if os.path.exists(mod_objects_dir):
                                mod_name_from_dir = os.path.basename(mod_dir) if mod_dir else 'unknown_mod'
                                self._merge_objects_directories(mod_objects_dir, export_objects_dir, mod_name_from_dir)
                            else:
                                shutil.copytree(export_objects_dir, mod_objects_dir)
                            self.patching_logger.info(f'Copied exported objects to {mod_objects_dir} for later import')
                    scripts_to_run = []
                    if self.utmt_wrapper.get_script_path('ImportGraphics'):
                        scripts_to_run.append('ImportGraphics')
                    if self.utmt_wrapper.get_script_path('ImportShaders'):
                        scripts_to_run.append('ImportShaders')
                    if self.utmt_wrapper.get_script_path('ImportNewObjects'):
                        scripts_to_run.append('ImportNewObjects')
                    if self.utmt_wrapper.get_script_path('ImportGML'):
                        scripts_to_run.append('ImportGML')
                    if self.utmt_wrapper.get_script_path('ImportExistingObjects'):
                        scripts_to_run.append('ImportExistingObjects')
                    if self.utmt_wrapper.get_script_path('ImportRooms'):
                        scripts_to_run.append('ImportRooms')
                    if self.utmt_wrapper.get_script_path('ImportTilesets'):
                        scripts_to_run.append('ImportTilesets')
                    if self.utmt_wrapper.get_script_path('ImportAssetOrder'):
                        scripts_to_run.append('ImportAssetOrder')
                    if scripts_to_run:
                        returncode, stdout, stderr = self.utmt_wrapper.execute_scripts(base_file, scripts_to_run, output_path=base_file, cwd=export_temp)
                        if returncode == 0:
                            self.patching_logger.info('Successfully merged two data.win files using UTMTCLI scripts')
                            return True
            self.patching_logger.error('UTMTCLI merge failed: Cannot merge data.win files')
            self.patching_logger.error('Fallback copy would overwrite base_file and lose previous mod changes')
            self.patching_logger.error('This mod cannot be merged and will be skipped to prevent data loss')
            return False
        except Exception as e:
            self.patching_logger.error(f'Failed to merge two data.win files: {e}', exc_info=True)
            self.patching_logger.error('Cannot use fallback copy as it would cause irreversible data loss')
            return False

    def _mod_has_assets(self, mod_source_dir: str) -> bool:
        if not os.path.isdir(mod_source_dir):
            return False
        asset_extensions = ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.gml', '.txt')
        for root, dirs, files in os.walk(mod_source_dir):
            for file in files:
                if file.lower().endswith(asset_extensions):
                    return True
        return False

    def _apply_file_overrides(self, mod_source_dir: str, target_dir: str, used_archive_names: set, is_modpack: bool) -> bool:
        if not os.path.isdir(mod_source_dir):
            return True
        if used_archive_names is None:
            used_archive_names = set()
        from config.constants import DATA_FILE_EXTENSIONS
        xdelta_extensions = DATA_FILE_EXTENSIONS
        archive_extensions = ('.zip', '.7z', '.rar', '.tar.gz', '.lzma')
        for root, dirs, files in os.walk(mod_source_dir):
            for file in files:
                if file.lower() in ('config.json', '_icon.png'):
                    continue
                if file.lower().endswith(xdelta_extensions):
                    continue
                source_path = os.path.join(root, file)
                file_lower = file.lower()
                if file_lower.endswith(archive_extensions):
                    if is_modpack:
                        archive_name = os.path.basename(file)
                        target_archive_path = os.path.join(target_dir, archive_name)
                        if os.path.exists(target_archive_path):
                            from utils.file_utils import remove_archive_extension
                            base_name = remove_archive_extension(archive_name)
                            archive_name_lower = archive_name.lower()
                            if archive_name_lower.endswith('.tar.gz'):
                                ext = '.tar.gz'
                            elif archive_name_lower.endswith('.tar.lzma'):
                                ext = '.tar.lzma'
                            else:
                                _, ext = os.path.splitext(archive_name)
                            mod_index = 1
                            while os.path.exists(target_archive_path):
                                target_archive_name = f'{base_name}_mod{mod_index}{ext}'
                                target_archive_path = os.path.join(target_dir, target_archive_name)
                                mod_index += 1
                        self.patching_logger.debug(f'Copying archive: {archive_name} -> {os.path.basename(target_archive_path)}')
                        try:
                            shutil.copy2(source_path, target_archive_path)
                        except Exception as e:
                            self.patching_logger.error(f'Failed to copy archive {source_path}: {e}')
                            return False
                    else:
                        self.patching_logger.debug(f'Extracting archive contents: {os.path.basename(file)}')
                        if not self._extract_archive_to_target(source_path, target_dir):
                            self.patching_logger.warning(f'Failed to extract archive {source_path}, continuing...')
                    continue
                rel_path = os.path.relpath(source_path, mod_source_dir)
                target_path = os.path.join(target_dir, rel_path)
                if not is_modpack:
                    chapter_id = self._extract_chapter_id_from_path(target_dir)
                    is_new_file = not os.path.exists(target_path)
                    if not is_new_file:
                        if chapter_id is not None and self.backup_manager:
                            self.backup_manager.backup_file(chapter_id, target_path)
                    elif chapter_id is not None and self.backup_manager:
                        self.backup_manager.mark_file_added(chapter_id, target_path)
                        if self._session_manifest_path:
                            self.backup_manager.save_backups_to_manifest(self._session_manifest_path)
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                try:
                    shutil.copy2(source_path, target_path)
                except Exception as e:
                    self.patching_logger.error(f'Failed to copy override file {source_path}: {e}')
                    return False
        return True

    def _extract_archive_to_target(self, archive_path: str, target_dir: str) -> bool:
        try:
            from utils.file_utils import extract_any_archive
            import tempfile
            archive_lower = os.path.basename(archive_path).lower()
            chapter_id = self._extract_chapter_id_from_path(target_dir)
            with tempfile.TemporaryDirectory(prefix='mm_extract_') as temp_extract_dir:
                extract_any_archive(archive_path, temp_extract_dir)
                for root, dirs, files in os.walk(temp_extract_dir):
                    rel_root = os.path.relpath(root, temp_extract_dir)
                    if rel_root == '.':
                        rel_root = ''
                    for file in files:
                        source_file = os.path.join(root, file)
                        if rel_root:
                            target_file = os.path.join(target_dir, rel_root, file)
                        else:
                            target_file = os.path.join(target_dir, file)
                        target_dirname = os.path.dirname(target_file)
                        os.makedirs(target_dirname, exist_ok=True)
                        is_new_file = not os.path.exists(target_file)
                        if not is_new_file:
                            if chapter_id is not None and self.backup_manager:
                                self.backup_manager.backup_file(chapter_id, target_file)
                        elif chapter_id is not None and self.backup_manager:
                            self.backup_manager.mark_file_added(chapter_id, target_file)
                        shutil.copy2(source_file, target_file)
                if chapter_id is not None and self.backup_manager and (chapter_id in self.backup_manager.added_files):
                    if self._session_manifest_path:
                        self.backup_manager.save_backups_to_manifest(self._session_manifest_path)
            self.patching_logger.debug(f'Extracted archive: {archive_path}')
            return True
        except Exception as e:
            self.patching_logger.error(f'Failed to extract archive {archive_path}: {e}', exc_info=True)
            return False

    def _find_files_by_extension(self, directory: str, extensions: List[str], exact_names: Optional[List[str]] = None) -> List[str]:
        found_files = []
        if not os.path.isdir(directory):
            return found_files
        extensions_lower = [ext.lower() if not ext.startswith('.') else ext.lower() for ext in extensions]
        exact_names_lower = [name.lower() for name in exact_names] if exact_names else None
        for root, dirs, files in os.walk(directory):
            for file in files:
                file_lower = file.lower()
                if exact_names_lower and file_lower in exact_names_lower:
                    found_files.append(os.path.join(root, file))
                elif any((file_lower.endswith(ext) for ext in extensions_lower)):
                    found_files.append(os.path.join(root, file))
        return found_files

    def _find_data_patches(self, mod_source_dir: str) -> List[str]:
        return self._find_files_by_extension(mod_source_dir, ['.xdelta', '.vcdiff'])

    def _find_ready_data_win_files(self, mod_source_dir: str) -> List[str]:
        ready_files = []
        if not os.path.isdir(mod_source_dir):
            return ready_files
        data_file_names = [DATA_WIN_FILENAME, 'game.ios']
        main_files = self._find_files_by_extension(mod_source_dir, ['.win', '.ios'], data_file_names)
        for file_path in main_files:
            file_lower = os.path.basename(file_path).lower()
            if file_lower in [name.lower() for name in data_file_names]:
                ready_files.append(file_path)
                self.patching_logger.debug(f'Found ready data file: {file_path}')
            elif file_lower.endswith('.win') and file_lower != DATA_WIN_FILENAME.lower():
                ready_files.append(file_path)
                self.patching_logger.debug(f'Found ready .win file: {file_path}')
        info_datawinmod_dir = None
        if mod_source_dir:
            mod_root = os.path.dirname(mod_source_dir) if os.path.basename(mod_source_dir).startswith('chapter_') else mod_source_dir
            info_datawinmod_path = os.path.join(mod_root, 'INFO', 'datawinmod')
            if os.path.isdir(info_datawinmod_path):
                info_datawinmod_dir = info_datawinmod_path
                self.patching_logger.debug(f'Found INFO/datawinmod directory: {info_datawinmod_path}')
        if info_datawinmod_dir:
            chapter_name = os.path.basename(mod_source_dir)
            datawinmod_chapter_dir = os.path.join(info_datawinmod_dir, chapter_name)
            if os.path.isdir(datawinmod_chapter_dir):
                self.patching_logger.debug(f'Searching for ready files in INFO/datawinmod: {datawinmod_chapter_dir}')
                info_files = self._find_files_by_extension(datawinmod_chapter_dir, ['.win', '.ios'], data_file_names)
                ready_files.extend(info_files)
                for file_path in info_files:
                    self.patching_logger.debug(f'Found ready data file in INFO/datawinmod: {file_path}')
        self.patching_logger.info(f'_find_ready_data_win_files: found {len(ready_files)} ready data file(s) in {mod_source_dir}')
        return ready_files

    def _find_csx_scripts(self, mod_source_dir: str) -> List[str]:
        return self._find_files_by_extension(mod_source_dir, ['.csx'])

    def _detect_mod_type(self, mod_source_dir: str) -> Dict[str, bool]:
        mod_type = {'has_xdelta_patch': False, 'has_ready_data_win': False, 'has_csx_scripts': False, 'has_file_overrides': False}
        if not os.path.isdir(mod_source_dir):
            return mod_type
        patches = self._find_data_patches(mod_source_dir)
        if patches:
            mod_type['has_xdelta_patch'] = True
        ready_files = self._find_ready_data_win_files(mod_source_dir)
        if ready_files:
            mod_type['has_ready_data_win'] = True
        scripts = self._find_csx_scripts(mod_source_dir)
        if scripts:
            mod_type['has_csx_scripts'] = True
        has_other_files = False
        for root, dirs, files in os.walk(mod_source_dir):
            for file in files:
                file_lower = file.lower()
                if file_lower in ('config.json', '_icon.png'):
                    continue
                if file_lower.endswith(('.xdelta', '.vcdiff')):
                    continue
                if file_lower.endswith(('data.win', 'game.ios')):
                    continue
                if file_lower.endswith('.csx'):
                    continue
                has_other_files = True
                break
            if has_other_files:
                break
        if has_other_files:
            mod_type['has_file_overrides'] = True
        return mod_type

    def _detect_mod_asset_types(self, mod_dir: str) -> Dict[str, bool]:
        asset_types = {'has_code': False, 'has_textures': False, 'has_new_objects': False}
        objects_dir = os.path.join(mod_dir, 'Objects')
        if os.path.exists(objects_dir):
            code_entries_dir = os.path.join(objects_dir, 'CodeEntries')
            if os.path.exists(code_entries_dir):
                try:
                    if os.listdir(code_entries_dir):
                        asset_types['has_code'] = True
                except Exception:
                    pass
            sprites_dir = os.path.join(objects_dir, 'Sprites')
            backgrounds_dir = os.path.join(objects_dir, 'Backgrounds')
            fonts_dir = os.path.join(objects_dir, 'Fonts')
            if os.path.exists(sprites_dir) or os.path.exists(backgrounds_dir) or os.path.exists(fonts_dir):
                asset_types['has_textures'] = True
            new_objects_dir = os.path.join(objects_dir, 'NewObjects')
            if os.path.exists(new_objects_dir):
                try:
                    if os.listdir(new_objects_dir):
                        asset_types['has_new_objects'] = True
                except Exception:
                    pass
        else:
            data_win_path = os.path.join(mod_dir, 'data.win')
            if os.path.exists(data_win_path):
                asset_types['has_code'] = True
                asset_types['has_textures'] = True
                self.patching_logger.debug(f'Objects directory not found for {mod_dir}, assuming mod has code and textures (will be verified by SmartExport)')
        return asset_types

    def _select_export_strategy(self, mod_type: Dict[str, bool], mod_asset_types: Dict[str, bool], mod_number: int, has_previous_mod: bool) -> tuple[List[str], Optional[str]]:
        scripts = []
        comparison_file = None
        if mod_type.get('has_ready_data_win') and (not mod_type.get('has_xdelta_patch')) and (not mod_type.get('has_csx_scripts')):
            return ([], None)
        if mod_type.get('has_csx_scripts') and (not mod_type.get('has_xdelta_patch')):
            scripts.append('SmartExport')
            comparison_file = 'vanilla'
            return (scripts, comparison_file)
        if mod_type.get('has_xdelta_patch'):
            has_code = mod_asset_types.get('has_code', False)
            has_textures = mod_asset_types.get('has_textures', False)
            if has_textures and (not has_code):
                scripts.append('ExportAllTexturesGrouped')
                comparison_file = None
                return (scripts, comparison_file)
            if has_code:
                scripts.append('ExportAllCode')
                scripts.append('SmartExport')
                comparison_file = 'vanilla'
                return (scripts, comparison_file)
            scripts.append('SmartExport')
            comparison_file = 'vanilla'
            return (scripts, comparison_file)
        scripts.append('SmartExport')
        comparison_file = 'vanilla'
        return (scripts, comparison_file)

    def _check_critical_script_errors(self, stderr: str, script_name: str, context: str = '') -> None:
        if not stderr:
            return
        stderr_upper = stderr.upper()
        critical_patterns = ['COMPILATIONERROREXCEPTION', 'CS0103', 'CS8098', 'CS0234', 'CS0246', 'CS0006', 'CS0012']
        for pattern in critical_patterns:
            if pattern in stderr_upper:
                error_msg = f'КРИТИЧЕСКАЯ ОШИБКА: Ошибка компиляции в скрипте {script_name}'
                if context:
                    error_msg += f' ({context})'
                error_msg += f'\n\nДетали ошибки:\n{stderr[:1000]}'
                self.patching_logger.error(error_msg)
                raise RuntimeError(error_msg)
        cs_error_pattern = 'CS\\d{4}'
        if re.search(cs_error_pattern, stderr):
            error_msg = f'КРИТИЧЕСКАЯ ОШИБКА: Ошибка компиляции C# в скрипте {script_name}'
            if context:
                error_msg += f' ({context})'
            error_msg += f'\n\nДетали ошибки:\n{stderr[:1000]}'
            self.patching_logger.error(error_msg)
            raise RuntimeError(error_msg)

    def _export_mod_assets_optimized(self, mod_data_win: str, mod_number: int, scripts: List[str], comparison_file: Optional[str], vanilla_file: str, merge_root: str, cache_running_dir: str, chapter_str: str) -> bool:
        vanilla_backup = None
        try:
            mod_dir = os.path.dirname(mod_data_win)
            objects_dir = os.path.join(mod_dir, 'Objects')
            code_entries_dir = os.path.join(objects_dir, 'CodeEntries')
            os.makedirs(code_entries_dir, exist_ok=True)
            os.makedirs(os.path.join(objects_dir, 'Sprites'), exist_ok=True)
            os.makedirs(os.path.join(objects_dir, 'Backgrounds'), exist_ok=True)
            chapter_file = os.path.join(cache_running_dir, 'chapterNumber.txt')
            mod_file = os.path.join(cache_running_dir, 'modNumbersCache.txt')
            with open(chapter_file, 'w', encoding='utf-8') as f:
                f.write(chapter_str)
            with open(mod_file, 'w', encoding='utf-8') as f:
                f.write(str(mod_number))
            env = None
            if comparison_file and comparison_file == 'vanilla':
                env = os.environ.copy()
                env['SMARTEXPORT_VANILLA_PATH'] = vanilla_file
                self.patching_logger.debug(f'Setting SMARTEXPORT_VANILLA_PATH={vanilla_file} for mod {mod_number}')
            elif comparison_file and comparison_file == 'previous':
                mod_dir_path = os.path.dirname(mod_data_win)
                xdelta_combiner_dir = os.path.dirname(mod_dir_path)
                previous_mod_number = mod_number - 1
                if previous_mod_number >= 1 and os.path.exists(vanilla_file):
                    previous_mod_dir = os.path.join(xdelta_combiner_dir, str(previous_mod_number))
                    vanilla_filename = os.path.basename(vanilla_file)
                    previous_mod_data_win = os.path.join(previous_mod_dir, vanilla_filename)
                    if os.path.exists(previous_mod_data_win):
                        vanilla_backup = vanilla_file + '.backup'
                        if os.path.exists(vanilla_backup):
                            safe_remove(vanilla_backup)
                        shutil.copy2(vanilla_file, vanilla_backup)
                        shutil.copy2(previous_mod_data_win, vanilla_file)
                        self.patching_logger.info(f'Using previous mod {previous_mod_number} for incremental comparison (mod {mod_number})')
            if scripts:
                if self._cancelled:
                    return False
                returncode, stdout, stderr = self.utmt_wrapper.execute_scripts(mod_data_win, scripts, output_path=mod_data_win, cwd=merge_root, env=env)
                if 'SmartExport' in scripts:
                    try:
                        self._check_critical_script_errors(stderr, 'SmartExport', f'мод {mod_number}')
                    except RuntimeError:
                        self.patching_logger.error(f'Процесс слияния прерван из-за критической ошибки в SmartExport для мода {mod_number}')
                        raise
                if returncode != 0:
                    self.patching_logger.warning(f'Export scripts failed for mod {mod_number}: {stderr[:500]}')
                    return False
                self.patching_logger.info(f'Successfully exported assets from mod {mod_number} using {scripts}')
                if 'SmartExport' in scripts:
                    if stdout:
                        for line in stdout.split('\n'):
                            if '[SmartExport] Summary' in line or 'Total exports:' in line or 'NEW' in line or ('CHANGED' in line) or ('Loading comparison file' in line) or ('Using custom vanilla path' in line):
                                self.patching_logger.info(f'[SmartExport] {line.strip()}')
                    if stderr and ('ERROR' in stderr or 'Exception' in stderr):
                        self.patching_logger.warning(f'[SmartExport] stderr: {stderr[:500]}')
                    if os.path.exists(objects_dir):
                        code_entries_exported = os.path.join(objects_dir, 'CodeEntries')
                        sprites_exported = os.path.join(objects_dir, 'Sprites')
                        code_count_exported = len([f for f in os.listdir(code_entries_exported) if f.endswith('.gml')]) if os.path.exists(code_entries_exported) else 0
                        sprite_count_exported = len([d for d in os.listdir(sprites_exported) if os.path.isdir(os.path.join(sprites_exported, d))]) if os.path.exists(sprites_exported) else 0
                        self.patching_logger.info(f'[EXPORT] Verified: {code_count_exported} code files, {sprite_count_exported} sprites in Objects directory after SmartExport')
                        if code_count_exported == 0 and sprite_count_exported == 0:
                            self.patching_logger.warning(f'[EXPORT] WARNING: SmartExport exported 0 resources for mod {mod_number}! This may indicate a problem with comparison file or mod has no changes.')
                if self._cancelled:
                    return False
                export_rooms_script = self.utmt_wrapper.get_script_path('ExportRooms')
                if export_rooms_script:
                    returncode, stdout, stderr = self.utmt_wrapper.execute_scripts(mod_data_win, ['ExportRooms'], output_path=mod_data_win, cwd=merge_root)
                    if returncode != 0:
                        self.patching_logger.warning(f'ExportRooms failed for mod {mod_number}: {stderr[:500]}')
                    else:
                        self.patching_logger.info(f'Successfully exported rooms from mod {mod_number}')
                if self._cancelled:
                    return False
                export_shaders_script = self.utmt_wrapper.get_script_path('ExportShaders')
                if export_shaders_script:
                    returncode, stdout, stderr = self.utmt_wrapper.execute_scripts(mod_data_win, ['ExportShaders'], output_path=mod_data_win, cwd=merge_root)
                    if returncode != 0:
                        self.patching_logger.warning(f'ExportShaders failed for mod {mod_number}: {stderr[:500]}')
                export_tilesets_script = self.utmt_wrapper.get_script_path('ExportTilesets')
                if export_tilesets_script:
                    returncode, stdout, stderr = self.utmt_wrapper.execute_scripts(mod_data_win, ['ExportTilesets'], output_path=mod_data_win, cwd=merge_root)
                    if returncode != 0:
                        self.patching_logger.warning(f'ExportTilesets failed for mod {mod_number}: {stderr[:500]}')
                    else:
                        self.patching_logger.info(f'Successfully exported tilesets from mod {mod_number}')
                export_fonts_script = self.utmt_wrapper.get_script_path('ExportFonts')
                if export_fonts_script:
                    returncode, stdout, stderr = self.utmt_wrapper.execute_scripts(mod_data_win, ['ExportFonts'], output_path=mod_data_win, cwd=merge_root)
                    if returncode != 0:
                        self.patching_logger.warning(f'ExportFonts failed for mod {mod_number}: {stderr[:500]}')
                    else:
                        self.patching_logger.info(f'Successfully exported fonts from mod {mod_number}')
                export_sounds_script = self.utmt_wrapper.get_script_path('ExportSounds')
                if export_sounds_script:
                    returncode, stdout, stderr = self.utmt_wrapper.execute_scripts(mod_data_win, ['ExportSounds'], output_path=mod_data_win, cwd=merge_root)
                    if returncode != 0:
                        self.patching_logger.warning(f'ExportSounds failed for mod {mod_number}: {stderr[:500]}')
                    else:
                        self.patching_logger.info(f'Successfully exported sounds from mod {mod_number}')
                return True
            else:
                self.patching_logger.debug(f'Skipping export for mod {mod_number} (no scripts needed)')
                return True
        except Exception as e:
            self.patching_logger.error(f'Failed to export mod assets: {e}', exc_info=True)
            return False
        finally:
            if vanilla_backup and os.path.exists(vanilla_backup):
                try:
                    if os.path.exists(vanilla_file):
                        safe_remove(vanilla_file)
                    shutil.copy2(vanilla_backup, vanilla_file)
                    safe_remove(vanilla_backup)
                    self.patching_logger.debug(f'Restored vanilla file after incremental comparison for mod {mod_number}')
                except Exception as restore_error:
                    self.patching_logger.error(f'Failed to restore vanilla file: {restore_error}', exc_info=True)

    def _get_mod_source_dir(self, mod_data: Any, chapter_id: int) -> Optional[str]:
        mod_key = get_mod_key(mod_data)
        if not mod_key:
            self.patching_logger.warning('_get_mod_source_dir: mod_data has no mod_key')
            return None
        mod_folder_path = self.mod_manager.get_mod_folder_path(mod_key)
        if mod_folder_path and os.path.isdir(mod_folder_path):
            source_dir = mod_folder_path
        else:
            mod_name = get_mod_name(mod_data, mod_key)
            folder_name = sanitize_filename(mod_name)
            source_dir = os.path.join(self.app_state.mods_dir, folder_name)
            if not os.path.isdir(source_dir):
                source_dir = None
                if os.path.exists(self.app_state.mods_dir):
                    for folder_name in os.listdir(self.app_state.mods_dir):
                        folder_path = os.path.join(self.app_state.mods_dir, folder_name)
                        if not os.path.isdir(folder_path):
                            continue
                        config_path = os.path.join(folder_path, 'mod_config.json')
                        if os.path.exists(config_path):
                            try:
                                with open(config_path, 'r', encoding='utf-8') as f:
                                    import json
                                    config_data = json.load(f)
                                    if config_data.get('mod_key') == mod_key:
                                        source_dir = folder_path
                                        break
                            except Exception:
                                pass
                if not source_dir:
                    return None
        chapter_folder_name = {-1: 'demo', 0: 'chapter_0'}.get(chapter_id, f'chapter_{chapter_id}')
        chapter_dir = os.path.join(source_dir, chapter_folder_name)
        if not os.path.isdir(chapter_dir):
            if chapter_id == 0:
                alt_menu_dir = os.path.join(source_dir, 'menu')
                if os.path.isdir(alt_menu_dir):
                    return alt_menu_dir
            elif chapter_id == -1:
                return source_dir
            return None
        return chapter_dir

    def _get_target_dir(self, chapter_id: int) -> Optional[str]:
        base_path = self.app_state.game_mode.get_game_path(self.app_state.local_config)
        if not base_path:
            return None
        return find_chapter_resource_dir(base_path, chapter_id)

    def _find_data_win(self, target_dir: str) -> Optional[str]:
        import platform
        system = platform.system()
        if system == 'Darwin':
            ios_path = os.path.join(target_dir, 'game.ios')
            if os.path.exists(ios_path):
                return ios_path
        else:
            win_path = os.path.join(target_dir, DATA_WIN_FILENAME)
            if os.path.exists(win_path):
                return win_path
        return None

    def _extract_chapter_id_from_path(self, path: str) -> Optional[int]:
        import re
        match = re.search('chapter[_-]?(\\d+)', path, re.IGNORECASE)
        if match:
            return int(match.group(1))
        if 'demo' in path.lower():
            return -1
        return None

    def cleanup(self, force: bool = False) -> None:
        has_backups = False
        if self.backup_manager:
            has_backups = bool(self.backup_manager.original_files)
        if force or not has_backups:
            if self.temp_merge_dir and os.path.exists(self.temp_merge_dir):
                if safe_rmtree(self.temp_merge_dir):
                    self.patching_logger.info(f'Cleaned up temp merge directory: {self.temp_merge_dir}')
                else:
                    self.patching_logger.warning(f'Failed to cleanup temp merge dir {self.temp_merge_dir}')
            self.temp_merge_dir = None
        elif self.temp_merge_dir and os.path.exists(self.temp_merge_dir):
            try:
                for item in os.listdir(self.temp_merge_dir):
                    item_path = os.path.join(self.temp_merge_dir, item)
                    if item != 'backups':
                        if os.path.isdir(item_path):
                            if safe_rmtree(item_path):
                                self.patching_logger.debug(f'Removed temp directory: {item_path}')
                            else:
                                self.patching_logger.warning(f'Failed to remove temp directory {item_path}')
                        elif safe_remove(item_path):
                            self.patching_logger.debug(f'Removed temp file: {item_path}')
                        else:
                            self.patching_logger.warning(f'Failed to remove temp file {item_path}')
                self.patching_logger.info(f'Cleaned up temp files from merge directory, kept backups: {self.temp_merge_dir}')
            except Exception as e:
                self.patching_logger.warning(f'Failed to cleanup temp files from merge dir {self.temp_merge_dir}: {e}')

    def restore_all_backups(self) -> bool:
        if self.backup_manager:
            return self.backup_manager.restore_all_backups()
        import json
        if self._session_manifest_path and os.path.exists(self._session_manifest_path):
            try:
                with open(self._session_manifest_path, 'r', encoding='utf-8') as f:
                    manifest_data = json.load(f)
                backup_dir = manifest_data.get('multimod_backup_dir')
                original_files_data = manifest_data.get('original_files', {})
                added_files_data = manifest_data.get('added_files', {})
                multimod_backups = manifest_data.get('multimod_backups', {})
                if original_files_data or added_files_data:
                    if not backup_dir:
                        if self.temp_merge_dir:
                            backup_dir = os.path.join(self.temp_merge_dir, 'backups')
                    if backup_dir and os.path.exists(backup_dir):
                        self.patching_logger.info(f'Loading backup info from session manifest (new format): {len(original_files_data)} chapter(s) with original files, {len(added_files_data)} chapter(s) with added files')
                        backup_manager = BackupManager(backup_dir, patching_logger=self.patching_logger)
                        for chapter_key, files_dict in original_files_data.items():
                            chapter_id = int(chapter_key)
                            for file_path, backup_path in files_dict.items():
                                if backup_path is None or backup_path == 'null':
                                    backup_manager.original_files.setdefault(chapter_id, {})[file_path] = None
                                else:
                                    backup_manager.original_files.setdefault(chapter_id, {})[file_path] = backup_path
                        for chapter_key, file_list in added_files_data.items():
                            chapter_id = int(chapter_key)
                            if not isinstance(file_list, list):
                                continue
                            for file_path in file_list:
                                backup_manager.added_files.setdefault(chapter_id, {})[file_path] = True
                                if chapter_id not in backup_manager.original_files or file_path not in backup_manager.original_files[chapter_id]:
                                    backup_manager.original_files.setdefault(chapter_id, {})[file_path] = None
                        result = backup_manager.restore_all_backups()
                    else:
                        self.patching_logger.debug(f'Backup directory from manifest does not exist: {backup_dir}')
                        self.patching_logger.debug('Backups were already restored in previous session, cleaning up manifest')
                        if self._session_manifest_path and os.path.exists(self._session_manifest_path):
                            if safe_remove(self._session_manifest_path):
                                self.patching_logger.debug('Removed stale session manifest')
                            else:
                                self.patching_logger.debug('Failed to remove stale manifest')
                        return False
                elif multimod_backups and backup_dir:
                    self.patching_logger.info(f'Loading backup info from session manifest (old format): {len(multimod_backups)} chapter(s)')
                    if not os.path.exists(backup_dir):
                        self.patching_logger.debug(f'Backup directory from manifest does not exist: {backup_dir}')
                        self.patching_logger.debug('Backups were already restored in previous session, cleaning up manifest')
                        if self._session_manifest_path and os.path.exists(self._session_manifest_path):
                            if safe_remove(self._session_manifest_path):
                                self.patching_logger.debug('Removed stale session manifest')
                            else:
                                self.patching_logger.debug('Failed to remove stale manifest')
                        return False
                    backup_manager = BackupManager(backup_dir, patching_logger=self.patching_logger)
                    for chapter_key, files_dict in multimod_backups.items():
                        chapter_id = int(chapter_key)
                        for file_path, backup_path in files_dict.items():
                            if backup_path is None or backup_path == 'null':
                                backup_manager.original_files.setdefault(chapter_id, {})[file_path] = None
                            else:
                                backup_manager.original_files.setdefault(chapter_id, {})[file_path] = backup_path
                    result = backup_manager.restore_all_backups()
                else:
                    self.patching_logger.debug('No valid backup data found in manifest')
                    return False
                if self.temp_merge_dir and os.path.exists(self.temp_merge_dir):
                    if safe_rmtree(self.temp_merge_dir):
                        self.patching_logger.info('Cleaned up multi-mod merge directory and backups')
                    else:
                        self.patching_logger.warning('Failed to cleanup temp merge dir')
                if self._session_manifest_path and os.path.exists(self._session_manifest_path):
                    if safe_remove(self._session_manifest_path):
                        self.patching_logger.debug('Removed session manifest after backup restoration')
                    else:
                        self.patching_logger.debug('Failed to remove session manifest')
                return result
            except Exception as e:
                self.patching_logger.warning(f'Failed to load backups from manifest: {e}')
        self.patching_logger.debug('No backup files found to restore')
        return False
