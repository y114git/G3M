"""Startup and initialization helpers for AppWindow."""

import logging

from app.game_ui import show_chapter_mode_instruction
from app.localization_utils import relocalize_ui
from bootstrap.bootstrap_coordinator import BootstrapCoordinator
from config.config import UI_COLORS
from presentation.update_presenter import check_and_show_announce
from services.localization_service import tr


def handle_pending_install(window) -> None:
    if window.context.pending_install_url:
        window.handle_one_click_install(window.context.pending_install_url)
        window.context.pending_install_url = None


def finish_initialization(window) -> None:
    window.app_state.initialization_completed = True
    window.initialization_finished.emit()
    if (
        hasattr(window.app_state, "pending_announce_check")
        and window.app_state.pending_announce_check
        and (not window.app_state.update_in_progress)
    ):
        check_and_show_announce(window)


def on_mods_loaded(window) -> None:
    if window.initialization_timer and window.initialization_timer.isActive():
        window.initialization_timer.stop()
    finish_initialization(window)


def force_finish_initialization(window) -> None:
    if window.app_state.initialization_completed:
        return
    window.app_state.mods_loaded = True
    finish_initialization(window)


def post_show_initialization(window) -> None:
    if hasattr(window, "_post_show_initialized") and window._post_show_initialized:
        return
    window._post_show_initialized = True
    BootstrapCoordinator.post_show_initialization(window)


def update_installed_mods_display(window, *, set_library_initialized=False):
    is_chapter_mode = window.app_state.current_mode == "chapter"
    selected_id = window.app_state.selected_chapter_id
    if is_chapter_mode and selected_id is None:
        show_chapter_mode_instruction(window)
    else:
        window.library_display.update_display()
        if set_library_initialized:
            window.app_state.library_initialized = True


def trigger_initial_mods_refresh(window, *, saved_chapter_mode=False) -> None:
    try:

        def update_filtered_mods_callback():
            try:
                if hasattr(window, "search_display"):
                    window.search_display.update_filtered_mods(preserve_page=False)
            except Exception as e:
                logging.error(
                    f"AppWindow: Error building mods list: {e}", exc_info=True
                )

        on_fetch_finished_kwargs = {
            "update_filtered_mods_callback": update_filtered_mods_callback,
            "update_installed_mods_callback": lambda: (
                update_installed_mods_display(
                    window,
                    set_library_initialized=not saved_chapter_mode,
                )
            ),
            "update_action_button_callback": lambda: (
                window.game_launch.update_button_state()
            ),
            "mods_loaded_signal": window.mods_loaded_signal,
        }
        window.refresh_controller.refresh_mods_list(
            is_initial=True,
            language_combo=window.language_combo,
            localization_callback=lambda: relocalize_ui(window),
            on_fetch_finished_kwargs=on_fetch_finished_kwargs,
        )
        try:
            if (
                hasattr(window, "search_display")
                and hasattr(window.app_state, "all_mods")
                and window.app_state.all_mods
            ):
                window.search_display.update_filtered_mods(preserve_page=False)
        except Exception as e:
            logging.error(
                f"AppWindow: Error building initial mods list: {e}", exc_info=True
            )
    except Exception as e:
        logging.error(
            f"AppWindow: Error in _load_mods_and_build_list_synchronously: {e}",
            exc_info=True,
        )


def on_mod_scan_finished(window, scan_cache: dict) -> None:
    try:
        if hasattr(window.mod_service, "_mods_cache") and hasattr(
            window.mod_service, "_cache_lock"
        ):
            with window.mod_service._cache_lock:
                window.mod_service._mods_cache = scan_cache
                window.mod_service._mods_cache_valid = True
        window.mod_service.load_local_mods()
        saved_chapter_mode = window.app_state.local_config.get(
            "chapter_mode_enabled", False
        )
        trigger_initial_mods_refresh(window, saved_chapter_mode=saved_chapter_mode)
        window._load_used_mods_debounce.call(
            window.used_mods_service.load_used_mods_state
        )
    except Exception as e:
        logging.error(
            f"AppWindow: Error in _on_mod_scan_finished: {e}", exc_info=True
        )
        window.feedback_service.update_status(
            tr("status.mod_scan_error", details=str(e)), UI_COLORS["status_error"]
        )
        window.setEnabled(True)
