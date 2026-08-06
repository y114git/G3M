"""Localization utilities for the main application window."""

import contextlib
import logging
import os

from PyQt6.QtWidgets import QApplication

from app.game_ui import (
    full_install_tooltip,
    refresh_game_lists,
    update_change_path_button_text,
    update_custom_executable_ui,
    update_path_input_localizations,
    update_portproton_ui,
    update_settings_library_tab,
    update_steam_launch_checkbox_state,
)
from config.config import (
    COMBO_LOCALIZATIONS,
    SETTINGS_COLOR_CONFIG,
    WIDGET_LOCALIZATIONS,
)
from services.localization_service import (
    add_application_font_from_file,
    get_library_tab_title,
    get_settings_library_tab_title,
    localization_service,
    tr,
)

logger = logging.getLogger(__name__)


def _relocalize_widgets(main_window) -> None:
    """Refresh every live G3M widget that exposes a localization contract."""
    for widget in QApplication.allWidgets():
        if widget is main_window:
            continue
        callback = getattr(widget, "relocalize_ui", None)
        if not callable(callback):
            callback = getattr(widget, "update_labels_text", None)
        if callable(callback):
            try:
                callback()
            except RuntimeError as exc:
                if "deleted" in str(exc).casefold():
                    continue
                logger.exception(
                    "Failed to relocalize widget %s",
                    type(widget).__name__,
                )
            except AttributeError:
                logger.exception(
                    "Failed to relocalize widget %s",
                    type(widget).__name__,
                )
            except Exception:
                logger.exception(
                    "Failed to relocalize widget %s",
                    type(widget).__name__,
                )


def relocalize_texts(w):
    """Apply all localized texts to the window's widgets."""
    w.color_config = {
        key: tr(lang_key) for key, lang_key in SETTINGS_COLOR_CONFIG.items()
    }
    w.settings_button.setText(
        tr("ui.back_button")
        if w.app_state.is_settings_view
        else tr("ui.settings_title")
    )
    tab_labels = []
    if hasattr(w, "mods_browser_tab"):
        tab_labels.append((w.mods_browser_tab, tr("ui.search_tab")))
    if hasattr(w, "library_tab"):
        tab_labels.append((w.library_tab, get_library_tab_title(w.app_state)))
    for tab_widget, label in tab_labels:
        idx = w.main_tab_widget.indexOf(tab_widget)
        if idx >= 0:
            w.main_tab_widget.setTabText(idx, label)
    w._apply_widget_localizations(WIDGET_LOCALIZATIONS)
    if hasattr(w, "priority_button") and w.priority_button:
        w.priority_button.setText(tr("ui.priority_steps").replace("&", "&&"))
    update_path_input_localizations(w)
    for combo_name, keys in COMBO_LOCALIZATIONS.items():
        w._apply_combo_localizations(combo_name, keys)
    refresh_game_lists(w)
    if hasattr(w, "search_tab_builder") and hasattr(
        w.search_tab_builder, "refresh_dynamic_styles"
    ):
        w.search_tab_builder.refresh_dynamic_styles()
    if (
        hasattr(w, "settings_reset_custom_exe_button")
        and w.settings_reset_custom_exe_button
    ):
        update_custom_executable_ui(w)
    w.full_install_checkbox.setToolTip(full_install_tooltip(w))
    update_steam_launch_checkbox_state(w)
    if w.use_portproton_checkbox:
        w.use_portproton_checkbox.setText(tr("ui.use_portproton"))
        w.use_portproton_checkbox.setToolTip(
            "<html><body style='white-space: normal;'>"
            + tr("tooltips.portproton")
            + "</body></html>"
        )
    update_change_path_button_text(w)
    if hasattr(w, "settings_tab_widget"):
        w.settings_tab_widget.setTabText(0, tr("ui.settings_tab_general"))
        w.settings_tab_widget.setTabText(1, tr("ui.settings_tab_appearance"))
        w.settings_tab_widget.setTabText(2, tr("ui.settings_tab_game"))
        w.settings_tab_widget.setTabText(3, tr("ui.settings_tab_mods_browser"))
        w.settings_tab_widget.setTabText(4, get_settings_library_tab_title(w.app_state))
        if hasattr(w, "plugins_tab"):
            plugins_index = w.settings_tab_widget.indexOf(w.plugins_tab)
            if plugins_index >= 0:
                w.settings_tab_widget.setTabText(
                    plugins_index, tr("ui.settings_tab_plugins")
                )
    update_settings_library_tab(w)
    if hasattr(w, "_section_headers"):
        for lbl, key in w._section_headers:
            with contextlib.suppress(RuntimeError, AttributeError):
                lbl.setText(tr(key))
    if hasattr(w, "_section_reset_buttons"):
        for reset_btn, *_ in w._section_reset_buttons:
            with contextlib.suppress(RuntimeError, AttributeError):
                reset_btn.setToolTip(tr("buttons.reset_settings"))
    if hasattr(w, "_update_section_reset_buttons_visibility"):
        w._update_section_reset_buttons_visibility()
    w.theme.update_background_button_state()
    w.theme.update_logo_button_state()
    w.change_font_button.setText(w.customization_service.get_font_button_text())
    w.background_music_button.setText(
        w.customization_service.get_background_music_button_text()
    )
    w.startup_sound_button.setText(
        w.customization_service.get_startup_sound_button_text()
    )
    if hasattr(w, "sort_order_btn") and w.sort_order_btn:
        tooltip_text = tr("ui.ascending") if w.sort_ascending else tr("ui.descending")
        w.sort_order_btn.setToolTip(tooltip_text)
    if hasattr(w, "library_sort_order_btn") and w.library_sort_order_btn:
        tooltip_text = (
            tr("ui.ascending") if w.library_sort_ascending else tr("ui.descending")
        )
        w.library_sort_order_btn.setToolTip(tooltip_text)
    if hasattr(w, "chapter_tab_buttons") and w.chapter_tab_buttons:
        chapter_tab_names = [
            tr("chapters.menu"),
            tr("tabs.chapter_1"),
            tr("tabs.chapter_2"),
            tr("tabs.chapter_3"),
            tr("tabs.chapter_4"),
            tr("tabs.chapter_5"),
        ]
        for i, btn in enumerate(w.chapter_tab_buttons):
            if i < len(chapter_tab_names):
                btn.setText(chapter_tab_names[i])
    if hasattr(w, "title_bar") and w.title_bar:
        w.title_bar.set_localized_texts(
            tr("ui.windows_menu"),
            tr("ui.log_viewer"),
            tr("ui.support_packager"),
            tr("ui.help_menu"),
            tr("buttons.changelog"),
            tr("onboarding.menu_action"),
            tr("ui.about_title"),
            tr("ui.minimize_window"),
            tr("ui.maximize_window"),
            tr("ui.restore_window"),
            tr("ui.close_window"),
        )
    support_dialog = getattr(w, "_support_packager_dialog", None)
    if support_dialog and hasattr(support_dialog, "relocalize_ui"):
        support_dialog.relocalize_ui()
    for key in w.color_widgets:
        if key in w.color_labels:
            w.color_labels[key].setText(w.color_config[key])
        color_btn = getattr(w, "_color_btns", {}).get(key)
        if color_btn:
            color_btn.setText(tr("ui.select_color"))
        if hasattr(w, "settings_builder"):
            reset_btn = w.settings_builder.get_widgets().get(f"color_reset_{key}")
            if reset_btn:
                reset_btn.setToolTip(tr("buttons.reset_settings"))
    if w.portproton_frame:
        update_portproton_ui(w)
    for btn_attr in ("downloads_button", "library_downloads_button"):
        btn = getattr(w, btn_attr, None)
        if btn:
            btn.setToolTip(tr("downloads.title"))
    if hasattr(w, "downloads_manager"):
        w.downloads_manager._emit_badge()
    for btn_attr in ("library_modding_tools_button",):
        btn = getattr(w, btn_attr, None)
        if btn:
            btn.setToolTip(tr("modding_tools.title"))
            btn.setAccessibleName(tr("modding_tools.title"))
    btn = getattr(w, "diagnostics_button", None)
    if btn:
        btn.setText(tr("diagnostics.button"))
        btn.setToolTip(tr("diagnostics.tooltip"))
        btn.setAccessibleName(tr("diagnostics.title"))
    summary = getattr(w, "mod_summary_panel", None)
    if summary and hasattr(summary, "update_labels_text"):
        summary.update_labels_text()
    if hasattr(w, "plugins_ui") and w.plugins_ui:
        w.plugins_ui.relocalize_ui()
    if hasattr(w, "_refresh_localized_status"):
        w._refresh_localized_status()


def relocalize_ui(w):
    """Orchestrate full UI relocalization when language changes."""
    w._suppress_tab_handlers = True
    try:
        current_index = (
            w.main_tab_widget.currentIndex() if hasattr(w, "main_tab_widget") else -1
        )
        language_code = w.app_state.local_config.get("language", "en")
        localization_service.load_language(language_code)
        if hasattr(w, "plugin_runtime_service"):
            w.plugin_runtime_service.reload_plugin_localizations()
        w._update_qt_locale(language_code)
        w.custom_font_family = localization_service.load_font()
        cs = getattr(w, "customization_service", None)
        if cs:
            from PyQt6.QtGui import QFontDatabase

            old_font_id = getattr(w, "_custom_font_id", None)
            if old_font_id is not None and old_font_id != -1:
                QFontDatabase.removeApplicationFont(old_font_id)
            w._custom_font_id = None
            w._custom_font_file_key = None

            cfp = cs.get_custom_font_path()
            if cfp and os.path.exists(cfp):
                font_id = add_application_font_from_file(cfp)
                families = (
                    QFontDatabase.applicationFontFamilies(font_id)
                    if font_id != -1
                    else []
                )
                if families:
                    try:
                        stat_result = os.stat(cfp)
                    except OSError:
                        QFontDatabase.removeApplicationFont(font_id)
                    else:
                        w._custom_font_id = font_id
                        w._custom_font_file_key = (
                            cfp,
                            stat_result.st_mtime_ns,
                            stat_result.st_size,
                        )
                        w.custom_font_family = families[0]
                elif font_id != -1:
                    QFontDatabase.removeApplicationFont(font_id)
        if (
            hasattr(w, "main_tab_widget")
            and current_index >= 0
            and current_index < w.main_tab_widget.count()
        ):
            w.main_tab_widget.setCurrentIndex(current_index)
        relocalize_texts(w)
        _relocalize_widgets(w)
        w.theme.apply_theme()
        try:
            if hasattr(w, "online_label"):
                w._update_online_label(getattr(w, "_last_online_count", 0))
        except Exception as e:
            logger.debug(
                f"relocalize_app_ui: failed to refresh online label: {e}", exc_info=True
            )
        w.search_display.update_filtered_mods()
        if hasattr(w, "search_display") and hasattr(
            w.search_display, "update_all_cards_labels"
        ):
            w.search_display.update_all_cards_labels()
        w.library_display.update_display()
        w.search_display.update_pagination()
        w.game_launch.update_button_state()
        w.update()
    finally:
        w._suppress_tab_handlers = False
