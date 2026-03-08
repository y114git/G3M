"""Localization utilities for the main application window."""
import os
from config.constants import WIDGET_LOCALIZATIONS, PLUGIN_WIDGET_LOCALIZATIONS, COMBO_LOCALIZATIONS, SETTINGS_COLOR_CONFIG
from services.localization_service import tr, localization_service


def relocalize_texts(w):
    """Apply all localized texts to the window's widgets."""
    w.color_config = {key: tr(lang_key) for key, lang_key in SETTINGS_COLOR_CONFIG.items()}
    w.settings_button.setText(tr('ui.back_button') if w.app_state.is_settings_view else tr('ui.settings_title'))
    tab_labels = []
    if hasattr(w, 'search_mods_tab'):
        tab_labels.append((w.search_mods_tab, tr('ui.search_tab')))
    if hasattr(w, 'library_tab'):
        tab_labels.append((w.library_tab, tr('ui.library_tab')))
    if hasattr(w, 'plugins_tab'):
        tab_labels.append((w.plugins_tab, tr('ui.plugins_tab')))
    for tab_widget, label in tab_labels:
        idx = w.main_tab_widget.indexOf(tab_widget)
        if idx >= 0:
            w.main_tab_widget.setTabText(idx, label)
    w._apply_widget_localizations(WIDGET_LOCALIZATIONS)
    for combo_name, keys in COMBO_LOCALIZATIONS.items():
        w._apply_combo_localizations(combo_name, keys)
    if hasattr(w, 'search_tab_builder') and hasattr(w.search_tab_builder, 'refresh_dynamic_styles'):
        w.search_tab_builder.refresh_dynamic_styles()
    if hasattr(w, 'settings_reset_custom_exe_button') and w.settings_reset_custom_exe_button:
        w._update_custom_executable_ui()
    w.full_install_checkbox.setToolTip(w._full_install_tooltip())
    w.launch_via_steam_checkbox.setToolTip("<html><body style='white-space: normal;'>" + tr('tooltips.steam') + '</body></html>')
    if w.use_portproton_checkbox:
        w.use_portproton_checkbox.setText(tr('ui.use_portproton'))
        w.use_portproton_checkbox.setToolTip("<html><body style='white-space: normal;'>" + tr('tooltips.portproton') + '</body></html>')
    if w.select_portproton_path_button:
        w.select_portproton_path_button.setText(tr('buttons.select_portproton_path'))
    w.hide_wips_without_downloads_checkbox.setToolTip("<html><body style='white-space: normal;'>" + tr('tooltips.hide_wips_without_downloads') + '</body></html>')
    w._update_change_path_button_text()
    if hasattr(w, 'settings_tab_widget'):
        w.settings_tab_widget.setTabText(0, tr('ui.settings_tab_general'))
        w.settings_tab_widget.setTabText(1, tr('ui.settings_tab_appearance'))
        w.settings_tab_widget.setTabText(2, tr('ui.settings_tab_mods_browser'))
        w.settings_tab_widget.setTabText(3, tr('ui.settings_tab_library'))
        w.settings_tab_widget.setTabText(4, tr('ui.settings_tab_launch'))
        w.settings_tab_widget.setTabText(5, tr('ui.settings_tab_plugins'))
    if hasattr(w, '_update_settings_library_tab'):
        w._update_settings_library_tab()
    if hasattr(w, '_section_headers'):
        for lbl, key in w._section_headers:
            try:
                lbl.setText(tr(key))
            except (RuntimeError, AttributeError):
                pass
    w._apply_combo_localizations('gb_sort_combo', ['ui.gamebanana_sort_default', 'ui.gamebanana_sort_new', 'ui.gamebanana_sort_updated'])
    if hasattr(w, 'gb_sort_combo'):
        w.gb_sort_combo.setToolTip(tr('ui.gamebanana_sort_tooltip'))
    w.theme.update_background_button_state()
    w.theme.update_logo_button_state()
    w.change_font_button.setText(w.customization_service.get_font_button_text())
    w.background_music_button.setText(w.customization_service.get_background_music_button_text())
    w.startup_sound_button.setText(w.customization_service.get_startup_sound_button_text())
    if hasattr(w, 'sort_order_btn') and w.sort_order_btn:
        tooltip_text = tr('ui.ascending') if w.sort_ascending else tr('ui.descending')
        w.sort_order_btn.setToolTip(tooltip_text)
    if hasattr(w, 'library_sort_order_btn') and w.library_sort_order_btn:
        tooltip_text = tr('ui.ascending') if w.library_sort_ascending else tr('ui.descending')
        w.library_sort_order_btn.setToolTip(tooltip_text)
    if hasattr(w, 'chapter_tab_buttons') and w.chapter_tab_buttons:
        chapter_tab_names = [tr('chapters.menu'), tr('tabs.chapter_1'), tr('tabs.chapter_2'), tr('tabs.chapter_3'), tr('tabs.chapter_4')]
        for i, btn in enumerate(w.chapter_tab_buttons):
            if i < len(chapter_tab_names):
                btn.setText(chapter_tab_names[i])
    if hasattr(w, 'title_bar') and w.title_bar:
        w.title_bar.set_localized_texts(
            tr('ui.help_menu'),
            tr('buttons.changelog'),
            tr('ui.about_title'),
            tr('ui.minimize_window'),
            tr('ui.maximize_window'),
            tr('ui.restore_window'),
            tr('ui.close_window'),
        )
    for key in w.color_widgets.keys():
        if key in w.color_labels:
            w.color_labels[key].setText(w.color_config[key])
        color_btn = getattr(w, '_color_btns', {}).get(key)
        if color_btn:
            color_btn.setText(tr('ui.select_color'))
        if hasattr(w, 'settings_builder'):
            reset_btn = w.settings_builder.get_widgets().get(f'color_reset_{key}')
            if reset_btn:
                reset_btn.setToolTip(tr('buttons.reset_settings'))
    if hasattr(w, '_update_portproton_ui') and w.portproton_frame:
        w._update_portproton_ui()


def relocalize_ui(w):
    """Orchestrate full UI relocalization when language changes."""
    w._suppress_tab_handlers = True
    try:
        current_index = w.main_tab_widget.currentIndex() if hasattr(w, 'main_tab_widget') else -1
        current_plugin = None
        try:
            if current_index >= 0 and current_index in getattr(w, '_plugin_tab_map', {}):
                current_plugin = w._plugin_tab_map.get(current_index)
        except Exception:
            pass
        language_code = w.app_state.local_config.get('language', 'en')
        localization_service.load_language(language_code)
        w._update_qt_locale(language_code)
        w.custom_font_family = localization_service.load_font()
        if (cs := getattr(w, 'customization_service', None)) and (cfp := cs.get_custom_font_path()) and os.path.exists(cfp):
            from PyQt6.QtGui import QFontDatabase
            if families := QFontDatabase.applicationFontFamilies(QFontDatabase.addApplicationFont(cfp)):
                w.custom_font_family = families[0]
        w._update_plugin_tabs()
        try:
            if hasattr(w, 'main_tab_widget') and current_index >= 0 and (current_index < w.main_tab_widget.count()):
                w.main_tab_widget.setCurrentIndex(current_index)
                if current_plugin:
                    w._init_plugin_placeholder_tab(current_index)
        except Exception:
            pass
        w._relocalize_texts()
        w.theme.apply_theme()
        try:
            if hasattr(w, 'online_label'):
                w._update_online_label(getattr(w, '_last_online_count', 0))
        except Exception:
            pass
        w.search_display.update_filtered_mods()
        if hasattr(w, 'search_display') and hasattr(w.search_display, 'update_all_cards_labels'):
            w.search_display.update_all_cards_labels()
        w.library_display.update_display()
        w.search_display.update_pagination()
        w.game_launch.update_button_state()
        w._apply_widget_localizations(PLUGIN_WIDGET_LOCALIZATIONS)
        if hasattr(w, 'plugin_tab_builder') and hasattr(w.plugin_tab_builder, 'widgets'):
            widgets = w.plugin_tab_builder.widgets
            if 'installed_plugins_label' in widgets:
                widgets['installed_plugins_label'].setText(tr('plugins.installed_plugins'))
        if hasattr(w, 'plugin_display'):
            w.plugin_display.relocalize_plugin_widgets()
        w.update()
    finally:
        w._suppress_tab_handlers = False
