import os
import shutil
import logging
from typing import Dict, List, Optional
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QDialog
from managers.localization_manager import tr
from config.constants import UI_COLORS
from ui.widgets.mod.installed_mod_widget import InstalledModWidget
from workers.background_workers import InstallModsThread
from workers.install_gamebanana_mod import InstallGameBananaModThread
from utils.mod_utils import get_mod_key, get_mod_name
from ui.dialogs.gamebanana_file_picker_dialog import GameBananaFilePickerDialog


class ModOperationsController:

    def __init__(self, app_state, feedback_manager, mod_manager, app_window):
        self.app_state = app_state
        self.feedback_manager = feedback_manager
        self.mod_manager = mod_manager
        self.app = app_window
        self._last_gamebanana_progress = -1

    def _safe_execute(self, func, error_msg_prefix='', default_return=None):
        try:
            return func()
        except (AttributeError, RuntimeError) as e:
            logging.debug(f'{error_msg_prefix}: {e}', exc_info=True)
            return default_return
        except Exception as e:
            logging.debug(f'{error_msg_prefix}: {e}')
            return default_return

    def handle_url_install(self, url: str):
        from utils.game_utils import is_game_running
        if is_game_running():
            return
        self.app.activateWindow()
        self.app.raise_()
        if self.app_state.is_installing:
            self.feedback_manager.show_message('warning', 'dialogs.install_in_progress_title', tr('dialogs.install_in_progress_body'))
            return
        self.mod_manager.install_from_url(url)

    def on_mod_install_requested(self, mod):
        if self.app_state.is_installing:
            logging.debug('ModOperationsController: Installation already in progress, ignoring request')
            return
        if self.app_state.current_task and self.app_state.current_task.isRunning():
            logging.debug('ModOperationsController: Previous task still running, ignoring request')
            return
        self.install_mod(mod)

    def _install_gamebanana_mod(self, mod, force=False, is_update=False, selected_file=None):
        try:
            self._safe_execute(lambda: setattr(self.app_state, 'operation_cancelled', False), 'Failed to set operation_cancelled')
            if self.app_state.current_task and self.app_state.current_task.isRunning():
                logging.info('ModOperationsController: Previous task is still running, cancelling it first')
                previous_task = self.app_state.current_task
                try:
                    if hasattr(previous_task, 'progress'):
                        try:
                            previous_task.progress.disconnect()
                        except (TypeError, RuntimeError):
                            pass
                    if hasattr(previous_task, 'status'):
                        try:
                            previous_task.status.disconnect()
                        except (TypeError, RuntimeError):
                            pass
                    if hasattr(previous_task, 'finished'):
                        try:
                            previous_task.finished.disconnect()
                        except (TypeError, RuntimeError):
                            pass
                except Exception as e:
                    logging.warning(f'ModOperationsController: Error disconnecting signals: {e}')
                if hasattr(previous_task, 'cancel'):
                    logging.info('ModOperationsController: Cancelling previous task')
                    try:
                        previous_task.cancel()
                    except Exception as e:
                        logging.warning(f'ModOperationsController: Error cancelling previous task: {e}')
                self.app_state.clear_current_task()

                def on_previous_task_finished():
                    logging.info('ModOperationsController: Previous task finished, starting new installation')
                    try:
                        if previous_task.isFinished():
                            previous_task.deleteLater()
                    except Exception as e:
                        logging.debug(f'ModOperationsController: Error deleting previous task: {e}')
                    self._start_gamebanana_install(mod, force, is_update)
                if hasattr(previous_task, 'finished'):
                    previous_task.finished.connect(on_previous_task_finished)
                elif not previous_task.isRunning():
                    on_previous_task_finished()
                else:
                    QTimer.singleShot(100, lambda: on_previous_task_finished() if not previous_task.isRunning() else None)
                return
            if self.app_state.current_task:
                logging.info('ModOperationsController: Cleaning up finished previous task')
                previous_task = self.app_state.current_task
                try:
                    if previous_task.isFinished():
                        previous_task.deleteLater()
                except Exception:
                    pass
                self.app_state.clear_current_task()
            self._start_gamebanana_install(mod, force, is_update, selected_file)
        except Exception as e:
            logging.error(f'Error starting GameBanana mod installation: {e}', exc_info=True)
            self.app_state.is_installing = False
            self.set_install_buttons_enabled(True)
            self.app_state.clear_current_task()
            self._safe_execute(lambda: self.app.game_launch.update_button_state(), 'Failed to update button state')
            self.feedback_manager.show_message('error', 'errors.gamebanana_install_failed', error=str(e))

    def _start_install_thread(self, install_thread, op_id: int):
        try:
            self.app_state.is_installing = True
            self.app_state._scan_blocked = True
            self.set_install_buttons_enabled(False)
            self.app.action_button.setText(tr('ui.cancel_button'))
            install_thread.progress.connect(lambda v, oid=op_id: self.on_install_progress_token(v, oid))
            install_thread.status.connect(lambda msg, col, oid=op_id: self.on_install_status_token(msg, col, oid))
            if isinstance(install_thread, InstallGameBananaModThread):
                install_thread.finished.connect(lambda ok, msg, oid=op_id: self._on_gamebanana_install_finished(ok, msg, oid))
            else:
                install_thread.finished.connect(lambda ok, oid=op_id: self._on_install_task_finished(ok, oid))
            self.app.progress_bar.setVisible(True)
            self.app.progress_bar.setValue(0)
            self._safe_execute(lambda: self.feedback_manager.update_status(tr('status.preparing_download'), UI_COLORS['status_warning']), 'Feedback manager update failed')
            self.app_state.current_task = install_thread
            self.app.game_launch.update_button_state()
            install_thread.start()
            thread_type = 'GameBanana' if isinstance(install_thread, InstallGameBananaModThread) else 'Standard'
            logging.info(f'ModOperationsController: Started {thread_type} mod installation thread (op_id={op_id})')
        except Exception as e:
            logging.error(f'Error starting install thread: {e}', exc_info=True)
            self.app_state.is_installing = False
            self.set_install_buttons_enabled(True)
            self.app_state.clear_current_task()
            self._safe_execute(lambda: self.app.game_launch.update_button_state(), 'Failed to update button state')
            self.feedback_manager.show_message('error', 'errors.gamebanana_install_failed', error=str(e))

    def _start_gamebanana_install(self, mod, force=False, is_update=False, selected_file=None):
        try:
            self.app._install_op_id += 1
            op_id = self.app._install_op_id
            identifier = self._get_mod_identifier(mod)
            self.app_state.current_install_mod_identifier = identifier
            self.app_state.current_install_is_gamebanana = True
            self.app_state.current_install_progress = 0
            self._last_gamebanana_progress = -1
            self._safe_execute(lambda: self.app.search_display.update_search_plaques(), 'Failed to refresh plaques before download')
            install_thread = InstallGameBananaModThread(self.app, mod, selected_file=selected_file)
            self._start_install_thread(install_thread, op_id)
        except Exception as e:
            logging.error(f'Error starting GameBanana mod installation thread: {e}', exc_info=True)
            self.app_state.is_installing = False
            self.set_install_buttons_enabled(True)
            self.app_state.clear_current_task()
            self._safe_execute(lambda: self.app.game_launch.update_button_state(), 'Failed to update button state')
            self.feedback_manager.show_message('error', 'errors.gamebanana_install_failed', error=str(e))

    def _show_incompatible_gamebanana_dialog(self, mod=None, mod_url: Optional[str] = None):
        from PyQt6.QtWidgets import QMessageBox
        import webbrowser
        url_to_open = mod_url
        if not url_to_open and mod:
            url_to_open = getattr(mod, 'external_url', None)
            if not url_to_open:
                key = getattr(mod, 'key', None) or getattr(mod, 'mod_key', None)
                if key and key.startswith('gb_'):
                    mod_id = key.replace('gb_', '', 1)
                    if mod_id:
                        url_to_open = f'https://gamebanana.com/mods/{mod_id}'
        msg_box = QMessageBox(self.app)
        msg_box.setIcon(QMessageBox.Icon.Information)
        msg_box.setWindowTitle(tr('errors.mod_not_compatible_title'))
        msg_box.setText(tr('errors.mod_requires_manual_installation'))
        open_btn = msg_box.addButton(tr('ui.open_instructions'), QMessageBox.ButtonRole.AcceptRole)
        msg_box.addButton(tr('buttons.close'), QMessageBox.ButtonRole.RejectRole)
        msg_box.setDefaultButton(open_btn)
        msg_box.exec()
        if msg_box.clickedButton() == open_btn and url_to_open:
            webbrowser.open(url_to_open)

    def _get_available_gamebanana_files(self, mod) -> List[Dict]:
        files = getattr(mod, 'gamebanana_supported_files', []) or []
        if files:
            self._notify_gamebanana_status_refresh()
            return files
        key = getattr(mod, 'key', None) or getattr(mod, 'mod_key', None)
        if not key or not key.startswith('gb_'):
            return []
        mod_id_str = key.replace('gb_', '', 1)
        if not mod_id_str:
            return []
        mod_id = int(mod_id_str)
        try:
            from utils.gamebanana_api import GameBananaAPI
            api = GameBananaAPI()
            external_url = getattr(mod, 'external_url', None)
            compat = api.get_supported_files_for_mod(int(mod_id), external_url=external_url)
            files = compat.get('supported_files') or []
            if files:
                setattr(mod, 'gamebanana_supported_files', files)
                setattr(mod, 'gamebanana_is_tool_compatible', compat.get('has_supported_files', False))
                setattr(mod, 'gamebanana_compatibility_checked', compat.get('compatibility_checked', False))
                self._notify_gamebanana_status_refresh()
            return files
        except Exception as e:
            logging.warning(f'ModOperationsController: Failed to refresh GameBanana files for {mod_id}: {e}')
            return []

    def _get_mod_identifier(self, mod) -> Optional[str]:
        try:
            key = getattr(mod, 'key', None) or getattr(mod, 'mod_key', None)
            if key:
                if key.startswith('gb_'):
                    mod_id = key.replace('gb_', '', 1)
                    if mod_id:
                        return f'gb::{mod_id}'
                return f'key::{key}'
        except Exception as e:
            logging.debug(f'ModOperationsController: Failed to get identifier for mod: {e}')
        return None

    def _notify_gamebanana_status_refresh(self):
        try:
            if hasattr(self.app, 'search_display'):
                QTimer.singleShot(0, self.app.search_display.update_search_plaques)
        except Exception:
            pass

    def _on_gamebanana_install_finished(self, success: bool, message: str, op_id: int):
        current_op_id = getattr(self.app, '_install_op_id', 0)
        if current_op_id != op_id:
            logging.debug(f'ModOperationsController: Ignoring finished signal for old operation {op_id}, current is {current_op_id}')
            return
        if not success and message and (message == tr('status.operation_cancelled') or 'cancelled' in message.lower()):
            logging.info('ModOperationsController: GameBanana mod installation was cancelled')
            self._on_install_complete(False, tr('status.operation_cancelled'), was_installed_before=False)
            return
        if not success and message and message.startswith('MOD_NOT_COMPATIBLE:'):
            mod_url = message.replace('MOD_NOT_COMPATIBLE:', '')
            if mod_url:
                self._show_incompatible_gamebanana_dialog(mod_url=mod_url)
            self._on_install_complete(False, '', was_installed_before=False)
            return
        self._on_install_complete(success, message, was_installed_before=False)

    def install_mod(self, mod, force=False, is_update=False):
        try:
            if self.app_state.is_installing and (not force):
                return
            if hasattr(mod, 'is_gamebanana_mod') and callable(mod.is_gamebanana_mod) and mod.is_gamebanana_mod():
                available_files = self._get_available_gamebanana_files(mod)
                is_checked = bool(getattr(mod, 'gamebanana_compatibility_checked', False))
                is_compatible = bool(getattr(mod, 'gamebanana_is_tool_compatible', False))
                if is_checked and (not is_compatible):
                    self._show_incompatible_gamebanana_dialog(mod=mod)
                    return
                if not available_files:
                    self._show_incompatible_gamebanana_dialog(mod=mod)
                    return
                selected_file = available_files[0]
                if len(available_files) > 1:
                    dialog = GameBananaFilePickerDialog(self.app, available_files, mod.name, getattr(mod, 'external_url', None))
                    result = dialog.exec()
                    if result != QDialog.DialogCode.Accepted:
                        self.feedback_manager.update_status(tr('status.operation_cancelled'), UI_COLORS['status_warning'])
                        return
                    selection = dialog.get_selected_file()
                    if selection:
                        selected_file = selection
                self._install_gamebanana_mod(mod, force, is_update, selected_file)
                return
            available_chapters = []
            if mod.game == 'undertale':
                if mod.files.get('undertale'):
                    available_chapters.append(0)
            elif mod.game == 'deltarunedemo':
                if mod.files.get('demo'):
                    available_chapters.append(-1)
            else:
                for chapter_id in range(0, 5):
                    chapter_data = mod.get_chapter_data(chapter_id)
                    if chapter_data:
                        available_chapters.append(chapter_id)
            if not available_chapters:
                self.feedback_manager.show_message('warning', 'errors.mod_no_files', mod_name=mod.name)
                return
            was_installed_before = self.mod_manager.is_mod_installed(mod.key) or is_update
            install_tasks = [(mod, chapter_id) for chapter_id in available_chapters]
            self._safe_execute(lambda: setattr(self.app_state, 'operation_cancelled', False), 'Failed to set operation_cancelled')
            if self.app_state.current_task:
                try:
                    if hasattr(self.app_state.current_task, 'progress'):
                        self.app_state.current_task.progress.disconnect()
                    if hasattr(self.app_state.current_task, 'status'):
                        self.app_state.current_task.status.disconnect()
                    if hasattr(self.app_state.current_task, 'finished'):
                        self.app_state.current_task.finished.disconnect()
                except (TypeError, RuntimeError) as e:
                    logging.debug(f'Failed to disconnect signals from previous task: {e}')
            self.app._install_op_id += 1
            op_id = self.app._install_op_id
            install_thread = InstallModsThread(self.app, install_tasks, was_installed_before)
            self._start_install_thread(install_thread, op_id)
        except (IOError, OSError) as e:
            from core.exceptions import ModInstallationError
            key = get_mod_key(mod)
            mod_name = get_mod_name(mod, 'Unknown Mod')
            raise ModInstallationError(f'File operation failed during installation: {e}', key=key, mod_name=mod_name, reason='io_error') from e
        except KeyError as e:
            from core.exceptions import ModInstallationError
            key = get_mod_key(mod)
            mod_name = get_mod_name(mod, 'Unknown Mod')
            raise ModInstallationError(f'Missing required data: {e}', key=key, mod_name=mod_name, reason='missing_data') from e
        except Exception as e:
            from core.exceptions import ModInstallationError
            key = get_mod_key(mod)
            mod_name = get_mod_name(mod, 'Unknown Mod')
            raise ModInstallationError(f'Unexpected error during installation: {e}', key=key, mod_name=mod_name, reason='unknown') from e

    def on_install_progress_token(self, value: int, op_id: int):
        current_op_id = getattr(self.app, '_install_op_id', 0)
        if current_op_id == op_id and self.app_state.is_installing:
            self.app.progress_bar.setValue(value)
            if getattr(self.app_state, 'current_install_is_gamebanana', False):
                self.app_state.current_install_progress = value
                if value >= 100 or abs(value - self._last_gamebanana_progress) >= 2:
                    self._last_gamebanana_progress = value
                    self._safe_execute(lambda: self.app.search_display.update_search_plaques(), 'Failed to refresh plaques for progress')

    def on_install_status_token(self, message: str, color: str, op_id: int):
        current_op_id = getattr(self.app, '_install_op_id', 0)
        if current_op_id == op_id and self.app_state.is_installing:
            self.app._update_status(message, color)

    def _on_install_task_finished(self, success: bool, op_id: int):
        current_op_id = getattr(self.app, '_install_op_id', 0)
        if current_op_id != op_id:
            return
        was_installed_before = False
        if self.app_state.current_task:
            was_installed_before = getattr(self.app_state.current_task, 'was_installed_before', False)
        self._on_install_complete(success, '', was_installed_before)

    def _on_install_complete(self, success: bool, message: str = '', was_installed_before: bool = False):
        current_task = self.app_state.current_task
        installed_mod_info = None
        if current_task and hasattr(current_task, 'mod_info'):
            installed_mod_info = current_task.mod_info
        self.app.progress_bar.setValue(0)
        self.app.progress_bar.setVisible(False)
        self.app_state.clear_current_task()
        self.app_state.is_installing = False
        self.app_state.current_install_progress = 0
        self.app_state.current_install_mod_identifier = None
        self.app_state.current_install_is_gamebanana = False
        self._last_gamebanana_progress = -1
        self.set_install_buttons_enabled(True)
        self._safe_execute(lambda: self.app.game_launch.update_button_state(), 'Failed to update button state')
        if not success:
            is_cancelled = message == tr('status.operation_cancelled') or 'cancelled' in message.lower() or self.app_state.operation_cancelled
            if is_cancelled:
                logging.info('ModOperationsController: Installation was cancelled')
                self._safe_execute(lambda: setattr(self.app_state, 'operation_cancelled', False), 'Failed to set operation_cancelled')
                self.feedback_manager.update_status(tr('status.operation_cancelled'), UI_COLORS['status_warning'])
            else:
                self.feedback_manager.update_status(tr('status.mod_install_error'), UI_COLORS['status_error'])
            try:
                if current_task:
                    temp_root = getattr(current_task, 'temp_root', None)
                    if temp_root and os.path.isdir(temp_root):
                        shutil.rmtree(temp_root, ignore_errors=True)
            except (AttributeError, OSError, shutil.Error) as e:
                logging.debug(f'Failed to clean temp root: {e}', exc_info=True)
            self.app.game_launch.update_button_state()
            self.app_state._scan_blocked = False
            return
        logging.info('ModOperationsController: Installation complete, invalidating mods cache and reloading local mods')
        self.app_state._scan_blocked = False
        self._safe_execute(lambda: self.mod_manager.invalidate_mods_cache(), 'invalidate_mods_cache failed', default_return=None)
        try:
            self.mod_manager.load_local_mods()
            logging.info('ModOperationsController: Local mods reloaded after installation')
            self.mod_manager.mod_list_updated.emit()
            QTimer.singleShot(100, lambda: self._safe_execute(lambda: self.app.search_display.update_search_plaques() if hasattr(self.app, 'search_display') else None, 'Failed to update search plaques'))
            self._safe_execute(lambda: self.app.search_display.update_search_plaques(), 'Failed to refresh plaques after cache reload')
            if installed_mod_info and hasattr(self.app_state, 'all_mods'):
                if not self.app_state.all_mods:
                    self.app_state.all_mods = []
                key = getattr(installed_mod_info, 'key', None) or getattr(installed_mod_info, 'mod_key', None)
                mod_already_in_all_mods = False
                if key:
                    mod_already_in_all_mods = any(((getattr(m, 'key', None) or getattr(m, 'mod_key', None)) == key for m in self.app_state.all_mods))
                is_gamebanana_mod = key and key.startswith('gb_')
                if not mod_already_in_all_mods:
                    try:
                        cache = self.mod_manager._get_mods_cache()
                        mod_to_add = None
                        if key and key in cache:
                            mod_to_add = self.mod_manager.create_mod_object_from_info(cache[key].config_data, self.app_state.all_mods)
                        if mod_to_add:
                            self.app_state.append_mod(mod_to_add)
                            logging.info(f'''ModOperationsController: Added installed mod "{mod_to_add.name}" (key: {getattr(mod_to_add, 'key', None) or getattr(mod_to_add, 'mod_key', 'N/A')}) to all_mods''')
                        else:
                            logging.warning(f'ModOperationsController: Could not create mod object for installed mod (key: {key})')
                    except Exception as e:
                        logging.warning(f'ModOperationsController: Failed to add installed mod to all_mods: {e}', exc_info=True)
                elif is_gamebanana_mod and mod_already_in_all_mods:
                    try:
                        existing_mod = None
                        for m in self.app_state.all_mods:
                            mod_key_attr = getattr(m, 'key', None) or getattr(m, 'mod_key', None)
                            if mod_key_attr == key:
                                existing_mod = m
                                break
                        if existing_mod:
                            cache = self.mod_manager._get_mods_cache()
                            if key and key in cache:
                                config_data = cache[key].config_data
                                if config_data.get('files') and (not hasattr(existing_mod, 'files') or not existing_mod.files):
                                    temp_mod = self.mod_manager.create_mod_object_from_info(config_data, self.app_state.all_mods)
                                    if hasattr(temp_mod, 'files') and temp_mod.files:
                                        existing_mod.files = temp_mod.files
                    except Exception as e:
                        logging.debug(f'ModOperationsController: Failed to update files for GameBanana mod {key}: {e}')
        except Exception as e:
            logging.warning(f'ModOperationsController: Failed to reload local mods: {e}', exc_info=True)

        def update_filtered_mods():
            try:
                if hasattr(self.app, 'search_display'):
                    logging.info('ModOperationsController: Updating filtered mods after installation')
                    self.app.search_display.update_filtered_mods(preserve_page=True)
                    logging.info('ModOperationsController: Filtered mods updated')
                    if installed_mod_info and hasattr(self.app_state, 'filtered_mods') and self.app_state.filtered_mods:
                        try:
                            installed_mod_found = False
                            installed_mod_page = None
                            key = getattr(installed_mod_info, 'key', None) or getattr(installed_mod_info, 'mod_key', None)
                            if key and key.startswith('gb_'):
                                logging.info(f'ModOperationsController: Searching for installed GameBanana mod with key {key} in {len(self.app_state.filtered_mods)} filtered mods')
                                for idx, mod in enumerate(self.app_state.filtered_mods):
                                    if (getattr(mod, 'key', None) or getattr(mod, 'mod_key', None)) == key:
                                        installed_mod_found = True
                                        installed_mod_page = idx // self.app_state.mods_per_page + 1
                                        logging.info(f'''ModOperationsController: Found installed mod "{mod.name}" (key: {key}) at index {idx}, page {installed_mod_page}, is_local={getattr(mod, 'is_local_mod', False)}''')
                                        break
                                if not installed_mod_found:
                                    logging.warning(f'ModOperationsController: Installed mod with key {key} NOT FOUND in filtered_mods! Checking all_mods...')
                                    if hasattr(self.app_state, 'all_mods') and self.app_state.all_mods:
                                        for mod in self.app_state.all_mods:
                                            if (getattr(mod, 'key', None) or getattr(mod, 'mod_key', None)) == key:
                                                mod_key_attr = getattr(mod, 'key', None) or getattr(mod, 'mod_key', None)
                                                logging.warning(f'''ModOperationsController: Mod "{mod.name}" (key: {key}) found in all_mods but NOT in filtered_mods! Key: {mod_key_attr}, is_local: {getattr(mod, 'is_local_mod', False)}, status: {getattr(mod, 'status', 'N/A')}''')
                                                break
                                    for idx, mod in enumerate(self.app_state.filtered_mods[:10]):
                                        mod_key_attr = getattr(mod, 'key', None) or getattr(mod, 'mod_key', None)
                                        if mod_key_attr and mod_key_attr.startswith('gb_'):
                                            logging.info(f'''ModOperationsController: Filtered mod {idx}: "{mod.name}" (key: {mod_key_attr}, is_local: {getattr(mod, 'is_local_mod', False)})''')
                            else:
                                key = getattr(installed_mod_info, 'key', None) or getattr(installed_mod_info, 'mod_key', None)
                                logging.info(f'ModOperationsController: Searching for installed mod with key {key} in {len(self.app_state.filtered_mods)} filtered mods')
                                for idx, mod in enumerate(self.app_state.filtered_mods):
                                    mod_key_attr = getattr(mod, 'key', None) or getattr(mod, 'mod_key', None)
                                    if mod_key_attr == key:
                                        installed_mod_found = True
                                        installed_mod_page = idx // self.app_state.mods_per_page + 1
                                        logging.info(f'ModOperationsController: Found installed mod "{mod.name}" (key: {key}) at index {idx}, page {installed_mod_page}')
                                        break
                            if installed_mod_found and installed_mod_page:
                                if installed_mod_page != self.app_state.current_page:
                                    logging.info(f'ModOperationsController: Navigating to page {installed_mod_page} to show installed mod')
                                    self.app_state.current_page = installed_mod_page
                                self._safe_execute(lambda: self.app.search_display.update_display(), 'Failed to update display after installation')
                            elif not installed_mod_found:
                                logging.error('ModOperationsController: Installed mod was not found in filtered_mods after installation! This is a bug.')
                        except Exception as e:
                            logging.warning(f'ModOperationsController: Failed to navigate to installed mod page: {e}', exc_info=True)
            except Exception as e:
                logging.warning(f'ModOperationsController: Failed to update filtered mods: {e}', exc_info=True)

        def check_cache_and_update():
            try:
                cache = self.mod_manager._get_mods_cache()
                logging.info(f'ModOperationsController: Cache after reload has {len(cache)} mods')
                for key, mod_info in list(cache.items())[:5]:
                    if key and key.startswith('gb_'):
                        logging.info(f'ModOperationsController: Found installed GameBanana mod - key={key}')
            except Exception as e:
                logging.warning(f'ModOperationsController: Failed to check cache: {e}')

        def update_plaques_with_retry():
            try:
                logging.info('ModOperationsController: Updating search plaques')
                self.mod_manager.invalidate_mods_cache()
                logging.info('ModOperationsController: Mods cache invalidated before updating plaques')
                cache = self.mod_manager._get_mods_cache()
                logging.info(f'ModOperationsController: Reloaded mods cache, found {len(cache)} installed mods')
                for key, mod_info in cache.items():
                    if key and key.startswith('gb_'):
                        logging.info(f'ModOperationsController: Installed GameBanana mod in cache - key={key}')
                self.app.search_display.update_search_plaques()
                logging.info('ModOperationsController: Search plaques updated')
            except Exception as e:
                logging.warning(f'ModOperationsController: Failed to update search plaques: {e}', exc_info=True)

        def update_library_with_retry():
            try:
                if hasattr(self.app, 'library_display'):
                    logging.info('ModOperationsController: Updating library display')
                    self.app.library_display.update_display()
                    logging.info('ModOperationsController: Library display updated')
            except Exception as e:
                logging.warning(f'ModOperationsController: Failed to update library display: {e}', exc_info=True)
        from utils.ui_utils import DebounceTimer
        if not hasattr(self, '_update_debounce_short'):
            self._update_debounce_short = DebounceTimer(delay_ms=200)
        if not hasattr(self, '_update_debounce_long'):
            self._update_debounce_long = DebounceTimer(delay_ms=1000)
        if current_task and installed_mod_info:
            self.refresh_specific_mod_widget_after_update(installed_mod_info)
        self._update_debounce_short.call(check_cache_and_update)
        self._update_debounce_short.call(update_filtered_mods)
        self._update_debounce_short.call(update_plaques_with_retry)
        self._update_debounce_short.call(update_library_with_retry)
        self._update_debounce_long.call(update_plaques_with_retry)
        self._update_debounce_long.call(update_library_with_retry)
        if message:
            self.feedback_manager.update_status(message, UI_COLORS['status_success'])
        else:
            self.feedback_manager.update_status(tr('status.mod_installed_success'), UI_COLORS['status_success'])
        if not was_installed_before:
            self._safe_execute(lambda: QTimer.singleShot(0, lambda: self.feedback_manager.show_message('info', 'dialogs.mod_installed_apply_info')), 'Failed to show mod installed info')
        if getattr(self.app, 'pending_updates', None):
            next_mod = self.app.pending_updates.pop(0)
            QTimer.singleShot(0, lambda: self.mod_manager.update_mod(next_mod))
        self.app.game_launch.update_button_state()

    def refresh_specific_mod_widget_after_update(self, mod_info=None):
        mod_to_update = mod_info
        if mod_to_update is None:
            if not self.app_state.current_task:
                return
            install_tasks = getattr(self.app_state.current_task, 'install_tasks', [])
            if not install_tasks:
                return
            mod_data_tuple = install_tasks[0]
            mod_to_update = mod_data_tuple[0]
        key_to_find = get_mod_key(mod_to_update)
        if not key_to_find:
            return
        if hasattr(self.app, 'installed_mods_layout'):
            for i in range(self.app.installed_mods_layout.count()):
                item = self.app.installed_mods_layout.itemAt(i)
                if item and item.widget():
                    widget = item.widget()
                    if isinstance(widget, InstalledModWidget):
                        widget_key = get_mod_key(widget.mod_data)
                        if widget_key == key_to_find:
                            widget.update_status()
                            break

    def on_mod_uninstall_requested(self, mod):
        if self.app_state.is_installing:
            return
        if self.feedback_manager.ask_question('dialogs.delete_confirmation', 'dialogs.delete_mod_confirmation', '', False, mod_name=mod.name):
            QTimer.singleShot(5, lambda m=mod: self.uninstall_mod(m))

    def uninstall_mod(self, mod):
        self.mod_manager.uninstall_mod(mod)
        self.mod_manager.mod_list_updated.emit()
        self.app.search_display.update_search_plaques()
        if hasattr(self.app, 'library_display'):
            self.app.library_display.update_display()
        if hasattr(self.app, 'search_display'):
            self.app.search_display.update_filtered_mods(preserve_page=True)

    def set_install_buttons_enabled(self, enabled: bool):
        self._safe_execute(lambda: (self.app.action_button.setEnabled(True if self.app_state.is_installing else enabled), self.app.saves_button.setEnabled(True), self.app.shortcut_button.setEnabled(enabled)), 'Failed to set install buttons enabled')
