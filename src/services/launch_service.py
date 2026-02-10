"""Game launch and mod patching management."""
import os
import platform
import shutil
import subprocess
import webbrowser
import logging
from typing import Dict, Optional, Any, List
from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import QDialog
from services.localization_service import tr
from utils.file_utils import ensure_writable
from utils.path_utils import is_path_in_steam_common
from services.game_detection_service import is_game_running, get_game_name_string, get_game_type_string
from models.game_modes import UndertaleGameMode, UndertaleYellowGameMode, PizzaTowerGameMode, SugarySpireGameMode, FullGameMode
from utils.path_utils import find_chapter_resource_dir, resolve_game_executable
from services.patching_log_service import rotate_patching_log
from workers.game_monitor_worker import GameMonitorWorker
from services.mod_patching_service import ModPatcher
from config.constants import UI_COLORS, SLOT_ID_UNIVERSAL


class GameLauncher(QObject):
    """Manages game launching, mod patching, and game monitoring."""
    status_changed = pyqtSignal(str, str)
    progress_updated = pyqtSignal(int)
    game_launch_started = pyqtSignal()
    game_launch_finished = pyqtSignal()
    mod_patching_finished = pyqtSignal(bool)

    def __init__(self, app_state, feedback_service, mod_service, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.feedback_service = feedback_service
        self.mod_service = mod_service
        self.monitor_thread = None
        self._backup_temp_dir = None
        self._backup_files = {}
        self._mod_files_to_cleanup = []
        self._mod_dirs_to_cleanup = []
        self._direct_launch_cleanup_info = None
        self.mod_patcher = ModPatcher(app_state, mod_service, parent)
        self.mod_patcher.status_update.connect(self._on_patching_status)
        self.mod_patcher.progress_update.connect(self._on_patching_progress)
        self.mod_patcher._session_manifest_path = os.path.join(self.app_state.config_dir, 'session.lock')
        self._patching_thread = None
        self._pending_selections = None
        self._patching_finished_callback = None
        self.restore_window_callback = None
        self.execute_plugin_hooks = None

    def _on_warning_confirmation_needed(self, warning_type: str, title: str, message: str):
        from PyQt6.QtWidgets import QMessageBox
        msg_box = QMessageBox()
        msg_box.setWindowTitle(title)
        msg_box.setText(message)
        msg_box.setIcon(QMessageBox.Icon.Warning)
        continue_btn = msg_box.addButton(tr('dialogs.patching_warning.continue_button'), QMessageBox.ButtonRole.AcceptRole)
        cancel_btn = msg_box.addButton(tr('dialogs.patching_warning.cancel_button'), QMessageBox.ButtonRole.RejectRole)
        msg_box.setDefaultButton(cancel_btn)
        msg_box.exec()
        result = msg_box.clickedButton() == continue_btn
        if self._patching_thread:
            self._patching_thread.set_warning_response(result)

    def _stop_monitor_thread(self):
        if not self.monitor_thread:
            return
        try:
            if self.monitor_thread.isRunning():
                self.monitor_thread.requestInterruption()
                self.monitor_thread.quit()
            self.monitor_thread.deleteLater()
            if hasattr(self, 'monitor_worker') and self.monitor_worker is not None:
                self.monitor_worker.deleteLater()
        except Exception as e:
            logging.error(f'monitor thread cleanup failed: {e}', exc_info=True)

    def launch_game_with_all_mods(self, execute_plugin_hooks=None, restore_window_callback=None):
        selections = self._get_used_mods_selections()
        self._launch_game_with_selections(selections, execute_plugin_hooks, restore_window_callback)

    def _get_used_mods_selections(self) -> Dict[int, Any]:
        try:
            parent_obj = self.parent()
        except (AttributeError, TypeError):
            parent_obj = None
        slot_service = getattr(parent_obj, 'slot_service', None) if parent_obj else None
        if not slot_service or not hasattr(slot_service, 'get_active_mod_selections'):
            return {chapter_id: [] for chapter_id in range(5)}
        return slot_service.get_active_mod_selections()

    def _launch_game_with_selections(self, selections: Dict[int, Any], execute_plugin_hooks=None, restore_window_callback=None):
        rotate_patching_log()
        self.execute_plugin_hooks = execute_plugin_hooks
        self.restore_window_callback = restore_window_callback
        if execute_plugin_hooks:
            hook_result = execute_plugin_hooks('on_before_game_launch')
            if hook_result is False:
                if restore_window_callback:
                    restore_window_callback()
                return
            self._hook_result = hook_result
        self.status_changed.emit(tr('status.launching_game'), UI_COLORS['status_success'])
        has_selected_mods = self._has_selected_mods(selections)
        current_path = self._get_current_game_path()
        if not current_path or not os.path.exists(current_path):
            if not self._find_and_validate_game_path(selections, is_initial=False):
                if has_selected_mods:
                    self.status_changed.emit(tr('status.game_path_required_for_mods'), UI_COLORS['status_error'])
                else:
                    self.status_changed.emit(tr('status.no_game_path'), UI_COLORS['status_error'])
                self._handle_launch_failure()
                return
            current_path = self._get_current_game_path()
        if has_selected_mods and (not current_path or not os.path.exists(current_path)):
            self.status_changed.emit(tr('status.game_path_required_for_mods'), UI_COLORS['status_error'])
            self._handle_launch_failure()
            return
        has_list_format = any((isinstance(mods_list, list) for mods_list in selections.values()))
        needs_multi_mod = has_list_format and any((len(mods_list) > 0 for mods_list in selections.values() if isinstance(mods_list, list)))
        logging.info(f'Multi-mod check: needs_multi_mod={needs_multi_mod} (has_list_format={has_list_format})')
        if needs_multi_mod:
            logging.info('Using multi-mod patcher for game launch')
            self.app_state.progress_bar_visible = True
            self.app_state.progress_bar_value = 0
            self.app_state.is_patching = True
            self.app_state.action_button_text = tr('ui.cancel_button')
            self.app_state.action_button_enabled = True
            self._pending_selections = selections
            if not self._prepare_game_files_multi_mod_async(selections):
                logging.error('Failed to start multi-mod patching')
                self.app_state.progress_bar_visible = False
                self.app_state.is_patching = False
                self._handle_launch_failure()
                return
        else:
            self._continue_after_patching(selections, True, needs_multi_mod)

    def _handle_launch_failure(self):
        if self.restore_window_callback:
            self.restore_window_callback()

    def _execute_game(self, launch_config: Dict[str, Any], vanilla_mode: bool = False):
        target_path = launch_config.get('target')
        working_directory = launch_config.get('cwd')
        launch_type = launch_config.get('type')
        if not target_path:
            self.status_changed.emit(tr('errors.launch_target_not_defined'), 'red')
            self._handle_launch_failure()
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
                self._handle_launch_failure()
                return
            system = platform.system()
            if system == 'Darwin':
                custom_exec_key = self.app_state.game_mode.get_custom_exec_config_key()
                custom_path = self.app_state.local_config.get(custom_exec_key, '')
                use_custom_exe = custom_path and os.path.isfile(custom_path) and (os.path.abspath(custom_path) == os.path.abspath(target_path))
                if use_custom_exe:
                    subprocess.Popen(['open', target_path])
                    self.status_changed.emit(tr('status.macos_file_opened'), UI_COLORS['status_steam'])
                    if self.restore_window_callback:
                        QTimer.singleShot(2000, self.restore_window_callback)
                    return
                if target_path.endswith('.app'):
                    process = subprocess.Popen(['open', '-W', target_path])
            else:
                command = [target_path]
                if system == 'Linux' and target_path.lower().endswith('.exe'):
                    is_steam_launch = self.app_state.local_config.get('launch_via_steam', False)
                    use_portproton = self.app_state.local_config.get('use_portproton', False)
                    if not is_steam_launch:
                        if use_portproton:
                            portproton_path = self.app_state.local_config.get('portproton_path', '')
                            if portproton_path:
                                command = [portproton_path, 'run', target_path]
                            else:
                                command = ['portproton', 'run', target_path]
                        else:
                            command.insert(0, 'wine')
                creationflags = 0
                if system == 'Windows':
                    creationflags = 8
                try:
                    process = subprocess.Popen(command, cwd=working_directory, creationflags=creationflags)
                except (OSError, ValueError, subprocess.SubprocessError) as launch_error:
                    error_msg = str(launch_error).lower()
                    invalid_exe_keywords = ['not a valid', 'invalid', 'cannot execute', 'exec format error', 'bad executable', 'invalid executable']
                    is_invalid_exe = any((keyword in error_msg for keyword in invalid_exe_keywords))
                    if is_invalid_exe:
                        self.status_changed.emit(tr('errors.invalid_executable_file', file=os.path.basename(target_path)), UI_COLORS['status_error'])
                    else:
                        self.status_changed.emit(tr('errors.game_launch_error', error=str(launch_error)), UI_COLORS['status_error'])
                    self._handle_launch_failure()
                    return
            self.status_changed.emit(tr('status.game_launched_waiting_for_exit'), UI_COLORS['status_steam'])
            self.monitor_thread = QThread(self)
            self.monitor_worker = GameMonitorWorker(process, vanilla_mode)
            self.monitor_worker.moveToThread(self.monitor_thread)
            self.monitor_worker.finished.connect(self._on_game_process_finished)
            self.monitor_thread.started.connect(self.monitor_worker.run)
            self.monitor_thread.start()
        except Exception as e:
            self.status_changed.emit(tr('errors.game_launch_error', error=str(e)), 'red')
            self._handle_launch_failure()

    def _on_game_process_finished(self, vanilla_mode: bool):
        if self.execute_plugin_hooks:
            self.execute_plugin_hooks('on_before_game_exit')
        self._check_game_running(vanilla_mode)

    def _check_game_running(self, vanilla_mode):
        if is_game_running():
            logging.debug('[LAUNCH] Game is still running, checking again in 2 seconds')
            QTimer.singleShot(2000, lambda: self._check_game_running(vanilla_mode))
        else:
            logging.info('[LAUNCH] Game is no longer running, starting cleanup')
            self.status_changed.emit(tr('status.game_closed_restoring_files'), UI_COLORS['status_info'])
            self._cleanup_direct_launch_files()
            if self.monitor_thread:
                self._stop_monitor_thread()
                self.monitor_thread = None
                if hasattr(self, 'monitor_worker'):
                    self.monitor_worker = None
            self.game_launch_finished.emit()
            logging.info('[LAUNCH] Cleanup completed, game launch finished')

    def _determine_launch_config(self, selections: Dict[int, Any]) -> Optional[Dict[str, Any]]:
        use_steam = self.app_state.local_config.get('launch_via_steam', False)
        direct_launch_slot_id = self.app_state.local_config.get('direct_launch_slot_id', SLOT_ID_UNIVERSAL)
        is_chapter_mode = self.app_state.current_mode == 'chapter'
        is_deltarune = isinstance(self.app_state.game_mode, FullGameMode)
        direct_launch = direct_launch_slot_id > 0 and is_chapter_mode and self.app_state.game_mode.direct_launch_allowed and (platform.system() != 'Darwin')
        should_block_steam = is_deltarune and is_chapter_mode and (direct_launch_slot_id >= 0)
        if use_steam and self.app_state.game_mode.steam_id and (not should_block_steam):
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
        custom_exec_key = self.app_state.game_mode.get_custom_exec_config_key()
        custom_path = self.app_state.local_config.get(custom_exec_key, '')
        use_custom_exe = custom_path and os.path.isfile(custom_path) and (os.path.abspath(custom_path) == os.path.abspath(source_exe))
        if not chapter_folder or not source_exe:
            self.status_changed.emit(tr('errors.direct_launch_error'), UI_COLORS['status_error'])
            return None
        try:
            if not ensure_writable(chapter_folder):
                raise PermissionError(tr('errors.no_write_permission_for', path=chapter_folder))
            if use_custom_exe:
                target_exe = os.path.join(chapter_folder, os.path.basename(source_exe))
            else:
                from services.game_detection_service import get_executable_name_for_game
                game_type = get_game_type_string(self.app_state.game_mode)
                exe_name = get_executable_name_for_game(game_type) or 'DELTARUNE.exe'
                target_exe = os.path.join(chapter_folder, exe_name)
            shutil.copy2(source_exe, target_exe)
            game_root = self._get_current_game_path()
            mus_folders_copied = []
            if game_root and os.path.isdir(game_root):
                for entry in os.listdir(game_root):
                    entry_path = os.path.join(game_root, entry)
                    if os.path.isdir(entry_path) and entry.startswith('mus'):
                        target_mus_path = os.path.join(chapter_folder, entry)
                        if not os.path.exists(target_mus_path):
                            try:
                                shutil.copytree(entry_path, target_mus_path)
                                mus_folders_copied.append(target_mus_path)
                                logging.info(f'[DIRECT_LAUNCH] Copied music folder: {entry} -> {target_mus_path}')
                            except Exception as e:
                                logging.warning(f'[DIRECT_LAUNCH] Failed to copy music folder {entry}: {e}')
            self._direct_launch_cleanup_info = {'target_exe': target_exe, 'source_exe': source_exe, 'chapter_folder': chapter_folder, 'use_custom_exe': use_custom_exe, 'mus_folders': mus_folders_copied}
            return {'target': target_exe, 'cwd': chapter_folder, 'type': 'subprocess'}
        except PermissionError:
            self.status_changed.emit(tr('errors.permission_denied'), UI_COLORS['status_error'])
            return None

    def _get_executable_path(self):
        custom_path = self.app_state.local_config.get(self.app_state.game_mode.get_custom_exec_config_key(), '')
        if custom_path and os.path.isfile(custom_path):
            return custom_path
        current_game_path = self._get_current_game_path()
        if not current_game_path or not os.path.isdir(current_game_path):
            return None
        is_undertale = isinstance(self.app_state.game_mode, (UndertaleGameMode, UndertaleYellowGameMode))
        if isinstance(self.app_state.game_mode, (PizzaTowerGameMode, SugarySpireGameMode)):
            return resolve_game_executable(current_game_path, is_undertale=False, game_type=get_game_type_string(self.app_state.game_mode))
        return resolve_game_executable(current_game_path, is_undertale)

    def _get_source_executable_path(self):
        cfg_key = self.app_state.game_mode.get_custom_exec_config_key()
        custom_path = self.app_state.local_config.get(cfg_key, '')
        if custom_path and os.path.isfile(custom_path):
            return custom_path
        return self._get_executable_path()

    def _get_current_game_path(self) -> str:
        return self.app_state.game_mode.get_game_path(self.app_state.local_config) or ''

    def _prepare_game_files_multi_mod_async(self, selections: Dict[int, List[Any]]) -> bool:
        from workers.mod_patching_worker import ModPatchingThread
        logging.info('Starting multi-mod patching in background thread')
        chapter_mods = {chapter_id: mods_list for chapter_id, mods_list in selections.items() if isinstance(mods_list, list) and mods_list}
        if not chapter_mods:
            self._continue_after_patching(selections, True, False)
            return True
        self.app_state.progress_bar_visible = True
        self.app_state.progress_bar_value = 0
        session_manifest_path = os.path.join(self.app_state.config_dir, 'session.lock')
        fast_merge = self.app_state.local_config.get('fast_merging_enabled', False)
        self._patching_thread = ModPatchingThread(self.app_state, self.mod_service, chapter_mods, session_manifest_path, self, fast_merge=fast_merge)
        self._patching_thread.progress_update.connect(self._on_patching_progress)
        self._patching_thread.status_update.connect(self._on_patching_status)
        self._patching_thread.finished.connect(lambda success: self._on_patching_finished(selections, success))
        self._patching_thread.warning_confirmation_needed.connect(self._on_warning_confirmation_needed)
        self.app_state.current_task = self._patching_thread
        self._patching_thread.start()
        return True

    def _on_patching_finished(self, selections: Dict[int, Any], success: bool):
        self.app_state.progress_bar_visible = False
        self.app_state.is_patching = False
        self.app_state.clear_current_task()
        self.app_state.action_button_text = None
        patching_thread = self._patching_thread
        if patching_thread:
            try:
                if patching_thread.isRunning():
                    logging.debug('Patching thread still running, will clean up via finished signal')
                if patching_thread.patcher:
                    self.mod_patcher = patching_thread.patcher
                if not patching_thread.isRunning():
                    patching_thread.deleteLater()
                else:

                    def cleanup_patching_thread():
                        if patching_thread.patcher:
                            self.mod_patcher = patching_thread.patcher
                        patching_thread.deleteLater()
                    patching_thread.finished.connect(cleanup_patching_thread)
            except Exception as e:
                logging.error(f'Error cleaning up patching thread: {e}', exc_info=True)
            finally:
                self._patching_thread = None
        if not success:
            if patching_thread and (patching_thread.isInterruptionRequested() or getattr(patching_thread, '_cancelled', False)):
                logging.info('Multi-mod patching was cancelled by user')
            else:
                self._handle_launch_failure()
            return
        logging.info('Multi-mod patching completed successfully')
        self._continue_after_patching(selections, True, True)

    def _try_restore_backups(self, context: str = '') -> bool:
        if not hasattr(self, 'mod_patcher') or not self.mod_patcher:
            return False
        try:
            restored = self.mod_patcher.restore_all_backups()
            if restored:
                logging.info(f'{context}: backups restored successfully')
                self.status_changed.emit(tr('status.files_restored'), UI_COLORS['status_success'])
            else:
                logging.debug(f'{context}: no backups to restore')
            return restored
        except Exception as e:
            logging.error(f'{context}: Failed to restore backups: {e}', exc_info=True)
            return False

    def _cancel_launch_after_patching(self):
        try:
            self._try_restore_backups('cancel_launch_after_merge')
        except Exception as e:
            logging.error(f'Cancel launch cleanup failed: {e}', exc_info=True)
        finally:
            self.app_state.progress_bar_visible = False
            self.app_state.progress_bar_value = 0
            self.app_state.is_patching = False
            self.app_state.action_button_text = None
            self.app_state.action_button_enabled = True
            if self.restore_window_callback:
                try:
                    self.restore_window_callback()
                except Exception as e:
                    logging.error(f'Failed to restore window: {e}', exc_info=True)

    def _continue_after_patching(self, selections: Dict[int, Any], patching_success: bool, needs_multi_mod: bool = False):
        if not patching_success:
            return
        if needs_multi_mod and self.mod_patcher:
            conflicts_summary = self.mod_patcher.get_conflicts_summary()
            if conflicts_summary.get('has_conflicts', False):
                from ui.dialogs.conflicts_dialog import ConflictsDialog
                dialog = ConflictsDialog(conflicts_summary, self.app_state.config_dir, parent=None)
                result = dialog.exec()
                if result == QDialog.DialogCode.Rejected or result == 0:
                    logging.info('Game launch cancelled: conflicts dialog was closed without selecting an option')
                    self._cancel_launch_after_patching()
                    return
        if needs_multi_mod:
            pass
        elif self.restore_window_callback:
            self.game_launch_started.emit()
        has_selected_mods = self._has_selected_mods(selections)
        use_steam = self.app_state.local_config.get('launch_via_steam', False)
        if has_selected_mods and use_steam and self.app_state.game_mode.steam_id:
            current_path = self._get_current_game_path()
            if current_path:
                game_name = get_game_name_string(self.app_state.game_mode)
                is_steam_path = is_path_in_steam_common(current_path, game_name)
                if not is_steam_path:
                    should_continue = self.feedback_service.ask_question('ui.steam_launch_mods_warning_title', 'ui.steam_launch_mods_warning_body', game_path=current_path)
                    if not should_continue:
                        logging.info('Game launch cancelled: user declined Steam launch with mods warning')
                        self._handle_launch_failure()
                        return
        launch_config = self._determine_launch_config(selections)
        if not launch_config:
            self._handle_launch_failure()
            return
        if needs_multi_mod:
            if self.restore_window_callback:
                self.game_launch_started.emit()
        self._execute_game(launch_config)
        if self.execute_plugin_hooks:
            self.execute_plugin_hooks('on_after_game_launch')

    def _on_patching_status(self, message: str, status_type: str):
        color = UI_COLORS.get(f'status_{status_type}', UI_COLORS['status_error'])
        self.status_changed.emit(message, color)

    def _on_patching_progress(self, progress: int, message: str):
        self.app_state.progress_bar_value = progress
        self.app_state.progress_bar_visible = True
        if message:
            self.status_changed.emit(message, UI_COLORS['status_info'])

    def _cleanup_direct_launch_files(self):
        restore_errors = []
        try:
            try:
                self._try_restore_backups('[CLEANUP]')
            except Exception as e:
                restore_errors.append(str(e))
            cleanup_info = self._direct_launch_cleanup_info
            if cleanup_info:
                for mus_folder_path in cleanup_info.get('mus_folders', []):
                    if os.path.isdir(mus_folder_path):
                        try:
                            shutil.rmtree(mus_folder_path)
                        except Exception as e:
                            restore_errors.append(f'music folder {mus_folder_path}: {e}')
                target_exe = cleanup_info.get('target_exe')
                if target_exe and os.path.exists(target_exe):
                    try:
                        os.remove(target_exe)
                    except Exception as e:
                        restore_errors.append(f'direct launch exe: {e}')
                self._direct_launch_cleanup_info = None
            if restore_errors:
                logging.error(f'[CLEANUP] {len(restore_errors)} error(s): {restore_errors[:3]}')
                self.status_changed.emit(tr('errors.files_restore_error', error=str(restore_errors[0])), UI_COLORS['status_error'])
        except Exception as e:
            logging.error(f'[CLEANUP] Critical error: {e}', exc_info=True)
            self.status_changed.emit(tr('errors.files_restore_error', error=str(e)), UI_COLORS['status_error'])

    def recover_previous_session(self):
        try:
            self.feedback_service.update_status(tr('status.recovering_previous_session'), UI_COLORS['status_warning'])
            self._try_restore_backups('recover_previous_session')
        except Exception as e:
            logging.error(f'recover_previous_session: Failed: {e}', exc_info=True)
            self.feedback_service.update_status(tr('errors.files_restore_error', error=str(e)), UI_COLORS['status_error'])

    def _find_and_validate_game_path(self, selections: Optional[Dict[int, Any]] = None, is_initial: bool = False):
        from utils.path_utils import autodetect_path
        from services.game_detection_service import is_valid_game_path
        path_from_config = self._get_current_game_path()
        game_name = get_game_name_string(self.app_state.game_mode)
        game_type = get_game_type_string(self.app_state.game_mode)
        if path_from_config and os.path.exists(path_from_config):
            if is_valid_game_path(path_from_config, skip_data_check=False, game_type=game_type):
                self.status_changed.emit(tr('status.game_path', path=path_from_config), UI_COLORS['status_info'])
                return True
            parent_path = os.path.dirname(path_from_config)
            if parent_path and os.path.exists(parent_path) and is_valid_game_path(parent_path, skip_data_check=False, game_type=game_type):
                self.app_state.game_mode.set_game_path(self.app_state.local_config, parent_path)
                self.status_changed.emit(tr('status.game_folder_found', path=parent_path), UI_COLORS['status_success'])
                return True
        custom_exec_key = self.app_state.game_mode.get_custom_exec_config_key()
        custom_path = self.app_state.local_config.get(custom_exec_key, '')
        if custom_path and os.path.isfile(custom_path):
            if path_from_config and os.path.isdir(path_from_config):
                self.status_changed.emit(tr('status.game_path', path=path_from_config), UI_COLORS['status_info'])
                return True
            custom_dir = os.path.dirname(custom_path)
            if custom_dir and os.path.exists(custom_dir):
                self.app_state.game_mode.set_game_path(self.app_state.local_config, custom_dir)
                self.status_changed.emit(tr('status.game_folder_found', path=custom_dir), UI_COLORS['status_success'])
                return True
        self.status_changed.emit(tr('status.autodetecting_path'), UI_COLORS['status_info'])
        autodetected_path = autodetect_path(game_name)
        if autodetected_path and os.path.exists(autodetected_path):
            if is_valid_game_path(autodetected_path, skip_data_check=False, game_type=game_type):
                self.app_state.game_mode.set_game_path(self.app_state.local_config, autodetected_path)
                self.status_changed.emit(tr('status.game_folder_found', path=autodetected_path), UI_COLORS['status_success'])
                return True
        if is_initial:
            self.status_changed.emit(tr('status.no_game_path'), UI_COLORS['status_error'])
        return False

    def _has_selected_mods(self, selections: Dict[int, Any]) -> bool:
        return any((mod_data if isinstance(mod_data, list) else (mod_data and mod_data != 'no_change')) for mod_data in selections.values())
