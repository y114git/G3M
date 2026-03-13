"""Controller for settings UI management."""
from PyQt6.QtWidgets import QWidget
from core.app_post_init import _restore_ui_state_from_config
from services.localization_service import tr
from config.constants import UI_COLORS
from models.game_modes import DeltaruneGame, get_game


class SettingsUiController:
    """Manages settings UI display and interaction."""

    def __init__(self, app_state, feedback_service, settings_service, used_mods_service, customization_service, app_window):
        self.app_state, self.feedback_service, self.settings_service = app_state, feedback_service, settings_service
        self.used_mods_service, self.customization_service, self.app = used_mods_service, customization_service, app_window

    def _call_if_exists(self, obj, *attrs):
        for attr in attrs:
            if hasattr(obj, attr):
                getattr(obj, attr)()

    def toggle_settings_view(self):
        self.app_state.is_settings_view = not self.app_state.is_settings_view
        if self.app_state.is_settings_view:
            self.app.settings_button.setText(tr('ui.back_button'))
            self.app.tab_widget.setVisible(False)
            self.app.bottom_widget.setVisible(False)
            self.app.settings_widget.setVisible(True)
            self.customization_service.load_custom_style_settings(self.app.color_widgets)
            self.app._update_status(tr('status.launcher_settings'), UI_COLORS['status_info'])
        else:
            self.app.settings_button.setText(tr('ui.settings_title'))
            self.app.settings_widget.setVisible(False)
            self.app.main_tab_widget.setVisible(True)
            self.app.bottom_widget.setVisible(True)
            self.app.game_launch.update_button_state()

    def show_report_bug_dialog(self):
        from ui.dialogs.report_bug_dialog import ReportBugDialog
        ReportBugDialog(self.app, self.app_state).exec()

    def _set_combo_data(self, combo, value):
        was_blocked = combo.blockSignals(True)
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                combo.setCurrentIndex(i)
                combo.blockSignals(was_blocked)
                return
        combo.blockSignals(was_blocked)

    @staticmethod
    def _set_value_silently(widget, value):
        was_blocked = widget.blockSignals(True)
        widget.setValue(value)
        widget.blockSignals(was_blocked)

    @staticmethod
    def _collect_reset_targets(section_content):
        config_keys, reset_actions, reset_values = set(), set(), []
        for widget in section_content.findChildren(QWidget):
            if not hasattr(widget, 'property'):
                continue
            if key := widget.property('reset_config_key'):
                config_keys.add(key)
            if action := widget.property('reset_action'):
                reset_actions.add(action)
            if widget.property('reset_value') is not None:
                reset_values.append((widget, widget.property('reset_value')))
        return config_keys, reset_actions, reset_values

    def _refresh_after_section_reset(self):
        config = self.app_state.local_config
        self._set_combo_data(self.app.language_combo, config.get('language', 'en'))
        if hasattr(self.app, 'game_type_combo'):
            game_type = config.get('selected_game_type', 'deltarune')
            self._set_combo_data(self.app.game_type_combo, game_type)
            game_def = get_game(game_type)
            self.app_state.game_mode = game_def if game_def else DeltaruneGame()
            if hasattr(self.app, '_on_game_mode_updated_by_state'):
                self.app._on_game_mode_updated_by_state(self.app_state.game_mode)
        self._set_value_silently(self.app.ui_scale_spinbox, int(config.get('ui_scale', 1.0) * 100))
        self._set_value_silently(self.app.border_radius_spinbox, int(config.get('custom_border_radius', 7)))
        _restore_ui_state_from_config(self.app)
        self.customization_service.load_custom_style_settings(self.app.color_widgets)
        if hasattr(self.app, 'disable_animations_checkbox'):
            self.app.disable_animations_checkbox.setChecked(config.get('disable_animations', False))
        if hasattr(self.app, 'show_reset_buttons_checkbox'):
            self.app.show_reset_buttons_checkbox.setChecked(config.get('show_reset_buttons', False))
        for attr, key in (
            ('hide_mods_browser_tab_checkbox', 'hide_mods_browser_tab'),
            ('hide_library_tab_checkbox', 'hide_library_tab'),
            ('hide_plugins_tab_checkbox', 'hide_plugins_tab'),
        ):
            if hasattr(self.app, attr):
                getattr(self.app, attr).setChecked(config.get(key, False))
        self._call_if_exists(self.app, '_update_settings_library_tab', '_update_portproton_ui', '_update_custom_executable_ui', '_update_checkbox_visibility', '_update_section_reset_buttons_visibility')
        self.app.background_music_button.setText(self.customization_service.get_background_music_button_text())
        self.app.startup_sound_button.setText(self.customization_service.get_startup_sound_button_text())
        self.app.change_font_button.setText(self.customization_service.get_font_button_text())
        self.app.change_logo_button.setText(self.customization_service.get_logo_button_text())
        if hasattr(self.app, 'search_display'):
            self.app.search_display.update_filtered_mods()
        if hasattr(self.app, 'library_display'):
            self.app.library_display.update_display()
        self.app.game_launch.update_button_state()

    def reset_section(self, section_key, section_lang_key, section_content):
        config_keys, reset_actions, reset_values = self._collect_reset_targets(section_content)
        if not self.settings_service.reset_section(tr(section_lang_key) if section_lang_key else section_key, config_keys, reset_actions, bool(reset_values)):
            return
        if 'background_music' in reset_actions:
            self.customization_service.stop_background_music()
        for widget, value in reset_values:
            if hasattr(widget, 'setChecked'):
                widget.setChecked(bool(value))
        self._refresh_after_section_reset()

    def on_language_changed(self, lang): self.settings_service.on_language_changed(lang)

    def on_game_type_changed(self, index):
        game_type = self.app.game_type_combo.itemData(index)
        if not game_type:
            return
        self.used_mods_service.save_used_mods_state()
        game_def = get_game(game_type)
        self.app_state.game_mode = game_def if game_def else DeltaruneGame()
        self.app_state.local_config['selected_game_type'] = game_type
        self.settings_service.write_local_config()
        self._call_if_exists(self.app, '_update_saves_button_state', '_update_checkbox_visibility')
        self._call_if_exists(self.used_mods_service, '_update_steam_checkbox_state')

    def on_chapter_mode_changed(self, state):
        if self.app.game_type_combo.currentData() != 'deltarune':
            return
        self.app._previous_mode = getattr(self.app, 'current_mode', 'normal')
        is_chapter = bool(state)
        if (self.app_state.current_mode == 'chapter') != is_chapter:
            self.used_mods_service.save_used_mods_state()
        self.app_state.current_mode = 'chapter' if is_chapter else 'normal'
        if (self.app._previous_mode == 'normal') != is_chapter:
            self.used_mods_service.load_used_mods_state()
        self.app.game_type_combo.setEnabled(not is_chapter)
        if hasattr(self.app, 'library_display'):
            self.app.library_display.update_mod_widgets_active_status()
        self.app.game_launch.update_button_state()
        if hasattr(self.app, 'chapter_tabs_widget'):
            self.app.chapter_tabs_widget.setVisible(is_chapter)
        self.app_state.selected_chapter_id = None
        if is_chapter:
            if hasattr(self.app, 'library_display') and hasattr(self.app, 'priority_button'):
                self.app.library_display._set_priority_widgets_visible(False)
            self._call_if_exists(self.app, '_show_chapter_mode_instruction')
        elif hasattr(self.app, 'library_display'):
            self.app.library_display.update_display()
        self.app._update_change_path_button_text()
        self.app_state.local_config['chapter_mode_enabled'] = is_chapter
        self.settings_service.write_local_config()
        self._call_if_exists(self.used_mods_service, '_update_steam_checkbox_state')

    def on_toggle_beta_updates(self):
        self.settings_service.on_toggle_beta_updates(self.app.beta_updates_checkbox.isChecked())
        self.app.update_checker.check_for_updates()

    def on_toggle_fullscreen(self):
        fs = self.app.fullscreen_checkbox.isChecked()
        self.settings_service.on_toggle_fullscreen(fs)
        (self.app.showFullScreen if fs else self.app.showNormal)()
        self.settings_service.save_window_geometry(self.app)

    def on_toggle_steam_launch(self, state=None):
        is_steam = self.app.launch_via_steam_checkbox.isChecked()
        if is_steam and self.app_state.game_mode.game_id == 'deltarune' and self.app_state.current_mode == 'chapter' and self.app_state.local_config.get('direct_launch_chapter', ''):
            self.feedback_service.show_message('warning', 'ui.steam_launch', tr('ui.steam_launch_direct_conflict'))
            self.app.launch_via_steam_checkbox.setChecked(False)
            return
        self.settings_service.on_toggle_steam_launch(is_steam)
        self.app._update_custom_executable_ui()
        self._call_if_exists(self.app, '_update_portproton_ui')

    def on_toggle_portproton(self):
        use = self.app.use_portproton_checkbox.isChecked() if hasattr(self.app, 'use_portproton_checkbox') and self.app.use_portproton_checkbox else False
        self.settings_service.on_toggle_portproton(use)
        self._call_if_exists(self.app, '_update_portproton_ui')

    def on_toggle_dont_hide_window_on_launch(self, state):
        self.settings_service.on_toggle_dont_hide_window_on_launch(bool(state))

    def on_toggle_hide_library_filters(self, state):
        self.settings_service.on_toggle_hide_library_filters(bool(state))
        if hasattr(self.app, 'library_filters_widget'):
            self.app.library_filters_widget.setVisible(not state)

    def on_toggle_show_reset_buttons(self, state):
        self.settings_service.on_toggle_show_reset_buttons(bool(state))
        self._call_if_exists(self.app, '_update_section_reset_buttons_visibility')

    def on_toggle_disable_animations(self, state):
        self.settings_service.on_toggle_disable_animations(bool(state))

    def on_toggle_disable_background(self, state):
        self.settings_service.on_toggle_disable_background(bool(state))
        if hasattr(self.app, 'theme'):
            self.app.theme.update_background_button_state()

    def on_toggle_disable_splash(self, state): self.settings_service.on_toggle_disable_splash(bool(state))
    def on_toggle_skip_patching_warnings(self, state): self.settings_service.on_toggle_skip_patching_warnings(bool(state))

    def on_toggle_hide_mods_browser_tab(self, state):
        self.settings_service.on_toggle_hide_mods_browser_tab(bool(state))
        self._update_tab_visibility()

    def on_toggle_merge_properties(self, state):
        self.settings_service.on_toggle_merge_properties(bool(state))

    def on_toggle_merge_code(self, state):
        self.settings_service.on_toggle_merge_code(bool(state))

    def on_toggle_hide_library_tab(self, state):
        self.settings_service.on_toggle_hide_library_tab(bool(state))
        self._update_tab_visibility()

    def on_toggle_hide_plugins_tab(self, state):
        self.settings_service.on_toggle_hide_plugins_tab(bool(state))
        self._update_tab_visibility()

    def _update_tab_visibility(self):
        """Dynamically update tab visibility based on settings."""
        if not hasattr(self.app, 'main_tab_widget'):
            return

        tab_widget = self.app.main_tab_widget
        hide_mods_browser = self.app_state.local_config.get('hide_mods_browser_tab', False)
        hide_library = self.app_state.local_config.get('hide_library_tab', False)
        hide_plugins = self.app_state.local_config.get('hide_plugins_tab', False)

        old_suppress = getattr(self.app, '_suppress_tab_handlers', False)
        self.app._suppress_tab_handlers = True

        try:
            current_index = tab_widget.currentIndex()

            while tab_widget.count() > 0:
                tab_widget.removeTab(0)

            main_tabs_visible = 0
            if not hide_mods_browser and hasattr(self.app, 'mods_browser_tab'):
                tab_widget.addTab(self.app.mods_browser_tab, tr('ui.search_tab'))
                main_tabs_visible += 1
            if not hide_library and hasattr(self.app, 'library_tab'):
                tab_widget.addTab(self.app.library_tab, tr('ui.library_tab'))
                main_tabs_visible += 1
            if not hide_plugins and hasattr(self.app, 'plugins_tab'):
                tab_widget.addTab(self.app.plugins_tab, tr('ui.plugins_tab'))
                main_tabs_visible += 1

            self.app._num_main_tabs_visible = main_tabs_visible

            plugin_tabs_count = 0
            if hasattr(self.app, 'plugin_service') and hasattr(self.app.plugin_service, 'update_plugin_tabs'):
                try:
                    self.app._handling_plugin_tab = True
                    self.app._plugin_tab_map = self.app.plugin_service.update_plugin_tabs(
                        tab_widget, num_original_tabs=main_tabs_visible, preserve_widgets=True
                    )
                    plugin_tabs_count = len(self.app._plugin_tab_map)
                except Exception:
                    pass
                finally:
                    self.app._handling_plugin_tab = False

            self.app._update_nobody_came_state(main_tabs_visible, plugin_tabs_count)

            if tab_widget.count() > 0:
                tab_widget.setCurrentIndex(min(current_index, tab_widget.count() - 1))
        finally:
            self.app._suppress_tab_handlers = old_suppress
