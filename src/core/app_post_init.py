"""Post-show initialization logic extracted from AppWindow."""

import logging
import os

from PyQt6.QtCore import QThread, pyqtSignal

from config.constants import CLOUD_FUNCTIONS_BASE_URL, ONLINE_UPDATE_INTERVAL, UI_COLORS
from services.game_detection_service import is_game_running
from services.localization_service import tr
from utils.network_utils import check_internet_connection, get_session


class _NetworkInitThread(QThread):
    """Checks internet connectivity and fetches global settings off the main thread."""

    done = pyqtSignal(bool, dict)

    def __init__(self, app_state, parent=None) -> None:
        super().__init__(parent)
        self._app_state = app_state

    def run(self):
        has_internet = check_internet_connection()
        global_settings = {}
        if has_internet:
            try:
                r = get_session(self._app_state).get(
                    f"{CLOUD_FUNCTIONS_BASE_URL}/getGlobalSettings", timeout=5
                )
                if r.status_code == 200:
                    global_settings = r.json() or {}
            except Exception:
                has_internet = False
        if not has_internet:
            logging.info("No internet connection detected, running in offline mode")
        self.done.emit(has_internet, global_settings)


def post_show_initialization(app):
    """Run post-show init: recover session, local init, then async network + presence start."""
    app.game_launcher.recover_previous_session()
    is_first_launch = not app.app_state.local_config.get(
        "first_launch_splash_shown", False
    )
    if is_first_launch and getattr(app, "_splash_was_shown", False):
        app.app_state.local_config["first_launch_splash_shown"] = True
        app.app_state.local_config["disable_splash"] = True
        app.settings_service.write_local_config()
    if not is_game_running():
        _finish_local_init(app)
    else:
        app.feedback_service.update_status(
            tr("status.deltarune_already_running"), UI_COLORS["status_error"]
        )
    app.app_state.has_internet = False
    app._network_init_thread = _NetworkInitThread(app.app_state, parent=app)

    def _on_network_done(has_internet, global_settings):
        app.app_state.has_internet = has_internet
        app.app_state.global_settings = global_settings
        if not has_internet:
            app.feedback_service.update_status(
                tr("status.global_settings_load_failed"), UI_COLORS["status_warning"]
            )
        else:
            app.app_state.pending_announce_check = True
            if (
                app.app_state.initialization_completed
                and not app.app_state.update_in_progress
            ):
                app._check_and_show_announce()
        app.presence_thread.start()
        app._online_timer.start(ONLINE_UPDATE_INTERVAL)
        from PyQt6.QtCore import QMetaObject, Qt

        QMetaObject.invokeMethod(
            app.presence_worker, "run", Qt.ConnectionType.QueuedConnection
        )

    app._network_init_thread.done.connect(_on_network_done)
    app._network_init_thread.finished.connect(app._network_init_thread.deleteLater)
    app._network_init_thread.start()


def _finish_local_init(app):
    """Local post-show work: config reload, UI restore, mod scan, game path."""
    app._load_local_data()
    app.app_state.game_path = app.app_state.local_config.get("game_path", "")
    app.app_state.demo_game_path = app.app_state.local_config.get("demo_game_path", "")
    app.app_state.undertale_game_path = app.app_state.local_config.get(
        "undertale_game_path", ""
    )
    _restore_ui_state_from_config(app)
    try:
        from workers.mod_scan_worker import ModScanThread

        for d in (
            app.app_state.config_dir,
            app.app_state.mods_dir,
            app.app_state.plugins_dir,
        ):
            os.makedirs(d, exist_ok=True)
        app._mod_scan_thread = ModScanThread(app.app_state.mods_dir, app)
        app._mod_scan_thread.scan_completed.connect(app._on_mod_scan_finished)
        app._mod_scan_thread.start()
        app.status_label.setText(tr("status.scanning_mods"))
    except Exception as e:
        logging.error(f"AppWindow: Failed to start mod scan thread: {e}", exc_info=True)
        app.feedback_service.update_status(
            tr("status.mod_scan_init_error", details=str(e)), UI_COLORS["status_error"]
        )
        try:
            app._on_mod_scan_finished({})
        except Exception as scan_error:
            logging.error(
                f"AppWindow: Failed to handle mod scan error: {scan_error}",
                exc_info=True,
            )
    if not app.game_launcher._find_and_validate_game_path(is_initial=True):
        app.action_button.setEnabled(False)


def _restore_ui_state_from_config(app):
    """Restore checkbox and combo states from local_config."""
    config = app.app_state.local_config
    saved_demo_mode = config.get("demo_mode_enabled", False)
    saved_chapter_mode = config.get("chapter_mode_enabled", False)
    if hasattr(app, "game_type_combo") and saved_demo_mode:
        app.game_type_combo.blockSignals(True)
        for i in range(app.game_type_combo.count()):
            if app.game_type_combo.itemData(i) == "deltarunedemo":
                app.game_type_combo.setCurrentIndex(i)
                break
        app.game_type_combo.blockSignals(False)
    if hasattr(app, "chapter_mode_checkbox"):
        app._set_checkbox_checked_silently(
            app.chapter_mode_checkbox, saved_chapter_mode
        )
    app._set_checkbox_checked_silently(
        app.disable_background_checkbox, config.get("background_disabled", False)
    )
    app._set_checkbox_checked_silently(
        app.disable_splash_checkbox, config.get("disable_splash", False)
    )
    app.beta_updates_checkbox.setChecked(config.get("beta_updates_enabled", False))
    app.fullscreen_checkbox.setChecked(config.get("fullscreen_enabled", False))
    if hasattr(app, "hide_library_filters_checkbox"):
        app.hide_library_filters_checkbox.setChecked(
            config.get("hide_library_filters", False)
        )
    app._update_change_path_button_text()
    app.theme.update_background_button_state()
    app.skip_patching_warnings_checkbox.setChecked(
        config.get("skip_patching_warnings", False)
    )
    app.launch_via_steam_checkbox.setChecked(config.get("launch_via_steam", False))
    app.dont_hide_window_checkbox.setChecked(
        config.get("dont_hide_window_on_launch", False)
    )
    if app.use_portproton_checkbox:
        app.use_portproton_checkbox.setChecked(config.get("use_portproton", False))
        app._update_portproton_ui()
    for key in ("merge_properties", "merge_code"):
        if w := getattr(app, f"{key}_checkbox", None):
            w.setChecked(config.get(key, False))
    app._initialize_mutual_exclusions()
    app.settings_ui.on_toggle_steam_launch()
    app.theme.apply_theme()
