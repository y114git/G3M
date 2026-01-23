"""Controller for settings UI management.

This module handles the settings view toggle, settings page navigation,
and settings-related UI operations.
"""
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QWidget
from services.localization_service import tr
from config.constants import UI_COLORS, SLOT_ID_UNIVERSAL
from models.game_modes import DemoGameMode, UndertaleGameMode, UndertaleYellowGameMode, FullGameMode, PizzaTowerGameMode, SugarySpireGameMode


class SettingsUiController:
    """Manages settings UI display and interaction."""

    def __init__(self, app_state, feedback_service, settings_service, slot_service, customization_service, app_window):
        """Initialize the settings UI controller.

        Args:
            app_state: Application state manager.
            feedback_service: User feedback and dialog manager.
            settings_service: Application settings manager.
            slot_service: Slot and chapter management.
            customization_service: UI customization manager.
            app_window: Main application window reference.
        """
        self.app_state = app_state
        self.feedback_service = feedback_service
        self.settings_service = settings_service
        self.slot_service = slot_service
        self.customization_service = customization_service
        self.app = app_window

    def toggle_settings_view(self, show_changelog=False):
        """Toggle between settings view and main view.

        Args:
            show_changelog: Whether to show changelog instead of settings.
        """
        if show_changelog:
            self.app_state.is_changelog_view = not self.app_state.is_changelog_view
        else:
            self.app_state.is_settings_view = not self.app_state.is_settings_view
            if not self.app_state.is_settings_view:
                if self.app_state.is_changelog_view:
                    self.app_state.is_changelog_view = False
        if self.app_state.is_settings_view:
            self.app.settings_button.setText(tr('ui.back_button'))
            self.app.tab_widget.setVisible(False)
            self.app.bottom_widget.setVisible(False)
            self.app.settings_widget.setVisible(True)
            self.switch_settings_page(self.app.settings_menu_page)
            self.update_settings_page_visibility()
            QTimer.singleShot(0, lambda: self.customization_service.load_custom_style_settings(self.app.color_widgets, self.app.theme.apply_theme))
            self.app._update_status(tr('status.launcher_settings'), UI_COLORS['status_info'])
        else:
            self.app.settings_button.setText(tr('ui.settings_title'))
            self.app.setUpdatesEnabled(False)
            self.app.settings_widget.setVisible(False)
            self.app.main_tab_widget.setVisible(True)
            self.app.bottom_widget.setVisible(True)

            def apply_theme_and_enable_updates():
                self.app.theme.apply_theme()
                self.app.setUpdatesEnabled(True)
                self.app.update()
                self.app.repaint()
                self.app.game_launch.update_button_state()
            QTimer.singleShot(0, apply_theme_and_enable_updates)

    def show_report_bug_dialog(self):
        """Display the bug report dialog."""
        from ui.dialogs.report_bug_dialog import ReportBugDialog
        dialog = ReportBugDialog(self.app, self.app_state)
        dialog.exec()

    def update_settings_page_visibility(self):
        """Update visibility of settings pages and changelog."""
        is_changelog = self.app_state.is_changelog_view
        self.app.settings_pages_container.setVisible(not is_changelog)
        self.app.changelog_widget.setVisible(is_changelog)
        self.app.changelog_button.setText(tr('buttons.close') if is_changelog else tr('buttons.changelog'))

    def reset_settings(self):
        """Reset all settings to default values."""
        self.customization_service.stop_background_music()
        callbacks = {'migrate_config': lambda: (self.app._load_local_data(), self.settings_service.migrate_config_if_needed())}
        self.settings_service.on_reset_settings_click(callbacks)
        self.app.launch_via_steam_checkbox.setChecked(False)
        if hasattr(self.app, 'use_portproton_checkbox') and self.app.use_portproton_checkbox:
            self.app.use_portproton_checkbox.setChecked(False)
            if hasattr(self.app, '_update_portproton_ui'):
                self.app._update_portproton_ui()
        self.app.chapter_mode_checkbox.setChecked(False)
        self.app.beta_updates_checkbox.setChecked(False)
        self.app.fullscreen_checkbox.setChecked(False)
        self.app.hide_library_filters_checkbox.setChecked(False)
        self.app.full_install_checkbox.setChecked(False)
        self.app.disable_background_checkbox.setChecked(False)
        self.app.disable_splash_checkbox.setChecked(False)
        self.app.skip_patching_warnings_checkbox.setChecked(False)
        self.app._update_custom_executable_ui()
        self.app._update_checkbox_visibility()
        self.slot_service.used_mods.clear()
        self.slot_service.save_used_mods_state()
        self.slot_service.load_used_mods_state()
        self.update_settings_page_visibility()
        self.customization_service.load_custom_style_settings(self.app.color_widgets, self.app.theme.apply_theme)
        self.app.game_launch.update_button_state()
        self.app.background_music_button.setText(self.customization_service.get_background_music_button_text())
        self.app.startup_sound_button.setText(self.customization_service.get_startup_sound_button_text())

    def on_language_changed(self, language_code):
        self.settings_service.on_language_changed(language_code)

    def on_game_type_changed(self, index):
        game_type = self.app.game_type_combo.itemData(index)
        if not game_type:
            return
        self.slot_service.save_used_mods_state()
        if game_type == 'deltarunedemo':
            self.app_state.game_mode = DemoGameMode()
        elif game_type == 'undertale':
            self.app_state.game_mode = UndertaleGameMode()
        elif game_type == 'undertaleyellow':
            self.app_state.game_mode = UndertaleYellowGameMode()
        elif game_type == 'pizzatower':
            self.app_state.game_mode = PizzaTowerGameMode()
        elif game_type == 'sugaryspire':
            self.app_state.game_mode = SugarySpireGameMode()
        else:
            self.app_state.game_mode = FullGameMode()
        self.app_state.local_config['selected_game_type'] = game_type
        self.settings_service.write_local_config()
        if hasattr(self.app, '_update_saves_button_state'):
            self.app._update_saves_button_state()
        if hasattr(self.app, '_update_checkbox_visibility'):
            self.app._update_checkbox_visibility()
        if hasattr(self.slot_service, '_update_steam_checkbox_state'):
            self.slot_service._update_steam_checkbox_state()

    def on_chapter_mode_changed(self, state):
        game_type = self.app.game_type_combo.currentData()
        if game_type != 'deltarune':
            return
        old_mode = getattr(self.app, 'current_mode', 'normal')
        self.app._previous_mode = old_mode
        is_chapter = bool(state)
        old_is_chapter = self.app_state.current_mode == 'chapter'
        if old_is_chapter != is_chapter:
            self.slot_service.save_used_mods_state()
            self.app_state.current_mode = 'chapter' if is_chapter else 'normal'
            self.slot_service.load_used_mods_state()
        else:
            self.app_state.current_mode = 'chapter' if is_chapter else 'normal'
        self.app.game_type_combo.setEnabled(not is_chapter)
        if hasattr(self.app, 'library_display'):
            self.app.library_display.update_mod_widgets_slot_status()
        self.app.game_launch.update_button_state()
        if hasattr(self.app, 'chapter_tabs_widget'):
            self.app.chapter_tabs_widget.setVisible(is_chapter)
        self.app_state.selected_chapter_id = None
        if is_chapter:
            if hasattr(self.app, '_show_chapter_mode_instruction'):
                self.app._show_chapter_mode_instruction()
        elif hasattr(self.app, 'library_display'):
            self.app.library_display.update_display()
        self.app._update_change_path_button_text()
        self.app_state.local_config['chapter_mode_enabled'] = is_chapter
        self.settings_service.write_local_config()
        if hasattr(self.slot_service, '_update_steam_checkbox_state'):
            self.slot_service._update_steam_checkbox_state()

    def on_toggle_beta_updates(self):
        beta_enabled = self.app.beta_updates_checkbox.isChecked()
        self.settings_service.on_toggle_beta_updates(beta_enabled)
        self.app.update_checker.check_for_updates()

    def on_toggle_fullscreen(self):
        fullscreen_enabled = self.app.fullscreen_checkbox.isChecked()
        self.settings_service.on_toggle_fullscreen(fullscreen_enabled)
        if fullscreen_enabled:
            self.app.showFullScreen()
        else:
            self.app.showNormal()
        self.settings_service.save_window_geometry(self.app)

    def on_toggle_steam_launch(self, state=None):
        is_steam_launch = self.app.launch_via_steam_checkbox.isChecked()
        if is_steam_launch:
            direct_launch_slot_id = self.app_state.local_config.get('direct_launch_slot_id', SLOT_ID_UNIVERSAL)
            is_chapter_mode = self.app_state.current_mode == 'chapter'
            is_deltarune = isinstance(self.app_state.game_mode, FullGameMode)
            if is_deltarune and is_chapter_mode and (direct_launch_slot_id >= 0):
                self.feedback_service.show_message('warning', 'ui.steam_launch', tr('ui.steam_launch_direct_conflict'))
                self.app.launch_via_steam_checkbox.setChecked(False)
                return
        self.settings_service.on_toggle_steam_launch(is_steam_launch)
        self.app._update_custom_executable_ui()

    def on_toggle_portproton(self):
        use_portproton = self.app.use_portproton_checkbox.isChecked() if hasattr(self.app, 'use_portproton_checkbox') and self.app.use_portproton_checkbox else False
        self.settings_service.on_toggle_portproton(use_portproton)
        if hasattr(self.app, '_update_portproton_ui'):
            self.app._update_portproton_ui()

    def on_toggle_hide_mods_without_files(self):
        hide_mods = self.app.hide_mods_without_files_checkbox.isChecked()
        self.settings_service.on_toggle_hide_mods_without_files(hide_mods)
        if hasattr(self.app, 'search_display'):
            self.app.search_display.update_filtered_mods()

    def on_toggle_hide_library_filters(self, state):
        is_hidden = bool(state)
        self.settings_service.on_toggle_hide_library_filters(is_hidden)
        if hasattr(self.app, 'library_filters_widget'):
            self.app.library_filters_widget.setVisible(not is_hidden)

    def on_toggle_disable_background(self, state):
        is_disabled = bool(state)
        self.settings_service.on_toggle_disable_background(is_disabled)
        if hasattr(self.app, 'theme'):
            self.app.theme.update_background_button_state()

    def on_toggle_disable_splash(self, state):
        is_disabled = bool(state)
        self.settings_service.on_toggle_disable_splash(is_disabled)

    def on_toggle_skip_patching_warnings(self, state):
        is_enabled = bool(state)
        self.settings_service.on_toggle_skip_patching_warnings(is_enabled)

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
