"""Controller for game launch operations and installation management."""

import contextlib
import logging
import os
from typing import Any, cast

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from app.game_ui import full_install_tooltip
from config.config import UI_COLORS
from services.localization_service import tr
from ui.common.styling import get_launch_status_color
from utils.mod_utils import get_mod_id
from utils.process_utils import format_filesystem_error
from workers.install.full_install_worker import FullInstallThread


class GameLaunchController(QObject):
    """Manages game launch operations, installations, and related UI state."""

    window_hide_requested = pyqtSignal()
    window_restore_requested = pyqtSignal()
    full_install_checkbox_state_checked = pyqtSignal()
    pending_updates_requested = pyqtSignal(list)
    update_geometry_requested = pyqtSignal()
    library_display_update_requested = pyqtSignal()
    search_display_update_requested = pyqtSignal()
    show_pending_dialogs_requested = pyqtSignal()
    pending_updates_changed = pyqtSignal(list)

    def __init__(
        self,
        app_state,
        feedback_service,
        mod_service,
        used_mods_service,
        settings_service,
        game_launcher,
        customization_service,
        app_window,
    ) -> None:
        super().__init__()
        self.app_state = app_state
        self.feedback_service = feedback_service
        self.mod_service = mod_service
        self.used_mods_service = used_mods_service
        self.settings_service = settings_service
        self.game_launcher = game_launcher
        self.customization_service = customization_service
        self.app = app_window
        self._full_install_checkbox_is_checked = False
        self._window_hidden_for_launch = False

    def _is_full_install_enabled(self) -> bool:
        return (
            self.app_state.game_mode.supports_full_install
            and self._full_install_checkbox_is_checked
        )

    def _launch_status_color(self) -> str:
        return get_launch_status_color(getattr(self.app_state, "local_config", None))

    def update_button_state(self):
        if getattr(self.app_state, "game_is_running", False):
            self.app_state.action_button_text = tr("ui.close_game")
            self.app_state.action_button_enabled = True
            return
        if (
            self.app_state.is_installing and (not self.app_state.operation_cancelled)
        ) or self.app_state.is_patching:
            self.app_state.action_button_text = tr("ui.cancel_button")
            self.app_state.action_button_enabled = True
            return
        if not self.app_state.initialization_completed:
            self.app_state.action_button_text = tr("status.please_wait")
            self.app_state.action_button_enabled = False
            return
        action_text = (
            tr("buttons.install")
            if self._is_full_install_enabled()
            else tr("ui.update_button")
            if self.used_mods_service.check_used_mods_need_updates()
            else tr("ui.launch_button")
        )
        self.app_state.action_button_text = action_text
        self.app_state.action_button_enabled = True

    def _reset_progress_bar(self):
        try:
            self.app_state.progress_bar_value = 0
            self.app_state.progress_bar_visible = False
        except (AttributeError, RuntimeError):
            pass

    def _cancel_patching_operation(self):
        library_display = getattr(self.app, "library_display", None)
        is_modpack_creation = (
            library_display
            and hasattr(library_display, "_modpack_thread")
            and (library_display._modpack_thread == self.app_state.current_task)
        )
        modpack_dir = (
            getattr(library_display, "_modpack_dir", None)
            if is_modpack_creation
            else None
        )
        patching_thread = getattr(self.game_launcher, "_patching_thread", None)
        plugin_thread = getattr(self.game_launcher, "_plugin_hook_thread", None)
        if patching_thread:
            try:
                patching_thread.progress_update.disconnect()
                patching_thread.status_update.disconnect()
                patching_thread.finished.disconnect()
                if hasattr(patching_thread, "warning_confirmation_needed"):
                    patching_thread.warning_confirmation_needed.disconnect()
            except (TypeError, RuntimeError):
                pass
            patching_thread.cancel()
            if patching_thread.isRunning():
                if hasattr(patching_thread, "_warning_event"):
                    patching_thread._warning_event.set()
                patching_thread.wait(5000)
            try:
                if patching_thread.patcher:
                    if (
                        patching_thread.patcher.backup_service
                        and patching_thread.chapter_mods
                    ):
                        for chapter_id in patching_thread.chapter_mods:
                            patching_thread.patcher.backup_service.restore_backups(
                                chapter_id
                            )
                            logging.info(
                                f"[CANCEL] Restored backups for chapter {chapter_id}"
                            )
                    patching_thread.patcher.cleanup(force=True)
                if not patching_thread.isRunning():
                    patching_thread.deleteLater()
            except Exception as e:
                logging.error(
                    f"Error cleaning up cancelled patching thread: {e}", exc_info=True
                )
            finally:
                self.game_launcher._patching_thread = None
            runtime_service = getattr(self.app, "plugin_runtime_service", None)
            if runtime_service:
                with contextlib.suppress(Exception):
                    runtime_service.execute_hook(
                        "mod_apply_cancelled",
                        {"hook": "patching", "reason": "cancelled"},
                    )
        if plugin_thread:
            try:
                plugin_thread.progress_update.disconnect()
                plugin_thread.status_update.disconnect()
                plugin_thread.finished.disconnect()
            except (TypeError, RuntimeError):
                pass
            plugin_thread.cancel()
            if plugin_thread.isRunning():
                plugin_thread.wait(5000)
            with contextlib.suppress(Exception):
                if not plugin_thread.isRunning():
                    plugin_thread.deleteLater()
            self.game_launcher._plugin_hook_thread = None
        if is_modpack_creation and modpack_dir and os.path.exists(modpack_dir):
            try:
                import shutil

                shutil.rmtree(modpack_dir, ignore_errors=True)
                logging.info(
                    f"Cancelled modpack creation, removed directory: {modpack_dir}"
                )
            except Exception as e:
                logging.error(f"Failed to remove cancelled modpack directory: {e}")
            if library_display:
                library_display._modpack_thread = None
                library_display._modpack_dir = None
        self.app_state.is_patching = False
        self._reset_progress_bar()
        self.app_state.clear_current_task()
        self.app_state.action_button_text = None

    def _cancel_operation(self, operation_type: str):
        if operation_type == "install":
            logging.info(
                "GameLaunchController: Cancel button clicked during installation"
            )
            self.app_state.cancel_current_operation()
        elif operation_type == "patching":
            self._cancel_patching_operation()
        self.feedback_service.update_status(
            tr("status.operation_cancelled"), UI_COLORS["status_info"]
        )
        self._reset_progress_bar()
        self.update_button_state()

    def on_action_button_click(self):
        if getattr(self.app_state, "game_is_running", False):
            if hasattr(self.game_launcher, "close_game"):
                self.game_launcher.close_game()
            return
        if self.app_state.is_installing:
            self._cancel_operation("install")
            return
        patching_thread = getattr(self.game_launcher, "_patching_thread", None)
        if self.app_state.is_patching or (
            patching_thread and patching_thread.isRunning()
        ):
            self._cancel_operation("patching")
            return
        if self._is_full_install_enabled():
            self.perform_full_install()
            return
        if self.used_mods_service.check_used_mods_need_updates():
            self.update_mods_in_use()
            return
        if self.app_state.operation_cancelled:
            return
        if not self.app_state.is_patching:
            self.app_state.action_button_enabled = False
        self.app_state.progress_bar_visible = False
        self.launch_game()

    def launch_game(self):
        runtime_service = getattr(self.app, "plugin_runtime_service", None)
        if runtime_service and any(
            result is False for result in runtime_service.execute_hook("before_mod_apply")
        ):
            self.feedback_service.update_status(
                tr("plugins.launch_blocked"), UI_COLORS["status_warning"]
            )
            self.update_button_state()
            return
        self.game_launcher.launch_game_with_all_mods(
            restore_window_callback=self.app.restore_window_signal.emit,
        )

    @property
    def _dont_hide(self):
        return self.app_state.local_config.get("dont_hide_window_on_launch", False)

    def hide_window(self):
        with contextlib.suppress(Exception):
            self.customization_service.stop_background_music()
        self.settings_service.save_window_geometry(self.app)
        self.app_state.game_is_running = True
        self._window_hidden_for_launch = False
        if self._dont_hide:
            self.update_button_state()
            self.feedback_service.update_status(
                tr("status.game_launched_waiting_for_exit"), self._launch_status_color()
            )
        else:
            self._window_hidden_for_launch = True
            self.window_hide_requested.emit()

    def restore_window(self):
        self.app_state.game_is_running = False
        if self._window_hidden_for_launch:
            self.window_restore_requested.emit()
        self._window_hidden_for_launch = False
        self.app_state.progress_bar_visible = False
        self.update_button_state()
        self.update_geometry_requested.emit()
        self.library_display_update_requested.emit()
        self.search_display_update_requested.emit()
        self.customization_service.maybe_start_background_music()
        self.show_pending_dialogs_requested.emit()

    def perform_full_install(self):
        if self.app_state.is_installing or (
            self.app_state.current_task and self.app_state.current_task.isRunning()
        ):
            return
        self.app_state.action_button_enabled = False
        game_name = self.app_state.game_mode.display_label
        dlg = QDialog(cast(QWidget, self.app))
        dlg.setWindowTitle(tr("dialogs.full_install_game", game_name=game_name))
        folder_name = self.app_state.game_mode.display_name
        v = QVBoxLayout(dlg)
        lbl = QLabel(full_install_tooltip(self.app))
        lbl.setWordWrap(True)
        v.addWidget(lbl)
        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            self.app_state.action_button_enabled = True
            return
        base_dir = QFileDialog.getExistingDirectory(
            cast(QWidget, self.app),
            tr("dialogs.install_game_location", game_name=game_name),
        )
        if not base_dir:
            self.app_state.action_button_enabled = True
            return
        target_dir = os.path.join(base_dir, folder_name)
        try:
            os.makedirs(target_dir, exist_ok=True)
        except (OSError, PermissionError) as e:
            self.feedback_service.show_message(
                "error",
                "errors.error",
                format_filesystem_error(e, path=target_dir),
            )
            self.app_state.action_button_enabled = True
            return
        self.app_state.progress_bar_visible = True
        self.app_state.progress_bar_value = 0
        full_install_thread = FullInstallThread(cast(Any, self.app), target_dir)
        full_install_thread.progress.connect(
            lambda v: setattr(self.app_state, "progress_bar_value", v)
        )
        full_install_thread.status.connect(self.app.update_status_signal)
        full_install_thread.finished.connect(self.on_full_install_finished)
        self.app_state.current_task = full_install_thread
        full_install_thread.start()

    def on_full_install_finished(self, success, target_dir):
        self.app_state.clear_current_task()
        self._reset_progress_bar()
        self.app._set_checkbox_checked_silently(self.app.full_install_checkbox, False)
        self._full_install_checkbox_is_checked = False
        self.app_state.is_full_install = False
        if success:
            if self.app_state.game_mode.game_id == "deltarunedemo":
                self.app_state.demo_game_path = self.app_state.local_config[
                    "demo_game_path"
                ] = target_dir
            elif self.app_state.game_mode.supports_full_install:
                self.app_state.game_mode.set_game_path(
                    self.app_state.local_config, target_dir
                )
            else:
                self.app_state.game_path = self.app_state.local_config["game_path"] = (
                    target_dir
                )
            self.feedback_service.update_status(
                tr("status.game_files_install_complete"), UI_COLORS["status_success"]
            )
        else:
            self.feedback_service.update_status(
                tr("status.game_files_install_failed"), UI_COLORS["status_error"]
            )
        self.settings_service.write_local_config()
        self.update_button_state()

    def update_mods_in_use(self):
        mods_to_update = self.used_mods_service.collect_mods_needing_update()
        if mods_to_update:
            self.pending_updates_changed.emit(
                mods_to_update[1:] if len(mods_to_update) > 1 else []
            )
            self.app_state.operation_cancelled = False
            self.app_state.progress_bar_visible = True
            self.app_state.progress_bar_value = 0
            self.mod_service.update_mod(mods_to_update[0])

    def refresh_mods_in_use(self):
        if not self.app_state.all_mods:
            return
        all_mods_by_id = {get_mod_id(mod): mod for mod in self.app_state.all_mods if get_mod_id(mod)}
        for chapter_id, mods_list in list(self.used_mods_service.used_mods.items()):
            if not mods_list:
                continue
            refreshed_mods = []
            for mod_data in mods_list:
                key = get_mod_id(mod_data)
                if not key:
                    refreshed_mods.append(mod_data)
                    continue
                updated_mod = all_mods_by_id.get(key)
                if not updated_mod:
                    mod_config = self.mod_service.get_mod_config(key)
                    if mod_config:
                        updated_mod = self.mod_service.create_mod_object_from_info(
                            mod_config, self.app_state.all_mods
                        )
                refreshed_mods.append(updated_mod or mod_data)
            self.used_mods_service.used_mods[chapter_id] = refreshed_mods
