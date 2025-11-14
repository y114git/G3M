import os
import shutil
import tempfile
import logging
import subprocess
from typing import Dict, List, Optional, Any
from PyQt6.QtCore import QObject, pyqtSignal
from managers.utmtcli_manager import UTMTCLIManager
from utils.path_utils import get_xdelta_path, find_chapter_resource_dir
from utils.file_utils import ensure_writable, sanitize_filename
from managers.localization_manager import tr
from utils.mod_utils import get_mod_key, get_mod_name


class MultiModMerger(QObject):
    status_update = pyqtSignal(str, str)
    progress_update = pyqtSignal(int, str)
    _session_manifest_path: Optional[str] = None

    def __init__(self, app_state, mod_manager, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.mod_manager = mod_manager
        self.utmtcli = UTMTCLIManager()
        self.xdelta_path = get_xdelta_path()
        logging.info(f'[MultiModMerger.__init__] xdelta_path initialized: {self.xdelta_path}')
        if self.xdelta_path:
            import platform
            if platform.system() != 'Windows':
                import stat
                if os.path.exists(self.xdelta_path):
                    file_stat = os.stat(self.xdelta_path)
                    is_executable = bool(file_stat.st_mode & stat.S_IEXEC)
                    logging.info(f'[MultiModMerger.__init__] xdelta permissions: {oct(file_stat.st_mode)} (executable: {is_executable})')
        self.temp_merge_dir = None
        self.backup_dir = None
        self.original_files = {}
        self.added_files = {}
        self._session_manifest_path = None
        self._cancelled = False

    def process_mod_merge(self, chapter_mods: Dict[int, List[Any]], is_modpack: bool, modpack_dir: Optional[str] = None) -> bool:
        import logging
        if is_modpack:
            logging.info(f'Starting modpack creation for {len(chapter_mods)} chapter(s)')
        else:
            logging.info(f'Starting multi-mod merge for {len(chapter_mods)} chapter(s)')
        for chapter_id, mods_list in chapter_mods.items():
            mod_names = [getattr(m, 'name', 'Unknown') for m in mods_list]
            logging.info(f'Chapter {chapter_id}: {len(mods_list)} mod(s) - {mod_names}')
        if not self.utmtcli.is_available():
            logging.error(f'UTMTCLI not available for platform: {self.utmtcli.get_platform()}')
            self.status_update.emit(tr('errors.utmtcli_not_available', platform=self.utmtcli.get_platform()), 'error')
            return False
        if is_modpack:
            logging.info('UTMTCLI is available, proceeding with modpack creation')
        else:
            logging.info('UTMTCLI is available, proceeding with merge')
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
            if is_modpack:
                self.temp_merge_dir = tempfile.mkdtemp(prefix='deltahub_modpack_')
            else:
                self.temp_merge_dir = tempfile.mkdtemp(prefix='deltahub_multimod_')
            self.backup_dir = os.path.join(self.temp_merge_dir, 'backups')
            os.makedirs(self.backup_dir, exist_ok=True)
            logging.info(f'Created temp merge directory: {self.temp_merge_dir}')
            current_progress += 5
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
                if self._cancelled:
                    if not is_modpack:
                        for cid in chapter_mods.keys():
                            self._restore_backups(cid)
                    return False
                chapter_index += 1
                chapter_progress_base = (chapter_index - 1) * (100 // total_chapters) if total_chapters > 0 else 0
                logging.info(f'Processing chapter {chapter_id} with {len(mods_list)} mod(s)')
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
                        logging.warning(f'Target directory not found for chapter {chapter_id}, skipping mods for this chapter in modpack')
                        continue
                    if not self._merge_mods_for_chapter_to_dir(chapter_id, mods_list, chapter_modpack_dir, chapter_progress_base, total_chapters):
                        logging.error(f'Failed to merge mods for chapter {chapter_id} in modpack')
                        try:
                            failed_msg = tr('status.merge_failed')
                        except BaseException:
                            failed_msg = 'Modpack creation failed'
                        self.progress_update.emit(0, failed_msg)
                        return False
                elif not self._merge_mods_for_chapter(chapter_id, mods_list, chapter_progress_base, total_chapters):
                    target_dir = self._get_target_dir(chapter_id)
                    if not target_dir:
                        logging.warning(f'Target directory not found for chapter {chapter_id}, skipping mods for this chapter. The game may not have this chapter installed.')
                        continue
                    logging.error(f'Failed to merge mods for chapter {chapter_id}, restoring backups')
                    self._restore_backups(chapter_id)
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
                    logging.info(f'Successfully processed mods for chapter {chapter_id}')
                else:
                    logging.info(f'Successfully merged mods for chapter {chapter_id}')
            try:
                completed_msg = tr('status.merge_completed')
            except BaseException:
                if is_modpack:
                    completed_msg = 'Modpack creation completed successfully'
                else:
                    completed_msg = 'Mod merge completed successfully'
            self.progress_update.emit(100, completed_msg)
            if is_modpack:
                logging.info('Modpack creation completed successfully')
                if self.temp_merge_dir and os.path.exists(self.temp_merge_dir):
                    try:
                        shutil.rmtree(self.temp_merge_dir)
                        logging.info(f'Cleaned up temp merge directory for modpack: {self.temp_merge_dir}')
                    except Exception as e:
                        logging.warning(f'Failed to cleanup temp merge dir for modpack {self.temp_merge_dir}: {e}')
                self.temp_merge_dir = None
                self.backup_dir = None
            else:
                logging.info('Multi-mod merge completed successfully')
                if self.temp_merge_dir and os.path.exists(self.temp_merge_dir):
                    try:
                        for item in os.listdir(self.temp_merge_dir):
                            item_path = os.path.join(self.temp_merge_dir, item)
                            if item != 'backups':
                                try:
                                    if os.path.isdir(item_path):
                                        shutil.rmtree(item_path)
                                        logging.debug(f'Removed temp directory: {item_path}')
                                    else:
                                        os.remove(item_path)
                                        logging.debug(f'Removed temp file: {item_path}')
                                except Exception as e:
                                    logging.warning(f'Failed to remove temp item {item_path}: {e}')
                        logging.info(f'Cleaned up temp files from merge directory, kept backups: {self.temp_merge_dir}')
                    except Exception as e:
                        logging.warning(f'Failed to cleanup temp files from merge dir {self.temp_merge_dir}: {e}')
            return True
        except Exception as e:
            if is_modpack:
                logging.error(f'Modpack creation failed: {e}', exc_info=True)
            else:
                logging.error(f'Multi-mod merge failed: {e}', exc_info=True)
            self.status_update.emit(tr('errors.merge_failed', error=str(e)), 'error')
            if not is_modpack:
                for chapter_id in chapter_mods.keys():
                    self._restore_backups(chapter_id)
            return False

    def _merge_mods_for_chapter(self, chapter_id: int, mods_list: List[Any], progress_base: int = 0, total_chapters: int = 1) -> bool:
        import logging
        logging.debug(f'_merge_mods_for_chapter: chapter_id={chapter_id}, mods_count={len(mods_list)}')
        target_dir = self._get_target_dir(chapter_id)
        if not target_dir:
            logging.error(f'Target directory not found for chapter {chapter_id}')
            return False
        logging.debug(f'Target directory: {target_dir}')
        if not ensure_writable(target_dir):
            self.status_update.emit(tr('errors.no_write_permission_for', path=target_dir), 'error')
            return False
        data_win_path = self._find_data_win(target_dir)
        if not data_win_path:
            return self._apply_file_overrides_only(chapter_id, mods_list, target_dir)
        if not self._backup_file(chapter_id, data_win_path):
            return False
        return self._perform_chapter_merge(chapter_id, mods_list, data_win_path, target_dir, None, progress_base, total_chapters, is_modpack=False)

    def _perform_chapter_merge(self, chapter_id: int, mods_list: List[Any], output_data_win_path: str, target_dir: str, modpack_dir: Optional[str], progress_base: int, total_chapters: int, is_modpack: bool) -> bool:
        import logging
        import platform
        original_data_win = output_data_win_path
        chapter_progress_range = 100 // total_chapters if total_chapters > 0 else 100
        xdelta_progress = chapter_progress_range * 0.3
        export_progress = chapter_progress_range * 0.3
        import_progress = chapter_progress_range * 0.4
        merge_root = self.temp_merge_dir
        if not merge_root:
            logging.error('Temp merge directory not set')
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
        logging.info(f'Created vanilla copy at {vanilla_data_win} (from {original_data_win})')
        max_mods = len(mods_list) + 2
        for mod_num in range(max_mods):
            mod_dir = os.path.join(xdelta_combiner_dir, str(mod_num))
            objects_code_dir = os.path.join(mod_dir, 'Objects', 'CodeEntries')
            os.makedirs(objects_code_dir, exist_ok=True)
        mods_to_apply = list(reversed(mods_list))
        mods_count = len(mods_to_apply)
        logging.info(f"Processing {mods_count} mod(s): {[getattr(m, 'name', 'Unknown') for m in mods_to_apply]}")
        logging.info(f"Highest priority mod (will be mod {mods_count}): {(getattr(mods_list[0], 'name', 'Unknown') if mods_list else 'None')}")
        mod_patched_files = {}
        if not is_modpack and mods_count == 1:
            mod_data = mods_to_apply[0]
            mod_name = getattr(mod_data, 'name', 'Unknown')
            mod_source_dir = self._get_mod_source_dir(mod_data, chapter_id)
            if mod_source_dir:
                ready_data_win_files = self._find_ready_data_win_files(mod_source_dir)
                data_patches = self._find_data_patches(mod_source_dir)
                csx_scripts = self._find_csx_scripts(mod_source_dir)
                if ready_data_win_files and (not data_patches) and (not csx_scripts):
                    logging.info(f'Single mod {mod_name} with only ready data.win/game.ios - copying directly')
                    ready_file = ready_data_win_files[0]
                    logging.info(f'Copying ready file: {ready_file} -> {output_data_win_path}')
                    try:
                        if os.path.exists(output_data_win_path):
                            extracted_chapter_id = self._extract_chapter_id_from_path(target_dir)
                            if extracted_chapter_id is not None:
                                self._backup_file(extracted_chapter_id, output_data_win_path)
                        shutil.copy2(ready_file, output_data_win_path)
                        logging.info(f'Copied ready data.win/game.ios from {mod_name} to {output_data_win_path}')
                        used_archive_names = set()
                        if not self._apply_file_overrides(mod_source_dir, target_dir, used_archive_names, False):
                            logging.warning(f'Failed to apply file overrides from {mod_name}')
                        return True
                    except Exception as e:
                        logging.error(f'Failed to copy ready data.win file: {e}', exc_info=True)
                        if not is_modpack:
                            self._restore_backups(chapter_id)
                        return False
        mods_already_exported = set()
        mod_types = {}
        for idx, mod_data in enumerate(mods_to_apply):
            if self._cancelled:
                return False
            mod_name = getattr(mod_data, 'name', 'Unknown')
            mod_number = mods_count - idx
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
                logging.warning(f'Mod source directory not found for {mod_name}, skipping')
                continue
            mod_type = self._detect_mod_type(mod_source_dir)
            mod_types[mod_number] = mod_type
            mod_dir = os.path.join(xdelta_combiner_dir, str(mod_number))
            os.makedirs(mod_dir, exist_ok=True)
            original_filename = os.path.basename(original_data_win)
            mod_data_win = os.path.join(mod_dir, original_filename)
            if mod_number > 1:
                previous_mod_number = mod_number - 1
                previous_mod_dir = os.path.join(xdelta_combiner_dir, str(previous_mod_number))
                previous_mod_data_win = os.path.join(previous_mod_dir, original_filename)
                if os.path.exists(previous_mod_data_win):
                    shutil.copy2(previous_mod_data_win, mod_data_win)
                else:
                    shutil.copy2(original_data_win, mod_data_win)
            else:
                shutil.copy2(original_data_win, mod_data_win)
            ready_data_win_files = self._find_ready_data_win_files(mod_source_dir)
            data_patches = self._find_data_patches(mod_source_dir)
            csx_scripts = self._find_csx_scripts(mod_source_dir)
            if ready_data_win_files:
                logging.info(f'Found {len(ready_data_win_files)} ready data.win/game.ios file(s) from {mod_name} (mod {mod_number}), merging')
                patch_progress = mod_progress_start + int(mod_progress_range * 0.5)
                self.progress_update.emit(min(patch_progress, 95), f'Merging ready data.win from {mod_name}...')
                if not self._handle_ready_data_win(mod_data_win, ready_data_win_files, mod_dir):
                    logging.error(f'Failed to merge ready data.win files from {mod_name}')
                    if not is_modpack:
                        self._restore_backups(chapter_id)
                    return False
                logging.info(f'Successfully merged ready data.win files from {mod_name} (mod {mod_number})')
                target_dir_result = self._get_target_dir(chapter_id)
                if target_dir_result is not None and mod_source_dir:
                    used_archive_names = set()
                    if not self._apply_file_overrides(mod_source_dir, target_dir_result, used_archive_names, False):
                        logging.warning(f'Failed to apply file overrides from {mod_name} after ready data.win merge')
                if not data_patches and (not csx_scripts):
                    mods_already_exported.add(mod_number)
                    logging.info(f'Mod {mod_name} (number {mod_number}) has only ready data.win, will skip ExportModifiedOnly')
                mod_patched_files[mod_number] = mod_data_win
            if data_patches:
                logging.info(f'Found {len(data_patches)} data patch(es) from {mod_name} (mod {mod_number}), applying to original')
                patch_progress = mod_progress_start + int(mod_progress_range * 0.3)
                self.progress_update.emit(min(patch_progress, 95), f'Applying patches from {mod_name}...')
                if not self._apply_xdelta_patches(mod_data_win, data_patches, progress_callback=lambda p: self.progress_update.emit(min(mod_progress_start + int(mod_progress_range * (0.3 + p * 0.4)), 95), f'Applying patches from {mod_name}...')):
                    logging.error(f'Failed to apply data patches from {mod_name}')
                    if not is_modpack:
                        self._restore_backups(chapter_id)
                    return False
                logging.info(f'Successfully applied data patches from {mod_name} (mod {mod_number})')
                mod_patched_files[mod_number] = mod_data_win
            if csx_scripts:
                logging.info(f'Found {len(csx_scripts)} CSX script(s) from {mod_name} (mod {mod_number}), executing')
                script_progress = mod_progress_start + int(mod_progress_range * 0.7)
                self.progress_update.emit(min(script_progress, 95), f'Executing scripts from {mod_name}...')
                if not self._apply_csx_scripts(mod_data_win, csx_scripts):
                    logging.error(f'Failed to execute CSX scripts from {mod_name}')
                    if not is_modpack:
                        self._restore_backups(chapter_id)
                    return False
                logging.info(f'Successfully executed CSX scripts from {mod_name} (mod {mod_number})')
                mod_patched_files[mod_number] = mod_data_win
            if not ready_data_win_files and (not data_patches) and (not csx_scripts):
                target_dir_result = self._get_target_dir(chapter_id)
                if target_dir_result is not None and mod_source_dir:
                    used_archive_names = set()
                    if self._apply_file_overrides(mod_source_dir, target_dir_result, used_archive_names, False):
                        logging.info(f'Applied file overrides from {mod_name} (mod {mod_number})')
            if mod_number not in mod_patched_files:
                mod_patched_files[mod_number] = mod_data_win
            self.progress_update.emit(min(mod_progress_end, 95), f'Completed {mod_name}')
        mods_to_export = [m for i, m in enumerate(mods_to_apply) if mods_count - i != 1 and mods_count - i not in mods_already_exported]
        for idx, mod_data in enumerate(mods_to_export):
            if self._cancelled:
                return False
            mod_name = getattr(mod_data, 'name', 'Unknown')
            original_idx = mods_to_apply.index(mod_data)
            mod_number = mods_count - original_idx
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
                logging.info(f'Skipping export for mod {mod_number} ({mod_name}) - already exported')
                continue
            logging.info(f'Exporting assets from mod {mod_number} ({mod_name}) using strategy: {scripts}, comparison: {comparison_file}')
            if not self._export_mod_assets_optimized(mod_data_win, mod_number, scripts, comparison_file, vanilla_data_win, merge_root, cache_running_dir, chapter_str):
                logging.warning(f'Failed to export assets from mod {mod_number} ({mod_name})')
        base_mod_number = 1
        base_mod_dir = os.path.join(xdelta_combiner_dir, str(base_mod_number))
        base_data_win = mod_patched_files.get(base_mod_number)
        if not base_data_win:
            original_filename = os.path.basename(original_data_win)
            base_data_win = os.path.join(base_mod_dir, original_filename)
            os.makedirs(base_mod_dir, exist_ok=True)
            shutil.copy2(original_data_win, base_data_win)
            mod_patched_files[base_mod_number] = base_data_win
        logging.info(f'Importing all assets into base file (mod {base_mod_number})')
        if base_mod_number in mod_patched_files:
            mod_1_patched = mod_patched_files.get(base_mod_number)
            if mod_1_patched and os.path.exists(mod_1_patched):
                if mod_1_patched != base_data_win:
                    shutil.copy2(mod_1_patched, base_data_win)
                    logging.info('Applied mod 1 xdelta to base file')
        chapter_file = os.path.join(cache_running_dir, 'chapterNumber.txt')
        with open(chapter_file, 'w', encoding='utf-8') as f:
            f.write(chapter_str)
        objects_dirs_to_import = []
        for idx, mod_data in enumerate(mods_to_apply):
            mod_name = getattr(mod_data, 'name', 'Unknown')
            mod_number = mods_count - idx
            if mod_number == 1:
                continue
            mod_dir = os.path.join(xdelta_combiner_dir, str(mod_number))
            objects_dir = os.path.join(mod_dir, 'Objects')
            if os.path.exists(objects_dir):
                objects_dirs_to_import.append((mod_number, mod_name, objects_dir))
            else:
                logging.warning(f'Objects directory not found for mod {mod_number} ({mod_name}), will try direct import')
                mod_source_dir = self._get_mod_source_dir(mod_data, chapter_id)
                if mod_source_dir:
                    logging.info(f'Importing assets directly from mod {mod_number} ({mod_name}) source directory (fallback)')
                    if not self._merge_assets_with_utmtcli(base_data_win, mod_source_dir):
                        logging.warning(f'Failed to import assets from mod {mod_number}, continuing...')
        base_mod_dir = os.path.join(xdelta_combiner_dir, str(base_mod_number))
        base_objects_dir = os.path.join(base_mod_dir, 'Objects')
        for idx, (mod_number, mod_name, objects_dir) in enumerate(reversed(objects_dirs_to_import)):
            if self._cancelled:
                if not is_modpack:
                    self._restore_backups(chapter_id)
                return False
            reverse_idx = len(objects_dirs_to_import) - 1 - idx
            import_step = reverse_idx / len(objects_dirs_to_import) * import_progress if objects_dirs_to_import else 0
            current_progress = progress_base + int(xdelta_progress + export_progress + import_step)
            try:
                import_msg = tr('status.importing_assets', mod=mod_name, current=reverse_idx + 1, total=len(objects_dirs_to_import))
            except BaseException:
                import_msg = f'Importing assets from {mod_name} ({reverse_idx + 1}/{len(objects_dirs_to_import)})...'
            self.progress_update.emit(min(current_progress, 95), import_msg)
            logging.info(f'Importing exported assets from mod {mod_number} ({mod_name}) into base file')
            temp_objects_in_base = os.path.join(base_mod_dir, 'Objects')
            if os.path.exists(temp_objects_in_base):
                self._merge_objects_directories(temp_objects_in_base, objects_dir)
            elif os.path.exists(objects_dir):
                shutil.copytree(objects_dir, temp_objects_in_base, dirs_exist_ok=True)
            if os.path.exists(temp_objects_in_base):
                if self._cancelled:
                    if not is_modpack:
                        self._restore_backups(chapter_id)
                    return False
                if not self._import_assets_from_objects_dir(base_data_win, temp_objects_in_base):
                    logging.warning(f'Failed to import assets from mod {mod_number}, continuing...')
        if self._cancelled:
            if not is_modpack:
                self._restore_backups(chapter_id)
            return False
        if os.path.exists(base_objects_dir):
            logging.debug(f'Final Objects directory in base: {base_objects_dir}')
        if is_modpack:
            if modpack_dir is None:
                logging.error('modpack_dir is None but is_modpack is True')
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
            logging.info(f'Copied merged data.win to {final_output_path}')
        except Exception as e:
            logging.error(f'Failed to copy merged data.win: {e}')
            if not is_modpack:
                self._restore_backups(chapter_id)
            return False
        if self._cancelled:
            if not is_modpack:
                self._restore_backups(chapter_id)
            return False
        if is_modpack:
            if modpack_dir is None:
                logging.error('modpack_dir is None but is_modpack is True')
                return False
            for mod_data in mods_to_apply:
                mod_source_dir = self._get_mod_source_dir(mod_data, chapter_id)
                if mod_source_dir:
                    if not self._apply_file_overrides(mod_source_dir, modpack_dir, set(), True):
                        logging.warning(f"Failed to apply file overrides from {getattr(mod_data, 'name', 'Unknown')}")
        else:
            used_archive_names = set()
            for mod_data in mods_to_apply:
                if self._cancelled:
                    self._restore_backups(chapter_id)
                    return False
                mod_source_dir = self._get_mod_source_dir(mod_data, chapter_id)
                if mod_source_dir:
                    if not self._apply_file_overrides(mod_source_dir, target_dir, used_archive_names, False):
                        logging.warning(f"Failed to apply file overrides from {getattr(mod_data, 'name', 'Unknown')}")
        logging.info('Multi-mod merge completed successfully')
        return True

    def _merge_mods_for_chapter_to_dir(self, chapter_id: int, mods_list: List[Any], modpack_dir: str, progress_base: int = 0, total_chapters: int = 1) -> bool:
        import logging
        logging.debug(f'_merge_mods_for_chapter_to_dir: chapter_id={chapter_id}, mods_count={len(mods_list)}, modpack_dir={modpack_dir}')
        os.makedirs(modpack_dir, exist_ok=True)
        target_dir = self._get_target_dir(chapter_id)
        if not target_dir:
            logging.error(f'Target directory not found for chapter {chapter_id}')
            return False
        logging.debug(f'Target directory: {target_dir}')
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
            logging.error('xdelta executable not found')
            self.status_update.emit(tr('errors.xdelta_not_found'), 'error')
            return False
        if not os.path.exists(self.xdelta_path):
            logging.error(f'xdelta path does not exist: {self.xdelta_path}')
            self.status_update.emit(tr('errors.xdelta_not_found'), 'error')
            return False
        if platform.system() != 'Windows':
            try:
                file_stat = os.stat(self.xdelta_path)
                is_executable = bool(file_stat.st_mode & stat.S_IEXEC)
                if not is_executable:
                    os.chmod(self.xdelta_path, 493)
            except Exception as e:
                logging.error(f'Failed to check/set xdelta permissions: {e}', exc_info=True)
        if not os.path.exists(data_win_path):
            logging.error(f'Input file does not exist: {data_win_path}')
            return False
        total_patches = len(data_patches)
        for idx, patch_path in enumerate(data_patches):
            if self._cancelled:
                return False
            logging.info(f'Applying xdelta patch {idx + 1}/{total_patches}: {os.path.basename(patch_path)}')
            if progress_callback:
                progress_callback(idx / total_patches if total_patches > 0 else 0)
            if not os.path.exists(patch_path):
                logging.error(f'Patch file does not exist: {patch_path}')
                self.status_update.emit(tr('errors.xdelta_patch_failed', patch=os.path.basename(patch_path)), 'error')
                return False
            try:
                temp_output = data_win_path + '.tmp'
                temp_dir = os.path.dirname(temp_output)
                if not os.access(temp_dir, os.W_OK):
                    logging.error(f'Temp directory is not writable: {temp_dir}')
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
                    logging.error(f'xdelta patch failed: {result.stderr}')
                    self.status_update.emit(tr('errors.xdelta_patch_failed', patch=os.path.basename(patch_path)), 'error')
                    return False
                if not os.path.exists(temp_output):
                    logging.error(f'Temp output file was not created: {temp_output}')
                    self.status_update.emit(tr('errors.xdelta_patch_failed', patch=os.path.basename(patch_path)), 'error')
                    return False
                shutil.move(temp_output, data_win_path)
                logging.info(f'Patch {idx + 1}/{total_patches} applied successfully')
            except subprocess.TimeoutExpired:
                logging.error(f'xdelta patch timed out after 300 seconds: {patch_path}')
                return False
            except Exception as e:
                logging.error(f'xdelta patch error: {e}', exc_info=True)
                return False
        logging.info('All patches applied successfully')
        return True

    def _apply_csx_scripts(self, data_win_path: str, csx_scripts: List[str]) -> bool:
        if not csx_scripts:
            return True
        if not self.utmtcli.is_available():
            logging.error('UTMTCLI not available for executing CSX scripts')
            self.status_update.emit(tr('errors.utmtcli_not_available', platform=self.utmtcli.get_platform()), 'error')
            return False
        for script_path in csx_scripts:
            if self._cancelled:
                return False
            try:
                logging.info(f'Executing CSX script: {os.path.basename(script_path)}')
                returncode, stdout, stderr = self.utmtcli.execute_with_scripts(data_win_path, [script_path], output_path=data_win_path, cwd=self.temp_merge_dir if self.temp_merge_dir else None)
                if returncode != 0:
                    logging.error(f'CSX script execution failed: {stderr[:500]}')
                    self.status_update.emit(tr('errors.csx_script_failed', script=os.path.basename(script_path)), 'error')
                    return False
                logging.info(f'Successfully executed CSX script: {os.path.basename(script_path)}')
            except Exception as e:
                logging.error(f'CSX script error: {e}')
                return False
        return True

    def _handle_ready_data_win(self, base_data_win: str, ready_data_win_files: List[str], mod_dir: Optional[str] = None) -> bool:
        if not ready_data_win_files:
            return True
        for ready_file in ready_data_win_files:
            if self._cancelled:
                return False
            try:
                logging.info(f'Merging ready data.win file: {os.path.basename(ready_file)}')
                if not self._merge_two_data_win_files(base_data_win, ready_file, mod_dir):
                    logging.error(f'Failed to merge ready data.win file: {ready_file}')
                    return False
                logging.info(f'Successfully merged ready data.win file: {os.path.basename(ready_file)}')
            except Exception as e:
                logging.error(f'Error merging ready data.win file: {e}')
                return False
        return True

    def _merge_assets_with_utmtcli(self, data_win_path: str, mod_source_dir: str) -> bool:
        if not self.temp_merge_dir:
            logging.error('Temp merge directory not set')
            return False
        try:
            asset_temp_dir = os.path.join(self.temp_merge_dir, 'assets_temp')
            os.makedirs(asset_temp_dir, exist_ok=True)
            has_assets = self._mod_has_assets(mod_source_dir)
            if not has_assets:
                return True
            import_graphics_script = self.utmtcli.get_script_path('ImportGraphics')
            if import_graphics_script:
                returncode, stdout, stderr = self.utmtcli.execute_with_scripts(data_win_path, ['ImportGraphics'], output_path=data_win_path, cwd=mod_source_dir)
                if returncode != 0:
                    logging.warning(f'ImportGraphics failed: {stderr}')
            import_gml_script = self.utmtcli.get_script_path('ImportGML')
            if import_gml_script:
                returncode, stdout, stderr = self.utmtcli.execute_with_scripts(data_win_path, ['ImportGML'], output_path=data_win_path, cwd=mod_source_dir)
                if returncode != 0:
                    logging.warning(f'ImportGML failed: {stderr}')
            import_asset_order_script = self.utmtcli.get_script_path('ImportAssetOrder')
            if import_asset_order_script:
                returncode, stdout, stderr = self.utmtcli.execute_with_scripts(data_win_path, ['ImportAssetOrder'], output_path=data_win_path, cwd=mod_source_dir)
                if returncode != 0:
                    logging.warning(f'ImportAssetOrder failed: {stderr}')
            return True
        except Exception as e:
            logging.error(f'UTMTCLI asset merge failed: {e}', exc_info=True)
            return False

    def _import_assets_from_objects_dir(self, data_win_path: str, objects_dir: str) -> bool:
        import logging
        try:
            if not os.path.exists(objects_dir):
                logging.debug(f'Objects directory does not exist: {objects_dir}')
                return False
            data_win_dir = os.path.dirname(data_win_path)
            expected_objects_dir = os.path.join(data_win_dir, 'Objects')
            if objects_dir != expected_objects_dir:
                logging.warning(f'Objects directory is not next to data.win! Expected: {expected_objects_dir}, Got: {objects_dir}')
                if os.path.exists(expected_objects_dir):
                    self._merge_objects_directories(expected_objects_dir, objects_dir)
                else:
                    shutil.copytree(objects_dir, expected_objects_dir, dirs_exist_ok=True)
                objects_dir = expected_objects_dir
            sprites_dir = os.path.join(objects_dir, 'Sprites')
            backgrounds_dir = os.path.join(objects_dir, 'Backgrounds')
            has_graphics = os.path.exists(sprites_dir) or os.path.exists(backgrounds_dir)
            code_entries_dir = os.path.join(objects_dir, 'CodeEntries')
            has_gml = bool(os.path.exists(code_entries_dir) and os.listdir(code_entries_dir))
            asset_order_path = os.path.join(objects_dir, 'AssetOrder.txt')
            has_asset_order = os.path.exists(asset_order_path)
            if not (has_graphics or has_gml or has_asset_order):
                logging.debug(f'Objects directory has no assets to import: {objects_dir}')
                return True
            import_graphics_script = self.utmtcli.get_script_path('ImportGraphics')
            if import_graphics_script and has_graphics:
                logging.debug(f'Importing graphics from {objects_dir}')
                returncode, stdout, stderr = self.utmtcli.execute_with_scripts(data_win_path, ['ImportGraphics'], output_path=data_win_path, cwd=data_win_dir)
                if returncode != 0:
                    logging.warning(f'ImportGraphics failed: {stderr[:300]}')
                else:
                    logging.info('Successfully imported graphics from Objects directory')
            import_gml_script = self.utmtcli.get_script_path('ImportGML')
            if import_gml_script and has_gml:
                logging.debug(f'Importing GML from {objects_dir}')
                returncode, stdout, stderr = self.utmtcli.execute_with_scripts(data_win_path, ['ImportGML'], output_path=data_win_path, cwd=data_win_dir)
                if returncode != 0:
                    logging.warning(f'ImportGML failed: {stderr[:300]}')
                else:
                    logging.info('Successfully imported GML from Objects directory')
            import_asset_order_script = self.utmtcli.get_script_path('ImportAssetOrder')
            if import_asset_order_script and has_asset_order:
                logging.debug(f'Importing asset order from {objects_dir}')
                returncode, stdout, stderr = self.utmtcli.execute_with_scripts(data_win_path, ['ImportAssetOrder'], output_path=data_win_path, cwd=data_win_dir)
                if returncode != 0:
                    logging.warning(f'ImportAssetOrder failed: {stderr[:300]}')
                else:
                    logging.info('Successfully imported asset order from Objects directory')
            return True
        except Exception as e:
            logging.error(f'Failed to import assets from Objects directory: {e}', exc_info=True)
            return False

    def _merge_objects_directories(self, target_objects_dir: str, source_objects_dir: str) -> None:
        if not os.path.exists(source_objects_dir):
            return
        os.makedirs(target_objects_dir, exist_ok=True)
        source_sprites = os.path.join(source_objects_dir, 'Sprites')
        target_sprites = os.path.join(target_objects_dir, 'Sprites')
        if os.path.exists(source_sprites):
            if os.path.exists(target_sprites):
                for root, dirs, files in os.walk(source_sprites):
                    rel_path = os.path.relpath(root, source_sprites)
                    target_path = os.path.join(target_sprites, rel_path)
                    os.makedirs(target_path, exist_ok=True)
                    for file in files:
                        src_file = os.path.join(root, file)
                        dst_file = os.path.join(target_path, file)
                        shutil.copy2(src_file, dst_file)
            else:
                shutil.copytree(source_sprites, target_sprites, dirs_exist_ok=True)
        source_backgrounds = os.path.join(source_objects_dir, 'Backgrounds')
        target_backgrounds = os.path.join(target_objects_dir, 'Backgrounds')
        if os.path.exists(source_backgrounds):
            if os.path.exists(target_backgrounds):
                for root, dirs, files in os.walk(source_backgrounds):
                    rel_path = os.path.relpath(root, source_backgrounds)
                    target_path = os.path.join(target_backgrounds, rel_path)
                    os.makedirs(target_path, exist_ok=True)
                    for file in files:
                        src_file = os.path.join(root, file)
                        dst_file = os.path.join(target_path, file)
                        shutil.copy2(src_file, dst_file)
            else:
                shutil.copytree(source_backgrounds, target_backgrounds, dirs_exist_ok=True)
        source_code = os.path.join(source_objects_dir, 'CodeEntries')
        target_code = os.path.join(target_objects_dir, 'CodeEntries')
        if os.path.exists(source_code):
            if os.path.exists(target_code):
                for file in os.listdir(source_code):
                    src_file = os.path.join(source_code, file)
                    dst_file = os.path.join(target_code, file)
                    if os.path.isfile(src_file):
                        shutil.copy2(src_file, dst_file)
            else:
                shutil.copytree(source_code, target_code, dirs_exist_ok=True)
        source_asset_order = os.path.join(source_objects_dir, 'AssetOrder.txt')
        target_asset_order = os.path.join(target_objects_dir, 'AssetOrder.txt')
        if os.path.exists(source_asset_order):
            shutil.copy2(source_asset_order, target_asset_order)
        source_new_objects = os.path.join(source_objects_dir, 'NewObjects')
        target_new_objects = os.path.join(target_objects_dir, 'NewObjects')
        if os.path.exists(source_new_objects):
            if os.path.exists(target_new_objects):
                shutil.rmtree(target_new_objects)
            shutil.copytree(source_new_objects, target_new_objects, dirs_exist_ok=True)

    def _merge_two_data_win_files(self, base_file: str, other_file: str, mod_dir: Optional[str] = None) -> bool:
        if not self.temp_merge_dir:
            logging.error('Temp merge directory not set')
            return False
        try:
            merge_temp_dir = os.path.join(self.temp_merge_dir, 'merge_temp')
            os.makedirs(merge_temp_dir, exist_ok=True)
            export_script = self.utmtcli.get_script_path('ExportModifiedOnly')
            if export_script:
                export_temp = os.path.join(merge_temp_dir, 'other_export')
                os.makedirs(export_temp, exist_ok=True)
                returncode, stdout, stderr = self.utmtcli.execute_with_scripts(other_file, ['ExportModifiedOnly'], cwd=export_temp)
                if returncode == 0:
                    if mod_dir:
                        export_objects_dir = os.path.join(export_temp, 'Objects')
                        mod_objects_dir = os.path.join(mod_dir, 'Objects')
                        if os.path.exists(export_objects_dir):
                            if os.path.exists(mod_objects_dir):
                                self._merge_objects_directories(mod_objects_dir, export_objects_dir)
                            else:
                                shutil.copytree(export_objects_dir, mod_objects_dir)
                            logging.info(f'Copied exported objects to {mod_objects_dir} for later import')
                    scripts_to_run = []
                    if self.utmtcli.get_script_path('ImportGraphics'):
                        scripts_to_run.append('ImportGraphics')
                    if self.utmtcli.get_script_path('ImportGML'):
                        scripts_to_run.append('ImportGML')
                    if self.utmtcli.get_script_path('ImportAssetOrder'):
                        scripts_to_run.append('ImportAssetOrder')
                    if scripts_to_run:
                        returncode, stdout, stderr = self.utmtcli.execute_with_scripts(base_file, scripts_to_run, output_path=base_file, cwd=export_temp)
                        if returncode == 0:
                            logging.info('Successfully merged two data.win files using UTMTCLI scripts')
                            return True
            logging.error('UTMTCLI merge failed: Cannot merge data.win files')
            logging.error('Fallback copy would overwrite base_file and lose previous mod changes')
            logging.error('This mod cannot be merged and will be skipped to prevent data loss')
            return False
        except Exception as e:
            logging.error(f'Failed to merge two data.win files: {e}', exc_info=True)
            logging.error('Cannot use fallback copy as it would cause irreversible data loss')
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
                        logging.debug(f'Copying archive: {archive_name} -> {os.path.basename(target_archive_path)}')
                        try:
                            shutil.copy2(source_path, target_archive_path)
                        except Exception as e:
                            logging.error(f'Failed to copy archive {source_path}: {e}')
                            return False
                    else:
                        logging.debug(f'Extracting archive contents: {os.path.basename(file)}')
                        if not self._extract_archive_to_target(source_path, target_dir):
                            logging.warning(f'Failed to extract archive {source_path}, continuing...')
                    continue
                rel_path = os.path.relpath(source_path, mod_source_dir)
                target_path = os.path.join(target_dir, rel_path)
                if not is_modpack:
                    chapter_id = self._extract_chapter_id_from_path(target_dir)
                    is_new_file = not os.path.exists(target_path)
                    if not is_new_file:
                        if chapter_id is not None:
                            self._backup_file(chapter_id, target_path)
                    elif chapter_id is not None:
                        if chapter_id not in self.added_files:
                            self.added_files[chapter_id] = set()
                        self.added_files[chapter_id].add(target_path)
                        self._save_backups_to_manifest()
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                try:
                    shutil.copy2(source_path, target_path)
                except Exception as e:
                    logging.error(f'Failed to copy override file {source_path}: {e}')
                    return False
        return True

    def _extract_archive_to_target(self, archive_path: str, target_dir: str) -> bool:
        import zipfile
        import tarfile
        import logging
        try:
            archive_lower = archive_path.lower()
            chapter_id = self._extract_chapter_id_from_path(target_dir)
            if archive_lower.endswith('.zip'):
                with zipfile.ZipFile(archive_path, 'r') as zf:
                    for member in zf.namelist():
                        if member.endswith('/'):
                            continue
                        target_file = os.path.join(target_dir, member)
                        is_new_file = not os.path.exists(target_file)
                        if not is_new_file:
                            if chapter_id is not None:
                                self._backup_file(chapter_id, target_file)
                        elif chapter_id is not None:
                            if chapter_id not in self.added_files:
                                self.added_files[chapter_id] = set()
                            self.added_files[chapter_id].add(target_file)
                    zf.extractall(target_dir)
                    if chapter_id is not None and chapter_id in self.added_files:
                        self._save_backups_to_manifest()
                logging.debug(f'Extracted ZIP archive: {archive_path}')
                return True
            elif archive_lower.endswith('.tar.gz'):
                with tarfile.open(archive_path, 'r:gz') as tf:
                    for member in tf.getmembers():
                        if member.isdir():
                            continue
                        target_file = os.path.join(target_dir, member.name)
                        is_new_file = not os.path.exists(target_file)
                        if not is_new_file:
                            if chapter_id is not None:
                                self._backup_file(chapter_id, target_file)
                        elif chapter_id is not None:
                            if chapter_id not in self.added_files:
                                self.added_files[chapter_id] = set()
                            self.added_files[chapter_id].add(target_file)
                    tf.extractall(target_dir)
                    if chapter_id is not None and chapter_id in self.added_files:
                        self._save_backups_to_manifest()
                logging.debug(f'Extracted TAR.GZ archive: {archive_path}')
                return True
            elif archive_lower.endswith('.rar'):
                try:
                    import rarfile
                    with rarfile.RarFile(archive_path, 'r') as rf:
                        for member in rf.namelist():
                            if member.endswith('/'):
                                continue
                            target_file = os.path.join(target_dir, member)
                            is_new_file = not os.path.exists(target_file)
                            if not is_new_file:
                                if chapter_id is not None:
                                    self._backup_file(chapter_id, target_file)
                            elif chapter_id is not None:
                                if chapter_id not in self.added_files:
                                    self.added_files[chapter_id] = set()
                                self.added_files[chapter_id].add(target_file)
                        rf.extractall(target_dir)
                        if chapter_id is not None and chapter_id in self.added_files:
                            self._save_backups_to_manifest()
                    logging.debug(f'Extracted RAR archive: {archive_path}')
                    return True
                except ImportError:
                    logging.warning('rarfile not available, cannot extract RAR archive')
                    return False
            elif archive_lower.endswith('.7z'):
                try:
                    import py7zr
                    with py7zr.SevenZipFile(archive_path, mode='r') as zf:
                        file_list = zf.getnames()
                        for member in file_list:
                            target_file = os.path.join(target_dir, member)
                            is_new_file = not os.path.exists(target_file)
                            if not is_new_file:
                                if chapter_id is not None:
                                    self._backup_file(chapter_id, target_file)
                            elif chapter_id is not None:
                                if chapter_id not in self.added_files:
                                    self.added_files[chapter_id] = set()
                                self.added_files[chapter_id].add(target_file)
                        zf.extractall(path=target_dir)
                        if chapter_id is not None and chapter_id in self.added_files:
                            self._save_backups_to_manifest()
                    logging.debug(f'Extracted 7Z archive: {archive_path}')
                    return True
                except ImportError:
                    logging.warning('py7zr not available, cannot extract 7Z archive')
                    return False
            elif archive_lower.endswith('.lzma'):
                try:
                    import lzma
                    target_file = os.path.join(target_dir, os.path.basename(archive_path)[:-5])
                    is_new_file = not os.path.exists(target_file)
                    if not is_new_file:
                        if chapter_id is not None:
                            self._backup_file(chapter_id, target_file)
                    elif chapter_id is not None:
                        if chapter_id not in self.added_files:
                            self.added_files[chapter_id] = set()
                        self.added_files[chapter_id].add(target_file)
                        self._save_backups_to_manifest()
                    with lzma.open(archive_path, 'rb') as lzma_file:
                        with open(target_file, 'wb') as out_file:
                            out_file.write(lzma_file.read())
                    logging.debug(f'Extracted LZMA file: {archive_path}')
                    return True
                except Exception as e:
                    logging.warning(f'Failed to extract LZMA file: {e}')
                    return False
            else:
                logging.warning(f'Unknown archive format: {archive_path}')
                return False
        except Exception as e:
            logging.error(f'Failed to extract archive {archive_path}: {e}', exc_info=True)
            return False

    def _find_data_patches(self, mod_source_dir: str) -> List[str]:
        patches = []
        if not os.path.isdir(mod_source_dir):
            return patches
        for root, dirs, files in os.walk(mod_source_dir):
            for file in files:
                if file.lower().endswith(('.xdelta', '.vcdiff')):
                    patches.append(os.path.join(root, file))
        return patches

    def _find_ready_data_win_files(self, mod_source_dir: str) -> List[str]:
        ready_files = []
        if not os.path.isdir(mod_source_dir):
            return ready_files
        data_file_names = ['data.win', 'game.ios']
        info_datawinmod_dir = None
        if mod_source_dir:
            mod_root = os.path.dirname(mod_source_dir) if os.path.basename(mod_source_dir).startswith('chapter_') else mod_source_dir
            info_datawinmod_path = os.path.join(mod_root, 'INFO', 'datawinmod')
            if os.path.isdir(info_datawinmod_path):
                info_datawinmod_dir = info_datawinmod_path
                logging.debug(f'Found INFO/datawinmod directory: {info_datawinmod_path}')
        for root, dirs, files in os.walk(mod_source_dir):
            for file in files:
                file_lower = file.lower()
                if file_lower in [name.lower() for name in data_file_names]:
                    ready_files.append(os.path.join(root, file))
                    logging.debug(f'Found ready data file: {os.path.join(root, file)}')
                elif file_lower.endswith('.win') and file_lower != 'data.win':
                    ready_files.append(os.path.join(root, file))
                    logging.debug(f'Found ready .win file: {os.path.join(root, file)}')
        if info_datawinmod_dir:
            chapter_name = os.path.basename(mod_source_dir)
            datawinmod_chapter_dir = os.path.join(info_datawinmod_dir, chapter_name)
            if os.path.isdir(datawinmod_chapter_dir):
                logging.debug(f'Searching for ready files in INFO/datawinmod: {datawinmod_chapter_dir}')
                for root, dirs, files in os.walk(datawinmod_chapter_dir):
                    for file in files:
                        file_lower = file.lower()
                        if file_lower in [name.lower() for name in data_file_names] or file_lower.endswith('.win'):
                            ready_files.append(os.path.join(root, file))
                            logging.debug(f'Found ready data file in INFO/datawinmod: {os.path.join(root, file)}')
        logging.info(f'_find_ready_data_win_files: found {len(ready_files)} ready data file(s) in {mod_source_dir}')
        return ready_files

    def _find_csx_scripts(self, mod_source_dir: str) -> List[str]:
        scripts = []
        if not os.path.isdir(mod_source_dir):
            return scripts
        for root, dirs, files in os.walk(mod_source_dir):
            for file in files:
                if file.lower().endswith('.csx'):
                    scripts.append(os.path.join(root, file))
        return scripts

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
        if not os.path.exists(objects_dir):
            return asset_types
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
        return asset_types

    def _select_export_strategy(self, mod_type: Dict[str, bool], mod_asset_types: Dict[str, bool], mod_number: int, has_previous_mod: bool) -> tuple[List[str], Optional[str]]:
        scripts = []
        comparison_file = None
        if mod_type.get('has_ready_data_win') and (not mod_type.get('has_xdelta_patch')) and (not mod_type.get('has_csx_scripts')):
            return ([], None)
        if mod_type.get('has_csx_scripts') and (not mod_type.get('has_xdelta_patch')):
            scripts.append('ExportModifiedOnly')
            comparison_file = 'previous' if has_previous_mod else 'vanilla'
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
                scripts.append('ExportModifiedOnly')
                comparison_file = 'previous' if has_previous_mod else 'vanilla'
                return (scripts, comparison_file)
            scripts.append('ExportModifiedOnly')
            comparison_file = 'previous' if has_previous_mod else 'vanilla'
            return (scripts, comparison_file)
        scripts.append('ExportModifiedOnly')
        comparison_file = 'previous' if has_previous_mod else 'vanilla'
        return (scripts, comparison_file)

    def _export_mod_assets_optimized(self, mod_data_win: str, mod_number: int, scripts: List[str], comparison_file: Optional[str], vanilla_file: str, merge_root: str, cache_running_dir: str, chapter_str: str) -> bool:
        import logging
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
            if comparison_file and comparison_file == 'previous':
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
                            os.remove(vanilla_backup)
                        shutil.copy2(vanilla_file, vanilla_backup)
                        shutil.copy2(previous_mod_data_win, vanilla_file)
                        logging.info(f'Using previous mod {previous_mod_number} for incremental comparison (mod {mod_number})')
            if scripts:
                returncode, stdout, stderr = self.utmtcli.execute_with_scripts(mod_data_win, scripts, output_path=mod_data_win, cwd=merge_root)
                if returncode != 0:
                    logging.warning(f'Export scripts failed for mod {mod_number}: {stderr[:500]}')
                    return False
                logging.info(f'Successfully exported assets from mod {mod_number} using {scripts}')
                return True
            else:
                logging.debug(f'Skipping export for mod {mod_number} (no scripts needed)')
                return True
        except Exception as e:
            logging.error(f'Failed to export mod assets: {e}', exc_info=True)
            return False
        finally:
            if vanilla_backup and os.path.exists(vanilla_backup):
                try:
                    if os.path.exists(vanilla_file):
                        os.remove(vanilla_file)
                    shutil.copy2(vanilla_backup, vanilla_file)
                    os.remove(vanilla_backup)
                    logging.debug(f'Restored vanilla file after incremental comparison for mod {mod_number}')
                except Exception as restore_error:
                    logging.error(f'Failed to restore vanilla file: {restore_error}', exc_info=True)

    def _get_mod_source_dir(self, mod_data: Any, chapter_id: int) -> Optional[str]:
        mod_key = get_mod_key(mod_data)
        if not mod_key:
            logging.warning('_get_mod_source_dir: mod_data has no mod_key')
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
            win_path = os.path.join(target_dir, 'data.win')
            if os.path.exists(win_path):
                return win_path
        return None

    def _backup_file(self, chapter_id: int, file_path: str) -> bool:
        if not os.path.exists(file_path):
            return True
        if chapter_id not in self.original_files:
            self.original_files[chapter_id] = {}
        if file_path in self.original_files[chapter_id]:
            return True
        if not self.backup_dir:
            logging.error('Backup directory not set')
            return False
        try:
            import hashlib
            import time
            file_path_abs = os.path.abspath(file_path)
            path_hash = hashlib.sha256(file_path_abs.encode('utf-8')).hexdigest()[:16]
            timestamp = int(time.time() * 1000000)
            file_basename = sanitize_filename(os.path.basename(file_path))
            backup_filename = f'chapter_{chapter_id}_{file_basename}_{path_hash}_{timestamp}'
            backup_path = os.path.join(self.backup_dir, backup_filename)
            shutil.copy2(file_path, backup_path)
            self.original_files[chapter_id][file_path] = backup_path
            self._save_backups_to_manifest()
            return True
        except Exception as e:
            logging.error(f'Failed to backup file {file_path}: {e}')
            return False

    def _save_backups_to_manifest(self) -> None:
        if not self._session_manifest_path:
            return
        try:
            import json
            manifest_data = {}
            if os.path.exists(self._session_manifest_path):
                try:
                    with open(self._session_manifest_path, 'r', encoding='utf-8') as f:
                        manifest_data = json.load(f)
                except Exception:
                    pass
            multimod_backups = {}
            for chapter_id, files_dict in self.original_files.items():
                chapter_key = str(chapter_id)
                multimod_backups[chapter_key] = {}
                for file_path, backup_path in files_dict.items():
                    multimod_backups[chapter_key][file_path] = backup_path
            multimod_added_files = {}
            for chapter_id, files_set in self.added_files.items():
                chapter_key = str(chapter_id)
                multimod_added_files[chapter_key] = list(files_set)
            manifest_data['multimod_backups'] = multimod_backups
            manifest_data['multimod_added_files'] = multimod_added_files
            manifest_data['multimod_backup_dir'] = self.backup_dir
            manifest_data['multimod_temp_dir'] = self.temp_merge_dir
            temp_path = self._session_manifest_path + '.tmp'
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(manifest_data, f, ensure_ascii=False, indent=2)
            if os.path.exists(self._session_manifest_path):
                os.replace(temp_path, self._session_manifest_path)
            else:
                shutil.move(temp_path, self._session_manifest_path)
        except Exception as e:
            logging.warning(f'Failed to save backups to manifest: {e}')

    def _restore_backups(self, chapter_id: int) -> None:
        if chapter_id not in self.original_files:
            return
        for file_path, backup_path in self.original_files[chapter_id].items():
            if os.path.exists(backup_path):
                try:
                    shutil.copy2(backup_path, file_path)
                    logging.info(f'Restored backup: {file_path}')
                except Exception as e:
                    logging.error(f'Failed to restore backup {backup_path}: {e}')

    def _extract_chapter_id_from_path(self, path: str) -> Optional[int]:
        import re
        match = re.search('chapter[_-]?(\\d+)', path, re.IGNORECASE)
        if match:
            return int(match.group(1))
        if 'demo' in path.lower():
            return -1
        return None

    def cleanup(self, force: bool = False) -> None:
        if force or not self.original_files:
            if self.temp_merge_dir and os.path.exists(self.temp_merge_dir):
                try:
                    shutil.rmtree(self.temp_merge_dir)
                    logging.info(f'Cleaned up temp merge directory: {self.temp_merge_dir}')
                except Exception as e:
                    logging.warning(f'Failed to cleanup temp merge dir {self.temp_merge_dir}: {e}')
            self.temp_merge_dir = None
            self.backup_dir = None
        elif self.temp_merge_dir and os.path.exists(self.temp_merge_dir):
            try:
                for item in os.listdir(self.temp_merge_dir):
                    item_path = os.path.join(self.temp_merge_dir, item)
                    if item != 'backups':
                        try:
                            if os.path.isdir(item_path):
                                shutil.rmtree(item_path)
                                logging.debug(f'Removed temp directory: {item_path}')
                            else:
                                os.remove(item_path)
                                logging.debug(f'Removed temp file: {item_path}')
                        except Exception as e:
                            logging.warning(f'Failed to remove temp item {item_path}: {e}')
                logging.info(f'Cleaned up temp files from merge directory, kept backups: {self.temp_merge_dir}')
            except Exception as e:
                logging.warning(f'Failed to cleanup temp files from merge dir {self.temp_merge_dir}: {e}')

    def restore_all_backups(self) -> bool:
        import json
        success = True
        files_restored = 0
        if not self.original_files and self._session_manifest_path and os.path.exists(self._session_manifest_path):
            try:
                with open(self._session_manifest_path, 'r', encoding='utf-8') as f:
                    manifest_data = json.load(f)
                multimod_backups = manifest_data.get('multimod_backups', {})
                multimod_added_files = manifest_data.get('multimod_added_files', {})
                backup_dir = manifest_data.get('multimod_backup_dir')
                if multimod_backups and backup_dir:
                    logging.info(f'Loading backup info from session manifest: {len(multimod_backups)} chapter(s)')
                    if not os.path.exists(backup_dir):
                        logging.debug(f'Backup directory from manifest does not exist: {backup_dir}')
                        logging.debug('Backups were already restored in previous session, cleaning up manifest')
                        try:
                            if os.path.exists(self._session_manifest_path):
                                os.remove(self._session_manifest_path)
                                logging.debug('Removed stale session manifest')
                        except Exception as e:
                            logging.debug(f'Failed to remove stale manifest: {e}')
                        return False
                    self.backup_dir = backup_dir
                    for chapter_key, files_dict in multimod_backups.items():
                        chapter_id = int(chapter_key)
                        self.original_files[chapter_id] = files_dict
                    for chapter_key, files_list in multimod_added_files.items():
                        chapter_id = int(chapter_key)
                        self.added_files[chapter_id] = set(files_list)
            except Exception as e:
                logging.warning(f'Failed to load backups from manifest: {e}')
        if not self.original_files:
            logging.debug('No backup files found to restore (original_files is empty)')
            return False
        logging.info(f'Restoring backups for {len(self.original_files)} chapter(s)')
        for chapter_id, files_dict in self.original_files.items():
            logging.debug(f'Chapter {chapter_id}: {len(files_dict)} file(s) to restore')
            for file_path, backup_path in files_dict.items():
                if not os.path.exists(backup_path):
                    logging.warning(f'Backup file not found: {backup_path} (original: {file_path})')
                    continue
                try:
                    target_dir = os.path.dirname(file_path)
                    if target_dir and (not os.path.exists(target_dir)):
                        os.makedirs(target_dir, exist_ok=True)
                    shutil.copy2(backup_path, file_path)
                    logging.info(f'Restored backup: {file_path}')
                    files_restored += 1
                except Exception as e:
                    logging.error(f'Failed to restore backup {backup_path} to {file_path}: {e}', exc_info=True)
                    success = False
        files_removed = 0
        for chapter_id, added_files_set in self.added_files.items():
            logging.debug(f'Chapter {chapter_id}: {len(added_files_set)} added file(s) to remove')
            for file_path in added_files_set:
                if os.path.exists(file_path):
                    try:
                        if os.path.isfile(file_path):
                            os.remove(file_path)
                            logging.info(f'Removed added file: {file_path}')
                            files_removed += 1
                        elif os.path.isdir(file_path):
                            try:
                                os.rmdir(file_path)
                                logging.info(f'Removed empty added directory: {file_path}')
                                files_removed += 1
                            except OSError:
                                logging.debug(f'Added directory not empty, leaving: {file_path}')
                    except Exception as e:
                        logging.warning(f'Failed to remove added file {file_path}: {e}')
        logging.info(f'Restored {files_restored} file(s) from backups, removed {files_removed} added file(s)')
        if self.temp_merge_dir and os.path.exists(self.temp_merge_dir):
            try:
                shutil.rmtree(self.temp_merge_dir)
                logging.info('Cleaned up multi-mod merge directory and backups')
            except Exception as e:
                logging.warning(f'Failed to cleanup temp merge dir: {e}')
        if self._session_manifest_path and os.path.exists(self._session_manifest_path):
            try:
                os.remove(self._session_manifest_path)
                logging.debug('Removed session manifest after backup restoration')
            except Exception as e:
                logging.debug(f'Failed to remove session manifest: {e}')
        self.original_files = {}
        self.added_files = {}
        self.backup_dir = None
        self.temp_merge_dir = None
        return success and (files_restored > 0 or files_removed > 0)
