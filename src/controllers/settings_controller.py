"""Controller for settings UI management."""
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QWidget
from services.localization_service import tr
from config.constants import UI_COLORS, SLOT_ID_UNIVERSAL
from models.game_modes import DemoGameMode, UndertaleGameMode, UndertaleYellowGameMode, FullGameMode, PizzaTowerGameMode, SugarySpireGameMode


class SettingsUiController:
    """Manages settings UI display and interaction."""
    _GAME_TYPE_MODES = {'deltarunedemo': DemoGameMode, 'undertale': UndertaleGameMode, 'undertaleyellow': UndertaleYellowGameMode, 'pizzatower': PizzaTowerGameMode, 'sugaryspire': SugarySpireGameMode}

    def __init__(self, app_state, feedback_service, settings_service, slot_service, customization_service, app_window):
        self.app_state, self.feedback_service, self.settings_service = app_state, feedback_service, settings_service
        self.slot_service, self.customization_service, self.app = slot_service, customization_service, app_window

    def _call_if_exists(self, obj, *attrs):
        for attr in attrs:
            if hasattr(obj, attr):
                getattr(obj, attr)()

    def toggle_settings_view(self, show_changelog=False):
        if show_changelog:
            self.app_state.is_changelog_view = not self.app_state.is_changelog_view
        else:
            self.app_state.is_settings_view = not self.app_state.is_settings_view
            if not self.app_state.is_settings_view and self.app_state.is_changelog_view:
                self.app_state.is_changelog_view = False
        if self.app_state.is_settings_view:
            self.app.settings_button.setText(tr('ui.back_button'))
            self.app.tab_widget.setVisible(False), self.app.bottom_widget.setVisible(False), self.app.settings_widget.setVisible(True)
            self.switch_settings_page(self.app.settings_menu_page)
            self.update_settings_page_visibility()
            QTimer.singleShot(0, lambda: self.customization_service.load_custom_style_settings(self.app.color_widgets, self.app.theme.apply_theme))
            self.app._update_status(tr('status.launcher_settings'), UI_COLORS['status_info'])
        else:
            self.app.settings_button.setText(tr('ui.settings_title'))
            self.app.setUpdatesEnabled(False)
            self.app.settings_widget.setVisible(False), self.app.main_tab_widget.setVisible(True), self.app.bottom_widget.setVisible(True)

            def finalize():
                self.app.theme.apply_theme(), self.app.setUpdatesEnabled(True), self.app.update(), self.app.repaint(), self.app.game_launch.update_button_state()
            QTimer.singleShot(0, finalize)

    def show_report_bug_dialog(self):
        from ui.dialogs.report_bug_dialog import ReportBugDialog
        ReportBugDialog(self.app, self.app_state).exec()

    def update_settings_page_visibility(self):
        is_cl = self.app_state.is_changelog_view
        self.app.settings_pages_container.setVisible(not is_cl), self.app.changelog_widget.setVisible(is_cl)
        self.app.changelog_button.setText(tr('buttons.close') if is_cl else tr('buttons.changelog'))

    def reset_settings(self):
        self.customization_service.stop_background_music()
        self.settings_service.on_reset_settings_click({'migrate_config': lambda: (self.app._load_local_data(), self.settings_service.migrate_config_if_needed())})
        self.app.launch_via_steam_checkbox.setChecked(False)
        if hasattr(self.app, 'use_portproton_checkbox') and self.app.use_portproton_checkbox:
            self.app.use_portproton_checkbox.setChecked(False)
            self._call_if_exists(self.app, '_update_portproton_ui')
        for cb in ('chapter_mode_checkbox', 'beta_updates_checkbox', 'fullscreen_checkbox', 'hide_library_filters_checkbox', 'full_install_checkbox', 'disable_background_checkbox', 'disable_splash_checkbox', 'skip_patching_warnings_checkbox'):
            getattr(self.app, cb).setChecked(False)
        self.app._update_custom_executable_ui(), self.app._update_checkbox_visibility()
        self.slot_service.used_mods.clear(), self.slot_service.save_used_mods_state(), self.slot_service.load_used_mods_state()
        self.update_settings_page_visibility()
        self.customization_service.load_custom_style_settings(self.app.color_widgets, self.app.theme.apply_theme)
        self.app.game_launch.update_button_state()
        self.app.background_music_button.setText(self.customization_service.get_background_music_button_text())
        self.app.startup_sound_button.setText(self.customization_service.get_startup_sound_button_text())

    def on_language_changed(self, lang): self.settings_service.on_language_changed(lang)

    def on_game_type_changed(self, index):
        game_type = self.app.game_type_combo.itemData(index)
        if not game_type:
            return
        self.slot_service.save_used_mods_state()
        self.app_state.game_mode = self._GAME_TYPE_MODES.get(game_type, FullGameMode)()
        self.app_state.local_config['selected_game_type'] = game_type
        self.settings_service.write_local_config()
        self._call_if_exists(self.app, '_update_saves_button_state', '_update_checkbox_visibility')
        self._call_if_exists(self.slot_service, '_update_steam_checkbox_state')

    def on_chapter_mode_changed(self, state):
        if self.app.game_type_combo.currentData() != 'deltarune':
            return
        self.app._previous_mode = getattr(self.app, 'current_mode', 'normal')
        is_chapter = bool(state)
        if (self.app_state.current_mode == 'chapter') != is_chapter:
            self.slot_service.save_used_mods_state()
        self.app_state.current_mode = 'chapter' if is_chapter else 'normal'
        if (self.app._previous_mode == 'normal') != is_chapter:
            self.slot_service.load_used_mods_state()
        self.app.game_type_combo.setEnabled(not is_chapter)
        if hasattr(self.app, 'library_display'):
            self.app.library_display.update_mod_widgets_slot_status()
        self.app.game_launch.update_button_state()
        if hasattr(self.app, 'chapter_tabs_widget'):
            self.app.chapter_tabs_widget.setVisible(is_chapter)
        self.app_state.selected_chapter_id = None
        if is_chapter:
            for attr in ('priority_button', 'create_modpack_button', 'fast_merging_checkbox', 'fast_merging_label'):
                if hasattr(self.app, attr):
                    getattr(self.app, attr).setVisible(False)
            if hasattr(self.app, 'library_tab_builder'):
                w = self.app.library_tab_builder.widgets
                if 'priority_button_container' in w:
                    w['priority_button_container'].setFixedHeight(0)
                if 'priority_button_layout' in w:
                    w['priority_button_layout'].setContentsMargins(0, 0, 0, 0)
            self._call_if_exists(self.app, '_show_chapter_mode_instruction')
        elif hasattr(self.app, 'library_display'):
            self.app.library_display.update_display()
        self.app._update_change_path_button_text()
        self.app_state.local_config['chapter_mode_enabled'] = is_chapter
        self.settings_service.write_local_config()
        self._call_if_exists(self.slot_service, '_update_steam_checkbox_state')

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
        if is_steam and isinstance(self.app_state.game_mode, FullGameMode) and self.app_state.current_mode == 'chapter' and self.app_state.local_config.get('direct_launch_slot_id', SLOT_ID_UNIVERSAL) >= 0:
            self.feedback_service.show_message('warning', 'ui.steam_launch', tr('ui.steam_launch_direct_conflict'))
            self.app.launch_via_steam_checkbox.setChecked(False)
            return
        self.settings_service.on_toggle_steam_launch(is_steam), self.app._update_custom_executable_ui()

    def on_toggle_portproton(self):
        use = self.app.use_portproton_checkbox.isChecked() if hasattr(self.app, 'use_portproton_checkbox') and self.app.use_portproton_checkbox else False
        self.settings_service.on_toggle_portproton(use)
        self._call_if_exists(self.app, '_update_portproton_ui')

    def on_toggle_hide_mods_without_files(self):
        self.settings_service.on_toggle_hide_mods_without_files(self.app.hide_mods_without_files_checkbox.isChecked())
        if hasattr(self.app, 'search_display'):
            self.app.search_display.update_filtered_mods()

    def on_toggle_hide_library_filters(self, state):
        self.settings_service.on_toggle_hide_library_filters(bool(state))
        if hasattr(self.app, 'library_filters_widget'):
            self.app.library_filters_widget.setVisible(not state)

    def on_toggle_disable_background(self, state):
        self.settings_service.on_toggle_disable_background(bool(state))
        if hasattr(self.app, 'theme'):
            self.app.theme.update_background_button_state()

    def on_toggle_disable_splash(self, state): self.settings_service.on_toggle_disable_splash(bool(state))
    def on_toggle_skip_patching_warnings(self, state): self.settings_service.on_toggle_skip_patching_warnings(bool(state))

    def switch_settings_page(self, page: QWidget):
        if self.app_state.current_settings_page and self.app_state.current_settings_page is not page:
            self.app_state.settings_nav_stack.append(self.app_state.current_settings_page)
            if len(self.app_state.settings_nav_stack) > 20:
                self.app_state.settings_nav_stack.pop(0)
            self.app_state.current_settings_page.setVisible(False)
        page.setVisible(True)
        self.app_state.current_settings_page = page

    def go_back_to_settings_menu(self):
        if self.app_state.current_settings_page and self.app_state.current_settings_page is not self.app.settings_menu_page:
            self.app_state.current_settings_page.setVisible(False)
        self.app.settings_menu_page.setVisible(True)
        self.app_state.current_settings_page = self.app.settings_menu_page
        if self.app_state.settings_nav_stack and self.app_state.settings_nav_stack[-1] is self.app.settings_menu_page:
            self.app_state.settings_nav_stack.pop()
