import os
import sys
import platform
import shutil
import subprocess
import webbrowser
import logging
from typing import Dict, Optional, Any, List
from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal
from managers.localization_manager import tr
from utils.file_utils import ensure_writable
from utils.game_utils import is_game_running, is_demo_mode, is_undertale_mode, is_undertale_yellow_mode
from utils.path_utils import find_chapter_resource_dir, resolve_game_executable
from utils.mod_utils import get_mod_key
from workers.game_monitor import GameMonitorWorker
from managers.multi_mod_merger import MultiModMerger
from config.constants import UI_COLORS, SLOT_ID_UNIVERSAL


class GameLauncher(QObject):
    status_changed = pyqtSignal(str, str)
    progress_updated = pyqtSignal(int)
    game_launch_started = pyqtSignal()
    game_launch_finished = pyqtSignal()
    multi_mod_merge_finished = pyqtSignal(bool)

    def __init__(self, app_state, feedback_manager, mod_manager, save_manager=None, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.feedback_manager = feedback_manager
        self.mod_manager = mod_manager
        self.save_manager = save_manager
        self.monitor_thread = None
        self._backup_temp_dir = None
        self._backup_files = {}
        self._mod_files_to_cleanup = []
        self._mod_dirs_to_cleanup = []
        self._direct_launch_cleanup_info = None
        self._collection_backup_info = {}
        self.multi_mod_merger = MultiModMerger(app_state, mod_manager, parent)
        self.multi_mod_merger.status_update.connect(self._on_merge_status)
        self.multi_mod_merger.progress_update.connect(self._on_merge_progress)
        self.multi_mod_merger._session_manifest_path = os.path.join(self.app_state.config_dir, 'session.lock')
        self._merge_thread = None
        self._pending_selections = None
        self._merge_finished_callback = None

    def _stop_monitor_thread(self):
        if not self.monitor_thread:
            return
        try:
            if self.monitor_thread.isRunning():
                self.monitor_thread.requestInterruption()
                self.monitor_thread.quit()
                if not self.monitor_thread.wait(2000):
                    logging.warning('monitor thread did not stop in time')
                    self.monitor_thread.terminate()
                    self.monitor_thread.wait(1000)
            self.monitor_thread.deleteLater()
            if hasattr(self, 'monitor_worker') and self.monitor_worker is not None:
                self.monitor_worker.deleteLater()
        except Exception as e:
            logging.error(f'monitor thread cleanup failed: {e}', exc_info=True)

    def launch_game_with_all_mods(self, execute_plugin_hooks=None, restore_window_callback=None):
        if self.save_manager:
            if is_undertale_mode(self.app_state.game_mode) or is_undertale_yellow_mode(self.app_state.game_mode):
                collection_idx = -1
            else:
                collection_idx = self.save_manager.prompt_for_save_collection_on_launch()
            if collection_idx is None:
                if restore_window_callback:
                    restore_window_callback()
                return
            if collection_idx != -1:
                self._collection_backup_info = self.save_manager.apply_collection_saves_for_launch(collection_idx)
        selections = self._get_used_mods_selections()
        self._launch_game_with_selections(selections, execute_plugin_hooks, restore_window_callback)

    def _get_used_mods_selections(self) -> Dict[int, Any]:
        try:
            parent_obj = self.parent()
        except (AttributeError, TypeError):
            parent_obj = None
        slot_manager = getattr(parent_obj, 'slot_manager', None) if parent_obj else None
        if not slot_manager or not hasattr(slot_manager, 'get_active_mod_selections'):
            selections = {}
            for chapter_id in range(5):
                selections[chapter_id] = []
            return selections
        return slot_manager.get_active_mod_selections()

    def _launch_game_with_selections(self, selections: Dict[int, Any], execute_plugin_hooks=None, restore_window_callback=None):
        self.execute_plugin_hooks = execute_plugin_hooks
        self.restore_window_callback = restore_window_callback
        if execute_plugin_hooks:
            execute_plugin_hooks('on_before_game_launch')
        self.status_changed.emit(tr('status.launching_game'), UI_COLORS['status_success'])
        if not self._find_and_validate_game_path(selections):
            self._handle_launch_failure()
            return
        has_list_format = any((isinstance(mods_list, list) for mods_list in selections.values()))
        needs_multi_mod = has_list_format and any((len(mods_list) > 0 for mods_list in selections.values() if isinstance(mods_list, list)))
        logging.info(f'Multi-mod check: needs_multi_mod={needs_multi_mod} (has_list_format={has_list_format})')
        if needs_multi_mod:
            logging.info('Using multi-mod merger for game launch')
            self.app_state.progress_bar_visible = True
            self.app_state.progress_bar_value = 0
            self.app_state.is_merging = True
            self.app_state.action_button_text = tr('ui.cancel_button')
            self.app_state.action_button_enabled = True
            self._pending_selections = selections
            if not self._prepare_game_files_multi_mod_async(selections):
                logging.error('Failed to start multi-mod merge')
                self.app_state.progress_bar_visible = False
                self.app_state.is_merging = False
                self._handle_launch_failure()
                return
            return
        else:
            self._continue_after_merge(selections, True)

    def _handle_launch_failure(self):
        if hasattr(self, 'restore_window_callback') and self.restore_window_callback:
            self.restore_window_callback()

    def _execute_game(self, launch_config: Dict[str, Any], vanilla_mode: bool = False):
        target_path = launch_config.get('target')
        working_directory = launch_config.get('cwd')
        launch_type = launch_config.get('type')
        if not target_path:
            self.status_changed.emit(tr('errors.launch_target_not_defined'), 'red')
            if hasattr(self, 'restore_window_callback') and self.restore_window_callback:
                self.restore_window_callback()
            return
        try:
            self._stop_monitor_thread()
            if launch_type == 'webbrowser':
                self.monitor_thread = QThread(self)
                self.monitor_worker = GameMonitorWorker(None, vanilla_mode)
                self.monitor_worker.moveToThread(self.monitor_thread)
                self.monitor_worker.finished.connect(self._on_game_process_finished)
                self.monitor_thread.started.connect(self.monitor_worker.run)
                self.monitor_thread.start()
                webbrowser.open(target_path)
                self.status_changed.emit(tr('status.launching_via_steam'), UI_COLORS['status_steam'])
                return
            if not working_directory or not os.path.isdir(working_directory):
                msg = tr('errors.working_directory_not_found', path=working_directory)
                self.status_changed.emit(msg, 'red')
                if hasattr(self, 'restore_window_callback') and self.restore_window_callback:
                    self.restore_window_callback()
                return
            system = platform.system()
            if system == 'Darwin':
                use_custom_exe = self.app_state.local_config.get('use_custom_executable', False)
                if use_custom_exe:
                    subprocess.Popen(['open', target_path])
                    self.status_changed.emit(tr('status.macos_file_opened'), UI_COLORS['status_steam'])
                    if getattr(self, 'is_shortcut_launch', False):
                        sys.exit(0)
                    elif hasattr(self, 'restore_window_callback') and self.restore_window_callback:
                        QTimer.singleShot(2000, self.restore_window_callback)
                    return
                if target_path.endswith('.app'):
                    process = subprocess.Popen(['open', '-W', target_path])
            else:
                command = [target_path]
                if system == 'Linux' and target_path.lower().endswith('.exe'):
                    is_steam_launch = self.app_state.local_config.get('launch_via_steam', False)
                    if not is_steam_launch:
                        command.insert(0, 'wine')
                creationflags = 0
                if system == 'Windows':
                    creationflags = 8
                process = subprocess.Popen(command, cwd=working_directory, creationflags=creationflags)
            self.status_changed.emit(tr('status.game_launched_waiting_for_exit'), UI_COLORS['status_steam'])
            self.monitor_thread = QThread(self)
            self.monitor_worker = GameMonitorWorker(process, vanilla_mode)
            self.monitor_worker.moveToThread(self.monitor_thread)
            self.monitor_worker.finished.connect(self._on_game_process_finished)
            self.monitor_thread.started.connect(self.monitor_worker.run)
            self.monitor_thread.start()
        except Exception as e:
            self.status_changed.emit(tr('errors.game_launch_error', error=str(e)), 'red')
            if hasattr(self, 'restore_window_callback') and self.restore_window_callback:
                self.restore_window_callback()

    def _on_game_process_finished(self, vanilla_mode: bool):
        if hasattr(self, 'execute_plugin_hooks') and self.execute_plugin_hooks:
            self.execute_plugin_hooks('on_before_game_exit')
        if getattr(self, 'is_shortcut_launch', False):
            sys.exit(0)
        else:
            self._check_game_running(vanilla_mode)

    def _check_game_running(self, vanilla_mode):
        if is_game_running():
            QTimer.singleShot(2000, lambda: self._check_game_running(vanilla_mode))
        else:
            self.status_changed.emit(tr('status.game_closed_restoring_files'), UI_COLORS['status_info'])
            self._cleanup_direct_launch_files()
            if self.save_manager and self._collection_backup_info:
                self.save_manager.restore_original_saves_after_launch(self._collection_backup_info)
                self._collection_backup_info = {}
            if self.monitor_thread:
                self._stop_monitor_thread()
                self.monitor_thread = None
                if hasattr(self, 'monitor_worker'):
                    self.monitor_worker = None
            self.game_launch_finished.emit()

    def _determine_launch_config(self, selections: Dict[int, Any]) -> Optional[Dict[str, Any]]:
        use_steam = self.app_state.local_config.get('launch_via_steam', False)
        direct_launch_slot_id = self.app_state.local_config.get('direct_launch_slot_id', SLOT_ID_UNIVERSAL)
        is_chapter_mode = self.app_state.current_mode == 'chapter'
        direct_launch = direct_launch_slot_id >= 0 and direct_launch_slot_id != 0 and is_chapter_mode and self.app_state.game_mode.direct_launch_allowed and (platform.system() != 'Darwin')
        if use_steam and self.app_state.game_mode.steam_id:
            return {'target': f'steam://rungameid/{self.app_state.game_mode.steam_id}', 'cwd': None, 'type': 'webbrowser'}
        if direct_launch:
            return self._handle_direct_launch(direct_launch_slot_id)
        launch_target = self._get_executable_path()
        if not launch_target:
            self.status_changed.emit(tr('errors.executable_not_found'), UI_COLORS['status_error'])
            return None
        return {'target': launch_target, 'cwd': self._get_current_game_path(), 'type': 'subprocess'}

    def _handle_direct_launch(self, selected_tab_index: int) -> Optional[Dict[str, Any]]:
        chapter_id = self.app_state.game_mode.get_chapter_id(selected_tab_index)
        if chapter_id == 0:
            self.status_changed.emit(tr('ui.direct_launch_menu_not_allowed'), UI_COLORS['status_warning'])
            return None
        chapter_folder = find_chapter_resource_dir(self._get_current_game_path(), chapter_id)
        source_exe = self._get_source_executable_path()
        use_custom_exe = self.app_state.local_config.get('use_custom_executable', False)
        if not chapter_folder or not source_exe:
            self.status_changed.emit(tr('errors.direct_launch_error'), UI_COLORS['status_error'])
            return None
        try:
            if not ensure_writable(chapter_folder):
                raise PermissionError(tr('errors.no_write_permission_for', path=chapter_folder))
            if use_custom_exe:
                target_exe = os.path.join(chapter_folder, os.path.basename(source_exe))
            else:
                if is_undertale_mode(self.app_state.game_mode) or is_undertale_yellow_mode(self.app_state.game_mode):
                    exe_name = 'UNDERTALE.exe' if is_undertale_mode(self.app_state.game_mode) else 'Undertale Yellow.exe'
                else:
                    exe_name = 'DELTARUNE.exe'
                target_exe = os.path.join(chapter_folder, exe_name)
            shutil.copy2(source_exe, target_exe)
            self._direct_launch_cleanup_info = {'target_exe': target_exe, 'source_exe': source_exe, 'chapter_folder': chapter_folder, 'use_custom_exe': use_custom_exe}
            return {'target': target_exe, 'cwd': chapter_folder, 'type': 'subprocess'}
        except PermissionError:
            self.status_changed.emit(tr('errors.permission_denied'), UI_COLORS['status_error'])
            return None

    def _get_executable_path(self):
        use_custom_exe = self.app_state.local_config.get('use_custom_executable', False)
        if use_custom_exe:
            custom_path = self.app_state.local_config.get(self.app_state.game_mode.get_custom_exec_config_key(), '')
            if custom_path and os.path.isfile(custom_path):
                return custom_path
        current_game_path = self._get_current_game_path()
        if not current_game_path or not os.path.isdir(current_game_path):
            return None
        from utils.game_utils import is_undertale_yellow_mode
        is_undertale = is_undertale_mode(self.app_state.game_mode) or is_undertale_yellow_mode(self.app_state.game_mode)
        executable = resolve_game_executable(current_game_path, is_undertale)
        if not executable:
            self.status_changed.emit(tr('errors.executable_not_found_deltarune'), UI_COLORS['status_error'])
        return executable

    def _get_source_executable_path(self):
        if self.app_state.local_config.get('use_custom_executable', False):
            cfg_key = self.app_state.game_mode.get_custom_exec_config_key()
            return self.app_state.local_config.get(cfg_key, '')
        return self._get_executable_path()

    def _get_current_game_path(self) -> str:
        return self.app_state.game_mode.get_game_path(self.app_state.local_config) or ''

    def _prepare_game_files_multi_mod_async(self, selections: Dict[int, List[Any]]) -> bool:
        import logging
        from workers.mod_merge_thread import ModMergeThread
        logging.info('Starting multi-mod merge in background thread')
        chapter_mods = {chapter_id: mods_list for chapter_id, mods_list in selections.items() if isinstance(mods_list, list) and mods_list}
        if not chapter_mods:
            self._continue_after_merge(selections, True)
            return True
        session_manifest_path = os.path.join(self.app_state.config_dir, 'session.lock')
        self._merge_thread = ModMergeThread(self.app_state, self.mod_manager, chapter_mods, session_manifest_path, self)
        self._merge_thread.progress_update.connect(self._on_merge_progress)
        self._merge_thread.status_update.connect(self._on_merge_status)
        self._merge_thread.finished.connect(lambda success: self._on_merge_finished(selections, success))
        self.app_state.current_task = self._merge_thread
        self._merge_thread.start()
        return True

    def _on_merge_finished(self, selections: Dict[int, Any], success: bool):
        self.app_state.progress_bar_visible = False
        self.app_state.is_merging = False
        self.app_state.clear_current_task()
        self.app_state.action_button_text = None
        merge_thread = self._merge_thread
        if merge_thread:
            try:
                if merge_thread.isRunning():
                    merge_thread.wait(5000)
                if merge_thread.merger:
                    self.multi_mod_merger = merge_thread.merger
                merge_thread.deleteLater()
            except Exception as e:
                logging.error(f'Error cleaning up merge thread: {e}', exc_info=True)
            finally:
                self._merge_thread = None
        if not success:
            if merge_thread and (merge_thread.isInterruptionRequested() or getattr(merge_thread, '_cancelled', False)):
                logging.info('Multi-mod merge was cancelled by user')
            else:
                self._handle_launch_failure()
            return
        logging.info('Multi-mod merge completed successfully')
        self._continue_after_merge(selections, True)

    def _continue_after_merge(self, selections: Dict[int, Any], merge_success: bool):
        if not merge_success:
            return
        has_list_format = any((isinstance(mods_list, list) for mods_list in selections.values()))
        needs_multi_mod = has_list_format and any((len(mods_list) > 0 for mods_list in selections.values() if isinstance(mods_list, list)))
        if needs_multi_mod:
            pass
        elif hasattr(self, 'restore_window_callback') and self.restore_window_callback:
            self.game_launch_started.emit()
        launch_config = self._determine_launch_config(selections)
        if not launch_config:
            self._handle_launch_failure()
            return
        if needs_multi_mod:
            if hasattr(self, 'restore_window_callback') and self.restore_window_callback:
                self.game_launch_started.emit()
        self._execute_game(launch_config)
        if self.execute_plugin_hooks:
            self.execute_plugin_hooks('on_after_game_launch')

    def _on_merge_status(self, message: str, status_type: str):
        color = UI_COLORS.get(f'status_{status_type}', UI_COLORS['status_error'])
        self.status_changed.emit(message, color)

    def _on_merge_progress(self, progress: int, message: str):
        self.app_state.progress_bar_value = progress
        if message:
            self.status_changed.emit(message, UI_COLORS['status_info'])

    def _verify_file_integrity(self, file_path: str, expected_size: Optional[int] = None) -> bool:
        try:
            if not os.path.exists(file_path):
                logging.error(f'_verify_file_integrity: file does not exist: {file_path}')
                return False
            if not os.path.isfile(file_path):
                logging.error(f'_verify_file_integrity: path is not a file: {file_path}')
                return False
            actual_size = os.path.getsize(file_path)
            if expected_size is not None and actual_size != expected_size:
                logging.error(f'_verify_file_integrity: size mismatch for {file_path}: expected {expected_size}, got {actual_size}')
                return False
            with open(file_path, 'rb') as f:
                f.read(1)
            return True
        except Exception as e:
            logging.error(f'_verify_file_integrity: verification failed for {file_path}: {e}', exc_info=True)
            return False

    def _cleanup_direct_launch_files(self):
        restore_errors = []
        try:
            if hasattr(self, 'multi_mod_merger') and self.multi_mod_merger:
                try:
                    logging.info('_cleanup_direct_launch_files: restoring multi-mod backups')
                    restored = self.multi_mod_merger.restore_all_backups()
                    if restored:
                        logging.info('_cleanup_direct_launch_files: multi-mod backups restored successfully')
                        self.status_changed.emit(tr('status.files_restored'), UI_COLORS['status_success'])
                    else:
                        logging.debug('_cleanup_direct_launch_files: no multi-mod backups to restore')
                except Exception as e:
                    error_msg = f'Failed to restore multi-mod backups: {e}'
                    logging.error(f'_cleanup_direct_launch_files: {error_msg}', exc_info=True)
                    restore_errors.append(error_msg)
            cleanup_info = self._direct_launch_cleanup_info
            if cleanup_info:
                if cleanup_info.get('save_collection_swap'):
                    logging.info('_cleanup_direct_launch_files: restoring save collection swap')
                    collection_path = cleanup_info.get('collection_path')
                    backup_path = cleanup_info.get('backup_path')
                    current_save_path = self.app_state.save_path
                    if not os.path.exists(current_save_path):
                        from utils.game_utils import get_default_save_path
                        current_save_path = self.app_state.local_config.get('save_path') or get_default_save_path()
                    if collection_path and backup_path and os.path.exists(current_save_path):
                        try:
                            if os.path.exists(collection_path):
                                shutil.rmtree(collection_path)
                            os.makedirs(collection_path, exist_ok=True)
                            import re
                            ignore_pattern = shutil.ignore_patterns('*_*_*')
                            shutil.copytree(current_save_path, collection_path, dirs_exist_ok=True, ignore=ignore_pattern)
                            for item in os.listdir(current_save_path):
                                item_path = os.path.join(current_save_path, item)
                                if not (os.path.isdir(item_path) and re.match('(.+?)_(\\d+)_(\\d+)$', item)):
                                    if os.path.isdir(item_path):
                                        shutil.rmtree(item_path)
                                    else:
                                        os.remove(item_path)
                            if os.path.exists(backup_path):
                                shutil.copytree(backup_path, current_save_path, dirs_exist_ok=True)
                                shutil.rmtree(backup_path)
                            logging.info('_cleanup_direct_launch_files: save collection swap restored successfully')
                        except Exception as e:
                            error_msg = f'Save collection swap restore failed: {e}'
                            logging.error(f'_cleanup_direct_launch_files: {error_msg}', exc_info=True)
                            restore_errors.append(error_msg)
                if 'target_exe' in cleanup_info and os.path.exists(cleanup_info['target_exe']):
                    try:
                        os.remove(cleanup_info['target_exe'])
                        logging.info(f"_cleanup_direct_launch_files: removed direct launch exe: {cleanup_info['target_exe']}")
                    except Exception as e:
                        error_msg = f'Failed to remove direct launch exe: {e}'
                        logging.error(f'_cleanup_direct_launch_files: {error_msg}', exc_info=True)
                        restore_errors.append(error_msg)
                self._direct_launch_cleanup_info = None
            if restore_errors:
                error_summary = f'Errors during cleanup: {len(restore_errors)} failure(s). See logs for details.'
                logging.error(f'_cleanup_direct_launch_files: {error_summary}. Errors: {restore_errors[:3]}')
                self.status_changed.emit(tr('errors.files_restore_error', error=str(restore_errors[0])), UI_COLORS['status_error'])
        except Exception as e:
            error_msg = f'Critical error during file restoration: {e}'
            logging.error(f'_cleanup_direct_launch_files: {error_msg}', exc_info=True)
            self.status_changed.emit(tr('errors.files_restore_error', error=str(e)), UI_COLORS['status_error'])

    def recover_previous_session(self):
        try:
            self.feedback_manager.update_status(tr('status.recovering_previous_session'), UI_COLORS['status_warning'])
            if hasattr(self, 'multi_mod_merger') and self.multi_mod_merger:
                try:
                    restored = self.multi_mod_merger.restore_all_backups()
                    if restored:
                        logging.info('recover_previous_session: backups restored successfully')
                        self.feedback_manager.update_status(tr('status.files_restored'), UI_COLORS['status_success'])
                    else:
                        logging.debug('recover_previous_session: no backups to restore')
                except Exception as e:
                    error_msg = f'Failed to restore backups: {e}'
                    logging.error(f'recover_previous_session: {error_msg}', exc_info=True)
                    self.feedback_manager.update_status(tr('errors.files_restore_error', error=str(e)), UI_COLORS['status_error'])
        except Exception as e:
            error_msg = f'Failed to recover previous session: {e}'
            logging.error(f'recover_previous_session: {error_msg}', exc_info=True)
            self.feedback_manager.update_status(tr('errors.files_restore_error', error=str(e)), UI_COLORS['status_error'])

    def _find_and_validate_game_path(self, selections: Optional[Dict[int, Any]] = None, is_initial: bool = False):
        from utils.game_utils import is_valid_game_path
        from utils.file_utils import autodetect_path
        path_from_config = self._get_current_game_path()
        skip_data_check = bool(selections and self._has_mods_with_data_files(selections)) if selections else False
        if is_demo_mode(self.app_state.game_mode):
            game_type = 'deltarune'
            game_name = 'DELTARUNEdemo'
        elif is_undertale_mode(self.app_state.game_mode):
            game_type = 'undertale'
            game_name = 'UNDERTALE'
        elif is_undertale_yellow_mode(self.app_state.game_mode):
            game_type = 'undertaleyellow'
            game_name = 'UNDERTALE Yellow'
        else:
            game_type = 'deltarune'
            game_name = 'DELTARUNE'
        if is_valid_game_path(path_from_config, skip_data_check, game_type):
            self.status_changed.emit(tr('status.game_path', path=path_from_config), UI_COLORS['status_info'])
            return True
        self.status_changed.emit(tr('status.autodetecting_path'), UI_COLORS['status_info'])
        autodetected_path = autodetect_path(game_name)
        if autodetected_path and is_valid_game_path(autodetected_path, skip_data_check, game_type):
            self.app_state.game_mode.set_game_path(self.app_state.local_config, autodetected_path)
            self.status_changed.emit(tr('status.game_folder_found', path=autodetected_path), UI_COLORS['status_success'])
            return True
        if is_initial:
            self.status_changed.emit(tr('status.no_game_path'), UI_COLORS['status_error'])
        return False

    def _mod_has_data_files_for_chapter(self, mod, chapter_id: int) -> bool:
        mod_key = get_mod_key(mod)
        if not mod_key:
            return False
        if mod_key.startswith('local_'):
            mod_config = self.mod_manager.get_mod_config(mod_key)
            if mod_config:
                chapter_files = mod_config.get('files', {}).get(str(chapter_id), {})
                if chapter_files.get('data_file_url'):
                    return True
        else:
            chapter_data = mod.get_chapter_data(chapter_id)
            if chapter_data and hasattr(chapter_data, 'data_file_url') and chapter_data.data_file_url:
                return True
        return False

    def _has_mods_with_data_files(self, selections: Dict[int, Any]) -> bool:
        for ui_index, mod_data in selections.items():
            if isinstance(mod_data, list):
                if not mod_data:
                    continue
                for mod in mod_data:
                    chapter_id = self.app_state.game_mode.get_chapter_id(ui_index)
                    if self._mod_has_data_files_for_chapter(mod, chapter_id):
                        return True
                continue
            if mod_data == 'no_change':
                continue
            mod = next((m for m in self.app_state.all_mods if m.key == mod_data), None)
            if not mod:
                continue
            chapter_id = self.app_state.game_mode.get_chapter_id(ui_index)
            if self._mod_has_data_files_for_chapter(mod, chapter_id):
                return True
        return False
