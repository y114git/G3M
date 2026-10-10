"""Controller for game launch operations and installation management."""

import contextlib
import logging
import os
import uuid
from collections.abc import Callable
from typing import Any, cast

from PyQt6.QtCore import QObject, QPoint, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from app.game_ui import full_install_tooltip
from config.config import UI_COLORS
from models.launch_modes import LaunchMode, get_launch_mode
from models.plugin_models import PluginLaunchAction, PluginLaunchOption
from services.game_detection_service import get_running_game_process_name
from services.localization_service import tr
from ui.common.styling import get_launch_status_color
from ui.dialogs.file_picker_dialog import GameBananaFilePickerDialog
from ui.utils.thread_lifetime import retire_qthread
from utils.mod.utils import get_mod_id
from utils.native_integration import get_existing_directory
from utils.process_utils import format_filesystem_error
from workers.install.full_install_worker import FullInstallThread

logger = logging.getLogger(__name__)


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
        self._external_process_status_visible = False
        self._external_process_missing_checks = 0
        self._external_game_timer = QTimer(self)
        self._external_game_timer.setInterval(250)
        self._external_game_timer.timeout.connect(self.refresh_external_game_process)
        self._external_game_timer.start()
        self._mod_update_worker = None
        self._mod_update_dialog = None
        self._mod_update_batch: dict[str, Any] | None = None
        self._deferred_mod_update_profile = ""
        self._automatic_update_profiles: list[str] | None = None
        self._automatic_update_restore_profile = ""
        self._automatic_update_switching = False
        profile_service = getattr(self.app, "profile_service", None)
        profile_switched = getattr(profile_service, "profile_switched", None)
        if profile_switched is not None:
            profile_switched.connect(self._on_profile_switched)
        self.used_mods_service.used_mods_updated.connect(
            lambda: QTimer.singleShot(0, self.refresh_mod_update_badge)
        )
        if hasattr(self.app_state, "external_game_process_name_changed"):
            self.app_state.external_game_process_name_changed.connect(
                lambda _name: self.update_button_state()
            )

    @property
    def launch_mode(self) -> LaunchMode:
        return get_launch_mode(self.app_state.local_config.get("launch_mode"))

    def _plugin_launch_actions(self) -> list[PluginLaunchAction]:
        runtime_service = getattr(self.app, "plugin_runtime_service", None)
        get_actions = getattr(runtime_service, "get_launch_actions", None)
        actions = get_actions() if callable(get_actions) else []
        return [
            action for action in actions if isinstance(action, PluginLaunchAction)
        ] if isinstance(actions, (list, tuple)) else []

    def _selected_plugin_launch_action(self) -> PluginLaunchAction | None:
        selected_id = str(self.app_state.local_config.get("launch_mode") or "")
        return next(
            (action for action in self._plugin_launch_actions() if action.id == selected_id),
            None,
        )

    def _plugin_launch_options(self) -> list[PluginLaunchOption]:
        runtime_service = getattr(self.app, "plugin_runtime_service", None)
        get_options = getattr(runtime_service, "get_launch_options", None)
        options = get_options() if callable(get_options) else []
        return (
            [option for option in options if isinstance(option, PluginLaunchOption)]
            if isinstance(options, (list, tuple))
            else []
        )

    def _selected_launch_id(self) -> str:
        selected_id = str(self.app_state.local_config.get("launch_mode") or "")
        if selected_id in {mode.value for mode in LaunchMode}:
            return selected_id
        action = self._selected_plugin_launch_action()
        return action.id if action is not None else LaunchMode.NORMAL.value

    def setup_launch_mode_menu(self, menu, button) -> None:
        """Populate the small selector that changes the primary launch action."""
        self._launch_mode_menu = menu
        self._launch_mode_button = button
        menu.aboutToShow.connect(self.refresh_launch_mode_menu)
        menu.aboutToShow.connect(
            lambda: QTimer.singleShot(0, self._position_launch_mode_menu)
        )
        self.refresh_launch_mode_menu()

    def _position_launch_mode_menu(self) -> None:
        """Center the selector over its primary action after Qt sizes it."""
        menu = getattr(self, "_launch_mode_menu", None)
        button = getattr(self, "_launch_mode_button", None)
        if menu is None or button is None:
            return
        size = menu.sizeHint()
        menu.move(
            button.mapToGlobal(
                QPoint((button.width() - size.width()) // 2, -size.height())
            )
        )

    def refresh_launch_mode_menu(self) -> None:
        menu = getattr(self, "_launch_mode_menu", None)
        if menu is None:
            return
        menu.clear()
        if self._add_launch_options(menu):
            menu.addSeparator()
        selected_id = self._selected_launch_id()
        for mode in LaunchMode:
            action = menu.addAction(tr(mode.label_key))
            action.setCheckable(True)
            action.setChecked(mode.value == selected_id)
            action.setToolTip(tr(mode.description_key))
            action.triggered.connect(
                lambda _checked=False, value=mode: self.set_launch_mode(value)
            )
        plugin_actions = self._plugin_launch_actions()
        if plugin_actions:
            menu.addSeparator()
        for plugin_action in plugin_actions:
            action = menu.addAction(plugin_action.label)
            action.setCheckable(True)
            action.setChecked(plugin_action.id == selected_id)
            action.setToolTip(plugin_action.description)
            action.triggered.connect(
                lambda _checked=False, value=plugin_action: self.set_plugin_launch_action(
                    value
                )
            )

    def _add_launch_options(self, menu) -> bool:
        added = False
        steam_checkbox = getattr(self.app, "launch_via_steam_checkbox", None)
        if steam_checkbox is not None:
            steam_action = menu.addAction(steam_checkbox.text() or tr("ui.steam_launch"))
            steam_action.setCheckable(True)
            steam_action.setChecked(steam_checkbox.isChecked())
            steam_action.setEnabled(steam_checkbox.isEnabled())
            steam_action.setToolTip(steam_checkbox.toolTip())
            steam_action.triggered.connect(self._set_steam_launch_from_menu)
            added = True
        for option in self._plugin_launch_options():
            action = menu.addAction(option.label)
            action.setCheckable(True)
            action.setChecked(option.checked)
            action.setEnabled(option.enabled)
            action.setToolTip(option.disabled_reason or option.description)
            action.triggered.connect(
                lambda checked=False, value=option: self.set_plugin_launch_option(
                    value, checked
                )
            )
            added = True
        return added

    def _set_steam_launch_from_menu(self, checked: bool) -> None:
        steam_checkbox = getattr(self.app, "launch_via_steam_checkbox", None)
        if steam_checkbox is None or not steam_checkbox.isEnabled():
            return
        steam_checkbox.setChecked(checked)
        self.refresh_launch_mode_menu()

    def set_plugin_launch_option(
        self, option: PluginLaunchOption, checked: bool
    ) -> None:
        runtime_service = getattr(self.app, "plugin_runtime_service", None)
        set_option = getattr(runtime_service, "set_launch_option", None)
        if callable(set_option):
            set_option(option, checked)
        self.refresh_launch_mode_menu()

    def set_launch_mode(self, mode: LaunchMode | str) -> None:
        selected = get_launch_mode(mode)
        self.app_state.local_config["launch_mode"] = selected.value
        self.settings_service.write_local_config()
        self.refresh_launch_mode_menu()
        self.update_button_state()

    def set_plugin_launch_action(self, action: PluginLaunchAction) -> None:
        self.app_state.local_config["launch_mode"] = action.id
        self.settings_service.write_local_config()
        self.refresh_launch_mode_menu()
        self.update_button_state()

    def _selected_launch_label(self) -> str:
        action = self._selected_plugin_launch_action()
        return action.label if action is not None else tr(self.launch_mode.label_key)

    def _set_launch_mode_selector_enabled(self, enabled: bool) -> None:
        menu = self.__dict__.get("_launch_mode_menu")
        if menu is not None:
            try:
                menu.setEnabled(enabled)
                return
            except RuntimeError:
                self.__dict__["_launch_mode_menu"] = None
        button = self.__dict__.get("_launch_mode_button")
        if button is not None:
            try:
                button.setEnabled(enabled)
            except RuntimeError:
                self.__dict__["_launch_mode_button"] = None

    def _confirm_selected_launch_mode(self) -> bool:
        plugin_action = self._selected_plugin_launch_action()
        if plugin_action is not None:
            if not plugin_action.requires_confirmation:
                return True
            ask = getattr(self.feedback_service, "ask_text_question", None)
            return bool(
                ask(
                    tr("launch_modes.confirm.title"),
                    plugin_action.description or plugin_action.label,
                    default_yes=False,
                )
                if callable(ask)
                else False
            )
        mode = self.launch_mode
        if not mode.needs_confirmation:
            return True
        ask = getattr(self.feedback_service, "ask_question", None)
        if not callable(ask):
            return False
        return bool(
            ask(
                "launch_modes.confirm.title",
                mode.description_key,
                default_yes=False,
            )
        )

    def set_external_game_process_name(self, process_name: str | None) -> None:
        self.app_state.external_game_process_name = process_name
        if not self._external_game_timer.isActive():
            self._external_game_timer.start()
        self.update_button_state()

    def refresh_external_game_process(self) -> None:
        if getattr(self.app_state, "game_is_running", False):
            return
        get_process_names: Callable[[], tuple[str, ...]] | None = getattr(
            self.app_state.game_mode, "get_process_names", None
        )
        process_names = get_process_names() if callable(get_process_names) else None
        current = get_running_game_process_name(process_names)
        previous = getattr(self.app_state, "external_game_process_name", "")
        if current:
            self._external_process_missing_checks = 0
            if current != previous:
                self.set_external_game_process_name(current)
        elif previous:
            self._external_process_missing_checks += 1
            if self._external_process_missing_checks >= 4:
                self._external_process_missing_checks = 0
                self._external_process_status_visible = True
                self.set_external_game_process_name(None)

    def _is_full_install_enabled(self) -> bool:
        return (
            self.app_state.game_mode.supports_full_install
            and self._full_install_checkbox_is_checked
        )

    def _launch_status_color(self) -> str:
        return get_launch_status_color(getattr(self.app_state, "local_config", None))

    def _safe_update_status(self, message: str, color: str) -> None:
        try:
            self.feedback_service.update_status(message, color)
        except Exception as e:
            logger.warning(
                "GameLaunchController: status update failed: %s",
                e,
                exc_info=True,
            )

    def _safe_show_message(self, level: str, title: str, message: str) -> None:
        try:
            self.feedback_service.show_message(level, title, message)
        except Exception as e:
            logger.warning(
                "GameLaunchController: feedback message failed: %s",
                e,
                exc_info=True,
            )

    def update_button_state(self):
        if getattr(self.game_launcher, "is_recovering_session", False) is True:
            self._set_launch_mode_selector_enabled(False)
            self.app_state.action_button_text = tr("status.please_wait")
            self.app_state.action_button_enabled = False
            return
        if getattr(self.app_state, "game_is_running", False):
            self._set_launch_mode_selector_enabled(False)
            self.app_state.action_button_text = tr("ui.close_game")
            self.app_state.action_button_enabled = True
            return
        if (
            self.app_state.is_installing and (not self.app_state.operation_cancelled)
        ) or self.app_state.is_patching:
            self._set_launch_mode_selector_enabled(False)
            self.app_state.action_button_text = tr("ui.cancel_button")
            self.app_state.action_button_enabled = True
            return
        if not self.app_state.initialization_completed:
            self._set_launch_mode_selector_enabled(False)
            self.app_state.action_button_text = tr("status.please_wait")
            self.app_state.action_button_enabled = False
            return
        external_process = getattr(self.app_state, "external_game_process_name", "")
        if external_process:
            self._set_launch_mode_selector_enabled(False)
            self.app_state.action_button_text = self._selected_launch_label()
            self.app_state.action_button_enabled = False
            self._safe_update_status(
                tr(
                    "status.close_current_process_to_launch",
                    process_name=external_process,
                ),
                UI_COLORS["status_warning"],
            )
            self._external_process_status_visible = True
            return
        action_text = (
            tr("buttons.install")
            if self._is_full_install_enabled()
            else tr("ui.update_button")
            if self.used_mods_service.check_used_mods_need_updates()
            else self._selected_launch_label()
        )
        self.app_state.action_button_text = action_text
        self.app_state.action_button_enabled = True
        self._set_launch_mode_selector_enabled(not self._is_full_install_enabled())
        if self._external_process_status_visible:
            self._external_process_status_visible = False
            self._safe_update_status(tr("status.ready"), UI_COLORS["status_info"])

    def _reset_progress_bar(self):
        try:
            self.app_state.progress_bar_value = 0
            self.app_state.progress_bar_visible = False
        except (AttributeError, RuntimeError) as error:
            logger.debug("Best-effort operation failed: %s", error, exc_info=True)

    def _cancel_patching_operation(self):
        library_display = getattr(self.app, "library_display", None)
        is_modpack_creation = (
            library_display
            and hasattr(library_display, "_modpack_thread")
            and (library_display._modpack_thread == self.app_state.current_task)
        )
        patching_thread = getattr(self.game_launcher, "_patching_thread", None)
        plugin_thread = getattr(self.game_launcher, "_plugin_hook_thread", None)
        dependency_thread = getattr(
            self.game_launcher, "_dependency_resolution_thread", None
        )
        if patching_thread:
            patching_thread.cancel()
            self.app_state.action_button_enabled = False
        elif plugin_thread:
            plugin_thread.cancel()
            self.app_state.action_button_enabled = False
        elif dependency_thread:
            dependency_thread.cancel()
            self.game_launcher.cancel_pending_launch()
        elif is_modpack_creation:
            self.app_state.current_task.cancel()
            self.app_state.action_button_enabled = False
        else:
            self.game_launcher.cancel_pending_launch()
        self._safe_update_status(
            tr("status.operation_cancelled"), UI_COLORS["status_info"]
        )

    def _cancel_operation(self, operation_type: str):
        if operation_type == "install":
            logger.info(
                "GameLaunchController: Cancel button clicked during installation"
            )
            self.app_state.cancel_current_operation()
        elif operation_type == "patching":
            self._cancel_patching_operation()
            return
        self._safe_update_status(
            tr("status.operation_cancelled"), UI_COLORS["status_info"]
        )
        self._reset_progress_bar()
        self.update_button_state()

    def on_action_button_click(self):
        if getattr(self.game_launcher, "is_recovering_session", False) is True:
            return
        self.refresh_external_game_process()
        external_process = getattr(self.app_state, "external_game_process_name", "")
        if external_process and not getattr(self.app_state, "game_is_running", False):
            self.update_button_state()
            return
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
        plugin_action = self._selected_plugin_launch_action()
        if plugin_action is not None:
            if not self._confirm_selected_launch_mode():
                self.update_button_state()
                return
            self.app_state.operation_cancelled = False
            self.app_state.action_button_enabled = False
            if not self.game_launcher.run_plugin_launch_action(plugin_action):
                self._safe_update_status(
                    tr("plugins.launch_blocked"), UI_COLORS["status_warning"]
                )
                self.update_button_state()
            return
        if not self._confirm_selected_launch_mode():
            self.update_button_state()
            return
        self.app_state.operation_cancelled = False
        if not self.app_state.is_patching:
            self.app_state.action_button_enabled = False
        self.app_state.progress_bar_visible = False
        self.launch_game(self.launch_mode)

    def launch_game(self, mode: LaunchMode = LaunchMode.NORMAL):
        self.game_launcher.launch_game_with_all_mods(
            restore_window_callback=self.app.restore_window_signal.emit,
            mode=mode,
        )

    def hide_window(self):
        with contextlib.suppress(Exception):
            self.customization_service.stop_background_music()
        self.settings_service.save_window_geometry(self.app)
        self.app_state.game_is_running = True
        self._window_hidden_for_launch = False
        if self.app_state.local_config.get("dont_hide_window_on_launch", False):
            self.update_button_state()
            self._safe_update_status(
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
        if not self.app_state.is_patching:
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
        base_dir = get_existing_directory(
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
            self._safe_show_message(
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
        full_install_thread.result_ready.connect(self.on_full_install_finished)
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
            self._safe_update_status(
                tr("status.game_files_install_complete"), UI_COLORS["status_success"]
            )
        else:
            self._safe_update_status(
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

    def open_mod_updates(self) -> None:
        """Show the profile-scoped GameBanana updater without blocking the library."""
        if self._mod_update_dialog is None:
            from ui.dialogs.mod.updates_dialog import ModUpdatesDialog

            self._mod_update_dialog = ModUpdatesDialog(
                self.app_state,
                self.app.profile_service.list_profiles(),
                self.app.profile_service.active_name,
                self.app,
            )
            self._mod_update_dialog.profile_changed.connect(
                self._on_mod_update_profile_changed
            )
            self._mod_update_dialog.updates_requested.connect(self._start_mod_updates)
            self._mod_update_dialog.destroyed.connect(
                lambda: setattr(self, "_mod_update_dialog", None)
            )
        self._mod_update_dialog.show()
        self._mod_update_dialog.raise_()
        self._mod_update_dialog.activateWindow()
        self._scan_mod_updates()

    def refresh_mod_update_badge(self) -> None:
        button = getattr(self.app, "update_mods_button", None)
        if button is None:
            return
        automatic = bool(self.app_state.local_config.get("automatic_mod_updates"))
        button.setVisible(False)
        if automatic:
            self._start_automatic_mod_updates()
        else:
            button.setText(tr("mod_updates.button", count=0))
            self._scan_mod_updates()

    def _start_automatic_mod_updates(self) -> None:
        if (
            self._automatic_update_profiles is not None
            or self._mod_update_batch is not None
            or (self._mod_update_worker is not None and self._mod_update_worker.isRunning())
            or getattr(self.app_state, "is_installing", False)
            or getattr(self.app_state, "is_patching", False)
            or getattr(self.app_state, "game_is_running", False)
        ):
            return
        active_profile = self.app.profile_service.active_name
        scope = self.app_state.local_config.get("automatic_mod_updates_scope", "profile")
        self._automatic_update_profiles = (
            self.app.profile_service.list_profiles()
            if scope == "all_profiles"
            else [active_profile]
        )
        self._automatic_update_restore_profile = active_profile
        self._advance_automatic_mod_updates()

    def _advance_automatic_mod_updates(self) -> None:
        profiles = self._automatic_update_profiles
        if profiles is None:
            return
        if not self.app_state.local_config.get("automatic_mod_updates") or not profiles:
            restore_profile = self._automatic_update_restore_profile
            self._automatic_update_profiles = None
            self._automatic_update_restore_profile = ""
            if restore_profile and restore_profile != self.app.profile_service.active_name:
                self._switch_automatic_update_profile(restore_profile)
            return
        profile = profiles.pop(0)
        if profile != self.app.profile_service.active_name:
            self._switch_automatic_update_profile(profile)
        QTimer.singleShot(0, self._scan_mod_updates)

    def _switch_automatic_update_profile(self, profile_name: str) -> None:
        self._automatic_update_switching = True
        try:
            self.app.profile_service.switch(profile_name)
        finally:
            self._automatic_update_switching = False

    def _on_profile_switched(self, _profile_name: str) -> None:
        worker = getattr(self, "_mod_update_worker", None)
        if worker is not None:
            worker.cancel()
            self._mod_update_worker = None
        if (
            self._automatic_update_profiles is not None
            and not getattr(self, "_automatic_update_switching", False)
        ):
            self._automatic_update_profiles = None
            self._automatic_update_restore_profile = ""

    def _on_mod_update_profile_changed(self, profile_name: str) -> None:
        if self._mod_update_batch is not None:
            self._deferred_mod_update_profile = profile_name
            return
        worker = self._mod_update_worker
        if worker is not None and worker.isRunning():
            worker.cancel()
            self._mod_update_worker = None
        if profile_name != self.app.profile_service.active_name:
            self.app.profile_service.switch(profile_name)
        QTimer.singleShot(0, self._scan_mod_updates)

    def _collect_gamebanana_update_candidates(self) -> list[dict[str, Any]]:
        metadata = self.mod_service._read_metadata()
        candidates: list[dict[str, Any]] = []
        seen: set[str] = set()
        for mod_info in self.mod_service.get_installed_mods_list():
            if not isinstance(mod_info, dict):
                continue
            mod_id = mod_info.get("id")
            if (
                not isinstance(mod_id, str)
                or mod_id in seen
                or not mod_id.startswith(("gb_mod_", "gb_wip_"))
            ):
                continue
            mod = self.mod_service.create_mod_object_from_info(
                mod_info, self.app_state.all_mods
            )
            if mod is None:
                continue
            seen.add(mod_id)
            stored = metadata.get(mod_id, {}) if isinstance(metadata, dict) else {}
            stored = stored if isinstance(stored, dict) else {}
            candidate = {
                "id": mod_id,
                "name": str(getattr(mod, "name", mod_id)),
                "game": str(getattr(mod, "game", "deltarune")),
                "version": str(getattr(mod, "version", "")),
                "file_id": stored.get("gamebanana_file_id"),
                "mod": mod,
                "mod_folder": self.mod_service.get_mod_folder_path(mod_id),
                "target_mods_dir": str(
                    getattr(self.app_state, "mods_dir", "") or ""
                ),
            }
            if stored.get("gamebanana_file_timestamp") is not None:
                candidate["file_timestamp"] = stored["gamebanana_file_timestamp"]
            candidates.append(candidate)
        return candidates

    def _scan_mod_updates(self, *, preserve_outcome: bool = False) -> None:
        if self._mod_update_worker is not None and self._mod_update_worker.isRunning():
            return
        dialog = self._mod_update_dialog
        if dialog is not None:
            dialog.set_checking(preserve_outcome=preserve_outcome)
        from workers.gamebanana.update_worker import ResolveGameBananaUpdatesThread

        worker = ResolveGameBananaUpdatesThread(
            self._collect_gamebanana_update_candidates(), self
        )
        self._mod_update_worker = worker
        worker.result_ready.connect(
            lambda updates, source=worker: self._on_mod_updates_resolved(source, updates)
        )
        worker.finished.connect(lambda source=worker: retire_qthread(source))
        worker.start()

    def _on_mod_updates_resolved(self, worker, updates: list[dict[str, Any]]) -> None:
        if worker is not self._mod_update_worker:
            return
        self._mod_update_worker = None
        button = getattr(self.app, "update_mods_button", None)
        hidden = bool(self.app_state.local_config.get("hide_update_mods_button"))
        if button is not None:
            button.setVisible(not hidden and bool(updates))
            button.setText(tr("mod_updates.button", count=len(updates)))
        if self._mod_update_dialog is not None:
            self._mod_update_dialog.set_candidates(updates)
        if self._automatic_update_profiles is not None:
            if self.app_state.local_config.get("automatic_mod_updates_scope") == "game":
                game_id = getattr(self.app_state.game_mode, "game_id", "")
                updates = [item for item in updates if item.get("game") == game_id]
            updates = [
                item
                for item in updates
                if len(item.get("resolutions", ())) <= 1
            ]
            if updates:
                self._start_mod_updates(
                    updates,
                    bool(
                        self.app_state.local_config.get(
                            "automatic_mod_updates_replace_current", False
                        )
                    ),
                )
            else:
                self._advance_automatic_mod_updates()

    def _start_mod_updates(
        self, candidates: list[dict[str, Any]], replace_current: bool
    ) -> None:
        if self._mod_update_batch is not None or not candidates:
            return
        selected_candidates = []
        for candidate in candidates:
            resolutions = candidate.get("resolutions")
            if isinstance(resolutions, list) and len(resolutions) > 1:
                resolved = self._pick_mod_update_resolution(candidate, resolutions)
                if resolved is None:
                    continue
                selected_candidates.append({**candidate, "resolved": resolved})
            else:
                selected_candidates.append(candidate)
        if not selected_candidates:
            return
        self._mod_update_batch = {
            "id": uuid.uuid4().hex,
            "pending": selected_candidates,
            "total": len(selected_candidates),
            "completed": 0,
            "replace_current": replace_current,
            "failed": [],
            "manual": [],
            "record_id": None,
        }
        if self._mod_update_dialog is not None:
            self._mod_update_dialog.set_busy(True)
            self._mod_update_dialog.set_progress(0, len(selected_candidates))
        self.app.downloads_manager.record_updated.connect(self._on_mod_update_record)
        self._start_next_mod_update()

    def _start_next_mod_update(self) -> None:
        batch = self._mod_update_batch
        if batch is None:
            return
        pending = batch["pending"]
        if not pending:
            self._finish_mod_updates()
            return
        candidate = pending.pop(0)
        mod = candidate.get("mod")
        resolved = candidate.get("resolved")
        try:
            record_id = (
                self.app.mod_ops.enqueue_resolved_gamebanana_update(
                    mod,
                    resolved,
                    replace_current=bool(batch["replace_current"]),
                    batch_id=batch["id"],
                    mod_folder=candidate.get("mod_folder"),
                    target_mods_dir=candidate.get("target_mods_dir"),
                )
                if mod is not None and isinstance(resolved, dict)
                else None
            )
        except Exception:
            logger.exception("Could not queue GameBanana update for %s", candidate.get("id"))
            record_id = None
        if not record_id:
            batch["failed"].append(str(candidate.get("name") or candidate.get("id")))
            batch["completed"] += 1
            QTimer.singleShot(0, self._start_next_mod_update)
            return
        batch["record_id"] = record_id
        if self._mod_update_dialog is not None:
            self._mod_update_dialog.set_progress(
                batch["completed"], batch["total"], str(candidate.get("name") or "")
            )

    def _pick_mod_update_resolution(
        self, candidate: dict[str, Any], resolutions: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        files = []
        for resolution in resolutions:
            metadata = resolution.get("metadata")
            source_url = resolution.get("source_url")
            if isinstance(metadata, dict) and isinstance(source_url, str):
                files.append({**metadata, "download_url": source_url})
        if len(files) < 2:
            return resolutions[0] if resolutions else None
        dialog = GameBananaFilePickerDialog(
            self.app,
            files,
            str(candidate.get("name") or candidate.get("id") or ""),
            str(files[0].get("homepage") or "") or None,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        selected = dialog.get_selected_file()
        selected_file_id = selected.get("gb_file_id") if isinstance(selected, dict) else None
        return next(
            (
                resolution
                for resolution in resolutions
                if isinstance(resolution.get("metadata"), dict)
                and resolution["metadata"].get("gb_file_id") == selected_file_id
            ),
            None,
        )

    def _on_mod_update_record(self, record) -> None:
        batch = self._mod_update_batch
        if batch is None or getattr(record, "id", None) != batch["record_id"]:
            return
        metadata = getattr(record, "metadata", {})
        if not isinstance(metadata, dict) or metadata.get("update_batch_id") != batch["id"]:
            return
        status = str(getattr(record, "use_status", ""))
        if status == "ready_to_use" and getattr(record, "ever_installed", False):
            batch["completed"] += 1
            batch["record_id"] = None
            QTimer.singleShot(0, self._start_next_mod_update)
        elif status == "needs_manual_install":
            batch["manual"].append(str(getattr(record, "display_name", "-")))
            batch["completed"] += 1
            batch["record_id"] = None
            QTimer.singleShot(0, self._start_next_mod_update)
        elif status in {"failed", "cancelled"}:
            batch["failed"].append(str(getattr(record, "display_name", "-")))
            batch["completed"] += 1
            batch["record_id"] = None
            QTimer.singleShot(0, self._start_next_mod_update)

    def _finish_mod_updates(self) -> None:
        batch = self._mod_update_batch
        if batch is None:
            return
        with contextlib.suppress(TypeError, RuntimeError):
            self.app.downloads_manager.record_updated.disconnect(self._on_mod_update_record)
        self._mod_update_batch = None
        if self._mod_update_dialog is not None:
            self._mod_update_dialog.set_busy(False)
            outcomes = []
            if batch["failed"]:
                outcomes.append(("mod_updates.failed", {"names": ", ".join(batch["failed"])}))
            if batch["manual"]:
                outcomes.append(
                    ("mod_updates.manual_required", {"names": ", ".join(batch["manual"])})
                )
            if outcomes:
                self._mod_update_dialog.set_outcome_messages(outcomes)
            else:
                self._mod_update_dialog.set_progress(batch["total"], batch["total"])
        self.mod_service.invalidate_mods_cache()
        self.mod_service.load_local_mods()
        self.mod_service.mod_list_updated.emit()
        self.refresh_mods_in_use()
        deferred_profile = self._deferred_mod_update_profile
        self._deferred_mod_update_profile = ""
        if deferred_profile:
            if deferred_profile != self.app.profile_service.active_name:
                self.app.profile_service.switch(deferred_profile)
            QTimer.singleShot(
                0,
                lambda: self._scan_mod_updates(
                    preserve_outcome=bool(batch["failed"] or batch["manual"])
                ),
            )
            return
        if self._automatic_update_profiles is not None:
            QTimer.singleShot(0, self._advance_automatic_mod_updates)
        else:
            self._scan_mod_updates(preserve_outcome=bool(batch["failed"] or batch["manual"]))

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
