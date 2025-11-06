import os
import shutil
import logging
import requests
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QInputDialog, QLineEdit, QMessageBox
from PyQt6.QtCore import Qt
from managers.localization_manager import tr
from config.constants import UI_COLORS
from ui.widgets.mod.installed_mod_widget import InstalledModWidget
from ui.dialogs.mod_editor import ModEditorDialog
from ui.dialogs.xdelta import XdeltaDialog
from workers.background_workers import InstallModsThread
from utils.mod_utils import get_mod_key, get_mod_name
from utils.network_utils import check_internet_connection


class ModOperationsController:

    def __init__(self, app_state, feedback_manager, mod_manager, app_window):
        self.app_state = app_state
        self.feedback_manager = feedback_manager
        self.mod_manager = mod_manager
        self.app = app_window

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
            return
        self.install_mod(mod)

    def install_mod(self, mod, force=False, is_update=False):
        try:
            if self.app_state.is_installing and (not force):
                return
            available_chapters = []
            if mod.modgame == 'undertale':
                if mod.files.get('undertale'):
                    available_chapters.append(0)
            elif mod.modgame == 'deltarunedemo':
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
            self.app_state.is_installing = True
            self.set_install_buttons_enabled(False)
            self.app.action_button.setText(tr('ui.cancel_button'))
            self.app._install_op_id += 1
            op_id = self.app._install_op_id
            install_thread = InstallModsThread(self.app, install_tasks, was_installed_before)
            install_thread.progress.connect(lambda v, oid=op_id: self.on_install_progress_token(v, oid))
            install_thread.status.connect(lambda msg, col, oid=op_id: self.on_install_status_token(msg, col, oid))
            install_thread.finished.connect(lambda ok, oid=op_id: self._on_install_task_finished(ok, oid))
            self.app.progress_bar.setVisible(True)
            self.app.progress_bar.setValue(0)
            self._safe_execute(lambda: self.feedback_manager.update_status(tr('status.preparing_download'), UI_COLORS['status_warning']), 'Feedback manager update failed')
            self.app_state.current_task = install_thread
            self.app.game_launch.update_button_state()
            install_thread.start()
        except (IOError, OSError) as e:
            from core.exceptions import ModInstallationError
            mod_key = get_mod_key(mod)
            mod_name = get_mod_name(mod, 'Unknown Mod')
            raise ModInstallationError(f'File operation failed during installation: {e}', mod_key=mod_key, mod_name=mod_name, reason='io_error') from e
        except KeyError as e:
            from core.exceptions import ModInstallationError
            mod_key = get_mod_key(mod)
            mod_name = get_mod_name(mod, 'Unknown Mod')
            raise ModInstallationError(f'Missing required data: {e}', mod_key=mod_key, mod_name=mod_name, reason='missing_data') from e
        except Exception as e:
            from core.exceptions import ModInstallationError
            mod_key = get_mod_key(mod)
            mod_name = get_mod_name(mod, 'Unknown Mod')
            raise ModInstallationError(f'Unexpected error during installation: {e}', mod_key=mod_key, mod_name=mod_name, reason='unknown') from e

    def on_install_progress_token(self, value: int, op_id: int):
        if self.app._install_op_id == op_id and self.app_state.is_installing:
            self.app.progress_bar.setValue(value)

    def on_install_status_token(self, message: str, color: str, op_id: int):
        if self.app._install_op_id == op_id and self.app_state.is_installing:
            self.app._update_status(message, color)

    def _on_install_task_finished(self, success: bool, op_id: int):
        if self.app._install_op_id != op_id:
            return
        was_installed_before = False
        if self.app_state.current_task:
            was_installed_before = getattr(self.app_state.current_task, 'was_installed_before', False)
        self._on_install_complete(success, '', was_installed_before)

    def _on_install_complete(self, success: bool, message: str = '', was_installed_before: bool = False):
        current_task = self.app_state.current_task
        self.app.progress_bar.setValue(0)
        self.app.progress_bar.setVisible(False)
        self.app_state.is_installing = False
        self.app_state.clear_current_task()
        self.set_install_buttons_enabled(True)
        if not success:
            if self.app_state.operation_cancelled:
                self._safe_execute(lambda: setattr(self.app_state, 'operation_cancelled', False), 'Failed to set operation_cancelled')
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
            return
        self._safe_execute(lambda: self.mod_manager.invalidate_mods_cache(), 'invalidate_mods_cache failed', default_return=None)
        self._safe_execute(lambda: self.mod_manager.load_local_mods(), 'load_local_mods failed', default_return=None)
        self._safe_execute(lambda: QTimer.singleShot(0, self.app.search_display.update_search_plaques), 'update_search_plaques failed')
        self._safe_execute(lambda: QTimer.singleShot(0, self.app.library_display.update_display) if hasattr(self.app, 'library_display') else None, 'update_library_display failed')
        if current_task:
            self.app_state.current_task = current_task
            QTimer.singleShot(100, self.refresh_specific_mod_widget_after_update)
            self.app_state.clear_current_task()
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

    def refresh_specific_mod_widget_after_update(self):
        if not self.app_state.current_task:
            return
        install_tasks = getattr(self.app_state.current_task, 'install_tasks', [])
        if not install_tasks:
            return
        mod_data_tuple = install_tasks[0]
        mod_to_update = mod_data_tuple[0]
        mod_key_to_find = get_mod_key(mod_to_update)
        if not mod_key_to_find:
            return
        if hasattr(self.app, 'installed_mods_layout'):
            for i in range(self.app.installed_mods_layout.count()):
                item = self.app.installed_mods_layout.itemAt(i)
                if item and item.widget():
                    widget = item.widget()
                    if isinstance(widget, InstalledModWidget):
                        widget_mod_key = get_mod_key(widget.mod_data)
                        if widget_mod_key == mod_key_to_find:
                            widget.update_status()
                            break

    def on_mod_uninstall_requested(self, mod):
        if self.app_state.is_installing:
            return
        if self.feedback_manager.ask_question('dialogs.delete_confirmation', 'dialogs.delete_mod_confirmation', '', False, mod_name=mod.name):
            self.uninstall_mod(mod)

    def uninstall_mod(self, mod):
        self.mod_manager.uninstall_mod(mod)
        self.app.search_display.update_search_plaques()

    def set_install_buttons_enabled(self, enabled: bool):
        self._safe_execute(lambda: (self.app.action_button.setEnabled(True if self.app_state.is_installing else enabled), self.app.saves_button.setEnabled(True), self.app.shortcut_button.setEnabled(enabled)), 'Failed to set install buttons enabled')

    def show_mod_management_dialog(self):
        has_internet = check_internet_connection()
        dialog = QDialog(self.app)
        dialog.setWindowTitle(tr('ui.mod_management'))
        dialog.setModal(True)
        dialog.resize(400, 300)
        layout = QVBoxLayout(dialog)
        layout.setSpacing(20)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel(tr('dialogs.what_do_you_want_to_do'))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet('font-size: 18px; font-weight: bold; margin-bottom: 20px;')
        layout.addWidget(title)
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(15)
        create_button = QPushButton(tr('ui.create_mod'))
        create_button.setFixedSize(180, 50)
        create_button.clicked.connect(lambda: self._on_create_mod_choice(dialog, has_internet))
        edit_button = QPushButton(tr('ui.edit_mod'))
        edit_button.setFixedSize(180, 50)
        edit_button.clicked.connect(lambda: self._on_edit_mod_choice(dialog, has_internet))
        buttons_layout.addWidget(create_button)
        buttons_layout.addWidget(edit_button)
        layout.addLayout(buttons_layout)
        layout.addSpacing(30)
        cancel_button = QPushButton(tr('ui.cancel_button'))
        cancel_button.clicked.connect(dialog.reject)
        layout.addWidget(cancel_button)
        dialog.exec()

    def _show_mod_choice_dialog(self, title_key, public_callback, local_callback, has_internet):
        dialog = QDialog(self.app)
        dialog.setWindowTitle(tr('ui.create_mod') if 'create' in title_key else tr('ui.edit_mod'))
        dialog.setModal(True)
        dialog.resize(300, 200)
        layout = QVBoxLayout(dialog)
        layout.setSpacing(20)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel(tr(title_key))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet('font-size: 16px; font-weight: bold;')
        layout.addWidget(title)
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(15)
        public_button = QPushButton(tr('buttons.public'))
        public_button.setFixedSize(130, 40)
        public_button.clicked.connect(lambda: (dialog.accept(), public_callback(dialog)))
        public_button.setEnabled(has_internet)
        if not has_internet:
            public_button.setToolTip(tr('errors.internet_required'))
        local_button = QPushButton(tr('tags.local'))
        local_button.setFixedSize(130, 40)
        local_button.clicked.connect(lambda: (dialog.accept(), local_callback(dialog)))
        buttons_layout.addWidget(public_button)
        buttons_layout.addWidget(local_button)
        layout.addLayout(buttons_layout)
        cancel_button = QPushButton(tr('ui.cancel_button'))
        cancel_button.clicked.connect(dialog.reject)
        layout.addWidget(cancel_button)
        dialog.exec()

    def _on_create_mod_choice(self, parent_dialog, has_internet):
        parent_dialog.accept()
        self._show_mod_choice_dialog('ui.how_to_create_mod', lambda d: self._create_mod(d, public=True), lambda d: self._create_mod(d, public=False), has_internet)

    def _on_edit_mod_choice(self, parent_dialog, has_internet):
        parent_dialog.accept()
        self._show_mod_choice_dialog('dialogs.what_mod_type_to_change', self._edit_public_mod, self._edit_local_mod, has_internet)

    def _activate_window_safe(self):
        try:
            self.app.activateWindow()
            self.app.raise_()
            self.app.setFocus()
        except Exception:
            pass

    def _create_mod(self, parent_dialog, public: bool):
        parent_dialog.accept()
        if public and (not check_internet_connection()):
            self.feedback_manager.show_message('error', 'errors.no_internet', tr('errors.public_mod_internet'))
            return
        editor = ModEditorDialog(self.app, is_creating=True, is_public=public)
        editor.exec()
        self._activate_window_safe()

    def _edit_public_mod(self, parent_dialog):
        parent_dialog.accept()
        if not check_internet_connection():
            self.feedback_manager.show_message('error', 'errors.no_internet', tr('errors.edit_mod_internet'))
            return
        secret_key, ok = QInputDialog.getText(self.app, tr('dialogs.enter_secret_key'), tr('ui.secret_key_label'), QLineEdit.EchoMode.Password)
        if not ok or not secret_key.strip():
            return
        try:
            mod_data, hashed_key, found_in_pending = self.mod_manager.fetch_mod_data_by_secret(secret_key)
        except requests.RequestException as e:
            error_msg = tr('errors.key_check_failed', error=str(e))
            self.feedback_manager.show_message('error', 'errors.error', error_msg)
            return
        except Exception as e:
            logging.error(f'Unexpected error fetching mod data: {e}', exc_info=True)
            self.feedback_manager.show_message('error', 'errors.error', tr('errors.key_check_failed', error=str(e)))
            return
        if not mod_data:
            self.feedback_manager.show_message('warning', 'errors.mod_not_found', tr('errors.secret_key_invalid'))
            return
        if not hashed_key:
            self.feedback_manager.show_message('warning', 'errors.mod_not_found', tr('errors.secret_key_invalid'))
            return
        if mod_data.get('ban_status', False):
            ban_reason = mod_data.get('ban_reason', tr('defaults.not_specified'))
            self.feedback_manager.show_message('error', 'dialogs.mod_blocked_title', tr('dialogs.mod_blocked_message', ban_reason=ban_reason, error_message=tr('dialogs.error_occurred')))
            return
        if found_in_pending:
            result = self.feedback_manager.ask_custom_question(QMessageBox.Icon.Information, 'dialogs.mod_on_moderation', 'dialogs.mod_on_moderation_message', [('buttons.withdraw_request', QMessageBox.ButtonRole.DestructiveRole, 'withdraw'), ('buttons.ok', QMessageBox.ButtonRole.AcceptRole, 'ok')], 'ok')
            if result == 'withdraw':
                try:
                    self.mod_manager.withdraw_pending_mod(hashed_key)
                    self.feedback_manager.show_message('info', 'dialogs.request_withdrawn', tr('dialogs.withdrawal_success'))
                except requests.RequestException as e:
                    error_msg = tr('errors.request_revoke_failed', error=str(e))
                    self.feedback_manager.show_message('error', 'errors.error', error_msg)
                except Exception as e:
                    logging.error(f'Unexpected error withdrawing pending mod: {e}', exc_info=True)
                    self.feedback_manager.show_message('error', 'errors.error', tr('errors.request_revoke_failed', error=str(e)))
            return
        if self.mod_manager.has_pending_changes(hashed_key):
            result = self.feedback_manager.ask_custom_question(QMessageBox.Icon.Information, 'dialogs.changes_under_review', 'dialogs.request_pending', [('buttons.withdraw_request', QMessageBox.ButtonRole.DestructiveRole, 'withdraw')])
            if result == 'withdraw':
                try:
                    self.mod_manager.withdraw_pending_change(hashed_key)
                    self.feedback_manager.show_message('info', 'dialogs.request_withdrawn', tr('dialogs.withdrawal_success'))
                except (requests.RequestException, Exception) as e:
                    if isinstance(e, requests.RequestException):
                        error_msg = tr('errors.request_revoke_failed', error=str(e))
                    else:
                        logging.error(f'Unexpected error withdrawing pending change: {e}', exc_info=True)
                        error_msg = tr('errors.request_revoke_failed', error=str(e))
                    self.feedback_manager.show_message('error', 'errors.error', error_msg)
                    return
            else:
                return
        editor = ModEditorDialog(self.app, is_creating=False, is_public=True, mod_data=mod_data)
        editor.exec()
        self._activate_window_safe()

    def _edit_local_mod(self, parent_dialog):
        parent_dialog.accept()
        local_mods = self.mod_manager.list_local_mods()
        if not local_mods:
            self.feedback_manager.show_message('info', 'dialogs.no_local_mods_title', tr('dialogs.no_local_mods_message'))
            return
        mod_names = [mod_info['name'] for mod_info in local_mods]
        selected_name, ok = QInputDialog.getItem(self.app, tr('dialogs.select_mod'), tr('dialogs.local_mods'), mod_names, 0, False)
        if not ok:
            return
        selected_mod = next((mod_info for mod_info in local_mods if mod_info['name'] == selected_name), None)
        if not selected_mod:
            self.feedback_manager.show_message('warning', 'errors.error', tr('errors.selected_mod_not_found'))
            return
        mod_data = selected_mod['data'].copy()
        mod_data['key'] = selected_mod['key']
        mod_data['folder_name'] = os.path.basename(selected_mod['folder_path']) if selected_mod.get('folder_path') else ''
        if selected_mod.get('folder_path'):
            mod_data['folder_path'] = selected_mod['folder_path']
        editor = ModEditorDialog(self.app, is_creating=False, is_public=False, mod_data=mod_data)
        editor.exec()
        self._activate_window_safe()

    def show_xdelta_patch_dialog(self):
        try:
            dialog = XdeltaDialog(self.app)
            dialog.exec()
        except Exception as e:
            self.feedback_manager.show_message('error', 'errors.error', tr('errors.patching_window_failed', error=str(e)))
