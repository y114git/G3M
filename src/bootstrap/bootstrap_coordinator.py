from __future__ import annotations

import logging
import os
import sys

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication, QMessageBox

from app.game_ui import (
    update_change_path_button_text,
    update_portproton_ui,
    update_steam_launch_checkbox_state,
)
from config.config import (
    CLOUD_FUNCTIONS_BASE_URL,
    SINGLE_INSTANCE_KEY,
    SPLASH_WATCHDOG_TIMEOUT,
    UI_COLORS,
)
from presentation.update_presenter import check_and_show_announce
from services.game_detection_service import is_game_running
from services.localization_service import tr
from ui.splash import create_png_splash
from ui.utils.audio_utils import _audio_service
from utils.network_utils import (
    check_internet_connection,
    cloud_function_request,
    get_session,
)


class _NetworkInitThread(QThread):
    done = pyqtSignal(bool, dict)

    def __init__(self, app_state, parent=None) -> None:
        super().__init__(parent)
        self._app_state = app_state

    def run(self) -> None:
        has_internet = check_internet_connection()
        global_settings = {}
        if has_internet:
            try:
                response = cloud_function_request(
                    "get",
                    f"{CLOUD_FUNCTIONS_BASE_URL}/getGlobalSettings",
                    session=get_session(self._app_state),
                    timeout=5,
                )
                if response and response.status_code == 200:
                    global_settings = response.json() or {}
            except Exception as error:
                logging.debug(f"Failed to fetch global settings: {error}")
        if not has_internet:
            logging.info("No internet connection detected, running in offline mode")
        self.done.emit(has_internet, global_settings)


class BootstrapCoordinator:
    _WINDOW_REVEAL_DELAY_MS = 50

    def __init__(
        self,
        app,
        user_root: str,
        initial_url: str | None,
        window_factory,
        server_factory,
    ) -> None:
        self.app = app
        self.user_root = user_root
        self.initial_url = initial_url
        self.window_factory = window_factory
        self.server_factory = server_factory
        self.instance = None
        self.splash = None
        self.window_shown = False
        self.init_ready = False
        self._network_started = False

    def launch(self) -> None:
        config_dir = os.path.join(self.user_root, "settings")
        self.splash = create_png_splash(config_dir)
        self.splash.show()
        self.app.processEvents()
        QTimer.singleShot(SPLASH_WATCHDOG_TIMEOUT, self._watchdog_callback)
        self._create_launcher()

    def _create_launcher(self) -> None:
        try:
            self.instance = self.window_factory(
                parent_for_dialogs=self.splash, initial_url=self.initial_url
            )
            server = self.server_factory(self.instance)
            if not server.listen(SINGLE_INSTANCE_KEY):
                error_msg = tr("errors.single_instance_error")
                logging.error(f"STARTUP ERROR: {error_msg}")
                QMessageBox.critical(None, tr("errors.error"), error_msg)
                sys.exit(1)
            self.instance.server = server
            self.instance.initialization_finished.connect(
                self._on_initialization_finished
            )
            if getattr(self.instance.app_state, "initialization_completed", False):
                self._on_initialization_finished()
            self._start_network_initialization()
            QTimer.singleShot(0, self._fallback_show_window)
        except Exception as error:
            self.splash.close()
            error_msg = tr("errors.startup_error_message", details=str(error))
            logging.exception(f"STARTUP ERROR: {error_msg}")
            QMessageBox.critical(None, tr("errors.startup_error_title"), error_msg)
            sys.exit(1)

    def _finalize_window_display(self) -> None:
        self.window_shown = True
        self._close_splash_and_show_launcher()

    def _on_initialization_finished(self) -> None:
        if self.window_shown:
            return
        self.init_ready = True
        self._finalize_window_display()

    def _fallback_show_window(self) -> None:
        if self.window_shown or self.init_ready:
            return
        logging.info("Showing window before initialization finishes")
        self._finalize_window_display()

    def _watchdog_callback(self) -> None:
        if self.window_shown or not self.instance:
            return
        try:
            if not self.instance.isVisible():
                logging.warning("Startup timed out, forcing main window display")
                self._finalize_window_display()
        except Exception as error:
            logging.error(f"Watchdog callback error: {error}", exc_info=True)

    def _show_launcher_window(self) -> None:
        if not self.instance:
            return
        if getattr(self.instance, "app_state", None) and getattr(
            self.instance.app_state, "game_is_running", False
        ):
            return
        try:
            self.restore_ui_state_from_config(self.instance)
            self.instance.setWindowState(
                self.instance.windowState() & ~Qt.WindowState.WindowMinimized
            )
            self.instance.show()
            self._play_startup_sound()
            self._bring_launcher_to_front()
            self.instance.is_shown_to_user = True
            self.instance.app_state.is_shown_to_user = True
            if qapp := QApplication.instance():
                qapp.processEvents()
            QTimer.singleShot(
                self._WINDOW_REVEAL_DELAY_MS, self.instance._post_show_initialization
            )
            QTimer.singleShot(
                self._WINDOW_REVEAL_DELAY_MS, self._bring_launcher_to_front
            )
        except Exception as error:
            logging.error(f"Error showing launcher window: {error}", exc_info=True)

    def _bring_launcher_to_front(self) -> None:
        if not self.instance:
            return
        try:
            self.instance.raise_()
            self.instance.activateWindow()
        except Exception as error:
            logging.debug(f"Failed to bring launcher to front: {error}")

    def _close_splash(self) -> None:
        self.splash.close()

    def _close_splash_and_show_launcher(self) -> None:
        self._show_launcher_window()
        QTimer.singleShot(self._WINDOW_REVEAL_DELAY_MS, self._finalize_window_reveal)

    def _finalize_window_reveal(self) -> None:
        self._close_splash()
        self._bring_launcher_to_front()

    def _play_startup_sound(self) -> None:
        if getattr(self.instance, "app_state", None) and not self.instance.app_state.local_config.get(
            "disable_startup_sound", False
        ):
            _audio_service.play_deltahub_sound()

    @staticmethod
    def post_show_initialization(window) -> None:
        window.game_launcher.recover_previous_session()
        if not is_game_running():
            BootstrapCoordinator._finish_local_init(window)
        else:
            window.feedback_service.update_status(
                tr("status.deltarune_already_running"), UI_COLORS["status_error"]
            )

    def _start_network_initialization(self) -> None:
        if self._network_started or not self.instance:
            return
        self._network_started = True
        self.instance.app_state.has_internet = False
        self.instance._network_init_thread = _NetworkInitThread(
            self.instance.app_state,
            parent=self.instance,
        )

        def _on_network_done(has_internet: bool, global_settings: dict) -> None:
            window = self.instance
            if window is None:
                return
            window.app_state.has_internet = has_internet
            window.app_state.global_settings = global_settings
            if not has_internet and self.window_shown:
                window.feedback_service.update_status(
                    tr("status.global_settings_load_failed"),
                    UI_COLORS["status_warning"],
                )
            elif has_internet:
                window.app_state.pending_announce_check = True
                if (
                    window.app_state.initialization_completed
                    and not window.app_state.update_in_progress
                ):
                    check_and_show_announce(window)
            window.session_manager.start()

        self.instance._network_init_thread.done.connect(_on_network_done)
        self.instance._network_init_thread.finished.connect(
            self.instance._network_init_thread.deleteLater
        )
        self.instance._network_init_thread.start()

    @staticmethod
    def _finish_local_init(window) -> None:
        window._load_local_data()
        window.app_state.game_path = window.app_state.local_config.get("game_path", "")
        window.app_state.demo_game_path = window.app_state.local_config.get(
            "demo_game_path", ""
        )
        window.app_state.undertale_game_path = window.app_state.local_config.get(
            "undertale_game_path", ""
        )
        try:
            from workers.mod_scan_worker import ModScanThread

            for path in (
                window.app_state.config_dir,
                window.app_state.mods_dir,
            ):
                os.makedirs(path, exist_ok=True)
            window._mod_scan_thread = ModScanThread(window.app_state.mods_dir, window)
            window._mod_scan_thread.scan_completed.connect(window._on_mod_scan_finished)
            window._mod_scan_thread.start()
            window.status_label.setText(tr("status.scanning_mods"))
        except Exception as error:
            logging.error(
                f"AppWindow: Failed to start mod scan thread: {error}", exc_info=True
            )
            window.feedback_service.update_status(
                tr("status.mod_scan_init_error", details=str(error)),
                UI_COLORS["status_error"],
            )
            window._on_mod_scan_finished({})
        if not window.game_launcher._find_and_validate_game_path(is_initial=True):
            window.action_button.setEnabled(False)

    @staticmethod
    def restore_ui_state_from_config(window) -> None:
        config = window.app_state.local_config
        saved_demo_mode = config.get("demo_mode_enabled", False)
        saved_chapter_mode = config.get("chapter_mode_enabled", False)
        if hasattr(window, "game_type_combo") and saved_demo_mode:
            window.game_type_combo.blockSignals(True)
            for index in range(window.game_type_combo.count()):
                if window.game_type_combo.itemData(index) == "deltarunedemo":
                    window.game_type_combo.setCurrentIndex(index)
                    break
            window.game_type_combo.blockSignals(False)
        if hasattr(window, "chapter_mode_checkbox"):
            window._set_checkbox_checked_silently(
                window.chapter_mode_checkbox, saved_chapter_mode
            )
        window._set_checkbox_checked_silently(
            window.disable_background_checkbox,
            config.get("background_disabled", False),
        )
        window._set_checkbox_checked_silently(
            window.beta_updates_checkbox, config.get("beta_updates_enabled", False)
        )
        window._set_checkbox_checked_silently(
            window.fullscreen_checkbox, config.get("fullscreen_enabled", False)
        )
        if hasattr(window, "hide_library_filters_checkbox"):
            window.hide_library_filters_checkbox.setChecked(
                config.get("hide_library_filters", False)
            )
        update_change_path_button_text(window)
        window.theme.update_background_button_state()
        window.skip_patching_warnings_checkbox.setChecked(
            config.get("skip_patching_warnings", False)
        )
        window.launch_via_steam_checkbox.setChecked(
            config.get("launch_via_steam", False)
        )
        window.dont_hide_window_checkbox.setChecked(
            config.get("dont_hide_window_on_launch", False)
        )
        if window.use_portproton_checkbox:
            window.use_portproton_checkbox.setChecked(
                config.get("use_portproton", False)
            )
            update_portproton_ui(window)
        for key in ("merge_properties", "merge_code"):
            if widget := getattr(window, f"{key}_checkbox", None):
                widget.setChecked(config.get(key, False))
        update_steam_launch_checkbox_state(window)
        window.settings_ui.on_toggle_steam_launch()
        window.theme.apply_theme()
