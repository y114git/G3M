import os
import logging
from typing import Any, cast
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QFileDialog, QWidget
from managers.localization_manager import tr
from config.constants import UI_COLORS
from models.game_modes import DemoGameMode
from ui.common.styling import load_mod_icon_universal
from workers.background_workers import FullInstallThread


class GameLaunchController:

    def __init__(self, app_window):
        self.app = app_window
        self.app_state = app_window.app_state
        self.feedback_manager = app_window.feedback_manager
        self.mod_manager = app_window.mod_manager
        self.slot_manager = app_window.slot_manager
        self.settings_manager = app_window.settings_manager
        self.game_launcher = app_window.game_launcher
        self.customization_manager = app_window.customization_manager

    def update_button_state(self):
        if self.app_state.is_installing and (not getattr(self.app, '_operation_cancelled', False)):
            self.app.action_button.setText(tr('ui.cancel_button'))
            self.app.action_button.setEnabled(True)
            return
        if not self.app_state.initialization_completed:
            self.app.action_button.setText(tr('status.please_wait'))
            self.app.action_button.setEnabled(False)
            return
        is_demo_mode = isinstance(self.app_state.game_mode, DemoGameMode)
        is_full_install_enabled = is_demo_mode and hasattr(self.app, 'full_install_checkbox') and self.app.full_install_checkbox.isChecked()
        if is_full_install_enabled:
            action_text = tr('buttons.install')
        elif self.slot_manager.check_active_slots_need_updates():
            action_text = tr('ui.update_button')
        else:
            action_text = tr('ui.launch_button')
        self.app.action_button.setText(action_text)
        self.app.action_button.setEnabled(True)

    def on_action_button_click(self):
        if self.app_state.is_installing:
            self.app._operation_cancelled = True
            self.feedback_manager.update_status(tr('status.operation_cancelled'), UI_COLORS['status_error'])
            try:
                self.app.progress_bar.setValue(0)
                self.app.progress_bar.setVisible(False)
            except Exception:
                pass
            try:
                thr = None
                if getattr(self.app, 'current_install_thread', None):
                    thr = self.app.current_install_thread
                elif getattr(self.app, 'install_thread', None):
                    thr = self.app.install_thread
                elif getattr(self.app, 'full_install_thread', None):
                    thr = self.app.full_install_thread
                elif getattr(self.app, 'mod_manager', None) and getattr(self.app.mod_manager, 'current_install_thread', None):
                    thr = self.app.mod_manager.current_install_thread
                elif getattr(self.app, 'mod_manager', None) and getattr(self.app.mod_manager, 'url_install_thread', None):
                    thr = self.app.mod_manager.url_install_thread
                if thr and hasattr(thr, 'cancel'):
                    thr.cancel()
            except Exception:
                pass
            try:
                self.app_state.is_installing = False
            except Exception:
                pass
            self.update_button_state()
            return
        if isinstance(self.app_state.game_mode, DemoGameMode) and getattr(self.app, 'full_install_checkbox', None) is not None and self.app.full_install_checkbox.isChecked():
            self.perform_full_install()
            return
        if self.app_state.is_installing:
            return
        if self.slot_manager.check_active_slots_need_updates():
            self.update_mods_in_active_slots()
            return
        if getattr(self.app, '_operation_cancelled', False):
            return
        self.app.action_button.setEnabled(False)
        self.app.saves_button.setEnabled(False)
        self.app.progress_bar.setVisible(False)
        self.launch_game()

    def launch_game(self):
        self.game_launcher.launch_game_with_all_mods(execute_plugin_hooks=lambda hook_name: self.app.plugin_manager.execute_hooks(hook_name, self.app), restore_window_callback=self.app.restore_window_signal.emit)

    def hide_window(self):
        try:
            self.customization_manager.stop_background_music()
        except Exception as e:
            logging.debug(f'stop_background_music failed: {e}')
        self.app_state.game_is_running = True
        self.app.hide()

    def restore_window(self):
        self.app_state.game_is_running = False
        self.app.showNormal()
        self.app.activateWindow()
        self.app.raise_()
        self.app.saves_button.setEnabled(True)
        self.app.progress_bar.setVisible(False)
        self.update_button_state()
        QTimer.singleShot(100, self.app.updateGeometry)
        if hasattr(self.app, 'library_display'):
            self.app.library_display.update_display()
        if hasattr(self.app, 'search_display'):
            self.app.search_display.update_display()
        self.customization_manager.maybe_start_background_music(getattr(self.app, 'is_shown_to_user', False), self.app.isVisible())
        if hasattr(self.app, '_show_pending_dialogs'):
            self.app._show_pending_dialogs()
        self.app.plugin_manager.execute_hooks('on_after_game_exit', self.app)

    def perform_full_install(self):
        if self.app_state.is_installing:
            return
        if hasattr(self.app, 'full_install_thread') and self.app.full_install_thread and self.app.full_install_thread.isRunning():
            return
        self.app.action_button.setEnabled(False)
        self.app.saves_button.setEnabled(False)
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
            self.app.action_button.setEnabled(True)
            return
        base_dir = QFileDialog.getExistingDirectory(cast(QWidget, self.app), tr('dialogs.install_demo_location'))
        if not base_dir:
            self.app.action_button.setEnabled(True)
            return
        target_dir = os.path.join(base_dir, 'DELTARUNEdemo')
        try:
            os.makedirs(target_dir, exist_ok=True)
        except Exception as e:
            self.feedback_manager.show_error('errors.error', tr('errors.folder_creation_failed', error=str(e)))
            self.app.action_button.setEnabled(True)
            return
        self.app.progress_bar.setVisible(True)
        self.app.progress_bar.setValue(0)
        self.app.full_install_thread = FullInstallThread(cast(Any, self.app), target_dir, False)
        self.app.full_install_thread.progress.connect(self.app.set_progress_signal)
        self.app.full_install_thread.progress.connect(self.app.progress_bar.setValue)
        self.app.full_install_thread.status.connect(self.app.update_status_signal)
        self.app.full_install_thread.progress.connect(self.app.progress_bar.setValue)
        self.app.full_install_thread.finished.connect(self.on_full_install_finished)
        self.app.full_install_thread.start()

    def on_full_install_finished(self, success, target_dir):
        self.app.progress_bar.setVisible(False)
        self.app.full_install_checkbox.blockSignals(True)
        self.app.progress_bar.setValue(0)
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
            self.app.pending_updates = mods_to_update[1:] if len(mods_to_update) > 1 else []
            try:
                self.app._operation_cancelled = False
            except Exception:
                pass
            if hasattr(self.app, 'progress_bar'):
                try:
                    self.app.progress_bar.setVisible(True)
                    self.app.progress_bar.setValue(0)
                except Exception:
                    pass
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
