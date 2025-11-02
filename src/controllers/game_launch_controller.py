import os
import logging
from typing import Any, cast
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QFileDialog, QWidget
from managers.localization_manager import tr
from config.constants import UI_COLORS
from models.game_modes import DemoGameMode
from ui.common.styling import load_mod_icon_universal
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
        if not self.app_state.initialization_completed:
            self.app_state.action_button_text = tr('status.please_wait')
            self.app_state.action_button_enabled = False
            return
        is_demo_mode = isinstance(self.app_state.game_mode, DemoGameMode)
        is_full_install_enabled = is_demo_mode and self._full_install_checkbox_is_checked
        if is_full_install_enabled:
            action_text = tr('buttons.install')
        elif self.slot_manager.check_active_slots_need_updates():
            action_text = tr('ui.update_button')
        else:
            action_text = tr('ui.launch_button')
        self.app_state.action_button_text = action_text
        self.app_state.action_button_enabled = True

    def on_action_button_click(self):
        if self.app_state.is_installing:
            self.app_state.operation_cancelled = True
            self.feedback_manager.update_status(tr('status.operation_cancelled'), UI_COLORS['status_error'])
            try:
                self.app_state.progress_bar_value = 0
                self.app_state.progress_bar_visible = False
            except (AttributeError, RuntimeError):
                import logging
                logging.debug('Progress bar update failed', exc_info=True)
            if self.app_state.current_task and hasattr(self.app_state.current_task, 'cancel'):
                self.app_state.current_task.cancel()
            self.app_state.is_installing = False
            self.app_state.clear_current_task()
            self.update_button_state()
            return
        if isinstance(self.app_state.game_mode, DemoGameMode) and self._full_install_checkbox_is_checked:
            self.perform_full_install()
            return
        if self.app_state.is_installing:
            return
        if self.slot_manager.check_active_slots_need_updates():
            self.update_mods_in_active_slots()
            return
        if self.app_state.operation_cancelled:
            return
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
        self.customization_manager.maybe_start_background_music(self.app_state.is_shown_to_user, True)
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
        dlg.setWindowTitle(tr('dialogs.full_demo_install'))
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
        base_dir = QFileDialog.getExistingDirectory(cast(QWidget, self.app), tr('dialogs.install_demo_location'))
        if not base_dir:
            self.app_state.action_button_enabled = True
            return
        target_dir = os.path.join(base_dir, 'DELTARUNEdemo')
        try:
            os.makedirs(target_dir, exist_ok=True)
        except (OSError, PermissionError) as e:
            self.feedback_manager.show_error('errors.error', tr('errors.folder_creation_failed', error=str(e)))
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
        self.app.full_install_checkbox.blockSignals(True)
        self.app_state.progress_bar_value = 0
        self.app.full_install_checkbox.setChecked(False)
        self.app.full_install_checkbox.blockSignals(False)
        if success:
            if isinstance(self.app_state.game_mode, DemoGameMode):
                self.app_state.demo_game_path = target_dir
                self.app_state.local_config['demo_game_path'] = target_dir
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

    def update_mods_in_active_slots(self):
        mods_to_update = self.slot_manager.collect_mods_needing_update_in_active_slots()
        if mods_to_update:
            self.pending_updates_changed.emit(mods_to_update[1:] if len(mods_to_update) > 1 else [])
            self.app_state.operation_cancelled = False
            self.app_state.progress_bar_visible = True
            self.app_state.progress_bar_value = 0
            self.mod_manager.update_mod(mods_to_update[0])

    def refresh_mods_in_slots(self):
        if not hasattr(self.app, 'slots') or not self.app_state.all_mods:
            return
        for slot_frame in self.app_state.slots.values():
            if slot_frame.assigned_mod:
                old_mod = slot_frame.assigned_mod
                mod_key = getattr(old_mod, 'key', None) or getattr(old_mod, 'mod_key', None)
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
                    slot_frame.assigned_mod = updated_mod
        self.refresh_slot_displays()

    def refresh_slot_displays(self):
        for slot_frame in self.app_state.slots.values():
            if slot_frame.assigned_mod and slot_frame.content_widget:
                self.refresh_slot_status_display(slot_frame)
                if hasattr(slot_frame, 'mod_icon') and slot_frame.mod_icon:
                    load_mod_icon_universal(slot_frame.mod_icon, slot_frame.assigned_mod, 32)

    def refresh_slot_status_display(self, slot_frame):
        if not slot_frame.assigned_mod or not slot_frame.content_widget:
            return
        mod_data = slot_frame.assigned_mod
        version_label = None
        content_layout = slot_frame.content_widget.layout()
        if content_layout:
            for i in range(content_layout.count()):
                item = content_layout.itemAt(i)
                if item and item.layout():
                    text_layout = item.layout()
                    if text_layout and text_layout.count() >= 2:
                        version_item = text_layout.itemAt(1)
                        if version_item and version_item.widget():
                            from PyQt6.QtWidgets import QLabel
                            if isinstance(version_item.widget(), QLabel):
                                version_label = version_item.widget()
                                break
        if version_label:
            is_large_slot = slot_frame.chapter_id < 0
            is_local_mod = getattr(mod_data, 'is_local_mod', False)
            if is_local_mod:
                if is_large_slot:
                    status_text, status_color = (tr('defaults.local_mod'), '#FFD700')
                    version_label.setStyleSheet(f'color: {status_color}; font-size: 10px; border: none; background: transparent;')
                else:
                    status_text, status_color = (tr('tags.local'), '#FFD700')
                    version_label.setStyleSheet(f'color: {status_color}; font-size: 9px; border: none; background: transparent;')
            elif is_large_slot:
                needs_update = any((self.mod_manager.mod_has_files_for_chapter(mod_data, i) and self.mod_manager.get_mod_status(mod_data, i) == 'update' for i in range(5)))
                status_text, status_color = (tr('status.update_available'), 'orange') if needs_update else (tr('status.version_current'), 'lightgreen')
                version_label.setStyleSheet(f'color: {status_color}; font-size: 10px; border: none; background: transparent;')
            else:
                needs_update = any((self.mod_manager.mod_has_files_for_chapter(mod_data, i) and self.mod_manager.get_mod_status(mod_data, i) == 'update' for i in range(5)))
                status_text, status_color = (tr('status.update_short'), 'orange') if needs_update else (tr('status.current_short'), 'lightgreen')
                version_label.setStyleSheet(f'color: {status_color}; font-size: 9px; border: none; background: transparent;')
            version_label.setText(status_text)

    def run_as_admin_windows(self, path: str) -> bool:
        import subprocess
        script = f"import os, stat; p = r'{path}'; [os.chmod(os.path.join(r, f), os.stat(os.path.join(r, f)).st_mode | stat.S_IWRITE) for r, _, fs in os.walk(p) for f in fs] if os.path.isdir(p) else os.chmod(p, os.stat(p).st_mode | stat.S_IWRITE) if os.path.exists(p) else None"
        command = f'Start-Process python -ArgumentList "-c \\"{script}\\"" -Verb RunAs -WindowStyle Hidden'
        try:
            subprocess.run(['powershell', '-Command', command], check=True, capture_output=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.feedback_manager.update_status(tr('status.permission_change_failed'), UI_COLORS['status_error'])
            return False
