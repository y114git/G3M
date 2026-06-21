"""Dialog openers, downloads callbacks, and profile management extracted from AppWindow."""

import logging

from app.game_ui import refresh_game_lists, update_checkbox_visibility
from config.config import UI_COLORS
from models.game_modes import DeltaruneGame, get_game
from services.localization_service import tr
from ui.dialogs.community_dialog import CommunityDialog

logger = logging.getLogger(__name__)


def _safe_show_message(w, level: str, title: str, message: str) -> None:
    try:
        w.feedback_service.show_message(level, title, message)
    except Exception as e:
        logger.warning(f"Dialog feedback message failed: {e}", exc_info=True)


def _safe_update_status(w, message: str, color: str) -> None:
    try:
        w.feedback_service.update_status(message, color)
    except Exception as e:
        logger.warning(f"Dialog status feedback failed: {e}", exc_info=True)


def open_community_dialog(w):
    if analytics := getattr(w, "analytics_service", None):
        analytics.record_dialog_opened("community")
    CommunityDialog(w, w.app_state).exec()


def on_downloads_record_updated(w, record):
    """Show yellow status feedback when a download record needs manual install, and refresh card buttons."""
    from models.download_models import UseStatus

    if record.use_status == UseStatus.NEEDS_MANUAL:
        name = record.display_name or record.id
        _safe_update_status(
            w,
            f"{name} - {tr('downloads.status_needs_manual')}",
            UI_COLORS["status_warning"],
        )
    refresh_mod_card_buttons(w)


def on_downloads_use_completed(w):
    """Refresh UI after Downloads system finishes a successful Use."""
    try:
        w.mod_service.invalidate_mods_cache()
        w.mod_service.load_local_mods()
        w.mod_service.mod_list_updated.emit()
        if hasattr(w, "search_display"):
            w.search_display.update_search_cards()
            w.search_display.update_filtered_mods(preserve_page=True)
        if hasattr(w, "library_display"):
            w.library_display.update_display()
        w.game_launch.update_button_state()
        _safe_update_status(w, tr("downloads.install_success"), UI_COLORS["status_success"])
    except Exception as e:
        logger.warning(f"on_downloads_use_completed failed: {e}", exc_info=True)


def refresh_mod_card_buttons(w):
    """Refresh download/install button enabled state on all visible mod cards."""
    if hasattr(w, "search_display") and hasattr(w.search_display, "card_widget_cache"):
        for card in w.search_display.card_widget_cache.values():
            if hasattr(card, "update_action_button_state"):
                card.update_action_button_state()


def open_downloads_dialog(w):
    from ui.dialogs.downloads_dialog import DownloadsDialog

    if w._downloads_dialog and w._downloads_dialog.isVisible():
        w._downloads_dialog.raise_()
        w._downloads_dialog.activateWindow()
        return
    analytics = getattr(w, "analytics_service", None)
    if analytics:
        analytics.record_dialog_opened("downloads")
    w._downloads_dialog = DownloadsDialog(w.downloads_manager, w.app_state, w)
    w._downloads_dialog.show()


def open_log_viewer_dialog(w):
    from ui.dialogs.log_viewer_dialog import LogViewerDialog

    if w._log_viewer_dialog is None:
        analytics = getattr(w, "analytics_service", None)
        if analytics:
            analytics.record_dialog_opened("log_viewer")
        w._log_viewer_dialog = LogViewerDialog(w.app_state, w)
        w._log_viewer_dialog.destroyed.connect(
            lambda: setattr(w, "_log_viewer_dialog", None)
        )
    w._log_viewer_dialog.show()
    w._log_viewer_dialog.raise_()
    w._log_viewer_dialog.activateWindow()


def open_game_versions_dialog(w):
    from ui.dialogs.game.versions_dialog import GameVersionsDialog

    if w._game_versions_dialog is None:
        analytics = getattr(w, "analytics_service", None)
        if analytics:
            analytics.record_dialog_opened("game_versions")
        initial_game = w.app_state.local_config.get("selected_game_type", "deltarune")
        w._game_versions_dialog = GameVersionsDialog(
            w.game_versions_manager, w.app_state, initial_game, w
        )
        w._game_versions_dialog.destroyed.connect(
            lambda: setattr(w, "_game_versions_dialog", None)
        )
    w._game_versions_dialog.show()
    w._game_versions_dialog.raise_()
    w._game_versions_dialog.activateWindow()


def open_modding_tools_dialog(w):
    from adapters.g3mtool_adapter import G3MToolManager
    from ui.dialogs.modding_tools_dialog import ModdingToolsDialog

    if w._modding_tools_dialog and w._modding_tools_dialog.isVisible():
        w._modding_tools_dialog.raise_()
        w._modding_tools_dialog.activateWindow()
        return
    analytics = getattr(w, "analytics_service", None)
    if analytics:
        analytics.record_dialog_opened("modding_tools")
    g3m = getattr(w, "_g3m_manager", None)
    if not g3m:
        g3m = G3MToolManager(w.app_state)
        w._g3m_manager = g3m
    w._modding_tools_dialog = ModdingToolsDialog(g3m, w.app_state, w)
    w._modding_tools_dialog.destroyed.connect(
        lambda: setattr(w, "_modding_tools_dialog", None)
    )
    w._modding_tools_dialog.show()


def open_diagnostics_dialog(w):
    from ui.dialogs.mod_diagnostics_dialog import ModDiagnosticsDialog

    if getattr(w, "_diagnostics_dialog", None) and w._diagnostics_dialog.isVisible():
        w._diagnostics_dialog.raise_()
        w._diagnostics_dialog.activateWindow()
        return
    analytics = getattr(w, "analytics_service", None)
    if analytics:
        analytics.record_dialog_opened("mod_diagnostics")
    w._diagnostics_dialog = ModDiagnosticsDialog(
        w.app_state,
        w.mod_service,
        w.used_mods_service,
        parent=w,
    )
    w._diagnostics_dialog.destroyed.connect(
        lambda: setattr(w, "_diagnostics_dialog", None)
    )
    w._diagnostics_dialog.show()


def populate_profile_combo(w):
    combo = w.profile_combo
    combo.blockSignals(True)
    combo.clear()
    for name in w.profile_service.list_profiles():
        combo.addItem(name, name)
    active = w.profile_service.active_name
    idx = combo.findData(active)
    if idx >= 0:
        combo.setCurrentIndex(idx)
    combo.blockSignals(False)


def open_profile_manager(w):
    from ui.dialogs.profile_manager_dialog import ProfileManagerDialog

    analytics = getattr(w, "analytics_service", None)
    if analytics:
        analytics.record_dialog_opened("profile_manager")
    dialog = ProfileManagerDialog(w.profile_service, w.app_state, w)
    dialog.exec()
    populate_profile_combo(w)


def open_game_manager(w):
    from ui.dialogs.game.manager_dialog import GameManagerDialog

    analytics = getattr(w, "analytics_service", None)
    if analytics:
        analytics.record_dialog_opened("game_manager")
    dialog = GameManagerDialog(
        w.game_registry_service,
        w.profile_service,
        w.game_versions_manager,
        w.settings_service,
        w.app_state,
        w,
    )
    dialog.exec()
    refresh_game_lists(w)


def on_profile_combo_changed(w, index: int):
    name = w.profile_combo.itemData(index)
    if not name or name == w.profile_service.active_name:
        return
    w.profile_service.switch(name)


def on_profile_switched(w, name: str):
    """Reload full library UI state from the newly active profile."""
    analytics = getattr(w, "analytics_service", None)
    if analytics:
        analytics.record_profile_switched()
    saved_game_type = w.app_state.local_config.get("selected_game_type", "deltarune")
    saved_chapter_mode = w.app_state.local_config.get("chapter_mode_enabled", False)
    saved_full_install = w.app_state.local_config.get("full_install_enabled", False)
    game_def = get_game(saved_game_type)
    w.app_state.game_mode = game_def if game_def else DeltaruneGame()
    idx = w.game_type_combo.findData(saved_game_type)
    if idx >= 0:
        w.game_type_combo.blockSignals(True)
        w.game_type_combo.setCurrentIndex(idx)
        w.game_type_combo.blockSignals(False)
    w._set_checkbox_checked_silently(w.chapter_mode_checkbox, saved_chapter_mode)
    w._set_checkbox_checked_silently(w.full_install_checkbox, saved_full_install)
    w.game_type_combo.setEnabled(not saved_chapter_mode)
    w.app_state.current_mode = "chapter" if saved_chapter_mode else "normal"
    w.app_state.is_full_install = saved_full_install
    w.app_state.selected_chapter_id = None
    w.downloads_manager.set_app_context(mods_dir=w.app_state.mods_dir)
    w.mod_service.invalidate_mods_cache()
    w.mod_service.load_local_mods()
    if hasattr(w, "game_launch"):
        w.game_launch._full_install_checkbox_is_checked = saved_full_install
    update_checkbox_visibility(w)
    w.used_mods_service.load_used_mods_state()
    if hasattr(w, "chapter_tabs_widget"):
        w.chapter_tabs_widget.setVisible(saved_chapter_mode)
    w._trigger_initial_mods_refresh(saved_chapter_mode)
    w.library_display.update_mod_widgets_active_status()
    w.library_display._update_priority_button_visibility()
    if hasattr(w, "game_launch"):
        w.game_launch.update_button_state()
