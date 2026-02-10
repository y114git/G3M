"""Localization utilities for the main application window."""
from PyQt6.QtWidgets import QWidget
from services.localization_service import tr
from ui.common.styling import get_theme_color
from services.localization_service import localization_service


WIDGET_LOCALIZATIONS = [
    ('online_label', 'setToolTip', 'tooltips.online_counter'),
    ('telegram_button', 'setText', 'buttons.telegram'),
    ('beta_updates_checkbox', 'setToolTip', 'tooltips.beta_updates'),
    ('discord_button', 'setText', 'buttons.discord'),
    ('chat_button', 'setText', 'ui.chat_button'),
    ('shortcut_button', 'setText', 'buttons.shortcut'),
    ('tags_label', 'setText', 'ui.tags_label'),
    ('tag_textedit', 'setText', 'tags.textedit'),
    ('tag_customization', 'setText', 'tags.customization'),
    ('tag_gameplay', 'setText', 'tags.gameplay'),
    ('tag_other', 'setText', 'tags.other'),
    ('search_button', 'setToolTip', 'ui.search_placeholder'),
    ('prev_page_btn', 'setText', 'ui.prev_page'),
    ('next_page_btn', 'setText', 'ui.next_page'),
    ('chapter_mode_checkbox', 'setText', 'ui.chapter_mode'),
    ('full_install_checkbox', 'setText', 'ui.full_install'),
    ('language_label', 'setText', 'ui.language_label'),
    ('beta_updates_checkbox', 'setText', 'ui.beta_updates'),
    ('skip_patching_warnings_checkbox', 'setText', 'ui.skip_patching_warnings'),
    ('skip_patching_warnings_checkbox', 'setToolTip', 'tooltips.skip_patching_warnings'),
    ('fullscreen_checkbox', 'setText', 'ui.fullscreen'),
    ('fullscreen_checkbox', 'setToolTip', 'tooltips.fullscreen_tooltip'),
    ('launch_via_steam_checkbox', 'setText', 'ui.steam_launch'),
    ('hide_mods_without_files_checkbox', 'setText', 'ui.hide_mods_without_files'),
    ('open_deltahub_folder_button', 'setText', 'buttons.open_deltahub_folder'),
    ('customization_button', 'setText', 'tags.customization'),
    ('reset_button', 'setText', 'buttons.reset_settings'),
    ('back_button_cust', 'setText', 'ui.back_button'),
    ('disable_background_checkbox', 'setText', 'checkboxes.disable_background'),
    ('disable_splash_checkbox', 'setText', 'checkboxes.disable_splash'),
    ('fast_merging_label', 'setText', 'ui.fast_merging'),
    ('fast_merging_label', 'setToolTip', 'ui.fast_merging_tooltip'),
    ('fast_merging_checkbox', 'setToolTip', 'ui.fast_merging_tooltip'),
    ('mods_per_page_label', 'setText', 'ui.mods_per_page_label'),
    ('mods_per_page_spinbox', 'setToolTip', 'ui.mods_per_page_tooltip'),
    ('custom_executable_button', 'setText', 'buttons.custom_executable'),
    ('custom_executable_button', 'setToolTip', 'tooltips.custom_executable_library'),
    ('auto_sorting_checkbox', 'setText', 'ui.auto_sorting'),
    ('auto_sorting_checkbox', 'setToolTip', 'ui.auto_sorting_tooltip'),
    ('blocklist_button', 'setText', 'ui.blocklist'),
    ('blocklist_button', 'setToolTip', 'ui.blocklist_tooltip'),
    ('priority_button', 'setText', 'ui.priority'),
    ('create_modpack_button', 'setText', 'ui.create_modpack_button'),
    ('library_tags_label', 'setText', 'ui.tags_label'),
    ('library_tag_textedit', 'setText', 'tags.textedit'),
    ('library_tag_customization', 'setText', 'tags.customization'),
    ('library_tag_gameplay', 'setText', 'tags.gameplay'),
    ('library_tag_other', 'setText', 'tags.other'),
    ('library_tag_gamebanana', 'setText', 'ui.only_gamebanana'),
    ('library_search_button', 'setToolTip', 'ui.search_placeholder'),
    ('installed_mods_label', 'setText', 'ui.installed_mods_label'),
    ('import_export_button', 'setText', 'ui.import_export_mod'),
    ('report_bug_button', 'setText', 'buttons.report_bug'),
    ('theme_button', 'setText', 'buttons.theme_management'),
]

PLUGIN_WIDGET_LOCALIZATIONS = [
    ('plugins_search_button', 'setText', 'plugins.search_plugins'),
    ('plugins_import_button', 'setText', 'plugins.import_plugins'),
]

COMBO_LOCALIZATIONS = {
    'sort_combo': ['ui.sort_by_downloads', 'ui.sort_by_update_date', 'ui.sort_by_creation_date'],
    'modgame_combo': ['dropdowns.all_mods', 'ui.deltarune', 'ui.deltarunedemo', 'ui.undertale'],
    'library_sort_combo': ['ui.sort_by_name', 'ui.sort_by_date'],
}


def relocalize_texts(w):
    """Apply all localized texts to the window's widgets."""
    w.color_config = {'background': tr('ui.background_color'), 'button': tr('ui.elements_color'), 'border': tr('ui.border_color'), 'button_hover': tr('ui.hover_color'), 'text': tr('ui.main_text_color'), 'version_text': tr('ui.secondary_text_color')}
    w.settings_button.setText(tr('ui.back_button') if w.app_state.is_settings_view else tr('ui.settings_title'))
    w.main_tab_widget.setTabText(0, tr('ui.search_tab'))
    w.main_tab_widget.setTabText(1, tr('ui.library_tab'))
    if hasattr(w, 'plugins_tab') and w.main_tab_widget.count() > 2:
        w.main_tab_widget.setTabText(2, tr('ui.plugins_tab'))
    w._apply_widget_localizations(WIDGET_LOCALIZATIONS)
    for combo_name, keys in COMBO_LOCALIZATIONS.items():
        w._apply_combo_localizations(combo_name, keys)
    if hasattr(w, 'gb_sort_label'):
        w.gb_sort_label.setText(tr('ui.gamebanana_sort_label'))
        w._apply_combo_localizations('gb_sort_combo', ['ui.gamebanana_sort_default', 'ui.gamebanana_sort_new', 'ui.gamebanana_sort_updated'])
        w.gb_sort_combo.setToolTip(tr('ui.gamebanana_sort_tooltip'))
    if hasattr(w, 'reset_custom_exe_button') and w.reset_custom_exe_button:
        w._update_custom_executable_ui()
    if hasattr(w, 'blocklist_button') and w.blocklist_button:
        w.blocklist_button.setStyleSheet('font-size: 11px; padding: 0px 4px; border: 2px solid white;')
    w.full_install_checkbox.setToolTip(w._full_install_tooltip())
    w.settings_title_label.setText(f"<h1>{tr('ui.settings_title')}</h1>")
    w.launch_via_steam_checkbox.setToolTip("<html><body style='white-space: normal;'>" + tr('tooltips.steam') + '</body></html>')
    if w.use_portproton_checkbox:
        w.use_portproton_checkbox.setText(tr('ui.use_portproton'))
        w.use_portproton_checkbox.setToolTip("<html><body style='white-space: normal;'>" + tr('tooltips.portproton') + '</body></html>')
    if w.select_portproton_path_button:
        w.select_portproton_path_button.setText(tr('buttons.select_portproton_path'))
    w.hide_mods_without_files_checkbox.setToolTip("<html><body style='white-space: normal;'>" + tr('tooltips.hide_mods_without_files') + '</body></html>')
    w._update_change_path_button_text()
    w.theme.update_background_button_state()
    w.theme.update_logo_button_state()
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
    for key in w.color_widgets.keys():
        if key in w.color_labels:
            w.color_labels[key].setText(w.color_config[key])
        color_btn = getattr(w, '_color_btns', {}).get(key)
        if color_btn:
            color_btn.setText(tr('ui.select_color'))
    w.changelog_button.setText(tr('buttons.close') if w.app_state.is_changelog_view else tr('buttons.changelog'))
    if hasattr(w, '_update_portproton_ui') and w.portproton_frame:
        w._update_portproton_ui()


def relocalize_ui(w):
    """Orchestrate full UI relocalization when language changes."""
    w._suppress_tab_handlers = True
    try:
        current_index = w.main_tab_widget.currentIndex() if hasattr(w, 'main_tab_widget') else -1
        current_widget = None
        current_plugin = None
        try:
            if current_index >= 0:
                current_widget = w.main_tab_widget.widget(current_index)
                if isinstance(current_widget, QWidget) and current_index in getattr(w, '_plugin_tab_map', {}):
                    current_plugin = w._plugin_tab_map.get(current_index)
        except Exception:
            pass
        language_code = w.app_state.local_config.get('language', 'en')
        localization_service.load_language(language_code)
        w._update_qt_locale(language_code)
        w.custom_font_family = localization_service.load_font()
        w._update_plugin_tabs()
        try:
            if hasattr(w, 'main_tab_widget') and current_index >= 0 and (current_index < w.main_tab_widget.count()):
                w.main_tab_widget.setCurrentIndex(current_index)
                if current_plugin:
                    widget = w.main_tab_widget.widget(current_index)
                    if isinstance(widget, QWidget) and widget.layout() is None:
                        handler = current_plugin.get('page_init') if callable(current_plugin.get('page_init')) else current_plugin.get('on_tab_open')
                        try:
                            plugin_api = current_plugin.get('api')
                            if plugin_api:
                                setattr(w, 'plugin_api', plugin_api)
                            try:
                                new_widget = handler(w) if callable(handler) else None
                                if isinstance(new_widget, QWidget):
                                    w.main_tab_widget.removeTab(current_index)
                                    w.main_tab_widget.insertTab(current_index, new_widget, tr(current_plugin['name_key']))
                                    w.main_tab_widget.setCurrentIndex(current_index)
                            finally:
                                if hasattr(w, 'plugin_api'):
                                    delattr(w, 'plugin_api')
                        except Exception:
                            if hasattr(w, 'plugin_api'):
                                delattr(w, 'plugin_api')
                            pass
        except Exception:
            pass
        w._relocalize_texts()
        try:
            if hasattr(w, 'hide_library_filters_checkbox'):
                w.hide_library_filters_checkbox.setText(tr('ui.hide_library_filters'))
                w.hide_library_filters_checkbox.setToolTip(tr('tooltips.hide_library_filters'))
        except Exception:
            pass
        w.theme.apply_theme()
        if hasattr(w, '_update_chapter_tabs_style'):
            w._update_chapter_tabs_style()
        try:
            if hasattr(w, 'online_label'):
                w._update_online_label(getattr(w, '_last_online_count', 0))
        except Exception:
            pass
        text_color = get_theme_color(w.app_state.local_config, 'text', 'white')
        bg_color = get_theme_color(w.app_state.local_config, 'background', '#000000')
        bold_label_style = f'font-weight: bold; font-size: 16px; color: {text_color};'
        if hasattr(w, 'plugin_tab_builder'):
            plugin_lbl = w.plugin_tab_builder.widgets.get('installed_plugins_label')
            if plugin_lbl:
                plugin_lbl.setStyleSheet(bold_label_style)
        if hasattr(w, 'installed_mods_label') and w.installed_mods_label:
            w.installed_mods_label.setStyleSheet(bold_label_style)
        checkbox_style = f'\n            QCheckBox {{\n                color: {text_color};\n                font-size: 12px;\n                spacing: 5px;\n            }}\n            QCheckBox::indicator {{\n                width: 16px;\n                height: 16px;\n            }}\n        '
        text_only_style = f'color: {text_color};'
        checkbox_targets = []
        if hasattr(w, 'library_tag_widgets'):
            checkbox_targets.extend(w.library_tag_widgets)
        if hasattr(w, 'tag_textedit'):
            checkbox_targets.extend(widget for widget in [w.tag_textedit, w.tag_customization, w.tag_gameplay, w.tag_other] if widget)
            if hasattr(w, 'auto_sorting_checkbox') and w.auto_sorting_checkbox:
                checkbox_targets.append(w.auto_sorting_checkbox)
        for cb in checkbox_targets:
            cb.setStyleSheet(checkbox_style)
        for attr_name in ('chapter_mode_checkbox', 'full_install_checkbox'):
            widget = getattr(w, attr_name, None)
            if widget:
                widget.setStyleSheet(text_only_style)
        if hasattr(w, 'blocklist_button') and w.blocklist_button:
            w.blocklist_button.setStyleSheet(f'\n                    QPushButton {{\n                        background-color: {bg_color};\n                        color: {text_color};\n                        border: 2px solid white;\n                        padding: 0px 4px;\n                        font-size: 11px;\n                    }}\n                    QPushButton:hover {{\n                        background-color: white;\n                        color: {bg_color};\n                    }}\n                ')
        w.search_display.update_filtered_mods()
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
