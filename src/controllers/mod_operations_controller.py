import os
import shutil
from PyQt6.QtCore import QTimer
from managers.localization_manager import tr
from config.constants import UI_COLORS
from ui.widgets.mod.installed_mod_widget import InstalledModWidget
from workers.background_workers import InstallModsThread


class ModOperationsController:

    def __init__(self, app_window):
        self.app = app_window
        self.app_state = app_window.app_state
        self.feedback_manager = app_window.feedback_manager
        self.mod_manager = app_window.mod_manager

    def handle_url_install(self, url: str):
        from utils.game_utils import is_game_running
        if is_game_running():
            return
        self.app.activateWindow()
        self.app.raise_()
        if self.app_state.is_installing:
            self.feedback_manager.show_warning('dialogs.install_in_progress_title', tr('dialogs.install_in_progress_body'))
            return
        self.mod_manager.install_from_url(url)

    def on_mod_install_requested(self, mod):
        if self.app_state.is_installing:
            return
        self.install_mod(mod)

    def install_mod(self, mod, force=False):
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
                self.feedback_manager.show_warning('errors.mod_no_files', mod_name=mod.name)
                return
            was_installed_before = self.mod_manager.is_mod_installed(mod.key)
            is_xdelta_mod = getattr(mod, 'is_xdelta', False)
            if not is_xdelta_mod and (not was_installed_before):
                if not self.feedback_manager.ask_question('dialogs.file_replacement_warning_title', 'dialogs.file_replacement_warning_body', '', False):
                    self.feedback_manager.update_status(tr('status.install_cancelled_by_user'), UI_COLORS['status_info'])
                    return
            install_tasks = [(mod, chapter_id) for chapter_id in available_chapters]
            try:
                self.app._operation_cancelled = False
            except Exception:
                pass
            self.app_state.is_installing = True
            self.set_install_buttons_enabled(False)
            self.app.action_button.setText(tr('ui.cancel_button'))
            self.app._install_op_id = getattr(self.app, '_install_op_id', 0) + 1
            op_id = self.app._install_op_id
            self.app.current_install_thread = InstallModsThread(self.app, install_tasks, was_installed_before)
            self.app.install_thread = self.app.current_install_thread
            self.app.install_thread.progress.connect(lambda v, oid=op_id: self.on_install_progress_token(v, oid))
            self.app.install_thread.status.connect(lambda msg, col, oid=op_id: self.on_install_status_token(msg, col, oid))
            self.app.install_thread.finished.connect(lambda ok, oid=op_id: self.on_install_finished_token(ok, oid))
            self.app.progress_bar.setVisible(True)
            self.app.progress_bar.setValue(0)
            try:
                self.feedback_manager.update_status(tr('status.preparing_download'), UI_COLORS['status_warning'])
            except Exception:
                pass
            self.app._update_action_button_state()
            self.app.install_thread.start()
        except Exception as e:
            self.feedback_manager.show_error('errors.mod_install_failed', error=str(e))

    def on_install_progress_token(self, value: int, op_id: int):
        if getattr(self.app, '_install_op_id', 0) == op_id and self.app_state.is_installing:
            self.app.progress_bar.setValue(value)

    def on_install_status_token(self, message: str, color: str, op_id: int):
        if getattr(self.app, '_install_op_id', 0) == op_id and self.app_state.is_installing:
            self.app._update_status(message, color)

    def on_install_finished_token(self, success: bool, op_id: int):
        if getattr(self.app, '_install_op_id', 0) != op_id:
            return
        self.on_install_finished(success)

    def on_install_finished(self, success: bool):
        was_installed_before = False
        if hasattr(self.app, 'current_install_thread') and self.app.current_install_thread:
            was_installed_before = getattr(self.app.current_install_thread, 'was_installed_before', False)
        self.app.progress_bar.setValue(0)
        self.app.progress_bar.setVisible(False)
        if success:
            self.feedback_manager.update_status(tr('status.mod_installed_success'), UI_COLORS['status_success'])
        else:
            if getattr(self.app, '_operation_cancelled', False):
                try:
                    self.app._operation_cancelled = False
                except Exception:
                    pass
            else:
                self.feedback_manager.update_status(tr('status.mod_install_error'), UI_COLORS['status_error'])
            try:
                thr = self.app.current_install_thread
                temp_root = getattr(thr, 'temp_root', None)
                if temp_root and os.path.isdir(temp_root):
                    shutil.rmtree(temp_root, ignore_errors=True)
            except Exception:
                pass
        self.app_state.is_installing = False
        self.set_install_buttons_enabled(True)
        self.app.current_install_thread = None
        if success:
            self.mod_manager.load_local_mods()
            self.app.search_display.update_search_plaques()
            if hasattr(self.app, 'library_display'):
                self.app.library_display.update_display()
            QTimer.singleShot(100, self.refresh_specific_mod_widget_after_update)
            try:
                if not was_installed_before:
                    self.feedback_manager.show_info('dialogs.mod_installed_title', tr('dialogs.mod_installed_apply_info'))
            except Exception:
                pass
            self.feedback_manager.update_status(tr('status.mod_installed_success'), UI_COLORS['status_success'])
        self.app._update_action_button_state()

    def on_mod_installation_finished(self, success: bool, message: str):
        self.app_state.is_installing = False
        self.set_install_buttons_enabled(True)
        self.app.progress_bar.setVisible(False)
        try:
            QTimer.singleShot(0, self.app.search_display.update_search_plaques)
        except Exception as e:
            import logging
            logging.debug(f'update_search_plaques failed: {e}')
        try:
            self.mod_manager.load_local_mods()
        except Exception as e:
            import logging
            logging.warning(f'load_local_mods failed: {e}')
        try:
            if hasattr(self.app, 'library_display'):
                QTimer.singleShot(0, self.app.library_display.update_display)
        except Exception as e:
            import logging
            logging.debug(f'update_library_display failed: {e}')
        try:
            if hasattr(self.app, 'slot_manager'):
                self.app.slot_manager.refresh_slots_content()
        except Exception as e:
            import logging
            logging.debug(f'refresh_slots_content failed: {e}')
        if success:
            try:
                QTimer.singleShot(0, lambda: self.feedback_manager.show_info('dialogs.mod_installed_apply_info'))
            except Exception:
                pass
        self.app._update_action_button_state()
        if success and getattr(self.app, 'pending_updates', None):
            next_mod = self.app.pending_updates.pop(0)
            QTimer.singleShot(0, lambda: self.mod_manager.update_mod(next_mod))

    def refresh_specific_mod_widget_after_update(self):
        if not hasattr(self.app, 'current_install_thread') or not self.app.current_install_thread:
            return
        install_tasks = getattr(self.app.current_install_thread, 'install_tasks', [])
        if not install_tasks:
            return
        mod_data_tuple = install_tasks[0]
        mod_to_update = mod_data_tuple[0]
        mod_key_to_find = getattr(mod_to_update, 'key', None)
        if not mod_key_to_find:
            return
        if hasattr(self.app, 'installed_mods_layout'):
            for i in range(self.app.installed_mods_layout.count()):
                item = self.app.installed_mods_layout.itemAt(i)
                if item and item.widget():
                    widget = item.widget()
                    if isinstance(widget, InstalledModWidget):
                        widget_mod_key = getattr(widget.mod_data, 'key', None)
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
        try:
            self.app.action_button.setEnabled(True if self.app_state.is_installing else enabled)
            self.app.saves_button.setEnabled(True)
            self.app.shortcut_button.setEnabled(enabled)
        except Exception:
            pass
