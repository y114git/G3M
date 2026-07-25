"""Runtime wiring helpers for AppWindow.

These helpers keep AppWindow as the stable public facade while moving
initialization and signal-wiring details out of the main window class.
"""

from __future__ import annotations

import contextlib
import os

from PyQt6.QtWidgets import QApplication

from config.config import INITIALIZATION_TIMEOUT
from presentation.update_presenter import prompt_for_update
from services.localization_service import (
    add_application_font_from_file,
    localization_service,
)


def connect_initialization_signals(window) -> None:
    window.initialization_finished.connect(window.game_launch.update_button_state)
    window.initialization_finished.connect(window._try_start_background_music)
    window.initialization_finished.connect(window._maybe_show_onboarding)


def finalize_window_setup(window) -> None:
    window.init_ui()
    window.custom_font_family = localization_service.load_font()
    if (
        custom_font_path := window.customization_service.get_custom_font_path()
    ) and os.path.exists(custom_font_path):
        from PyQt6.QtGui import QFontDatabase

        font_id = add_application_font_from_file(custom_font_path)
        if font_id != -1 and (
            families := QFontDatabase.applicationFontFamilies(font_id)
        ):
            try:
                stat_result = os.stat(custom_font_path)
            except OSError:
                QFontDatabase.removeApplicationFont(font_id)
            else:
                window._custom_font_id = font_id
                window._custom_font_file_key = (
                    custom_font_path,
                    stat_result.st_mtime_ns,
                    stat_result.st_size,
                )
                window.custom_font_family = families[0]
        elif font_id != -1:
            QFontDatabase.removeApplicationFont(font_id)
    window.ui_ready.emit()
    connect_window_signals(window)
    window.initialization_timer.setSingleShot(True)
    window.initialization_timer.timeout.connect(window._force_finish_initialization)
    window.initialization_timer.start(INITIALIZATION_TIMEOUT)
    window.settings_service.load_window_geometry(window)
    app = QApplication.instance()
    if app:
        app.installEventFilter(window)
        with contextlib.suppress(Exception):
            app.applicationStateChanged.connect(window._on_application_state_changed)


def connect_window_signals(window) -> None:
    """Connect AppWindow-owned signals to their handlers."""

    window.update_status_signal.connect(window._update_status)
    window.hide_window_signal.connect(window.game_launch.hide_window)
    window.restore_window_signal.connect(window.game_launch.restore_window)
    window.set_progress_signal.connect(window._on_progress_update)
    window.show_update_prompt.connect(lambda info: prompt_for_update(window, info))
    window.mods_loaded_signal.connect(window._on_mods_loaded)
    window.url_received_signal.connect(window.handle_one_click_install)
    window.activate_requested_signal.connect(window.activate_from_single_instance)
    window.install_from_gb_signal.connect(
        lambda mod: window.mod_ops.install_mod(mod, force=True)
    )
    window.initialization_finished.connect(window._handle_pending_install)
    window.app_state.all_mods_updated.connect(
        lambda mods: setattr(window.app_state, "all_mods", mods)
    )
    window.app_state.gb_rate_limit_error.connect(window._on_gb_rate_limit_error)
