"""Controller for mod installation and operation management."""
import os
import shutil
import logging
from typing import Dict, List, Optional
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QDialog, QMessageBox
from services.localization_service import tr
from config.constants import UI_COLORS
from ui.widgets.mod.installed_mod_widget import InstalledModWidget
from workers.install.batch_install_worker import InstallModsThread
from workers.install.gamebanana_install_worker import InstallGameBananaModThread
from workers.gamebanana.prepare_gamebanana_manual_install_worker import PrepareGameBananaManualInstallWorker
from utils.mod_utils import get_mod_key, get_mod_name
from adapters.gamebanana_adapter import GameBananaAPI
from ui.dialogs.file_picker_dialog import GameBananaFilePickerDialog


class ModOperationsController:
    """Manages mod installation operations and related workflows."""

    def __init__(self, app_state, feedback_service, mod_service, app_window):
        self.app_state = app_state
        self.feedback_service = feedback_service
        self.mod_service = mod_service
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

    @staticmethod
    def _disconnect_task_signals(task):
        for sig_name in ('progress', 'status', 'finished'):
            if hasattr(task, sig_name):
                try:
                    getattr(task, sig_name).disconnect()
                except (TypeError, RuntimeError):
                    pass

    def _pick_gamebanana_file(self, available_files, mod_name, external_url):
        if len(available_files) <= 1:
            return available_files[0] if available_files else None
        dialog = GameBananaFilePickerDialog(self.app, available_files, mod_name, external_url)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self.feedback_service.update_status(tr('status.operation_cancelled'), UI_COLORS['status_warning'])
            return None
        return dialog.get_selected_file() or available_files[0]

    def _handle_install_start_error(self, error: Exception) -> None:
        self.app_state.is_installing = False
        self.set_install_buttons_enabled(True)
        self.app_state.clear_current_task()
        self._safe_execute(lambda: self.app.game_launch.update_button_state(), 'Failed to update button state')
        self.feedback_service.show_message('error', 'errors.gamebanana_install_failed', error=str(error))

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
                    self._disconnect_task_signals(previous_task)
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
                    self._start_gamebanana_install(mod, force, is_update, selected_file)
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
            self._handle_install_start_error(e)

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
            self._safe_execute(lambda: self.feedback_service.update_status(tr('status.preparing_download'), UI_COLORS['status_warning']), 'Feedback manager update failed')
            self.app_state.current_task = install_thread
            self.app.game_launch.update_button_state()
            install_thread.start()
            thread_type = 'GameBanana' if isinstance(install_thread, InstallGameBananaModThread) else 'Standard'
            logging.info(f'ModOperationsController: Started {thread_type} mod installation thread (op_id={op_id})')
        except Exception as e:
            logging.error(f'Error starting install thread: {e}', exc_info=True)
            self._handle_install_start_error(e)

    def _start_gamebanana_install(self, mod, force=False, is_update=False, selected_file=None):
        try:
            self.app._install_op_id += 1
            op_id = self.app._install_op_id
            identifier = self._get_mod_identifier(mod)
            self.app_state.current_install_mod_identifier = identifier
            self.app_state.current_install_is_gamebanana = True
            self.app_state.current_install_progress = 0
            self._last_gamebanana_progress = -1
            self._safe_execute(lambda: self.app.search_display.update_search_cards(), 'Failed to refresh cards before download')
            install_thread = InstallGameBananaModThread(self.app, mod, selected_file=selected_file)
            self._start_install_thread(install_thread, op_id)
        except Exception as e:
            logging.error(f'Error starting GameBanana mod installation thread: {e}', exc_info=True)
            self._handle_install_start_error(e)

    def _show_incompatible_gamebanana_dialog(self, mod=None, mod_url: Optional[str] = None):
        import webbrowser
        url_to_open = mod_url
        if not url_to_open and mod:
            url_to_open = getattr(mod, 'external_url', None)
            if not url_to_open:
                key = get_mod_key(mod)
                if key and key.startswith('gb_'):
                    mod_id = key.replace('gb_', '', 1)
                    if mod_id:
                        url_to_open = f'https://gamebanana.com/mods/{mod_id}'
        msg_box = QMessageBox(self.app)
        msg_box.setIcon(QMessageBox.Icon.Information)
        msg_box.setWindowTitle(tr('errors.mod_not_compatible_title'))
        msg_box.setText(tr('errors.mod_requires_manual_installation'))
        msg_box.setInformativeText(tr('dialogs.manual_install_available'))
        manual_install_btn = msg_box.addButton(tr('ui.manual_install'), QMessageBox.ButtonRole.AcceptRole)
        open_btn = msg_box.addButton(tr('ui.open_instructions'), QMessageBox.ButtonRole.AcceptRole)
        msg_box.addButton(tr('buttons.close'), QMessageBox.ButtonRole.RejectRole)
        msg_box.setDefaultButton(manual_install_btn)
        msg_box.exec()
        clicked_btn = msg_box.clickedButton()
        if clicked_btn == manual_install_btn and mod:
            self._start_manual_install_from_gamebanana(mod)
        elif clicked_btn == open_btn and url_to_open:
            webbrowser.open(url_to_open)

    def _get_gamebanana_mod_id_str(self, mod) -> Optional[str]:
        """Extract GameBanana mod ID string from mod data."""
        from utils.mod_utils import get_gamebanana_mod_id
        return get_gamebanana_mod_id(mod)

    def _get_available_gamebanana_files(self, mod) -> List[Dict]:
        files = getattr(mod, 'gamebanana_supported_files', []) or []
        if files:
            self._notify_gamebanana_status_refresh()
            return files
        mod_id_str = self._get_gamebanana_mod_id_str(mod)
        if not mod_id_str:
            return []
        mod_id = int(mod_id_str)
        try:
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

    def _get_all_gamebanana_files(self, mod) -> List[Dict]:
        mod_id_str = self._get_gamebanana_mod_id_str(mod)
        if not mod_id_str:
            return []
        mod_id = int(mod_id_str)
        try:
            api = GameBananaAPI()
            external_url = getattr(mod, 'external_url', None)
            all_files = api.get_mod_files(mod_id, external_url=external_url)
            if not all_files:
                return []
            formatted_files = []
            for file_data in all_files:
                file_id = file_data.get('_idRow')
                if not file_id:
                    for key in file_data.keys():
                        if key.isdigit():
                            file_id = int(key)
                            break
                if not file_id:
                    logging.warning(f'ModOperationsController: Could not extract file_id from file_data: {file_data}')
                    continue
                has_contents = file_data.get('_bHasContents', True)
                if not has_contents:
                    continue
                file_name = file_data.get('_sFile') or file_data.get('_sName') or file_data.get('name') or f'file_{file_id}'
                download_url = file_data.get('_sDownloadUrl') or file_data.get('download_url')
                if not download_url:
                    download_url = f'https://gamebanana.com/dl/{file_id}'
                    logging.debug(f'ModOperationsController: Constructed download URL for file {file_id}: {download_url}')
                formatted_file = {'id': file_id, 'name': file_name, 'download_url': download_url, '_sDownloadUrl': download_url, '_sFile': file_name, '_idRow': file_id, '_bHasContents': True, 'version': file_data.get('_sVersion') or file_data.get('version', '1.0.0'), 'size_bytes': file_data.get('_nFilesize') or file_data.get('size_bytes', 0), 'download_count': file_data.get('_nDownloadCount') or file_data.get('download_count', 0)}
                formatted_files.append(formatted_file)
            return formatted_files
        except Exception as e:
            logging.error(f'ModOperationsController: Failed to get all GameBanana files for {mod_id}: {e}', exc_info=True)
            return []

    def _get_mod_identifier(self, mod) -> Optional[str]:
        try:
            key = self._get_mod_key_value(mod)
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
                QTimer.singleShot(0, self.app.search_display.update_search_cards)
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
                selected_file = self._pick_gamebanana_file(available_files, mod.name, getattr(mod, 'external_url', None))
                if selected_file is None:
                    return
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
                self.feedback_service.show_message('warning', 'errors.mod_no_files', mod_name=mod.name)
                return
            was_installed_before = self.mod_service.is_mod_installed(mod.key) or is_update
            install_tasks = [(mod, chapter_id) for chapter_id in available_chapters]
            self._safe_execute(lambda: setattr(self.app_state, 'operation_cancelled', False), 'Failed to set operation_cancelled')
            if self.app_state.current_task:
                try:
                    self._disconnect_task_signals(self.app_state.current_task)
                except (TypeError, RuntimeError) as e:
                    logging.debug(f'Failed to disconnect signals from previous task: {e}')
            self.app._install_op_id += 1
            op_id = self.app._install_op_id
            install_thread = InstallModsThread(self.app, install_tasks, was_installed_before)
            self._start_install_thread(install_thread, op_id)
        except (IOError, OSError, KeyError, Exception) as e:
            from core.exceptions import ModInstallationError
            key = get_mod_key(mod)
            mod_name_str = get_mod_name(mod, 'Unknown Mod')
            reason_map = {IOError: 'io_error', OSError: 'io_error', KeyError: 'missing_data'}
            reason = reason_map.get(type(e), 'unknown')
            raise ModInstallationError(f'{reason}: {e}', key=key, mod_name=mod_name_str, reason=reason) from e

    def on_install_progress_token(self, value: int, op_id: int):
        current_op_id = getattr(self.app, '_install_op_id', 0)
        if current_op_id == op_id and self.app_state.is_installing:
            self.app.progress_bar.setValue(value)
            if getattr(self.app_state, 'current_install_is_gamebanana', False):
                self.app_state.current_install_progress = value

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
                self.feedback_service.update_status(tr('status.operation_cancelled'), UI_COLORS['status_warning'])
            else:
                self.feedback_service.update_status(tr('status.mod_install_error'), UI_COLORS['status_error'])
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
        self.app_state._scan_blocked = False
        self._safe_execute(lambda: self.mod_service.invalidate_mods_cache(), 'invalidate_mods_cache failed', default_return=None)
        try:
            self.mod_service.load_local_mods()
            self.mod_service.mod_list_updated.emit()
            self._safe_execute(lambda: self.app.search_display.update_search_cards() if hasattr(self.app, 'search_display') else None, 'Failed to update search cards')
            if installed_mod_info and hasattr(self.app_state, 'all_mods'):
                key = get_mod_key(installed_mod_info)
                if key:
                    self._sync_installed_mod_to_all_mods(key)
        except Exception as e:
            logging.warning(f'ModOperationsController: Failed to reload local mods: {e}', exc_info=True)

        def update_filtered_mods():
            try:
                if not hasattr(self.app, 'search_display'):
                    return
                self.app.search_display.update_filtered_mods(preserve_page=True)
                if not (installed_mod_info and self.app_state.filtered_mods):
                    return
                key = get_mod_key(installed_mod_info)
                if not key:
                    return
                for idx, mod in enumerate(self.app_state.filtered_mods):
                    if get_mod_key(mod) == key:
                        page = idx // self.app_state.mods_per_page + 1
                        if page != self.app_state.current_page:
                            self.app_state.current_page = page
                        self._safe_execute(lambda: self.app.search_display.update_display(), 'Failed to update display')
                        return
                logging.debug(f'ModOperationsController: Installed mod {key} not found in filtered_mods')
            except Exception as e:
                logging.warning(f'ModOperationsController: Failed to update filtered mods: {e}', exc_info=True)

        def check_cache_and_update():
            try:
                self.mod_service._get_mods_cache()
            except Exception as e:
                logging.warning(f'ModOperationsController: Failed to check cache: {e}')

        def update_cards_with_retry():
            try:
                self.mod_service.invalidate_mods_cache()
                self.app.search_display.update_search_cards()
            except Exception as e:
                logging.warning(f'ModOperationsController: Failed to update search cards: {e}', exc_info=True)

        def update_library_with_retry():
            try:
                if hasattr(self.app, 'library_display'):
                    self.app.library_display.update_display()
            except Exception as e:
                logging.warning(f'ModOperationsController: Failed to update library display: {e}', exc_info=True)
        from ui.utils.ui_utils import DebounceTimer
        if not hasattr(self, '_update_debounce_short'):
            self._update_debounce_short = DebounceTimer(delay_ms=200)
        if not hasattr(self, '_update_debounce_long'):
            self._update_debounce_long = DebounceTimer(delay_ms=1000)
        if current_task and installed_mod_info:
            self.refresh_specific_mod_widget_after_update(installed_mod_info)
        self._update_debounce_short.call(check_cache_and_update)
        self._update_debounce_short.call(update_filtered_mods)
        self._update_debounce_short.call(update_cards_with_retry)
        self._update_debounce_short.call(update_library_with_retry)
        self._update_debounce_long.call(update_cards_with_retry)
        self._update_debounce_long.call(update_library_with_retry)
        if message:
            self.feedback_service.update_status(message, UI_COLORS['status_success'])
        else:
            self.feedback_service.update_status(tr('status.mod_installed_success'), UI_COLORS['status_success'])
        if not was_installed_before:
            self._safe_execute(lambda: QTimer.singleShot(0, lambda: self.feedback_service.show_message('info', 'dialogs.mod_installed_apply_info')), 'Failed to show mod installed info')
        if getattr(self.app, 'pending_updates', None):
            next_mod = self.app.pending_updates.pop(0)
            QTimer.singleShot(0, lambda: self.mod_service.update_mod(next_mod))
        self.app.game_launch.update_button_state()

    def _sync_installed_mod_to_all_mods(self, key: str):
        try:
            if not self.app_state.all_mods:
                self.app_state.all_mods = []
            existing_mod = next((m for m in self.app_state.all_mods if get_mod_key(m) == key), None)
            cache = self.mod_service._get_mods_cache()
            if key not in cache:
                return
            config_data = cache[key].config_data
            if not existing_mod:
                mod_to_add = self.mod_service.create_mod_object_from_info(config_data, self.app_state.all_mods)
                if mod_to_add:
                    self.app_state.append_mod(mod_to_add)
            elif config_data.get('files') and (not hasattr(existing_mod, 'files') or not existing_mod.files):
                temp_mod = self.mod_service.create_mod_object_from_info(config_data, self.app_state.all_mods)
                if hasattr(temp_mod, 'files') and temp_mod.files:
                    existing_mod.files = temp_mod.files
        except Exception as e:
            logging.debug(f'ModOperationsController: _sync_installed_mod_to_all_mods failed for {key}: {e}')

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
        if hasattr(self.app, 'search_display'):
            for card in self.app.search_display.card_widget_cache.values():
                if get_mod_key(card.mod_data) == key_to_find:
                    card.update_installation_status()

    def on_mod_uninstall_requested(self, mod):
        if self.app_state.is_installing:
            return
        if self.feedback_service.ask_question('dialogs.delete_confirmation', 'dialogs.delete_mod_confirmation', '', False, mod_name=mod.name):
            QTimer.singleShot(10, lambda m=mod: self.uninstall_mod(m))

    def uninstall_mod(self, mod):
        try:
            self.mod_service.delete_mod_files(mod)
            self.app.search_display.update_search_cards()
            if hasattr(self.app, 'library_display'):
                self.app.library_display.update_display()
            if hasattr(self.app, 'search_display'):
                self.app.search_display.update_filtered_mods(preserve_page=True)
        except Exception as e:
            logging.error(f'ModOperationsController: Failed to uninstall mod: {e}', exc_info=True)
            self.feedback_service.show_message('error', tr('errors.error'), tr('errors.mod_uninstall_failed', error=str(e)))
            return

    def _start_manual_install_from_gamebanana(self, mod):
        try:
            available_files = self._get_all_gamebanana_files(mod)
            if not available_files:
                self.feedback_service.show_message('error', tr('errors.error'), tr('errors.no_gamebanana_files_for_manual_install'))
                return
            selected_file = self._pick_gamebanana_file(available_files, mod.name, getattr(mod, 'external_url', None))
            if selected_file is None:
                return
            self._start_prepare_worker(mod, selected_file)
        except Exception as e:
            logging.error(f'Manual install from GameBanana failed: {e}', exc_info=True)
            self.feedback_service.show_message('error', tr('errors.error'), tr('errors.manual_install_failed', error=str(e)))

    def _start_prepare_worker(self, mod, selected_file: Dict):
        worker = PrepareGameBananaManualInstallWorker(mod, selected_file, parent=self.app)
        self.app_state.is_installing = True
        self.app_state._scan_blocked = True
        self.set_install_buttons_enabled(False)
        self.app.game_launch.update_button_state()

        def on_finished(success: bool, result):
            self.app_state.reset_install_state()
            self.app_state._scan_blocked = False
            self.set_install_buttons_enabled(True)
            self.app.game_launch.update_button_state()
            if success and isinstance(result, tuple):
                prepared_path, gb_metadata, temp_dir = result
                try:
                    from ui.dialogs.manual_install_dialog import ManualModInstallDialog
                    from services.game_detection_service import get_game_type_string
                    initial_game_type = getattr(mod, 'game', None)
                    if not initial_game_type and self.app_state and hasattr(self.app_state, 'game_mode'):
                        initial_game_type = get_game_type_string(self.app_state.game_mode)
                    dialog = ManualModInstallDialog(self.app, prepared_path, gamebanana_metadata=gb_metadata, source_file_path=None, initial_game_type=initial_game_type)
                    dialog.temp_dir_to_cleanup = temp_dir
                    if dialog.exec() == QDialog.DialogCode.Accepted:
                        self.mod_service.invalidate_mods_cache()
                        self.mod_service.load_local_mods(_skip_conversion=True)
                        self.mod_service.mod_list_updated.emit()
                        if hasattr(self.app, 'search_display'):
                            self.app.search_display.update_search_cards()
                        QMessageBox.information(self.app, tr('dialogs.success'), tr('dialogs.mod_created_successfully'))
                except Exception as e:
                    logging.error(f'Failed to open manual install dialog: {e}', exc_info=True)
                    self.feedback_service.show_message('error', tr('errors.error'), tr('errors.manual_install_failed', error=str(e)))
            else:
                error_msg = result if isinstance(result, str) else tr('errors.manual_install_failed', error='Unknown error')
                self.feedback_service.show_message('error', tr('errors.error'), error_msg)
        worker.finished_with_result.connect(on_finished)
        worker.progress.connect(lambda p: setattr(self.app_state, 'progress_bar_value', p))
        worker.status.connect(lambda s, c: self.feedback_service.update_status(s, c))
        self.app_state.progress_bar_visible = True
        self.app_state.progress_bar_value = 0
        self.app_state.current_task = worker
        worker.start()

    def set_install_buttons_enabled(self, enabled: bool):
        self._safe_execute(lambda: (self.app.action_button.setEnabled(True if self.app_state.is_installing else enabled), self.app.saves_button.setEnabled(True)), 'Failed to set install buttons enabled')
