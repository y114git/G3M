"""Multi-mod merging and patching system."""
import os
import platform
import shutil
import tempfile
import subprocess
import time
import re
import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Any
from PyQt6.QtCore import QObject, pyqtSignal, QTimer
from services.backup_service import BackupManager
from adapters.utmt_adapter import UtmtWrapper
from utils.path_utils import get_xdelta_path, find_chapter_resource_dir
from utils.file_utils import ensure_writable, sanitize_filename, safe_remove, safe_move, safe_rmtree, safe_copy, get_chapter_folder_name
from config.constants import DATA_WIN_FILENAME
from services.localization_service import tr
from utils.mod_utils import get_mod_key, get_mod_name
from services.patching_log_service import get_patching_logger, get_conflicts_logger, rotate_conflicts_log


class ProgressThrottler(QObject):
    """Throttles progress updates to avoid overwhelming the UI."""

    def __init__(self, callback, throttle_ms: int = 150, parent=None):
        super().__init__(parent)
        self.callback = callback
        self.throttle_ms = throttle_ms
        self._pending_progress = None
        self._pending_message = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._emit_pending_update)
        self._lock = threading.Lock()

    def update_progress(self, progress: int, message: str):
        with self._lock:
            self._pending_progress = progress
            self._pending_message = message
            if not self._timer.isActive():
                self._timer.start(self.throttle_ms)

    def _emit_pending_update(self):
        with self._lock:
            if self._pending_progress is not None and self._pending_message is not None:
                self.callback(self._pending_progress, self._pending_message)
                self._pending_progress = None
                self._pending_message = None

    def flush(self):
        self._timer.stop()
        self._emit_pending_update()


class MultiModMerger(QObject):
    status_update = pyqtSignal(str, str)
    progress_update = pyqtSignal(int, str)
    warning_confirmation_needed = pyqtSignal(str, str, str)
    _session_manifest_path: Optional[str] = None

    _EXPORT_SCRIPT_CONFIGS = [
        ('ExportSprites', 'Sprites'), ('ExportBackgrounds', 'Backgrounds'),
        ('ExportShaders', 'Shaders'), ('ExportFonts', 'Fonts'),
        ('ExportSounds', 'Sounds'), ('ExportCodeEntries', 'CodeEntries'),
        ('ExportTilesets', 'Tilesets'), ('ExportRooms', 'Rooms'),
        ('ExportGameObjects', 'GameObjects'), ('ExportPaths', 'Paths'),
        ('ExportTimelines', 'Timelines'), ('ExportAudioGroups', 'AudioGroups'),
        ('ExportTextureGroupInfo', 'TextureGroups'), ('ExportExtensions', 'Extensions'),
        ('ExportGeneralInfo', 'GeneralInfo'),
    ]
    _IMPORT_SCRIPT_CONFIGS = [
        ('ImportGeneralInfo', 'GeneralInfo'), ('ImportAudioGroups', 'AudioGroups'),
        ('ImportTextureGroupInfo', 'TextureGroups'), ('ImportSprites', 'Sprites'),
        ('ImportBackgrounds', 'Backgrounds'), ('ImportFonts', 'Fonts'),
        ('ImportSounds', 'Sounds'), ('ImportPaths', 'Paths'),
        ('ImportTilesets', 'Tilesets'), ('ImportShaders', 'Shaders'),
        ('ImportTimelines', 'Timelines'), ('ImportGameObjects', 'GameObjects'),
        ('ImportRooms', 'Rooms'), ('ImportCodeEntries', 'CodeEntries'),
        ('ImportExtensions', 'Extensions'),
    ]

    def __init__(self, app_state, mod_service, parent=None):
        super().__init__(parent)
        self.patching_logger = get_patching_logger()
        self.conflicts_logger = get_conflicts_logger()
        self.detected_conflicts: List[Dict[str, Any]] = []
        self._conflicts_log_rotated_this_session: bool = False
        self._mod_exported_code_files: Dict[int, set] = {}
        self.app_state = app_state
        self.mod_service = mod_service
        self.utmt_wrapper = UtmtWrapper(patching_logger=self.patching_logger)
        self.xdelta_path = get_xdelta_path()
        self.patching_logger.info(f'[MultiModMerger.__init__] xdelta_path initialized: {self.xdelta_path}')
        if self.xdelta_path:
            if platform.system() != 'Windows':
                import stat
                if os.path.exists(self.xdelta_path):
                    file_stat = os.stat(self.xdelta_path)
                    is_executable = bool(file_stat.st_mode & stat.S_IEXEC)
                    self.patching_logger.info(f'[MultiModMerger.__init__] xdelta permissions: {oct(file_stat.st_mode)} (executable: {is_executable})')
        self.temp_merge_dir = None
        self.backup_service: Optional[BackupManager] = None
        self._cancelled = False
        self.resource_modification_history: Dict[str, List[Dict[str, Any]]] = {}
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

    def _run_export_scripts(self, scripts: List[str], data_win: str, objects_dir: str, cwd: str, label: str = '') -> bool:
        all_ok = True
        for script_name, subdir in self._EXPORT_SCRIPT_CONFIGS:
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
        for script_name, subdir in self._IMPORT_SCRIPT_CONFIGS:
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

    @staticmethod
    def _resolve_macos_path(base_path: str, app_name: str) -> str:
        if platform.system() != 'Darwin':
            return base_path
        if base_path.endswith('.app'):
            return os.path.join(base_path, 'Contents', 'Resources')
        app_path = os.path.join(base_path, app_name)
        if os.path.isdir(app_path):
            return os.path.join(app_path, 'Contents', 'Resources')
        return base_path

    def _run_xdelta_process(self, input_file: str, patch_path: str, output_file: str) -> tuple:
        cmd = [self.xdelta_path, '-d', '-s', input_file, patch_path, output_file]
        startupinfo = None
        creationflags = 0
        if platform.system() == 'Windows':
            import subprocess as sp
            startupinfo = sp.STARTUPINFO()
            startupinfo.dwFlags |= sp.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = sp.SW_HIDE
            creationflags = sp.CREATE_NO_WINDOW
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, stdin=subprocess.DEVNULL, startupinfo=startupinfo, creationflags=creationflags)
        self._active_processes.append(process)
        try:
            stdout, stderr = process.communicate(timeout=300)
            returncode = process.returncode
        finally:
            if process in self._active_processes:
                self._active_processes.remove(process)
        return returncode, stdout, stderr

    def _ensure_xdelta_executable(self) -> bool:
        if not self.xdelta_path or not os.path.exists(self.xdelta_path):
            return False
        import stat
        if platform.system() != 'Windows':
            try:
                file_stat = os.stat(self.xdelta_path)
                if not bool(file_stat.st_mode & stat.S_IEXEC):
                    os.chmod(self.xdelta_path, 493)
            except Exception as e:
                self.patching_logger.error(f'Failed to check/set xdelta permissions: {e}', exc_info=True)
        return True

    def _log_resource_counts(self, objects_dir: str, label: str) -> tuple:
        code_dir = os.path.join(objects_dir, 'CodeEntries')
        sprites_dir = os.path.join(objects_dir, 'Sprites')
        code_count = len([f for f in os.listdir(code_dir) if f.endswith('.gml')]) if os.path.exists(code_dir) else 0
        sprite_count = len([d for d in os.listdir(sprites_dir) if os.path.isdir(os.path.join(sprites_dir, d))]) if os.path.exists(sprites_dir) else 0
        shaders_dir = os.path.join(objects_dir, 'Shaders')
        shader_count = len([d for d in os.listdir(shaders_dir) if os.path.isdir(os.path.join(shaders_dir, d))]) if os.path.exists(shaders_dir) else 0
        self.patching_logger.info(f'{label}: {code_count} code, {sprite_count} sprites, {shader_count} shaders')
        return code_count, sprite_count, shader_count

    def _cleanup_temp_dir(self, keep_backups: bool = False) -> None:
        if not self.temp_merge_dir or not os.path.exists(self.temp_merge_dir):
            return
        if not keep_backups:
            if safe_rmtree(self.temp_merge_dir):
                self.patching_logger.info(f'Cleaned up temp merge directory: {self.temp_merge_dir}')
            else:
                self.patching_logger.warning(f'Failed to cleanup temp merge dir {self.temp_merge_dir}')
            self.temp_merge_dir = None
        else:
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

    def _track_mod_history(self, resource_name: str, resource_type: str, mod_name: str, action: str = 'merged') -> None:
        if mod_name in ('0', 'vanilla', 'unknown_mod'):
            return
        if resource_name not in self.resource_modification_history:
            self.resource_modification_history[resource_name] = []
        existing_mods = [h['mod'] for h in self.resource_modification_history[resource_name]]
        if mod_name not in existing_mods:
            self.resource_modification_history[resource_name].append({'type': resource_type, 'mod': mod_name, 'action': action, 'timestamp': time.time()})

    def _log_conflict(self, resource_type: str, resource_name: str, prev_mods: List[str], current_mod: str) -> None:
        prev_filtered = [m for m in prev_mods if m not in ('0', 'vanilla', 'unknown_mod', 'merged_mods', current_mod)]
        prev_unique = list(dict.fromkeys(prev_filtered))
        if not prev_unique:
            return
        conflict_msg = f'''{resource_type.capitalize()} "{resource_name}" was modified by: {', '.join(prev_unique)} before "{current_mod}". Higher priority mod ({current_mod}) will be used.'''
        self.patching_logger.warning(f'[CONFLICT] {conflict_msg}')
        self._rotate_conflicts_log_if_needed()
        self.conflicts_logger.info(f'''Resource: {resource_type.capitalize()} "{resource_name}" | Conflict between: {', '.join(prev_unique)} vs "{current_mod}" | Resolution: Using "{current_mod}" (higher priority)''')
        self.detected_conflicts.append({'resource_type': resource_type, 'resource_name': resource_name, 'mods': prev_unique + [current_mod], 'resolution': current_mod})

    def _rotate_conflicts_log_if_needed(self):
        if not self._conflicts_log_rotated_this_session:
            rotate_conflicts_log()
            self._conflicts_log_rotated_this_session = True
            self.conflicts_logger = get_conflicts_logger()

    def _show_patching_warning(self, warning_type: str, title: str, message: str) -> bool:
        self.patching_logger.warning(f'[PATCHING_WARNING] {warning_type}: {message}')
        if self.app_state.local_config.get('skip_patching_warnings', False):
            self.patching_logger.info(f'[PATCHING_WARNING] Skipping warning (skip_patching_warnings enabled): {warning_type}')
            return True
        if self._warning_callback:
            return self._warning_callback(warning_type, title, message)
        return True

    def _track_exported_assets(self, objects_dir: str, mod_name: str, existing_code_files: Dict, existing_assets: Dict) -> None:
        _ASSET_CONFIGS = [
            ('CodeEntries', '.gml', 'code_files', False),
            ('Sprites', None, 'sprites', True),
            ('Backgrounds', '.png', 'backgrounds', False),
            ('Tilesets', '.json', 'tilesets', False),
            ('Shaders', None, 'shaders', True),
        ]
        for subdir, ext, asset_key, is_dir_check in _ASSET_CONFIGS:
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

    def _ensure_modpack_dir(self, modpack_dir: Optional[str]) -> bool:
        if modpack_dir is None:
            self.patching_logger.error('modpack_dir is None but is_modpack is True')
            return False
        return True

    def process_mod_merge(self, chapter_mods: Dict[int, List[Any]], is_modpack: bool, modpack_dir: Optional[str] = None, fast_merge: bool = False, xdelta_modpack: bool = False) -> bool:
        self.xdelta_modpack = xdelta_modpack
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
            merge_msg = self._safe_tr('status.preparing_mod_merge', f'Preparing to merge {total_mods} mod(s) for {total_chapters} chapter(s)...', chapters=total_chapters, mods=total_mods)
            self.progress_update.emit(0, merge_msg)
            try:
                if is_modpack:
                    self.temp_merge_dir = tempfile.mkdtemp(prefix='deltahub_modpack_')
                else:
                    self.temp_merge_dir = tempfile.mkdtemp(prefix='deltahub_multimod_')
                backup_dir = os.path.join(self.temp_merge_dir, 'backups')
                self.backup_service = BackupManager(backup_dir, patching_logger=self.patching_logger)
                self.patching_logger.info(f'Created temp merge directory: {self.temp_merge_dir}')
                current_progress += 5
            except Exception as e:
                self.patching_logger.error(f'Failed to create temp merge directory: {e}', exc_info=True)
                self.status_update.emit(tr('errors.temp_dir_creation_failed'), 'error')
                return False
            merge_msg = self._safe_tr('status.merging_mods', f'Merging mods... {current_progress}%', progress=current_progress)
            self.progress_update.emit(min(current_progress, 95), merge_msg)
            chapter_index = 0
            for chapter_id, mods_list in sorted(chapter_mods.items()):
                if not mods_list:
                    continue
                if is_modpack and chapter_id == -1:
                    continue
                if self._cancelled:
                    if not is_modpack:
                        for cid in chapter_mods.keys():
                            self.backup_service.restore_backups(cid)
                    return False
                chapter_index += 1
                chapter_progress_base = (chapter_index - 1) * (100 // total_chapters) if total_chapters > 0 else 0
                self.patching_logger.info(f'Processing chapter {chapter_id} with {len(mods_list)} mod(s)')
                from config.constants import SLOT_ID_CHAPTER_1, SLOT_ID_CHAPTER_2, SLOT_ID_CHAPTER_3, SLOT_ID_CHAPTER_4
                is_actual_chapter = chapter_id in (SLOT_ID_CHAPTER_1, SLOT_ID_CHAPTER_2, SLOT_ID_CHAPTER_3, SLOT_ID_CHAPTER_4)
                if is_actual_chapter:
                    chapter_msg = self._safe_tr('status.merging_chapter', f'Merging chapter {chapter_id} ({chapter_index}/{total_chapters})...', chapter=chapter_id, current=chapter_index, total=total_chapters)
                else:
                    progress_pct = min(chapter_progress_base + 5, 95)
                    chapter_msg = self._safe_tr('status.merging_mods', f'Merging mods... {progress_pct}%', progress=progress_pct)
                self.progress_update.emit(min(chapter_progress_base + 5, 95), chapter_msg)
                if is_modpack and modpack_dir:
                    game = None
                    if mods_list:
                        first_mod = mods_list[0]
                        game = getattr(first_mod, 'modgame', None)
                        if not game and hasattr(first_mod, 'config_data'):
                            config = getattr(first_mod, 'config_data')
                            if isinstance(config, dict):
                                game = config.get('game') or config.get('modgame')
                        if not game:
                            game = getattr(first_mod, 'game', None)
                    chapter_folder_name = get_chapter_folder_name(chapter_id, game=game)
                    chapter_modpack_dir = os.path.join(modpack_dir, chapter_folder_name)
                    if not self._merge_mods_for_chapter_to_dir(chapter_id, mods_list, chapter_modpack_dir, chapter_progress_base, total_chapters, fast_merge=fast_merge, game=game):
                        self.patching_logger.error(f'Failed to merge mods for chapter {chapter_id} in modpack')
                        failed_msg = self._safe_tr('status.merge_failed', 'Modpack creation failed')
                        self.progress_update.emit(0, failed_msg)
                        return False
                elif not self._merge_mods_for_chapter(chapter_id, mods_list, chapter_progress_base, total_chapters, fast_merge=fast_merge):
                    target_dir = self._get_target_dir(chapter_id)
                    if not target_dir:
                        self.patching_logger.warning(f'Target directory not found for chapter {chapter_id}, skipping mods for this chapter. The game may not have this chapter installed.')
                        continue
                    self.patching_logger.error(f'Failed to merge mods for chapter {chapter_id}, restoring backups')
                    if self.backup_service:
                        self.backup_service.restore_backups(chapter_id)
                    data_modifying_count = 0
                    for mod_data in mods_list:
                        mod_source_dir = self._get_mod_source_dir(mod_data, chapter_id)
                        if mod_source_dir:
                            mod_type = self._detect_mod_type(mod_source_dir)
                            if mod_type.get('has_xdelta_patch') or mod_type.get('has_ready_data_win') or mod_type.get('has_csx_scripts'):
                                data_modifying_count += 1
                    is_fast_path = not is_modpack and data_modifying_count <= 1
                    if is_fast_path and len(mods_list) == 1:
                        mod_name = getattr(mods_list[0], 'name', 'Unknown')
                        failed_msg = self._safe_tr('errors.mod_patch_failed_single', f'Failed to apply mod {mod_name}', mod_name=mod_name)
                    else:
                        failed_msg = self._safe_tr('status.merge_failed', 'Mod merge failed')
                    self.status_update.emit(failed_msg, 'error')
                    self.progress_update.emit(0, failed_msg)
                    return False
                chapter_progress = chapter_index * (100 // total_chapters) if total_chapters > 0 else 100
                merged_msg = self._safe_tr('status.chapter_merged', f'Chapter {chapter_id} merged successfully', chapter=chapter_id)
                self.progress_update.emit(min(chapter_progress, 95), merged_msg)
                if is_modpack:
                    self.patching_logger.info(f'Successfully processed mods for chapter {chapter_id}')
                else:
                    self.patching_logger.info(f'Successfully merged mods for chapter {chapter_id}')
                    if self.backup_service and self._session_manifest_path:
                        self.backup_service.save_backups_to_manifest(self._session_manifest_path)
            completed_msg = self._safe_tr('status.merge_completed', 'Mod merge completed successfully')
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
                    if self.backup_service:
                        self.backup_service.restore_backups(chapter_id)
            return False
        finally:
            if hasattr(self, 'temp_merge_dir') and self.temp_merge_dir and os.path.exists(self.temp_merge_dir):
                if is_modpack:
                    if not safe_rmtree(self.temp_merge_dir):
                        self.patching_logger.warning(f'Failed to cleanup temp merge dir in finally block: {self.temp_merge_dir}')
                    self.temp_merge_dir = None

    def _merge_mods_for_chapter(self, chapter_id: int, mods_list: List[Any], progress_base: int = 0, total_chapters: int = 1, fast_merge: bool = False) -> bool:
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
            expected_path = os.path.join(target_dir, 'data.win')
            warning_msg = tr('dialogs.patching_warning.data_win_not_found', search_path=expected_path)
            if not self._show_patching_warning('data_win_not_found', tr('dialogs.patching_warning.title'), warning_msg):
                self.patching_logger.info(f'[PATCHING_WARNING] User cancelled merge due to missing data.win at: {expected_path}')
                return False
            return self._apply_file_overrides_only(chapter_id, mods_list, target_dir)
        if not self.backup_service.backup_file(chapter_id, data_win_path):
            return False
        return self._perform_chapter_merge(chapter_id, mods_list, data_win_path, target_dir, None, progress_base, total_chapters, is_modpack=False, fast_merge=fast_merge)

    def _perform_chapter_merge(self, chapter_id: int, mods_list: List[Any], output_data_win_path: str, target_dir: str, modpack_dir: Optional[str], progress_base: int, total_chapters: int, is_modpack: bool, fast_merge: bool = False) -> bool:
        original_data_win = output_data_win_path
        if not mods_list or len(mods_list) == 0:
            self.patching_logger.info(f'[OPTIMIZATION] No mods to apply for chapter {chapter_id}, skipping')
            return True
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
        cache_running_dir = os.path.join(output_dir, 'DeltahubCache', 'running')
        os.makedirs(cache_running_dir, exist_ok=True)
        chapter_str = str(chapter_id)
        xdelta_combiner_dir = os.path.join(output_dir, 'DeltahubMergeWorkspace', chapter_str)
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
                mod_type = self._detect_mod_type(mod_source_dir)
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
                    ready_data_win_files = self._find_ready_data_win_files(mod_source_dir)
                    data_patches = self._find_data_patches(mod_source_dir)
                    csx_scripts = self._find_csx_scripts(mod_source_dir)
                    if ready_data_win_files and (not data_patches) and (not csx_scripts):
                        self.patching_logger.info(f'[FAST_PATH] Mod {mod_name} with only ready data.win/game.ios - copying directly')
                        ready_file = ready_data_win_files[0]
                        self.patching_logger.info(f'[FAST_PATH] Copying ready file: {ready_file} -> {output_data_win_path} (chapter {chapter_id})')
                        try:
                            extracted_chapter_id = self._extract_chapter_id_from_path(target_dir)
                            if extracted_chapter_id is not None:
                                self.patching_logger.info(f'[FAST_PATH] Creating backup before replacing data.win (chapter {extracted_chapter_id})')
                                if not self.backup_service.backup_file(extracted_chapter_id, output_data_win_path):
                                    self.patching_logger.error(f'[FAST_PATH] Failed to create backup of {output_data_win_path} before replacement')
                                    if not is_modpack:
                                        self.backup_service.restore_backups(chapter_id)
                                    return False
                            else:
                                self.patching_logger.warning(f'[FAST_PATH] Could not extract chapter ID from path {target_dir}, backup may not work correctly')
                            shutil.copyfile(ready_file, output_data_win_path)
                            file_size = os.path.getsize(output_data_win_path) if os.path.exists(output_data_win_path) else 0
                            self.patching_logger.info(f'[FAST_PATH] Successfully copied ready data.win/game.ios from {mod_name} to {output_data_win_path} (size: {file_size} bytes, chapter {chapter_id})')
                        except Exception as e:
                            self.patching_logger.error(f'[FAST_PATH] Failed to copy ready data.win file from {mod_name}: {e}', exc_info=True)
                            error_msg = str(e)[:200] if len(str(e)) > 200 else str(e)
                            self.status_update.emit(tr('errors.mod_patch_failed', mod_name=mod_name, error=error_msg), 'error')
                            if not is_modpack:
                                self.backup_service.restore_backups(chapter_id)
                            return False
                    elif data_patches and (not ready_data_win_files) and (not csx_scripts):
                        self.patching_logger.info(f'[FAST_PATH] Mod {mod_name} with only xdelta patch(es) - applying directly')
                        try:
                            if os.path.exists(output_data_win_path):
                                extracted_chapter_id = self._extract_chapter_id_from_path(target_dir)
                                if extracted_chapter_id is not None:
                                    self.backup_service.backup_file(extracted_chapter_id, output_data_win_path)
                            if not self._apply_xdelta_patches(output_data_win_path, data_patches, progress_callback=lambda p: self.progress_update.emit(min(int(p * 50), 95), f'Applying patch from {mod_name}...')):
                                self.patching_logger.error(f'[FAST_PATH] Failed to apply xdelta patches from {mod_name}')
                                if not is_modpack:
                                    self.backup_service.restore_backups(chapter_id)
                                return False
                            self.patching_logger.info(f'[FAST_PATH] Successfully applied xdelta patches from {mod_name} to {output_data_win_path}')
                        except Exception as e:
                            self.patching_logger.error(f'[FAST_PATH] Failed to apply xdelta patches: {e}', exc_info=True)
                            error_msg = str(e)[:200] if len(str(e)) > 200 else str(e)
                            self.status_update.emit(tr('errors.mod_patch_failed', mod_name=mod_name, error=error_msg), 'error')
                            if not is_modpack:
                                self.backup_service.restore_backups(chapter_id)
                            return False
                    elif csx_scripts and (not ready_data_win_files) and (not data_patches):
                        self.patching_logger.info(f'[FAST_PATH] Mod {mod_name} with only CSX script(s) - executing directly without vanilla export')
                        try:
                            if os.path.exists(output_data_win_path):
                                extracted_chapter_id = self._extract_chapter_id_from_path(target_dir)
                                if extracted_chapter_id is not None:
                                    self.backup_service.backup_file(extracted_chapter_id, output_data_win_path)
                            if not self._apply_csx_scripts(output_data_win_path, csx_scripts):
                                self.patching_logger.error(f'[FAST_PATH] Failed to execute CSX scripts from {mod_name}')
                                self.status_update.emit(tr('errors.mod_patch_failed', mod_name=mod_name, error=tr('errors.csx_script_failed', script=mod_name)), 'error')
                                if not is_modpack:
                                    self.backup_service.restore_backups(chapter_id)
                                return False
                            self.patching_logger.info(f'[FAST_PATH] Successfully executed CSX scripts from {mod_name} on {output_data_win_path}')
                        except Exception as e:
                            self.patching_logger.error(f'[FAST_PATH] Failed to execute CSX scripts: {e}', exc_info=True)
                            error_msg = str(e)[:200] if len(str(e)) > 200 else str(e)
                            self.status_update.emit(tr('errors.mod_patch_failed', mod_name=mod_name, error=error_msg), 'error')
                            if not is_modpack:
                                self.backup_service.restore_backups(chapter_id)
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
        vanilla_already_exported = os.path.exists(vanilla_objects_dir) and os.listdir(vanilla_objects_dir) if os.path.exists(vanilla_objects_dir) else False
        if not vanilla_already_exported:
            self.patching_logger.info('Exporting vanilla mod (mod 0) assets...')
            chapter_file = os.path.join(cache_running_dir, 'chapterNumber.txt')
            mod_file = os.path.join(cache_running_dir, 'modNumbersCache.txt')
            with open(chapter_file, 'w', encoding='utf-8') as f:
                f.write(chapter_str)
            with open(mod_file, 'w', encoding='utf-8') as f:
                f.write('0')
            vanilla_scripts = self._get_export_scripts()
            if vanilla_scripts:
                all_exports_successful = self._run_export_scripts(vanilla_scripts, vanilla_data_win, vanilla_objects_dir, merge_root, label='Vanilla ')
                if not all_exports_successful:
                    self.patching_logger.warning('Some vanilla export scripts failed')
                    warning_msg = tr('dialogs.patching_warning.export_failed', operation=tr('dialogs.patching_warning.export'), resource='vanilla')
                    if not self._show_patching_warning('vanilla_export_failed', tr('dialogs.patching_warning.title'), warning_msg):
                        self.patching_logger.info('[PATCHING_WARNING] User cancelled merge due to vanilla export failure')
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
            mod_type = self._detect_mod_type(mod_source_dir)
            mod_types[mod_number] = mod_type
            mod_dir = os.path.join(xdelta_combiner_dir, str(mod_number))
            os.makedirs(mod_dir, exist_ok=True)
            original_filename = os.path.basename(original_data_win)
            mod_data_win = os.path.join(mod_dir, original_filename)
            shutil.copyfile(original_data_win, mod_data_win)
            ready_data_win_files = self._find_ready_data_win_files(mod_source_dir)
            data_patches = self._find_data_patches(mod_source_dir)
            csx_scripts = self._find_csx_scripts(mod_source_dir)
            if ready_data_win_files:
                self.patching_logger.info(f'Found {len(ready_data_win_files)} ready data.win/game.ios file(s) from {mod_name} (mod {mod_number}), merging')
                patch_progress = mod_progress_start + int(mod_progress_range * 0.5)
                self.progress_update.emit(min(patch_progress, 95), f'Merging ready data.win from {mod_name}...')
                if not self._handle_ready_data_win(mod_data_win, ready_data_win_files, mod_dir):
                    self.patching_logger.error(f'Failed to merge ready data.win files from {mod_name}')
                    if not is_modpack and self.backup_service:
                        self.backup_service.restore_backups(chapter_id)
                    return False
                self.patching_logger.info(f'Successfully merged ready data.win files from {mod_name} (mod {mod_number})')
                target_dir_result = self._get_target_dir(chapter_id)
                if target_dir_result is not None and mod_source_dir:
                    used_archive_names = set()
                    if not self._apply_file_overrides(mod_source_dir, target_dir_result, used_archive_names, False, chapter_id):
                        self.patching_logger.warning(f'Failed to apply file overrides from {mod_name} after ready data.win merge')
                if not data_patches and (not csx_scripts):
                    mods_already_exported.add(mod_number)
                    self.patching_logger.info(f'Mod {mod_name} (number {mod_number}) has only ready data.win, will skip export scripts')
                mod_patched_files[mod_number] = mod_data_win
            if data_patches:
                self.patching_logger.info(f'Found {len(data_patches)} data patch(es) from {mod_name} (mod {mod_number}), applying to original')
                patch_progress = mod_progress_start + int(mod_progress_range * 0.3)
                self.progress_update.emit(min(patch_progress, 95), f'Applying patches from {mod_name}...')
                if not self._apply_xdelta_patches(mod_data_win, data_patches, progress_callback=lambda p: self.progress_update.emit(min(mod_progress_start + int(mod_progress_range * (0.3 + p * 0.4)), 95), f'Applying patches from {mod_name}...')):
                    self.patching_logger.error(f'[MERGE] Failed to apply data patches from {mod_name} (mod {mod_number}). This may be due to incompatibility with previously applied mods. The patch may have been created for the original data.win, but the file has already been modified.')
                    if not is_modpack and self.backup_service:
                        self.backup_service.restore_backups(chapter_id)
                    return False
                self.patching_logger.info(f'Successfully applied data patches from {mod_name} (mod {mod_number})')
                mod_patched_files[mod_number] = mod_data_win
            if csx_scripts:
                self.patching_logger.info(f'Found {len(csx_scripts)} CSX script(s) from {mod_name} (mod {mod_number}), executing')
                script_progress = mod_progress_start + int(mod_progress_range * 0.7)
                self.progress_update.emit(min(script_progress, 95), f'Executing scripts from {mod_name}...')
                if not self._apply_csx_scripts(mod_data_win, csx_scripts):
                    self.patching_logger.error(f'Failed to execute CSX scripts from {mod_name}')
                    if not is_modpack and self.backup_service:
                        self.backup_service.restore_backups(chapter_id)
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
        if fast_merge and mods_to_export:

            if not self._perform_parallel_export(mods_to_export, mods_to_apply, mod_patched_files, mod_types, vanilla_data_win, merge_root, cache_running_dir, chapter_str, chapter_id, progress_base + int(xdelta_progress), export_progress, lambda p, msg: self.progress_update.emit(p, msg)):
                if not is_modpack and self.backup_service:
                    self.backup_service.restore_backups(chapter_id)
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
                    code_entries_dir = os.path.join(objects_dir, 'CodeEntries')
                    if os.path.exists(code_entries_dir):
                        mod_exported_code = set()
                        for code_file in os.listdir(code_entries_dir):
                            if code_file.endswith('.gml'):
                                code_name = os.path.splitext(code_file)[0]
                                mod_exported_code.add(code_name)
                        self._mod_exported_code_files[mod_number] = mod_exported_code
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
                        shaders_dir = os.path.join(objects_dir, 'Shaders')
                        code_count = len([f for f in os.listdir(code_entries_dir) if f.endswith('.gml')]) if os.path.exists(code_entries_dir) else 0
                        sprite_count = len([d for d in os.listdir(sprites_dir) if os.path.isdir(os.path.join(sprites_dir, d))]) if os.path.exists(sprites_dir) else 0
                        shader_count = len([d for d in os.listdir(shaders_dir) if os.path.isdir(os.path.join(shaders_dir, d))]) if os.path.exists(shaders_dir) else 0
                        self.patching_logger.info(f'[EXPORT] Mod {mod_number} ({mod_name}) exported: {code_count} code, {sprite_count} sprites, {shader_count} shaders')
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
        base_mod_dir = os.path.join(xdelta_combiner_dir, str(base_mod_number))
        base_objects_dir = os.path.join(base_mod_dir, 'Objects')
        objects_dirs_to_import.sort(key=lambda x: x[1])
        self.patching_logger.info(f'Merge order (by priority): {[(m[1], m[2]) for m in objects_dirs_to_import]}')
        merged_objects_dir = os.path.join(xdelta_combiner_dir, 'DeltahubMerged')
        target_objects_dir = os.path.join(merged_objects_dir, 'Objects')
        if os.path.exists(merged_objects_dir):
            self.patching_logger.debug(f'Cleaning up previous merge directory: {merged_objects_dir}')
            if not safe_rmtree(merged_objects_dir):
                self.patching_logger.warning(f'Failed to clean up previous merge directory: {merged_objects_dir}')
        os.makedirs(target_objects_dir, exist_ok=True)
        self.patching_logger.info(f'Created clean merge directory: {target_objects_dir}')
        vanilla_objects_dir = os.path.join(xdelta_combiner_dir, '0', 'Objects')
        vanilla_hashes = {}
        if os.path.exists(vanilla_objects_dir):
            self.patching_logger.info('[FILTER] Computing hashes for vanilla resources...')
            vanilla_hashes = self._compute_resource_hashes(vanilla_objects_dir)
            self.patching_logger.info(f'[FILTER] Computed hashes for {sum((len(v) for v in vanilla_hashes.values()))} vanilla resources')
        filtered_objects_dirs = []
        if fast_merge and objects_dirs_to_import:
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
                    filtered_dir = self._filter_vanilla_identical_resources(vanilla_hashes, objects_dir, mod_number, mod_name)
                    if filtered_dir and os.path.exists(filtered_dir):
                        filtered_objects_dirs.append((mod_number, mod_priority, mod_name, filtered_dir))
        self.patching_logger.info('[MERGE] Merging filtered mods into clean directory (vanilla-identical resources already filtered out)')
        for idx, (mod_number, mod_priority, mod_name, objects_dir) in enumerate(filtered_objects_dirs):
            if self._cancelled:
                if not is_modpack and self.backup_service:
                    self.backup_service.restore_backups(chapter_id)
                return False
            merge_step = idx / len(filtered_objects_dirs) * (import_progress * 0.5) if filtered_objects_dirs else 0
            current_progress = progress_base + int(xdelta_progress + export_progress + merge_step)
            merge_msg = self._safe_tr('status.merging_assets', f'Merging assets from {mod_name} ({idx + 1}/{len(filtered_objects_dirs)})...', mod=mod_name, current=idx + 1, total=len(filtered_objects_dirs))
            self.progress_update.emit(min(current_progress, 90), merge_msg)
            self.patching_logger.info(f'Merging Objects from mod {mod_number} ({mod_name}, priority {mod_priority}) into clean merge directory (step {idx + 1}/{len(filtered_objects_dirs)})')
            code_entries_dir = os.path.join(objects_dir, 'CodeEntries')
            sprites_dir = os.path.join(objects_dir, 'Sprites')
            code_count = len([f for f in os.listdir(code_entries_dir) if f.endswith('.gml')]) if os.path.exists(code_entries_dir) else 0
            sprite_count = len([d for d in os.listdir(sprites_dir) if os.path.isdir(os.path.join(sprites_dir, d))]) if os.path.exists(sprites_dir) else 0
            self.patching_logger.debug(f'[MERGE] Mod {mod_number} ({mod_name}) has {code_count} code files, {sprite_count} sprites to merge (after filtering)')
            if os.path.exists(objects_dir):
                has_content = False
                for root, dirs, files in os.walk(objects_dir):
                    if dirs or files:
                        has_content = True
                        break
                if has_content:
                    self.patching_logger.debug(f'Merging Objects from mod {mod_number} ({mod_name}, priority {mod_priority}) into clean merge directory')
                    self._merge_objects_directories(target_objects_dir, objects_dir, mod_name)
                else:
                    self.patching_logger.debug(f'Mod {mod_number} ({mod_name}) has no resources to merge after filtering (all identical to vanilla or previous mods)')
        if os.path.exists(target_objects_dir):
            sprites_dir = os.path.join(target_objects_dir, 'Sprites')
            if os.path.exists(sprites_dir):
                sprite_dirs = [d for d in os.listdir(sprites_dir) if os.path.isdir(os.path.join(sprites_dir, d))]
                total_sprites = sum([len([f for f in os.listdir(os.path.join(sprites_dir, d)) if f.endswith('.png')]) for d in sprite_dirs if os.path.exists(os.path.join(sprites_dir, d))])
                self.patching_logger.info(f'[OPTIMIZATION] Collected {total_sprites} sprite files from {len(sprite_dirs)} sprite directories - Packer will run once for all sprites')
        if os.path.exists(target_objects_dir):
            code_entries_before = os.path.join(target_objects_dir, 'CodeEntries')
            sprites_before = os.path.join(target_objects_dir, 'Sprites')
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
                if not is_modpack and self.backup_service:
                    self.backup_service.restore_backups(chapter_id)
                return False
            import_progress_step = progress_base + int(xdelta_progress + export_progress + import_progress * 0.5)
            self.progress_update.emit(min(import_progress_step, 95), 'Importing merged assets into data.win...')
            self.patching_logger.info('Importing merged Objects directory (contains all exported mods, sorted by priority) into data.win')
            if self._cancelled:
                if not is_modpack and self.backup_service:
                    self.backup_service.restore_backups(chapter_id)
                return False
            if not self._import_assets_from_objects_dir(base_data_win, target_objects_dir, mods_to_apply, mods_count):
                self.patching_logger.warning('Failed to import merged assets into data.win')
                if not is_modpack and self.backup_service:
                    self.backup_service.restore_backups(chapter_id)
                return False
            if self._cancelled:
                if not is_modpack and self.backup_service:
                    self.backup_service.restore_backups(chapter_id)
                return False
            self.patching_logger.info('Successfully imported merged Objects into data.win')
            code_files_after = [f for f in os.listdir(code_entries_before) if f.endswith('.gml')] if os.path.exists(code_entries_before) else []
            sprite_dirs_after = [d for d in os.listdir(sprites_before) if os.path.isdir(os.path.join(sprites_before, d))] if os.path.exists(sprites_before) else []
            self.patching_logger.info(f'[IMPORT] After import: {len(code_files_after)} code files, {len(sprite_dirs_after)} sprites still in Objects directory')
        else:
            self.patching_logger.debug('No Objects directory to import after merging mods (only xdelta changes)')
        if self._cancelled:
            if not is_modpack and self.backup_service:
                self.backup_service.restore_backups(chapter_id)
            return False
        if os.path.exists(base_objects_dir):
            self.patching_logger.debug(f'Final Objects directory in base: {base_objects_dir}')
        if is_modpack:
            if not self._ensure_modpack_dir(modpack_dir):
                return False
            system = platform.system()
            if system == 'Darwin':
                final_output_path = os.path.join(modpack_dir, 'game.ios')
            else:
                final_output_path = os.path.join(modpack_dir, 'data.win')
        else:
            final_output_path = output_data_win_path
        if self._cancelled:
            if not is_modpack and self.backup_service:
                self.backup_service.restore_backups(chapter_id)
            return False
        try:
            shutil.copyfile(base_data_win, final_output_path)
            self.patching_logger.info(f'Copied merged data.win to {final_output_path}')
        except Exception as e:
            self.patching_logger.error(f'Failed to copy merged data.win: {e}')
            if not is_modpack and self.backup_service:
                self.backup_service.restore_backups(chapter_id)
            return False
        if self._cancelled:
            if not is_modpack and self.backup_service:
                self.backup_service.restore_backups(chapter_id)
            return False
        if is_modpack:
            if not self._ensure_modpack_dir(modpack_dir):
                return False
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
        self.patching_logger.info('Multi-mod merge completed successfully')
        return True

    def _merge_mods_for_chapter_to_dir(self, chapter_id: int, mods_list: List[Any], modpack_dir: str, progress_base: int = 0, total_chapters: int = 1, fast_merge: bool = False, game: Optional[str] = None) -> bool:
        self.patching_logger.debug(f'_merge_mods_for_chapter_to_dir: chapter_id={chapter_id}, mods_count={len(mods_list)}, modpack_dir={modpack_dir}, game={game}')
        os.makedirs(modpack_dir, exist_ok=True)
        target_dir = self._get_target_dir(chapter_id, game=game)
        if not target_dir:
            self.patching_logger.error(f'Target directory not found for chapter {chapter_id} (game={game})')
            return False
        self.patching_logger.debug(f'Target directory: {target_dir}')
        data_win_path = self._find_data_win(target_dir)
        if not data_win_path:
            return self._apply_file_overrides_only(chapter_id, mods_list, modpack_dir, is_modpack=True)
        return self._perform_chapter_merge(chapter_id, mods_list, data_win_path, target_dir, modpack_dir, progress_base, total_chapters, is_modpack=True, fast_merge=fast_merge)

    def _apply_file_overrides_only(self, chapter_id: int, mods_list: List[Any], target_dir: str, is_modpack: bool = False) -> bool:
        mods_to_apply = list(reversed(mods_list))
        used_archive_names = set()
        for mod_data in mods_to_apply:
            mod_source_dir = self._get_mod_source_dir(mod_data, chapter_id)
            if mod_source_dir:
                if not self._apply_file_overrides(mod_source_dir, target_dir, used_archive_names if not is_modpack else set(), is_modpack, chapter_id):
                    return False
        return True

    def _classify_xdelta_error(self, error_msg: str) -> str:
        lower = error_msg.lower()
        if 'checksum mismatch' in lower or 'XD3_INVALID_INPUT' in error_msg:
            return 'checksum'
        if any(k in lower for k in ('no such file', 'cannot find', 'file not found')):
            return 'not_found'
        if any(k in lower for k in ('permission denied', 'access denied')):
            return 'permission'
        if 'XD3_INTERNAL' in error_msg or any(k in lower for k in ('corrupt', 'invalid')):
            return 'corrupted'
        if any(k in lower for k in ('io error', 'input/output', 'disk')):
            return 'io'
        return 'unknown'

    def _handle_xdelta_error(self, error_type: str, patch_name: str, patch_path: str, data_win_path: str, error_msg: str) -> bool:
        error_short = error_msg[:200]
        _ERROR_MAP = {
            'checksum': ('xdelta_checksum_mismatch', 'dialogs.patching_warning.xdelta_checksum_mismatch', 'errors.xdelta_patch_checksum_mismatch', True),
            'not_found': (None, None, 'errors.xdelta_patch_file_not_found', False),
            'permission': (None, None, 'errors.xdelta_patch_permission_denied', False),
            'corrupted': ('xdelta_patch_corrupted', 'dialogs.patching_warning.xdelta_patch_failed', 'errors.xdelta_patch_corrupted', True),
            'io': (None, None, 'errors.xdelta_patch_io_error', False),
            'unknown': ('xdelta_patch_failed', 'dialogs.patching_warning.xdelta_patch_failed', 'errors.xdelta_patch_unknown_error', True),
        }
        warn_type, warn_key, err_key, can_continue = _ERROR_MAP.get(error_type, _ERROR_MAP['unknown'])
        self.patching_logger.error(f'[XDELTA] Patch "{patch_name}" failed ({error_type}): {error_msg[:500]}')
        if can_continue and warn_type:
            warning_msg = tr(warn_key, patch_name=patch_name, patch_path=patch_path, data_win_path=data_win_path, error=error_short)
            if not self._show_patching_warning(warn_type, tr('dialogs.patching_warning.title'), warning_msg):
                self.patching_logger.info(f'[PATCHING_WARNING] User cancelled merge: {patch_name}')
                self.status_update.emit(tr(err_key, patch=patch_name, error=error_short), 'error')
                return False
            self.patching_logger.info(f'[PATCHING_WARNING] User chose to continue: {patch_name}')
            return True
        self.status_update.emit(tr(err_key, patch=patch_name, error=error_short), 'error')
        return False

    def _cleanup_temp_output(self, temp_output: Optional[str]) -> None:
        if temp_output and os.path.exists(temp_output):
            try:
                safe_remove(temp_output)
            except Exception:
                pass

    def _apply_xdelta_patches(self, data_win_path: str, data_patches: List[str], progress_callback=None) -> bool:
        if not self._ensure_xdelta_executable():
            self.patching_logger.error('xdelta executable not found or not available')
            self.status_update.emit(tr('errors.xdelta_not_found'), 'error')
            return False
        if not os.path.exists(data_win_path):
            self.patching_logger.error(f'Input file does not exist: {data_win_path}')
            self.status_update.emit(tr('errors.xdelta_patch_file_not_found', patch=os.path.basename(data_win_path) if data_win_path else 'data.win'), 'error')
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
                self.status_update.emit(tr('errors.xdelta_patch_file_not_found', patch=patch_name), 'error')
                return False
            temp_output = None
            try:
                temp_output = data_win_path + '.tmp'
                self._temp_files_to_cleanup.append(temp_output)
                if not os.access(os.path.dirname(temp_output), os.W_OK):
                    self.patching_logger.error(f'Temp directory is not writable: {os.path.dirname(temp_output)}')
                    self.status_update.emit(tr('errors.xdelta_patch_permission_denied', patch=patch_name), 'error')
                    return False
                returncode, stdout, stderr = self._run_xdelta_process(data_win_path, patch_path, temp_output)
                if progress_callback:
                    progress_callback((idx + 1) / total_patches if total_patches > 0 else 1.0)
                if returncode != 0:
                    error_msg = stderr.strip() if stderr else stdout.strip() if stdout else 'Unknown error'
                    error_type = self._classify_xdelta_error(error_msg)
                    user_continues = self._handle_xdelta_error(error_type, patch_name, patch_path, data_win_path, error_msg)
                    if user_continues:
                        continue
                    return False
                if not os.path.exists(temp_output):
                    self.patching_logger.error(f'Temp output file was not created: {temp_output}')
                    self.status_update.emit(tr('errors.xdelta_patch_io_error', patch=patch_name), 'error')
                    return False
                if not safe_move(temp_output, data_win_path):
                    raise OSError(f'Failed to move patched file from {temp_output} to {data_win_path}')
                if temp_output in self._temp_files_to_cleanup:
                    self._temp_files_to_cleanup.remove(temp_output)
                self.patching_logger.info(f'Patch {idx + 1}/{total_patches} applied successfully')
            except subprocess.TimeoutExpired:
                self.patching_logger.error(f'xdelta patch timed out after 300 seconds: {patch_path}')
                self.status_update.emit(tr('errors.xdelta_patch_timeout_detailed', patch=patch_name), 'error')
                self._cleanup_temp_output(temp_output)
                return False
            except Exception as e:
                error_str = str(e)
                self.patching_logger.error(f'xdelta patch error: {e}', exc_info=True)
                error_type = self._classify_xdelta_error(error_str)
                _EXCEPTION_ERROR_KEYS = {
                    'permission': 'errors.xdelta_patch_permission_denied',
                    'not_found': 'errors.xdelta_patch_file_not_found',
                    'io': 'errors.xdelta_patch_io_error',
                }
                err_key = _EXCEPTION_ERROR_KEYS.get(error_type, 'errors.xdelta_patch_unknown_error')
                self.status_update.emit(tr(err_key, patch=patch_name, error=error_str[:200]), 'error')
                self._cleanup_temp_output(temp_output)
                return False
        self.patching_logger.info('All patches applied successfully')
        return True

    def _apply_csx_scripts(self, data_win_path: str, csx_scripts: List[str]) -> bool:
        if not csx_scripts:
            return True
        if not self.utmt_wrapper.is_available():
            self.patching_logger.error('UTMTCLI not available for executing CSX scripts')
            platform_name = self.utmt_wrapper.get_platform()
            warning_msg = tr('dialogs.patching_warning.utmt_not_available', platform=platform_name)
            if not self._show_patching_warning('utmt_not_available', tr('dialogs.patching_warning.title'), warning_msg):
                self.patching_logger.info('[PATCHING_WARNING] User cancelled merge due to UTMT not available')
                self.status_update.emit(tr('errors.utmtcli_not_available', platform=platform_name), 'error')
                return False
            self.patching_logger.info('[PATCHING_WARNING] User chose to continue despite UTMT not available')
            return True
        env = {}
        if self.temp_merge_dir and os.path.exists(os.path.join(self.temp_merge_dir, 'output')):
            env['DELTAHUB_ROOT'] = self.temp_merge_dir
        for script_path in csx_scripts:
            if self._cancelled:
                return False
            try:
                script_name = os.path.basename(script_path)
                self.patching_logger.info(f'Executing CSX script: {script_name}')
                returncode, stdout, stderr = self.utmt_wrapper.execute_script(data_win_path, script_path, output_path=data_win_path, cwd=self.temp_merge_dir if self.temp_merge_dir else None, env=env)
                if self._cancelled:
                    return False
                if returncode != 0:
                    error_msg = stderr[:200] if stderr and len(stderr) > 200 else (stderr or 'Unknown error')
                    self.patching_logger.error(f'CSX script execution failed: {stderr[:500] if stderr else "Unknown error"}')
                    warning_msg = tr('dialogs.patching_warning.csx_script_failed', script_name=script_name, error=error_msg)
                    if not self._show_patching_warning('csx_script_failed', tr('dialogs.patching_warning.title'), warning_msg):
                        self.patching_logger.info(f'[PATCHING_WARNING] User cancelled merge due to CSX script failure: {script_name}')
                        self.status_update.emit(tr('errors.csx_script_failed', script=script_name), 'error')
                        return False
                    self.patching_logger.info(f'[PATCHING_WARNING] User chose to continue despite CSX script failure: {script_name}')
                    continue
                self.patching_logger.info(f'Successfully executed CSX script: {script_name}')
            except Exception as e:
                script_name = os.path.basename(script_path)
                error_msg = str(e)[:200] if len(str(e)) > 200 else str(e)
                self.patching_logger.error(f'CSX script error: {e}')
                warning_msg = tr('dialogs.patching_warning.csx_script_failed', script_name=script_name, error=error_msg)
                if not self._show_patching_warning('csx_script_exception', tr('dialogs.patching_warning.title'), warning_msg):
                    self.patching_logger.info(f'[PATCHING_WARNING] User cancelled merge due to CSX script exception: {script_name}')
                    return False
                self.patching_logger.info(f'[PATCHING_WARNING] User chose to continue despite CSX script exception: {script_name}')
                continue
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
            self._track_mod_history(resource_name, resource_type, mod_name_for_tracking, resource_action)
        input_dir = os.path.join(objects_dir, resource_subdir) if resource_subdir else objects_dir
        returncode, stdout, stderr = self.utmt_wrapper.execute_script(data_win_path, script_name, output_path=data_win_path, cwd=data_win_dir, env={'INPUT_DIR': input_dir})
        if self._cancelled:
            self.patching_logger.info(f'{script_name} was cancelled by user, file may be partially modified')
            return False
        if analyze_errors:
            self._analyze_compilation_errors(stdout, stderr, script_name, mod_name_for_tracking)
        if returncode != 0:
            error_msg = stderr[:300] if len(stderr) > 300 else stderr
            self.patching_logger.warning(f'{script_name} failed: {error_msg}')
            if len(stderr) > 500:
                self.patching_logger.error(f'[IMPORT] {script_name} failed: {stderr[:500]}')
        else:
            self.patching_logger.info(f'Successfully imported {resource_type} from Objects directory')
        if mod_name_for_tracking not in ('0', 'vanilla', 'unknown_mod', 'merged_mods'):
            for resource_name in resource_names:
                if resource_name in self.resource_modification_history:
                    history = self.resource_modification_history[resource_name]
                    if returncode != 0 and history:
                        history[-1]['error'] = error_msg
                    if len(history) > 1:
                        prev_mods = [h['mod'] for h in history[:-1]]
                        self._log_conflict(resource_type, resource_name, prev_mods, mod_name_for_tracking)
                        prev_filtered = [m for m in prev_mods if m not in ('0', 'vanilla', 'unknown_mod', 'merged_mods', mod_name_for_tracking)]
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
                if 'DeltahubMergeWorkspace' in data_win_dir:
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
            sprites_dir = os.path.join(objects_dir, 'Sprites')
            backgrounds_dir = os.path.join(objects_dir, 'Backgrounds')
            has_graphics = os.path.exists(sprites_dir) or os.path.exists(backgrounds_dir)
            code_entries_dir = os.path.join(objects_dir, 'CodeEntries')
            has_gml = bool(os.path.exists(code_entries_dir) and os.listdir(code_entries_dir))
            shaders_dir = os.path.join(objects_dir, 'Shaders')
            has_shaders = bool(os.path.exists(shaders_dir) and os.listdir(shaders_dir))
            tilesets_dir = os.path.join(objects_dir, 'Tilesets')
            has_tilesets = bool(os.path.exists(tilesets_dir) and os.listdir(tilesets_dir))
            fonts_dir = os.path.join(objects_dir, 'Fonts')
            has_fonts = bool(os.path.exists(fonts_dir) and os.listdir(fonts_dir))
            sounds_dir = os.path.join(objects_dir, 'Sounds')
            has_sounds = bool(os.path.exists(sounds_dir) and os.listdir(sounds_dir))
            rooms_dir = os.path.join(objects_dir, 'Rooms')
            has_rooms = bool(os.path.exists(rooms_dir) and os.listdir(rooms_dir))
            if not (has_graphics or has_gml or has_shaders or has_tilesets or has_fonts or has_sounds or has_rooms):
                self.patching_logger.debug(f'Objects directory has no assets to import: {objects_dir}')
                return True
            mod_name_for_tracking = 'merged_mods'

            def _get_dir_resources(obj_dir, subdir):
                p = os.path.join(obj_dir, subdir)
                return [d for d in os.listdir(p) if os.path.isdir(os.path.join(p, d))] if os.path.exists(p) else []

            def _get_file_resources(obj_dir, subdir, exts, exclude=None):
                p = os.path.join(obj_dir, subdir)
                if not os.path.exists(p):
                    return []
                return [os.path.splitext(f)[0] for f in os.listdir(p) if f.endswith(exts) and (not exclude or not f.endswith(exclude))]

            def get_gml_resources(obj_dir):
                code_files = _get_file_resources(obj_dir, 'CodeEntries', '.gml')
                if code_files:
                    self.patching_logger.debug(f'[IMPORT] Code files to import: {code_files[:10]}...' if len(code_files) > 10 else f'[IMPORT] Code files to import: {code_files}')
                return code_files

            def get_tileset_config_resource(obj_dir):
                tilesets_path = os.path.join(obj_dir, 'Tilesets')
                return ['tilesets_config'] if os.path.exists(tilesets_path) and os.path.exists(os.path.join(tilesets_path, 'config.json')) else []

            def get_font_resources(obj_dir):
                fonts_path = os.path.join(obj_dir, 'Fonts')
                if not os.path.exists(fonts_path):
                    return []
                font_names = set()
                for f in os.listdir(fonts_path):
                    if f.endswith(('.png', '.json')):
                        font_names.add(os.path.splitext(f)[0])
                    elif f.startswith('glyphs_') and f.endswith('.csv'):
                        font_names.add(f[7:-4])
                return list(font_names)
            audio_groups_dir = os.path.join(objects_dir, 'AudioGroups')
            has_audio_groups = bool(os.path.exists(audio_groups_dir) and os.listdir(audio_groups_dir))
            paths_dir = os.path.join(objects_dir, 'Paths')
            has_paths = bool(os.path.exists(paths_dir) and os.listdir(paths_dir))
            timelines_dir = os.path.join(objects_dir, 'Timelines')
            has_timelines = bool(os.path.exists(timelines_dir) and os.listdir(timelines_dir))
            extensions_dir = os.path.join(objects_dir, 'Extensions')
            has_extensions = bool(os.path.exists(extensions_dir) and os.listdir(extensions_dir))
            if not (has_graphics or has_gml or has_shaders or has_tilesets or has_fonts or has_sounds or has_rooms or has_audio_groups or has_paths or has_timelines or has_extensions):
                self.patching_logger.debug(f'Objects directory has no assets to import: {objects_dir}')
                return True

            def _no_res(obj_dir):
                return []

            def _json_res(subdir):
                def _get_json_resources(obj_dir):
                    return _get_file_resources(obj_dir, subdir, '.json')
                return _get_json_resources

            asset_configs = [
                {'script_name': 'ImportGeneralInfo', 'has_assets': True, 'step_number': '1/15', 'resource_type': 'generalinfo', 'resource_action': 'imported', 'get_resources_func': _no_res, 'resource_subdir': ''},
                {'script_name': 'ImportAudioGroups', 'has_assets': has_audio_groups, 'step_number': '2/15', 'resource_type': 'audiogroup', 'resource_action': 'modified', 'get_resources_func': _json_res('AudioGroups'), 'resource_subdir': 'AudioGroups'},
                {'script_name': 'ImportTextureGroupInfo', 'has_assets': True, 'step_number': '3/15', 'resource_type': 'texturegroup', 'resource_action': 'imported', 'get_resources_func': _no_res, 'resource_subdir': ''},
                {'script_name': 'ImportSprites', 'has_assets': has_graphics, 'step_number': '4/15', 'resource_type': 'sprite', 'resource_action': 'imported', 'get_resources_func': lambda obj_dir: _get_dir_resources(obj_dir, 'Sprites'), 'resource_subdir': 'Sprites'},
                {'script_name': 'ImportBackgrounds', 'has_assets': has_graphics, 'step_number': '5/15', 'resource_type': 'background', 'resource_action': 'imported', 'get_resources_func': lambda obj_dir: _get_dir_resources(obj_dir, 'Backgrounds'), 'resource_subdir': 'Backgrounds'},
                {'script_name': 'ImportFonts', 'has_assets': has_fonts, 'step_number': '6/15', 'resource_type': 'font', 'resource_action': 'modified', 'get_resources_func': get_font_resources, 'resource_subdir': 'Fonts'},
                {'script_name': 'ImportSounds', 'has_assets': has_sounds, 'step_number': '7/15', 'resource_type': 'sound', 'resource_action': 'modified', 'get_resources_func': lambda obj_dir: _get_file_resources(obj_dir, 'Sounds', ('.ogg', '.wav')), 'resource_subdir': 'Sounds'},
                {'script_name': 'ImportPaths', 'has_assets': has_paths, 'step_number': '8/15', 'resource_type': 'path', 'resource_action': 'modified', 'get_resources_func': _json_res('Paths'), 'resource_subdir': 'Paths'},
                {'script_name': 'ImportTilesets', 'has_assets': has_tilesets, 'step_number': '9/15', 'resource_type': 'tileset', 'resource_action': 'imported', 'get_resources_func': lambda obj_dir: _get_file_resources(obj_dir, 'Tilesets', '.json', exclude='config.json'), 'extra_resources_func': get_tileset_config_resource, 'resource_subdir': 'Tilesets'},
                {'script_name': 'ImportShaders', 'has_assets': has_shaders, 'step_number': '10/15', 'resource_type': 'shader', 'resource_action': 'imported', 'get_resources_func': lambda obj_dir: _get_dir_resources(obj_dir, 'Shaders'), 'resource_subdir': 'Shaders'},
                {'script_name': 'ImportTimelines', 'has_assets': has_timelines, 'step_number': '11/15', 'resource_type': 'timeline', 'resource_action': 'modified', 'get_resources_func': _json_res('Timelines'), 'resource_subdir': 'Timelines'},
                {'script_name': 'ImportGameObjects', 'has_assets': has_graphics, 'step_number': '12/15', 'resource_type': 'object', 'resource_action': 'imported', 'get_resources_func': lambda obj_dir: _get_dir_resources(obj_dir, 'Sprites'), 'resource_subdir': 'Objects'},
                {'script_name': 'ImportRooms', 'has_assets': has_rooms, 'step_number': '13/15', 'resource_type': 'room', 'resource_action': 'modified', 'get_resources_func': _json_res('Rooms'), 'check_dir_func': lambda obj_dir: os.path.exists(os.path.join(obj_dir, 'Rooms')), 'resource_subdir': 'Rooms'},
                {'script_name': 'ImportCodeEntries', 'has_assets': has_gml, 'step_number': '14/15', 'resource_type': 'code', 'resource_action': 'modified', 'get_resources_func': get_gml_resources, 'analyze_errors': True, 'resource_subdir': 'CodeEntries'},
                {'script_name': 'ImportExtensions', 'has_assets': has_extensions, 'step_number': '15/15', 'resource_type': 'extension', 'resource_action': 'modified', 'get_resources_func': _json_res('Extensions'), 'resource_subdir': 'Extensions'},
            ]
            for asset_config in asset_configs:
                self._import_asset_type(asset_config, data_win_path, data_win_dir, objects_dir, mod_name_for_tracking)
            if 'DeltahubMergeWorkspace' in data_win_dir:
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
                self._rotate_conflicts_log_if_needed()
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

    def _merge_subdirectory(self, target_base: str, source_base: str, folder_name: str, resource_type: str, source_mod_name: str, track_history: bool = False) -> None:
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
                        is_identical = False
                        try:
                            if self._are_files_semantically_equal(src_file, dst_file, resource_type):
                                is_identical = True
                        except Exception:
                            pass
                        if not is_identical and resource_name not in conflicts_logged_this_call:
                            if resource_name in self.resource_modification_history:
                                prev_mods = [h['mod'] for h in self.resource_modification_history[resource_name]]
                                prev_mods_filtered = [m for m in prev_mods if m not in ['0', 'vanilla', 'unknown_mod', 'merged_mods']]
                                prev_mods_unique = list(dict.fromkeys(prev_mods_filtered))
                                if prev_mods_unique and source_mod_name not in prev_mods_unique:
                                    self.patching_logger.info(f"[CONFLICT] {resource_type} '{resource_name}': mod {prev_mods_unique[0]} vs mod {source_mod_name}, using mod {source_mod_name}")
                                    self._rotate_conflicts_log_if_needed()
                                    self.conflicts_logger.info(f'''Resource: {resource_type.capitalize()} "{resource_name}" | Conflict between: {', '.join(prev_mods_unique)} vs "{source_mod_name}" | Resolution: Using "{source_mod_name}" (higher priority)''')
                                    self.detected_conflicts.append({'resource_type': resource_type, 'resource_name': resource_name, 'mods': prev_mods_unique + [source_mod_name], 'resolution': source_mod_name})
                                    conflicts_logged_this_call.add(resource_name)
                    safe_copy(src_file, dst_file)
                    if track_history:
                        if source_mod_name != '0' and source_mod_name != 'vanilla' and (source_mod_name != 'unknown_mod'):
                            if resource_name not in history_added_this_call:
                                if resource_name not in self.resource_modification_history:
                                    self.resource_modification_history[resource_name] = []
                                existing_mods = [h['mod'] for h in self.resource_modification_history[resource_name]]
                                if source_mod_name not in existing_mods:
                                    self.resource_modification_history[resource_name].append({'type': resource_type, 'mod': source_mod_name, 'action': 'merged', 'timestamp': time.time()})
                                history_added_this_call.add(resource_name)
        else:
            shutil.copytree(source_dir, target_dir, dirs_exist_ok=True)

    def _hash_file(self, file_path: str) -> Optional[str]:
        try:
            with open(file_path, 'rb') as f:
                return hashlib.sha256(f.read()).hexdigest()
        except Exception:
            return None

    def _hash_dir_files(self, dir_path: str, ext_filter: str = None) -> Optional[str]:
        files = sorted(os.listdir(dir_path)) if not ext_filter else sorted(f for f in os.listdir(dir_path) if f.endswith(ext_filter))
        if not files:
            return None
        h = hashlib.sha256()
        for f in files:
            try:
                with open(os.path.join(dir_path, f), 'rb') as fh:
                    h.update(fh.read())
            except Exception:
                pass
        return h.hexdigest()

    def _hash_json_semantic(self, file_path: str) -> Optional[str]:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
        except Exception:
            return self._hash_file(file_path)

    def _compute_resource_hashes(self, objects_dir: str) -> Dict[str, Dict[str, str]]:
        hashes = {'code': {}, 'sprites': {}, 'backgrounds': {}, 'fonts': {}, 'shaders': {}, 'sounds': {}, 'rooms': {}}
        code_dir = os.path.join(objects_dir, 'CodeEntries')
        if os.path.exists(code_dir):
            for file in os.listdir(code_dir):
                if file.endswith('.gml'):
                    h = self._hash_file(os.path.join(code_dir, file))
                    if h:
                        hashes['code'][os.path.splitext(file)[0]] = h
        for subdir, key, use_dirs in [('Sprites', 'sprites', True), ('Shaders', 'shaders', True)]:
            res_dir = os.path.join(objects_dir, subdir)
            if os.path.exists(res_dir):
                for name in os.listdir(res_dir):
                    item_path = os.path.join(res_dir, name)
                    if os.path.isdir(item_path):
                        ext_filter = '.png' if key == 'sprites' else None
                        h = self._hash_dir_files(item_path, ext_filter)
                        if h:
                            hashes[key][name] = h
        backgrounds_dir = os.path.join(objects_dir, 'Backgrounds')
        if os.path.exists(backgrounds_dir):
            for bg_name in os.listdir(backgrounds_dir):
                bg_path = os.path.join(backgrounds_dir, bg_name)
                if os.path.isdir(bg_path):
                    h = self._hash_dir_files(bg_path, '.png')
                    if h:
                        hashes['backgrounds'][bg_name] = h
                elif bg_name.endswith('.png'):
                    h = self._hash_file(bg_path)
                    if h:
                        hashes['backgrounds'][os.path.splitext(bg_name)[0]] = h
        fonts_dir = os.path.join(objects_dir, 'Fonts')
        if os.path.exists(fonts_dir):
            font_names = {os.path.splitext(f)[0] for f in os.listdir(fonts_dir) if f.endswith(('.png', '.json'))}
            for font_name in font_names:
                h = hashlib.sha256()
                for ext in ('.png', '.json'):
                    fp = os.path.join(fonts_dir, f'{font_name}{ext}')
                    if os.path.exists(fp):
                        try:
                            with open(fp, 'rb') as f:
                                h.update(f.read())
                        except Exception:
                            pass
                hashes['fonts'][font_name] = h.hexdigest()
        for subdir, key, exts in [('Sounds', 'sounds', ('.ogg', '.wav')), ('Rooms', 'rooms', ('.json',))]:
            res_dir = os.path.join(objects_dir, subdir)
            if os.path.exists(res_dir):
                for file in os.listdir(res_dir):
                    if file.endswith(exts):
                        name = os.path.splitext(file)[0]
                        fp = os.path.join(res_dir, file)
                        if key == 'rooms':
                            h = self._hash_json_semantic(fp)
                        else:
                            h = self._hash_file(fp)
                        if h:
                            hashes[key][name] = h
        return hashes

    def _are_files_semantically_equal(self, file1: str, file2: str, resource_type: str) -> bool:
        try:
            if resource_type == 'room' or resource_type == 'rooms':
                try:
                    with open(file1, 'r', encoding='utf-8') as f1, open(file2, 'r', encoding='utf-8') as f2:
                        json1 = json.load(f1)
                        json2 = json.load(f2)
                    canonical1 = json.dumps(json1, sort_keys=True, separators=(',', ':'))
                    canonical2 = json.dumps(json2, sort_keys=True, separators=(',', ':'))
                    return canonical1 == canonical2
                except Exception:
                    pass
            with open(file1, 'rb') as f1, open(file2, 'rb') as f2:
                while True:
                    b1 = f1.read(8192)
                    b2 = f2.read(8192)
                    if b1 != b2:
                        return False
                    if not b1:
                        return True
        except Exception as e:
            self.patching_logger.warning(f'Failed to compare files {file1} and {file2}: {e}')
            return False

    def _filter_vanilla_identical_resources(self, vanilla_hashes: Dict[str, Dict[str, str]], mod_objects_dir: str, mod_number: int, mod_name: str) -> Optional[str]:
        if not os.path.exists(mod_objects_dir):
            return None
        mod_hashes = self._compute_resource_hashes(mod_objects_dir)
        filtered_dir = os.path.join(os.path.dirname(mod_objects_dir), f'Objects_filtered_{mod_number}')
        if os.path.exists(filtered_dir):
            safe_rmtree(filtered_dir)
        os.makedirs(filtered_dir, exist_ok=True)
        removed_counts = {'code': 0, 'sprites': 0, 'backgrounds': 0, 'fonts': 0, 'shaders': 0, 'sounds': 0, 'rooms': 0}
        for resource_type in ['code', 'sprites', 'backgrounds', 'fonts', 'shaders', 'sounds', 'rooms']:
            vanilla_type_hashes = vanilla_hashes.get(resource_type, {})
            mod_type_hashes = mod_hashes.get(resource_type, {})
            for resource_name, mod_hash in mod_type_hashes.items():
                vanilla_hash = vanilla_type_hashes.get(resource_name)
                if vanilla_hash is not None and mod_hash == vanilla_hash:
                    removed_counts[resource_type] += 1
                    continue
                self._copy_resource_to_filtered(resource_type, resource_name, mod_objects_dir, filtered_dir)
        total_removed = sum(removed_counts.values())
        if total_removed > 0:
            summary_parts = [f'{k}: {v}' for k, v in removed_counts.items() if v > 0]
            self.patching_logger.info(f"[FILTER] Mod {mod_number} ({mod_name}): Removed {total_removed} resources identical to vanilla ({', '.join(summary_parts)})")
        has_content = False
        for root, dirs, files in os.walk(filtered_dir):
            if dirs or files:
                has_content = True
                break
        if not has_content:
            safe_rmtree(filtered_dir)
            return None
        return filtered_dir

    def _copy_resource_to_filtered(self, resource_type: str, resource_name: str, source_objects_dir: str, target_objects_dir: str) -> None:
        if resource_type == 'code':
            source_file = os.path.join(source_objects_dir, 'CodeEntries', f'{resource_name}.gml')
            target_dir = os.path.join(target_objects_dir, 'CodeEntries')
            os.makedirs(target_dir, exist_ok=True)
            target_file = os.path.join(target_dir, f'{resource_name}.gml')
            if os.path.exists(source_file):
                safe_copy(source_file, target_file)
        elif resource_type == 'sprites':
            source_dir = os.path.join(source_objects_dir, 'Sprites', resource_name)
            target_dir = os.path.join(target_objects_dir, 'Sprites', resource_name)
            if os.path.exists(source_dir) and os.path.isdir(source_dir):
                os.makedirs(os.path.dirname(target_dir), exist_ok=True)
                if os.path.exists(target_dir):
                    safe_rmtree(target_dir)
                shutil.copytree(source_dir, target_dir)
        elif resource_type == 'backgrounds':
            source_dir = os.path.join(source_objects_dir, 'Backgrounds', resource_name)
            source_file = os.path.join(source_objects_dir, 'Backgrounds', f'{resource_name}.png')
            target_dir = os.path.join(target_objects_dir, 'Backgrounds')
            os.makedirs(target_dir, exist_ok=True)
            if os.path.exists(source_dir) and os.path.isdir(source_dir):
                target_subdir = os.path.join(target_dir, resource_name)
                if os.path.exists(target_subdir):
                    safe_rmtree(target_subdir)
                shutil.copytree(source_dir, target_subdir)
            elif os.path.exists(source_file):
                safe_copy(source_file, os.path.join(target_dir, f'{resource_name}.png'))
        elif resource_type == 'fonts':
            target_dir = os.path.join(target_objects_dir, 'Fonts')
            os.makedirs(target_dir, exist_ok=True)
            png_file = os.path.join(source_objects_dir, 'Fonts', f'{resource_name}.png')
            json_file = os.path.join(source_objects_dir, 'Fonts', f'{resource_name}.json')
            if os.path.exists(png_file):
                safe_copy(png_file, os.path.join(target_dir, f'{resource_name}.png'))
            if os.path.exists(json_file):
                safe_copy(json_file, os.path.join(target_dir, f'{resource_name}.json'))
        elif resource_type == 'shaders':
            source_dir = os.path.join(source_objects_dir, 'Shaders', resource_name)
            target_dir = os.path.join(target_objects_dir, 'Shaders', resource_name)
            if os.path.exists(source_dir) and os.path.isdir(source_dir):
                os.makedirs(os.path.dirname(target_dir), exist_ok=True)
                if os.path.exists(target_dir):
                    safe_rmtree(target_dir)
                shutil.copytree(source_dir, target_dir)
        elif resource_type == 'sounds':
            target_dir = os.path.join(target_objects_dir, 'Sounds')
            os.makedirs(target_dir, exist_ok=True)
            for ext in ['.ogg', '.wav']:
                source_file = os.path.join(source_objects_dir, 'Sounds', f'{resource_name}{ext}')
                if os.path.exists(source_file):
                    safe_copy(source_file, os.path.join(target_dir, f'{resource_name}{ext}'))
                    break
        elif resource_type == 'rooms':
            target_dir = os.path.join(target_objects_dir, 'Rooms')
            os.makedirs(target_dir, exist_ok=True)
            source_file = os.path.join(source_objects_dir, 'Rooms', f'{resource_name}.json')
            if os.path.exists(source_file):
                safe_copy(source_file, os.path.join(target_dir, f'{resource_name}.json'))

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
        subdirs_to_merge = [('Sprites', 'sprite', True), ('Backgrounds', 'background', False), ('Tilesets', 'tileset', False), ('Shaders', 'shader', False), ('Fonts', 'font', False), ('Sounds', 'sound', False), ('Rooms', 'room', True)]
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
                            prev_mods_filtered = [m for m in prev_mods if m not in ['0', 'vanilla', 'unknown_mod', 'merged_mods']]
                            prev_mods_unique = list(dict.fromkeys(prev_mods_filtered))
                            if prev_mods_unique and source_mod_name not in prev_mods_unique:
                                conflict_msg = f'''Code "{code_name}" was modified by: {', '.join(prev_mods_unique)} before "{source_mod_name}". Higher priority mod ({source_mod_name}) will overwrite.'''
                                self.patching_logger.warning(f'[CONFLICT] {conflict_msg}')
                                self._rotate_conflicts_log_if_needed()
                                self.conflicts_logger.info(f'''Resource: GML Code "{code_name}" | Conflict between: {', '.join(prev_mods_unique)} vs "{source_mod_name}" | Resolution: Using "{source_mod_name}" (higher priority)''')
                                self.detected_conflicts.append({'resource_type': 'code', 'resource_name': code_name, 'mods': prev_mods_unique + [source_mod_name], 'resolution': source_mod_name})
                    safe_copy(src_file, dst_file)
                    if source_mod_name != '0' and source_mod_name != 'vanilla' and (source_mod_name != 'unknown_mod'):
                        code_name = os.path.splitext(file)[0]
                        if code_name not in self.resource_modification_history:
                            self.resource_modification_history[code_name] = []
                        existing_mods = [h['mod'] for h in self.resource_modification_history[code_name]]
                        if source_mod_name not in existing_mods:
                            self.resource_modification_history[code_name].append({'type': 'code', 'mod': source_mod_name, 'action': 'merged', 'timestamp': time.time()})
        source_asset_order = os.path.join(source_objects_dir, 'AssetOrder.txt')
        target_asset_order = os.path.join(target_objects_dir, 'AssetOrder.txt')
        if os.path.exists(source_asset_order):
            safe_copy(source_asset_order, target_asset_order)

    def _merge_two_data_win_files(self, base_file: str, other_file: str, mod_dir: Optional[str] = None) -> bool:
        if not self.temp_merge_dir:
            self.patching_logger.error('Temp merge directory not set')
            return False
        try:
            merge_temp_dir = os.path.join(self.temp_merge_dir, 'merge_temp')
            os.makedirs(merge_temp_dir, exist_ok=True)
            if self._cancelled:
                return False
            mod_number = None
            chapter_str = None
            if mod_dir:
                parts = mod_dir.replace('\\', '/').split('/')
                if 'DeltahubMergeWorkspace' in parts:
                    idx = parts.index('DeltahubMergeWorkspace')
                    if idx + 1 < len(parts):
                        chapter_str = parts[idx + 1]
                    if idx + 2 < len(parts):
                        mod_number_str = parts[idx + 2]
                        try:
                            mod_number = int(mod_number_str)
                        except ValueError:
                            pass
            if mod_number is not None and chapter_str is not None:
                output_dir = os.path.join(self.temp_merge_dir, 'output')
                cache_running_dir = os.path.join(output_dir, 'DeltahubCache', 'running')
                os.makedirs(cache_running_dir, exist_ok=True)
                chapter_file = os.path.join(cache_running_dir, 'chapterNumber.txt')
                mod_file = os.path.join(cache_running_dir, 'modNumbersCache.txt')
                with open(chapter_file, 'w', encoding='utf-8') as f:
                    f.write(chapter_str)
                with open(mod_file, 'w', encoding='utf-8') as f:
                    f.write(str(mod_number))
                self.patching_logger.debug(f'Set mod number cache: chapter={chapter_str}, mod={mod_number} for export from ready data.win')
            export_scripts = self._get_export_scripts()
            if not export_scripts:
                self.patching_logger.error('No export scripts found! At least one export script is required.')
                return False
            if export_scripts:
                export_temp = os.path.join(merge_temp_dir, 'other_export')
                os.makedirs(export_temp, exist_ok=True)
                export_objects_dir = os.path.join(export_temp, 'Objects')
                os.makedirs(export_objects_dir, exist_ok=True)
                all_exports_successful = self._run_export_scripts(export_scripts, other_file, export_objects_dir, self.temp_merge_dir)
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
                                self._merge_objects_directories(mod_objects_dir, export_objects_dir, mod_name_from_dir)
                            else:
                                shutil.copytree(export_objects_dir, mod_objects_dir)
                            self.patching_logger.info(f'Copied exported objects from export_temp to {mod_objects_dir} for later import')
                    all_imports_successful = self._run_import_scripts_from_dir(None, base_file, export_objects_dir, export_temp)
                    if all_imports_successful:
                        self.patching_logger.info('Successfully merged two data.win files using UTMTCLI scripts')
                    else:
                        self.patching_logger.warning('Some import scripts failed during ready data.win merge, but continuing')
                    return True
            self.patching_logger.error('UTMTCLI merge failed: Cannot merge data.win files')
            self.patching_logger.error('Fallback copy would overwrite base_file and lose previous mod changes')
            self.patching_logger.error('This mod cannot be merged and will be skipped to prevent data loss')
            return False
        except Exception as e:
            self.patching_logger.error(f'Failed to merge two data.win files: {e}', exc_info=True)
            self.patching_logger.error('Cannot use fallback copy as it would cause irreversible data loss')
            return False

    def _apply_file_overrides(self, mod_source_dir: str, target_dir: str, used_archive_names: set, is_modpack: bool, chapter_id: Optional[int] = None) -> bool:
        if not os.path.isdir(mod_source_dir):
            return True
        if used_archive_names is None:
            used_archive_names = set()
        from config.constants import DATA_FILE_EXTENSIONS
        xdelta_extensions = DATA_FILE_EXTENSIONS
        archive_extensions = ('.zip', '.7z', '.rar', '.tar.gz', '.lzma')
        processed_archives = set()
        skip_files = ('config.json', 'mod_config.json', '_icon.png', 'icon.png', 'meta.json', '_deltamodInfo.json')
        if chapter_id is None:
            chapter_id = self._extract_chapter_id_from_path(target_dir)
        for root, dirs, files in os.walk(mod_source_dir):
            rel_path = os.path.relpath(root, mod_source_dir)
            for file in files:
                if file.lower() in skip_files:
                    continue
                source_path = os.path.join(root, file)
                file_lower = file.lower()
                if file_lower.endswith(('.xdelta', '.vcdiff')):
                    if not is_modpack:
                        xdelta_chapter_id = chapter_id if chapter_id is not None else self._extract_chapter_id_from_path(target_dir)
                        target_files = self._find_target_files_for_xdelta(target_dir, file)
                        if target_files:
                            patch_applied = False
                            for target_file in target_files:
                                if xdelta_chapter_id is not None and self.backup_service:
                                    if os.path.exists(target_file):
                                        self.backup_service.backup_file(xdelta_chapter_id, target_file)
                                if self._apply_xdelta_to_file(target_file, source_path):
                                    self.patching_logger.info(f'Applied xdelta patch {file} to {os.path.relpath(target_file, target_dir)}')
                                    patch_applied = True
                                else:
                                    self.patching_logger.warning(f'Failed to apply xdelta patch {file} to {os.path.relpath(target_file, target_dir)}, skipping')
                            if not patch_applied:
                                self.patching_logger.warning(f'Xdelta patch {file} could not be applied to any target files, skipping (xdelta files should not be copied to game directory)')
                        else:
                            self.patching_logger.debug(f'No target files found for xdelta patch {file}, skipping (expected filename: {os.path.splitext(file)[0]})')
                    elif self.xdelta_modpack:
                        rel_path = os.path.relpath(source_path, mod_source_dir)
                        target_path = os.path.join(target_dir, rel_path)
                        os.makedirs(os.path.dirname(target_path), exist_ok=True)
                        try:
                            shutil.copy2(source_path, target_path)
                            self.patching_logger.debug(f'Copied xdelta file {file} to modpack (xdelta_modpack enabled)')
                        except Exception as e:
                            self.patching_logger.warning(f'Failed to copy xdelta file {source_path}: {e}')
                    else:
                        self.patching_logger.debug(f'Skipping xdelta file {file} (xdelta_modpack disabled)')
                    continue
                if file_lower.endswith(xdelta_extensions):
                    continue
                if file_lower.endswith(archive_extensions):
                    normalized_path = os.path.normpath(source_path)
                    if normalized_path in processed_archives:
                        continue
                    processed_archives.add(normalized_path)
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
                        if not self._extract_archive_to_target(source_path, target_dir, chapter_id):
                            self.patching_logger.warning(f'Failed to extract archive {source_path}, continuing...')
                    continue
                rel_path = os.path.relpath(source_path, mod_source_dir)
                target_path = os.path.join(target_dir, rel_path)
                if os.path.normpath(source_path) in processed_archives:
                    continue
                if not is_modpack:
                    is_new_file = not os.path.exists(target_path)
                    if not is_new_file:
                        if chapter_id is not None and self.backup_service:
                            self.backup_service.backup_file(chapter_id, target_path)
                    elif chapter_id is not None and self.backup_service:
                        self.backup_service.mark_file_added(chapter_id, target_path)
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                try:
                    shutil.copy2(source_path, target_path)
                except Exception as e:
                    self.patching_logger.error(f'Failed to copy override file {source_path}: {e}')
                    return False
        return True

    def _extract_archive_to_target(self, archive_path: str, target_dir: str, chapter_id: Optional[int] = None) -> bool:
        try:
            from utils.archive_utils import extract_any_archive
            if chapter_id is None:
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
                        file_lower = file.lower()
                        if file_lower.endswith(('.xdelta', '.vcdiff')):
                            target_files = self._find_target_files_for_xdelta(target_dir, file)
                            if target_files:
                                patch_applied = False
                                for patch_target_file in target_files:
                                    if chapter_id is not None and self.backup_service:
                                        if os.path.exists(patch_target_file):
                                            self.backup_service.backup_file(chapter_id, patch_target_file)
                                    if self._apply_xdelta_to_file(patch_target_file, source_file):
                                        self.patching_logger.info(f'Applied xdelta patch {file} from archive to {os.path.relpath(patch_target_file, target_dir)}')
                                        patch_applied = True
                                    else:
                                        self.patching_logger.warning(f'Failed to apply xdelta patch {file} from archive to {os.path.relpath(patch_target_file, target_dir)}, skipping')
                                if not patch_applied:
                                    self.patching_logger.warning(f'Xdelta patch {file} from archive could not be applied to any target files, copying as regular file')
                                    is_new_file = not os.path.exists(target_file)
                                    if not is_new_file:
                                        if chapter_id is not None and self.backup_service:
                                            self.backup_service.backup_file(chapter_id, target_file)
                                    elif chapter_id is not None and self.backup_service:
                                        self.backup_service.mark_file_added(chapter_id, target_file)
                                    shutil.copy2(source_file, target_file)
                            else:
                                self.patching_logger.debug(f'No target files found for xdelta patch {file} from archive, copying as regular file (expected filename: {os.path.splitext(file)[0]})')
                                is_new_file = not os.path.exists(target_file)
                                if not is_new_file:
                                    if chapter_id is not None and self.backup_service:
                                        self.backup_service.backup_file(chapter_id, target_file)
                                elif chapter_id is not None and self.backup_service:
                                    self.backup_service.mark_file_added(chapter_id, target_file)
                                shutil.copy2(source_file, target_file)
                            continue
                        is_new_file = not os.path.exists(target_file)
                        if not is_new_file:
                            if chapter_id is not None and self.backup_service:
                                self.backup_service.backup_file(chapter_id, target_file)
                        elif chapter_id is not None and self.backup_service:
                            self.backup_service.mark_file_added(chapter_id, target_file)
                        shutil.copy2(source_file, target_file)
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

    _SCRIPT_TYPES = ['Sprites', 'Sounds', 'CodeEntries', 'Fonts', 'Shaders', 'Backgrounds', 'Tilesets', 'Rooms', 'GameObjects', 'Paths', 'Timelines', 'AudioGroups', 'TextureGroupInfo', 'Extensions', 'GeneralInfo']

    def _get_available_scripts(self, prefix: str) -> List[str]:
        return [f'{prefix}{t}' for t in self._SCRIPT_TYPES if self.utmt_wrapper.get_script_path(f'{prefix}{t}')]

    def _get_export_scripts(self) -> List[str]:
        return self._get_available_scripts('Export')

    def _detect_mod_type(self, mod_source_dir: str) -> Dict[str, bool]:
        mod_type = {'has_xdelta_patch': False, 'has_ready_data_win': False, 'has_csx_scripts': False, 'has_file_overrides': False}
        if not os.path.isdir(mod_source_dir):
            return mod_type
        mod_type['has_xdelta_patch'] = bool(self._find_data_patches(mod_source_dir))
        mod_type['has_ready_data_win'] = bool(self._find_ready_data_win_files(mod_source_dir))
        mod_type['has_csx_scripts'] = bool(self._find_csx_scripts(mod_source_dir))
        has_other_files = False
        for root, dirs, files in os.walk(mod_source_dir):
            for file in files:
                file_lower = file.lower()
                if file_lower in ('config.json', '_icon.png', 'mod_config.json'):
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

    @staticmethod
    def _dir_has_files(dir_path: str, ext_filter: tuple = None) -> bool:
        try:
            if not os.path.exists(dir_path):
                return False
            if ext_filter:
                return any(f.endswith(ext_filter) for f in os.listdir(dir_path))
            return bool(os.listdir(dir_path))
        except Exception:
            return False

    def _detect_mod_asset_types(self, mod_dir: str) -> Dict[str, bool]:
        asset_types = {'has_code': False, 'has_textures': False, 'has_shaders': False, 'has_tilesets': False, 'has_fonts': False, 'has_sounds': False, 'has_rooms': False}
        objects_dir = os.path.join(mod_dir, 'Objects')
        if os.path.exists(objects_dir):
            asset_types['has_code'] = self._dir_has_files(os.path.join(objects_dir, 'CodeEntries'))
            asset_types['has_textures'] = any(os.path.exists(os.path.join(objects_dir, d)) for d in ('Sprites', 'Backgrounds', 'Fonts'))
            asset_types['has_shaders'] = self._dir_has_files(os.path.join(objects_dir, 'Shaders'))
            asset_types['has_tilesets'] = self._dir_has_files(os.path.join(objects_dir, 'Backgrounds'), ('.png',))
            asset_types['has_fonts'] = self._dir_has_files(os.path.join(objects_dir, 'Fonts'))
            asset_types['has_sounds'] = self._dir_has_files(os.path.join(objects_dir, 'Sounds'), ('.wav', '.ogg'))
            asset_types['has_rooms'] = self._dir_has_files(os.path.join(objects_dir, 'Rooms'), ('.json',))
        elif os.path.exists(os.path.join(mod_dir, 'data.win')):
            for k in ('has_code', 'has_textures', 'has_shaders', 'has_tilesets', 'has_fonts', 'has_sounds'):
                asset_types[k] = True
            self.patching_logger.debug(f'Objects directory not found for {mod_dir}, assuming mod has all asset types (will be verified by export scripts)')
        return asset_types

    def _select_export_strategy(self, mod_type: Dict[str, bool], mod_asset_types: Dict[str, bool], mod_number: int, has_previous_mod: bool) -> tuple[List[str], Optional[str]]:
        scripts = []
        comparison_file = None
        if mod_type.get('has_ready_data_win') and (not mod_type.get('has_xdelta_patch')) and (not mod_type.get('has_csx_scripts')):
            return ([], None)
        has_any_assets = any([mod_asset_types.get('has_code', False), mod_asset_types.get('has_textures', False), mod_asset_types.get('has_shaders', False), mod_asset_types.get('has_tilesets', False), mod_asset_types.get('has_fonts', False), mod_asset_types.get('has_sounds', False)])
        if has_any_assets or mod_type.get('has_xdelta_patch') or mod_type.get('has_csx_scripts'):
            export_scripts = self._get_export_scripts()
            if not export_scripts:
                self.patching_logger.error('No export scripts found! At least one export script is required.')
                return ([], None)
            scripts.extend(export_scripts)
        comparison_file = None
        return (scripts, comparison_file)

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
            if scripts:
                if self._cancelled:
                    return False
                all_exports_successful = self._run_export_scripts(scripts, mod_data_win, objects_dir, merge_root, label=f'Mod {mod_number} ')
                if not all_exports_successful:
                    self.patching_logger.warning(f'Some export scripts failed for mod {mod_number}')
                    warning_msg = tr('dialogs.patching_warning.export_failed', operation=tr('dialogs.patching_warning.export'), resource=f'mod {mod_number}')
                    if not self._show_patching_warning('export_failed', tr('dialogs.patching_warning.title'), warning_msg):
                        self.patching_logger.info(f'[PATCHING_WARNING] User cancelled merge due to export failure for mod {mod_number}')
                        return False
                    self.patching_logger.info(f'[PATCHING_WARNING] User chose to continue despite export failure for mod {mod_number}')
                    return False
                self.patching_logger.info(f'Successfully exported assets from mod {mod_number} using {scripts}')
                if os.path.exists(objects_dir):
                    code_entries_exported = os.path.join(objects_dir, 'CodeEntries')
                    sprites_exported = os.path.join(objects_dir, 'Sprites')
                    code_count_exported = len([f for f in os.listdir(code_entries_exported) if f.endswith('.gml')]) if os.path.exists(code_entries_exported) else 0
                    sprite_count_exported = len([d for d in os.listdir(sprites_exported) if os.path.isdir(os.path.join(sprites_exported, d))]) if os.path.exists(sprites_exported) else 0
                    self.patching_logger.info(f'[EXPORT] Verified: {code_count_exported} code files, {sprite_count_exported} sprites in Objects directory after export')
                    if code_count_exported == 0 and sprite_count_exported == 0:
                        self.patching_logger.warning(f'[EXPORT] WARNING: Export scripts exported 0 resources for mod {mod_number}! This may indicate a problem or mod has no changes.')
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

    def _perform_parallel_export(self, mods_to_export: List[Any], mods_to_apply: List[Any], mod_patched_files: Dict[int, str], mod_types: Dict[int, Dict], vanilla_data_win: str, merge_root: str, cache_running_dir: str, chapter_str: str, chapter_id: int, progress_base: int, export_progress: int, progress_callback) -> bool:
        if not mods_to_export:
            return True
        log_lock = threading.Lock()
        completed_count = [0]
        total_mods = len(mods_to_export)
        max_workers = min(os.cpu_count() - 1, total_mods, 8)
        max_workers = max(1, max_workers)
        self.patching_logger.info(f'[PARALLEL_EXPORT] Starting parallel export for {total_mods} mod(s) using {max_workers} worker(s)')
        throttler = ProgressThrottler(progress_callback, throttle_ms=150, parent=self)

        def export_single_mod(mod_info):
            mod_data, idx, original_idx, mod_number = mod_info
            mod_name = getattr(mod_data, 'name', 'Unknown')
            thread_id = threading.current_thread().ident
            try:
                with log_lock:
                    self.patching_logger.info(f'[Mod-{mod_number}] [{thread_id}] Starting export for {mod_name}')
                mod_data_win = mod_patched_files.get(mod_number)
                if not mod_data_win or not os.path.exists(mod_data_win):
                    with log_lock:
                        self.patching_logger.warning(f'[Mod-{mod_number}] [{thread_id}] data.win not found, skipping export')
                    return (mod_number, False, mod_name, 'data.win not found')
                mod_dir = os.path.dirname(mod_data_win)
                mod_asset_types = self._detect_mod_asset_types(mod_dir)
                mod_type = mod_types.get(mod_number, {})
                has_previous_mod = mod_number > 1 and mod_number - 1 in mod_patched_files
                scripts, comparison_file = self._select_export_strategy(mod_type, mod_asset_types, mod_number, has_previous_mod)
                if not scripts and comparison_file is None:
                    with log_lock:
                        self.patching_logger.info(f'[Mod-{mod_number}] [{thread_id}] Skipping export - already exported')
                    return (mod_number, True, mod_name, 'already exported')
                with log_lock:
                    self.patching_logger.info(f'[Mod-{mod_number}] [{thread_id}] Exporting using strategy: {scripts}, comparison: {comparison_file}')
                success = self._export_mod_assets_optimized(mod_data_win, mod_number, scripts, comparison_file, vanilla_data_win, merge_root, cache_running_dir, chapter_str)
                if success:
                    objects_dir = os.path.join(mod_dir, 'Objects')
                    if os.path.exists(objects_dir):
                        code_entries_dir = os.path.join(objects_dir, 'CodeEntries')
                        sprites_dir = os.path.join(objects_dir, 'Sprites')
                        shaders_dir = os.path.join(objects_dir, 'Shaders')
                        code_count = len([f for f in os.listdir(code_entries_dir) if f.endswith('.gml')]) if os.path.exists(code_entries_dir) else 0
                        sprite_count = len([d for d in os.listdir(sprites_dir) if os.path.isdir(os.path.join(sprites_dir, d))]) if os.path.exists(sprites_dir) else 0
                        shader_count = len([d for d in os.listdir(shaders_dir) if os.path.isdir(os.path.join(shaders_dir, d))]) if os.path.exists(shaders_dir) else 0
                        with log_lock:
                            self.patching_logger.info(f'[Mod-{mod_number}] [{thread_id}] Export completed: {code_count} code, {sprite_count} sprites, {shader_count} shaders')
                    return (mod_number, True, mod_name, None)
                else:
                    with log_lock:
                        self.patching_logger.warning(f'[Mod-{mod_number}] [{thread_id}] Export failed for {mod_name}')
                    return (mod_number, False, mod_name, 'export failed')
            except Exception as e:
                with log_lock:
                    self.patching_logger.error(f'[Mod-{mod_number}] [{thread_id}] Exception during export: {e}', exc_info=True)
                return (mod_number, False, mod_name, str(e))
        export_tasks = []
        for idx, mod_data in enumerate(mods_to_export):
            original_idx = mods_to_apply.index(mod_data) if mod_data in mods_to_apply else idx
            mod_number = original_idx + 1
            export_tasks.append((mod_data, idx, original_idx, mod_number))
        results = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_mod = {executor.submit(export_single_mod, task): task for task in export_tasks}
            for future in as_completed(future_to_mod):
                if self._cancelled:
                    executor.shutdown(wait=False, cancel_futures=True)
                    return False
                try:
                    mod_number, success, mod_name, error = future.result()
                    results[mod_number] = (success, mod_name, error)
                    completed_count[0] += 1
                    progress = progress_base + int(completed_count[0] / total_mods * export_progress)
                    export_msg = MultiModMerger._safe_tr('status.exporting_assets', f'Exporting assets from {mod_name} ({completed_count[0]}/{total_mods})...', mod=mod_name, current=completed_count[0], total=total_mods)
                    throttler.update_progress(min(progress, 95), export_msg)
                    if not success:
                        self.patching_logger.error(f'[PARALLEL_EXPORT] Export failed for mod {mod_number} ({mod_name}): {error}')
                        executor.shutdown(wait=True, cancel_futures=False)
                        return False
                except Exception as e:
                    self.patching_logger.error(f'[PARALLEL_EXPORT] Exception in export task: {e}', exc_info=True)
                    executor.shutdown(wait=True, cancel_futures=False)
                    return False
        throttler.flush()
        self.patching_logger.info(f'[PARALLEL_EXPORT] All {total_mods} mod(s) exported successfully')
        return True

    def _perform_parallel_filtering(self, vanilla_hashes: Dict[str, Dict[str, str]], mods_dirs_info: List[tuple], progress_base: int, filter_progress: int, progress_callback) -> Dict[int, Optional[str]]:
        if not mods_dirs_info:
            return {}
        log_lock = threading.Lock()
        completed_count = [0]
        total_mods = len(mods_dirs_info)
        max_workers = min(os.cpu_count() - 1, total_mods, 8)
        max_workers = max(1, max_workers)
        self.patching_logger.info(f'[PARALLEL_FILTER] Starting parallel filtering for {total_mods} mod(s) using {max_workers} worker(s)')
        throttler = ProgressThrottler(progress_callback, throttle_ms=150, parent=self)

        def filter_single_mod(mod_info):
            mod_number, mod_objects_dir, mod_name = mod_info
            thread_id = threading.current_thread().ident
            try:
                with log_lock:
                    self.patching_logger.info(f'[Mod-{mod_number}] [{thread_id}] Starting filtering for {mod_name}')
                filtered_dir = self._filter_vanilla_identical_resources(vanilla_hashes, mod_objects_dir, mod_number, mod_name)
                with log_lock:
                    if filtered_dir:
                        self.patching_logger.info(f'[Mod-{mod_number}] [{thread_id}] Filtering completed, unique resources in {filtered_dir}')
                    else:
                        self.patching_logger.info(f'[Mod-{mod_number}] [{thread_id}] Filtering completed, no unique resources')
                return (mod_number, filtered_dir, mod_name, None)
            except Exception as e:
                with log_lock:
                    self.patching_logger.error(f'[Mod-{mod_number}] [{thread_id}] Exception during filtering: {e}', exc_info=True)
                return (mod_number, None, mod_name, str(e))
        results = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_mod = {executor.submit(filter_single_mod, mod_info): mod_info for mod_info in mods_dirs_info}
            for future in as_completed(future_to_mod):
                if self._cancelled:
                    executor.shutdown(wait=False, cancel_futures=True)
                    return {}
                try:
                    mod_number, filtered_dir, mod_name, error = future.result()
                    results[mod_number] = filtered_dir
                    completed_count[0] += 1
                    progress = progress_base + int(completed_count[0] / total_mods * filter_progress)
                    filter_msg = MultiModMerger._safe_tr('status.filtering_resources', f'Filtering resources from {mod_name} ({completed_count[0]}/{total_mods})...', mod=mod_name, current=completed_count[0], total=total_mods)
                    throttler.update_progress(min(progress, 95), filter_msg)
                    if error:
                        self.patching_logger.warning(f'[PARALLEL_FILTER] Filtering warning for mod {mod_number} ({mod_name}): {error}')
                except Exception as e:
                    self.patching_logger.error(f'[PARALLEL_FILTER] Exception in filtering task: {e}', exc_info=True)
                    executor.shutdown(wait=True, cancel_futures=False)
                    return {}
        throttler.flush()
        self.patching_logger.info(f'[PARALLEL_FILTER] All {total_mods} mod(s) filtered successfully')
        return results

    def _get_mod_source_dir(self, mod_data: Any, chapter_id: int) -> Optional[str]:
        key = get_mod_key(mod_data)
        if not key:
            self.patching_logger.warning('_get_mod_source_dir: mod_data has no key')
            return None
        mod_folder_path = self.mod_service.get_mod_folder_path(key)
        if mod_folder_path and os.path.isdir(mod_folder_path):
            source_dir = mod_folder_path
        else:
            mod_name = get_mod_name(mod_data, key)
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
                                from utils.file_utils import load_json
                                config_data = load_json(config_path, migrate_config=True)
                                if (config_data.get('key') or config_data.get('mod_key')) == key:
                                    source_dir = folder_path
                                    break
                            except Exception:
                                pass
                if not source_dir:
                    return None
        game = getattr(mod_data, 'game', None) or getattr(mod_data, 'modgame', None)
        if not game:
            if hasattr(mod_data, 'config_data'):
                config = getattr(mod_data, 'config_data')
                if isinstance(config, dict):
                    game = config.get('game') or config.get('modgame')
            if not game and source_dir:
                config_path = os.path.join(source_dir, 'mod_config.json')
                if os.path.exists(config_path):
                    try:
                        from utils.file_utils import load_json
                        config_data = load_json(config_path, migrate_config=True)
                        game = config_data.get('game') or config_data.get('modgame')
                    except Exception:
                        pass
        chapter_folder_name = get_chapter_folder_name(chapter_id, game=game)
        chapter_dir = os.path.join(source_dir, chapter_folder_name)
        if not os.path.isdir(chapter_dir):
            if chapter_id == 0:
                if game == 'pizzatower':
                    pizzatower_dir = os.path.join(source_dir, 'pizzatower')
                    if os.path.isdir(pizzatower_dir):
                        return pizzatower_dir
                alt_menu_dir = os.path.join(source_dir, 'menu')
                if os.path.isdir(alt_menu_dir):
                    return alt_menu_dir
            elif chapter_id == -1:
                return source_dir
            return None
        return chapter_dir

    def _get_target_dir(self, chapter_id: int, game: Optional[str] = None) -> Optional[str]:
        from models.game_modes import DemoGameMode, UndertaleGameMode, UndertaleYellowGameMode, PizzaTowerGameMode, SugarySpireGameMode
        from config.constants import SLOT_ID_PIZZA_TOWER, SLOT_ID_UNDERTALE, SLOT_ID_UNDERTALE_YELLOW, SLOT_ID_DEMO, SLOT_ID_SUGARY_SPIRE
        _GAME_CONFIGS = {
            'deltarune_demo': (DemoGameMode, 'DELTARUNEdemo.app', lambda s: s.app_state.demo_game_path, [SLOT_ID_DEMO, -1]),
            'undertale': (UndertaleGameMode, 'UNDERTALE.app', None, [SLOT_ID_UNDERTALE, 0]),
            'undertaleyellow': (UndertaleYellowGameMode, 'Undertale Yellow.app', None, [SLOT_ID_UNDERTALE_YELLOW, 0]),
            'pizzatower': (PizzaTowerGameMode, 'PizzaTower.app', None, [SLOT_ID_PIZZA_TOWER]),
            'sugaryspire': (SugarySpireGameMode, 'SugarySpire_ExhibitionNight.app', None, [SLOT_ID_SUGARY_SPIRE, 0]),
        }
        if game:
            if game in _GAME_CONFIGS:
                mode_cls, app_name, path_getter, slot_ids = _GAME_CONFIGS[game]
                gm = mode_cls()
                base_path = path_getter(self) if path_getter else gm.get_game_path(self.app_state.local_config)
                if chapter_id in slot_ids:
                    if not base_path:
                        self.patching_logger.warning(f'{game} game path not found in config for chapter {chapter_id}')
                        return None
                    return self._resolve_macos_path(base_path, app_name)
                if not base_path:
                    return None
            else:
                base_path = self.app_state.game_path
                if not base_path:
                    return None
        else:
            base_path = self.app_state.game_mode.get_game_path(self.app_state.local_config)
            if not base_path:
                return None
            for gkey, (mode_cls, app_name, _, slot_ids) in _GAME_CONFIGS.items():
                if isinstance(self.app_state.game_mode, mode_cls) and chapter_id in slot_ids:
                    return self._resolve_macos_path(base_path, app_name)
        return find_chapter_resource_dir(base_path, chapter_id)

    def _find_data_win(self, target_dir: str) -> Optional[str]:
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
        match = re.search('chapter[_-]?(\\d+)', path, re.IGNORECASE)
        if match:
            return int(match.group(1))
        if 'demo' in path.lower():
            return -1
        return None

    def _find_target_files_for_xdelta(self, target_dir: str, patch_filename: str) -> List[str]:
        target_files = []
        if not os.path.isdir(target_dir):
            return target_files
        excluded_files = {DATA_WIN_FILENAME.lower(), 'game.ios'}
        patch_lower = patch_filename.lower()
        if patch_lower.endswith('.xdelta'):
            patch_base_lower = os.path.splitext(patch_filename)[0].lower()
        elif patch_lower.endswith('.vcdiff'):
            patch_base_lower = os.path.splitext(patch_filename)[0].lower()
        else:
            patch_base_lower = os.path.splitext(patch_filename)[0].lower()
        for root, dirs, files in os.walk(target_dir):
            for file in files:
                file_lower = file.lower()
                if file_lower in excluded_files:
                    continue
                if file_lower == patch_base_lower:
                    target_files.append(os.path.join(root, file))
        return target_files

    def _apply_xdelta_to_file(self, target_file: str, patch_path: str) -> bool:
        if not self._ensure_xdelta_executable():
            self.patching_logger.warning(f'xdelta executable not found, cannot apply patch to {os.path.basename(target_file)}')
            return False
        if not os.path.exists(target_file) or not os.path.exists(patch_path):
            self.patching_logger.warning(f'Target or patch file does not exist: {target_file}, {patch_path}')
            return False
        temp_output = None
        try:
            temp_output = target_file + '.tmp'
            self._temp_files_to_cleanup.append(temp_output)
            if not os.access(os.path.dirname(temp_output), os.W_OK):
                self.patching_logger.warning(f'Temp directory is not writable: {os.path.dirname(temp_output)}')
                return False
            returncode, stdout, stderr = self._run_xdelta_process(target_file, patch_path, temp_output)
            if returncode != 0:
                self.patching_logger.debug(f'Failed to apply xdelta patch to {os.path.basename(target_file)}: {stderr.strip() if stderr else "Unknown error"}')
                return False
            if not os.path.exists(temp_output):
                self.patching_logger.warning(f'Temp output file was not created: {temp_output}')
                return False
            if not safe_move(temp_output, target_file):
                raise OSError(f'Failed to move patched file from {temp_output} to {target_file}')
            if temp_output in self._temp_files_to_cleanup:
                self._temp_files_to_cleanup.remove(temp_output)
            self.patching_logger.info(f'Successfully applied xdelta patch to {os.path.basename(target_file)}')
            return True
        except Exception as e:
            self.patching_logger.error(f'Error applying xdelta patch to {os.path.basename(target_file)}: {e}', exc_info=True)
            self._cleanup_temp_output(temp_output)
            return False

    def cleanup_processes_and_temp_files(self) -> None:
        processes_to_cleanup = list(self._active_processes)
        for process in processes_to_cleanup:
            try:
                if process.poll() is None:
                    process_type = 'UTMTCLI' if 'UndertaleModCli' in str(process.args) or 'dotnet' in str(process.args) else 'xdelta'
                    self.patching_logger.warning(f'Terminating active {process_type} process (PID: {process.pid})')
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process_type = 'UTMTCLI' if 'UndertaleModCli' in str(process.args) or 'dotnet' in str(process.args) else 'xdelta'
                        self.patching_logger.warning(f'Force killing {process_type} process (PID: {process.pid})')
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
        has_backups = bool(self.backup_service and self.backup_service.original_files)
        if not has_backups:
            self._cleanup_temp_dir(keep_backups=False)
        else:
            self._cleanup_temp_dir(keep_backups=True)

    def restore_all_backups(self) -> bool:
        if self.backup_service:
            return self.backup_service.restore_all_backups()
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
                        backup_service = BackupManager(backup_dir, patching_logger=self.patching_logger)
                        modification_order_data = manifest_data.get('modification_order', {})
                        for chapter_key, files_dict in original_files_data.items():
                            chapter_id = int(chapter_key)
                            for file_path, backup_path in files_dict.items():
                                if backup_path is None or backup_path == 'null':
                                    backup_service.original_files.setdefault(chapter_id, {})[file_path] = None
                                else:
                                    backup_service.original_files.setdefault(chapter_id, {})[file_path] = backup_path
                            if chapter_key in modification_order_data:
                                backup_service._modification_order[chapter_id] = modification_order_data[chapter_key]
                        for chapter_key, file_list in added_files_data.items():
                            chapter_id = int(chapter_key)
                            if not isinstance(file_list, list):
                                continue
                            for file_path in file_list:
                                backup_service.added_files.setdefault(chapter_id, {})[file_path] = True
                                if chapter_id not in backup_service.original_files or file_path not in backup_service.original_files[chapter_id]:
                                    backup_service.original_files.setdefault(chapter_id, {})[file_path] = None
                        result = backup_service.restore_all_backups()
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
                    backup_service = BackupManager(backup_dir, patching_logger=self.patching_logger)
                    for chapter_key, files_dict in multimod_backups.items():
                        chapter_id = int(chapter_key)
                        for file_path, backup_path in files_dict.items():
                            if backup_path is None or backup_path == 'null':
                                backup_service.original_files.setdefault(chapter_id, {})[file_path] = None
                            else:
                                backup_service.original_files.setdefault(chapter_id, {})[file_path] = backup_path
                    result = backup_service.restore_all_backups()
                else:
                    self.patching_logger.debug('No valid backup data found in manifest')
                    return False
                if result:
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
                else:
                    self.patching_logger.warning('Restoration failed or incomplete - keeping temp directories for manual recovery')
                return result
            except Exception as e:
                self.patching_logger.warning(f'Failed to load backups from manifest: {e}')
        self.patching_logger.debug('No backup files found to restore')
        return False
