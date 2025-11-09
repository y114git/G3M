import os
import logging
from typing import Any, cast
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QFileDialog, QWidget
from managers.localization_manager import tr
from config.constants import UI_COLORS
from models.game_modes import DemoGameMode, UndertaleYellowGameMode
from workers.background_workers import FullInstallThread


class GameLaunchController(QObject):
    window_hide_requested = pyqtSignal()
    window_restore_requested = pyqtSignal()
    full_install_checkbox_state_checked = pyqtSignal()
    pending_updates_requested = pyqtSignal(list)
    update_geometry_requested = pyqtSignal()
    library_display_update_requested = pyqtSignal()
    search_display_update_requested = pyqtSignal()
    show_pending_dialogs_requested = pyqtSignal()
    pending_updates_changed = pyqtSignal(list)

    def __init__(self, app_state, feedback_manager, mod_manager, slot_manager, settings_manager, game_launcher, customization_manager, plugin_manager, app_window):
        super().__init__()
        self.app_state = app_state
        self.feedback_manager = feedback_manager
        self.mod_manager = mod_manager
        self.slot_manager = slot_manager
        self.settings_manager = settings_manager
        self.game_launcher = game_launcher
        self.customization_manager = customization_manager
        self.plugin_manager = plugin_manager
        self.app = app_window
        self._full_install_checkbox_is_checked = False

    def set_full_install_checkbox_state(self, checked: bool):
        self._full_install_checkbox_is_checked = checked

    def update_button_state(self):
        if self.app_state.is_installing and (not self.app_state.operation_cancelled):
            self.app_state.action_button_text = tr('ui.cancel_button')
            self.app_state.action_button_enabled = True
            return
        if self.app_state.is_merging:
            self.app_state.action_button_text = tr('ui.cancel_button')
            self.app_state.action_button_enabled = True
            return
        if not self.app_state.initialization_completed:
            self.app_state.action_button_text = tr('status.please_wait')
            self.app_state.action_button_enabled = False
            return
        is_demo_mode = isinstance(self.app_state.game_mode, DemoGameMode)
        is_full_install_enabled = is_demo_mode and self._full_install_checkbox_is_checked
        if is_full_install_enabled:
            action_text = tr('buttons.install')
        elif self.slot_manager.check_used_mods_need_updates():
            action_text = tr('ui.update_button')
        else:
            action_text = tr('ui.launch_button')
        self.app_state.action_button_text = action_text
        self.app_state.action_button_enabled = True

    def on_action_button_click(self):
        if self.app_state.is_installing:
            logging.info('GameLaunchController: Cancel button clicked during installation')
            self.app_state.cancel_current_operation()
            self.feedback_manager.update_status(tr('status.operation_cancelled'), UI_COLORS['status_error'])
            try:
                self.app_state.progress_bar_value = 0
                self.app_state.progress_bar_visible = False
            except (AttributeError, RuntimeError):
                logging.debug('Progress bar update failed', exc_info=True)
            self.update_button_state()
            return
        if self.app_state.is_merging or (hasattr(self.game_launcher, '_merge_thread') and self.game_launcher._merge_thread and self.game_launcher._merge_thread.isRunning()):
            is_modpack_creation = False
            modpack_dir = None
            if hasattr(self.app, 'library_display') and hasattr(self.app.library_display, '_modpack_thread'):
                is_modpack_creation = self.app.library_display._modpack_thread == self.app_state.current_task
                if is_modpack_creation:
                    modpack_dir = getattr(self.app.library_display, '_modpack_dir', None)
            merge_thread = None
            if hasattr(self.game_launcher, '_merge_thread') and self.game_launcher._merge_thread:
                merge_thread = self.game_launcher._merge_thread
                merge_thread.cancel()
            if is_modpack_creation and modpack_dir and os.path.exists(modpack_dir):
                try:
                    import shutil
                    shutil.rmtree(modpack_dir, ignore_errors=True)
                    logging.info(f'Cancelled modpack creation, removed directory: {modpack_dir}')
                except Exception as e:
                    logging.error(f'Failed to remove cancelled modpack directory: {e}')
            if is_modpack_creation and hasattr(self.app, 'library_display'):
                if hasattr(self.app.library_display, '_modpack_thread'):
                    self.app.library_display._modpack_thread = None
                if hasattr(self.app.library_display, '_modpack_dir'):
                    self.app.library_display._modpack_dir = None
            self.app_state.is_merging = False
            self.app_state.progress_bar_visible = False
            self.app_state.progress_bar_value = 0
            self.app_state.clear_current_task()
            self.app_state.action_button_text = None
            if merge_thread:
                try:
                    if merge_thread.isRunning():
                        if not merge_thread.wait(3000):
                            logging.warning('Merge thread did not finish in time, requesting termination')
                            merge_thread.terminate()
                            merge_thread.wait(1000)
                    if merge_thread.merger:
                        merge_thread.merger.cleanup(force=True)
                    merge_thread.deleteLater()
                except Exception as e:
                    logging.error(f'Error cleaning up cancelled merge thread: {e}', exc_info=True)
                finally:
                    self.game_launcher._merge_thread = None
            self.feedback_manager.update_status(tr('status.operation_cancelled'), UI_COLORS['status_error'])
            try:
                self.app_state.progress_bar_value = 0
                self.app_state.progress_bar_visible = False
            except (AttributeError, RuntimeError):
                pass
            if self.app_state.current_task and hasattr(self.app_state.current_task, 'cancel'):
                self.app_state.current_task.cancel()
            self.app_state.clear_current_task()
            self.update_button_state()
            return
        if (isinstance(self.app_state.game_mode, DemoGameMode) or isinstance(self.app_state.game_mode, UndertaleYellowGameMode)) and self._full_install_checkbox_is_checked:
            self.perform_full_install()
            return
        if self.app_state.is_installing:
            return
        if self.slot_manager.check_used_mods_need_updates():
            self.update_mods_in_use()
            return
        if self.app_state.operation_cancelled:
            return
        if not self.app_state.is_merging:
            self.app_state.action_button_enabled = False
        self.app_state.saves_button_enabled = False
        self.app_state.progress_bar_visible = False
        self.launch_game()

    def launch_game(self):
        self.game_launcher.launch_game_with_all_mods(execute_plugin_hooks=lambda hook_name: self.plugin_manager.execute_hooks(hook_name, self.app), restore_window_callback=self.app.restore_window_signal.emit)

    def hide_window(self):
        try:
            self.customization_manager.stop_background_music()
        except Exception as e:
            logging.debug(f'stop_background_music failed: {e}')
        self.settings_manager.save_window_geometry(self.app)
        self.app_state.game_is_running = True
        self.window_hide_requested.emit()

    def restore_window(self):
        self.app_state.game_is_running = False
        self.window_restore_requested.emit()
        self.app_state.saves_button_enabled = True
        self.app_state.progress_bar_visible = False
        self.update_button_state()
        self.update_geometry_requested.emit()
        self.library_display_update_requested.emit()
        self.search_display_update_requested.emit()
        self.customization_manager.maybe_start_background_music()
        self.show_pending_dialogs_requested.emit()
        self.plugin_manager.execute_hooks('on_after_game_exit', self.app)

    def perform_full_install(self):
        if self.app_state.is_installing:
            return
        if self.app_state.current_task and self.app_state.current_task.isRunning():
            return
        self.app_state.action_button_enabled = False
        self.app_state.saves_button_enabled = False
        dlg = QDialog(cast(QWidget, self.app))
        if isinstance(self.app_state.game_mode, UndertaleYellowGameMode):
            dlg.setWindowTitle(tr('dialogs.full_yellow_install'))
            install_location_key = 'dialogs.install_yellow_location'
            folder_name = 'UNDERTALE Yellow'
        else:
            dlg.setWindowTitle(tr('dialogs.full_demo_install'))
            install_location_key = 'dialogs.install_demo_location'
            folder_name = 'DELTARUNEdemo'
        v = QVBoxLayout(dlg)
        lbl = QLabel(self.app._full_install_tooltip())
        lbl.setWordWrap(True)
        v.addWidget(lbl)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            self.app_state.action_button_enabled = True
            return
        base_dir = QFileDialog.getExistingDirectory(cast(QWidget, self.app), tr(install_location_key))
        if not base_dir:
            self.app_state.action_button_enabled = True
            return
        target_dir = os.path.join(base_dir, folder_name)
        try:
            os.makedirs(target_dir, exist_ok=True)
        except (OSError, PermissionError) as e:
            self.feedback_manager.show_message('error', 'errors.error', tr('errors.folder_creation_failed', error=str(e)))
            self.app_state.action_button_enabled = True
            return
        self.app_state.progress_bar_visible = True
        self.app_state.progress_bar_value = 0
        full_install_thread = FullInstallThread(cast(Any, self.app), target_dir, False)
        full_install_thread.progress.connect(self.app.set_progress_signal)
        full_install_thread.progress.connect(lambda v: setattr(self.app_state, 'progress_bar_value', v))
        full_install_thread.status.connect(self.app.update_status_signal)
        full_install_thread.finished.connect(self.on_full_install_finished)
        self.app_state.current_task = full_install_thread
        full_install_thread.start()

    def on_full_install_finished(self, success, target_dir):
        self.app_state.clear_current_task()
        self.app_state.progress_bar_visible = False
        self.app_state.progress_bar_value = 0
        self.app._set_checkbox_checked_silently(self.app.full_install_checkbox, False)
        if success:
            if isinstance(self.app_state.game_mode, DemoGameMode):
                self.app_state.demo_game_path = target_dir
                self.app_state.local_config['demo_game_path'] = target_dir
            elif isinstance(self.app_state.game_mode, UndertaleYellowGameMode):
                self.app_state.game_mode.set_game_path(self.app_state.local_config, target_dir)
            else:
                self.app_state.game_path = target_dir
                self.app_state.local_config['game_path'] = target_dir
            self.settings_manager.write_local_config()
            self.feedback_manager.update_status(tr('status.game_files_install_complete'), UI_COLORS['status_success'])
            self.update_button_state()
            return
        else:
            self.feedback_manager.update_status(tr('status.game_files_install_failed'), UI_COLORS['status_error'])
        self.settings_manager.write_local_config()
        self.update_button_state()

    def update_mods_in_use(self):
        mods_to_update = self.slot_manager.collect_mods_needing_update()
        if mods_to_update:
            self.pending_updates_changed.emit(mods_to_update[1:] if len(mods_to_update) > 1 else [])
            self.app_state.operation_cancelled = False
            self.app_state.progress_bar_visible = True
            self.app_state.progress_bar_value = 0
            self.mod_manager.update_mod(mods_to_update[0])

    def refresh_mods_in_use(self):
        if not self.app_state.all_mods:
            return
        for chapter_id, mod_data in list(self.slot_manager.used_mods.items()):
            if not mod_data:
                continue
            mod_key = getattr(mod_data, 'key', None) or getattr(mod_data, 'mod_key', None)
            if not mod_key:
                continue
            updated_mod = None
            for mod in self.app_state.all_mods:
                updated_mod_key = getattr(mod, 'key', None) or getattr(mod, 'mod_key', None)
                if updated_mod_key == mod_key:
                    updated_mod = mod
                    break
            if not updated_mod:
                mod_config = self.mod_manager.get_mod_config(mod_key)
                if mod_config:
                    updated_mod = self.mod_manager.create_mod_object_from_info(mod_config, getattr(self.app_state, 'all_mods', None))
            if updated_mod:
                self.slot_manager.used_mods[chapter_id] = updated_mod
