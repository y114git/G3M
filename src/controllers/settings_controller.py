"""Controller for settings UI management."""

import logging

from PyQt6.QtWidgets import QWidget

from app.game_ui import (
    on_game_mode_updated_by_state,
    show_chapter_mode_instruction,
    update_change_path_button_text,
    update_checkbox_visibility,
    update_custom_executable_ui,
    update_portproton_ui,
    update_settings_library_tab,
)
from bootstrap.bootstrap_coordinator import BootstrapCoordinator
from config.config import UI_COLORS
from models.game_modes import DeltaruneGame, get_game
from services.localization_service import get_library_tab_title, tr

logger = logging.getLogger(__name__)


class SettingsUiController:
    """Manages settings UI display and interaction."""

    def __init__(
        self,
        app_state,
        feedback_service,
        settings_service,
        used_mods_service,
        customization_service,
        app_window,
    ) -> None:
        self.app_state, self.feedback_service, self.settings_service = (
            app_state,
            feedback_service,
            settings_service,
        )
        self.used_mods_service, self.customization_service, self.app = (
            used_mods_service,
            customization_service,
            app_window,
        )

    def _safe_show_message(self, *args, **kwargs) -> None:
        show_message = getattr(self.feedback_service, "show_message", None)
        if not callable(show_message):
            return
        try:
            show_message(*args, **kwargs)
        except Exception as e:
            logger.warning(
                "Settings feedback message failed: %s",
                e,
                exc_info=True,
            )

    def toggle_settings_view(self):
        self.app_state.is_settings_view = not self.app_state.is_settings_view
        if self.app_state.is_settings_view:
            self.app.settings_button.setText(tr("ui.back_button"))
            self.app.tab_widget.setVisible(False)
            self.app.bottom_widget.setVisible(False)
            self.app.settings_widget.setVisible(True)
            self.customization_service.load_custom_style_settings(
                self.app.color_widgets
            )
            self.app._update_localized_status(
                "status.launcher_settings", UI_COLORS["status_info"]
            )
        else:
            self.app.settings_button.setText(tr("ui.settings_title"))
            self.app.settings_widget.setVisible(False)
            self.app.main_tab_widget.setVisible(True)
            self.app.bottom_widget.setVisible(True)
            self.app.game_launch.update_button_state()

    def _set_combo_data(self, combo, value):
        was_blocked = combo.blockSignals(True)
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                combo.setCurrentIndex(i)
                combo.blockSignals(was_blocked)
                return
        combo.blockSignals(was_blocked)

    @staticmethod
    def _set_value_silently(widget, value) -> None:
        was_blocked = widget.blockSignals(True)
        widget.setValue(value)
        widget.blockSignals(was_blocked)

    @staticmethod
    def _collect_reset_targets(
        section_content,
    ) -> tuple[set, set, list[tuple[QWidget, object]]]:
        config_keys, reset_actions, reset_values = set(), set(), []
        for widget in section_content.findChildren(QWidget):
            if not hasattr(widget, "property"):
                continue
            if key := widget.property("reset_config_key"):
                config_keys.add(key)
            if action := widget.property("reset_action"):
                reset_actions.add(action)
            if widget.property("reset_value") is not None:
                reset_values.append((widget, widget.property("reset_value")))
        return config_keys, reset_actions, reset_values

    def _refresh_after_section_reset(self):
        config = self.app_state.local_config
        self._set_combo_data(self.app.language_combo, config.get("language", "en"))
        if hasattr(self.app, "game_type_combo"):
            game_type = config.get("selected_game_type", "deltarune")
            self._set_combo_data(self.app.game_type_combo, game_type)
            game_def = get_game(game_type)
            self.app_state.game_mode = game_def if game_def else DeltaruneGame()
            on_game_mode_updated_by_state(self.app, self.app_state.game_mode)
        self._set_value_silently(
            self.app.ui_scale_spinbox, int(config.get("ui_scale", 1.0) * 100)
        )
        self._set_value_silently(
            self.app.border_radius_spinbox, int(config.get("custom_border_radius", 7))
        )
        BootstrapCoordinator.restore_ui_state_from_config(self.app)
        self.customization_service.load_custom_style_settings(self.app.color_widgets)
        if hasattr(self.app, "disable_animations_checkbox"):
            self.app.disable_animations_checkbox.setChecked(
                config.get("disable_animations", False)
            )
        if hasattr(self.app, "disable_startup_sound_checkbox"):
            self.app.disable_startup_sound_checkbox.setChecked(
                config.get("disable_startup_sound", False)
            )
        if hasattr(self.app, "pause_background_music_unfocused_checkbox"):
            self.app.pause_background_music_unfocused_checkbox.setChecked(
                config.get("pause_background_music_unfocused", False)
            )
        if hasattr(self.app, "show_reset_buttons_checkbox"):
            self.app.show_reset_buttons_checkbox.setChecked(
                config.get("show_reset_buttons", False)
            )
        if hasattr(self.app, "analytics_opt_in_checkbox"):
            self.app.analytics_opt_in_checkbox.setChecked(
                config.get("analytics_opt_in_enabled", False)
            )
        for attr, key in (
            ("hide_mods_browser_tab_checkbox", "hide_mods_browser_tab"),
            ("hide_library_tab_checkbox", "hide_library_tab"),
        ):
            if hasattr(self.app, attr):
                getattr(self.app, attr).setChecked(config.get(key, False))
        update_settings_library_tab(self.app)
        update_portproton_ui(self.app)
        update_custom_executable_ui(self.app)
        update_checkbox_visibility(self.app)
        self.app._update_section_reset_buttons_visibility()
        self.app.background_music_button.setText(
            self.customization_service.get_background_music_button_text()
        )
        self.app.startup_sound_button.setText(
            self.customization_service.get_startup_sound_button_text()
        )
        self.app.change_font_button.setText(
            self.customization_service.get_font_button_text()
        )
        self.app.change_logo_button.setText(
            self.customization_service.get_logo_button_text()
        )
        if hasattr(self.app, "search_display"):
            self.app.search_display.update_filtered_mods()
        if hasattr(self.app, "library_display"):
            self.app.library_display.update_display()
        self.app.game_launch.update_button_state()

    def reset_section(self, section_key, section_lang_key, section_content):
        config_keys, reset_actions, reset_values = self._collect_reset_targets(
            section_content
        )
        if not self.settings_service.reset_section(
            tr(section_lang_key) if section_lang_key else section_key,
            config_keys,
            reset_actions,
            bool(reset_values),
        ):
            return
        if "background_music" in reset_actions:
            self.customization_service.stop_background_music()
        for widget, value in reset_values:
            if hasattr(widget, "setChecked"):
                widget.setChecked(bool(value))
        self._refresh_after_section_reset()

    def on_language_changed(self, lang):
        self.settings_service.on_language_changed(lang)

    def on_game_type_changed(self, index):
        game_type = self.app.game_type_combo.itemData(index)
        if not game_type:
            return
        self.used_mods_service.save_used_mods_state()
        self.used_mods_service.used_mods.clear()
        game_def = get_game(game_type)
        self.app_state.game_mode = game_def if game_def else DeltaruneGame()
        self.app_state.local_config["selected_game_type"] = game_type
        self.settings_service.write_local_config()
        update_checkbox_visibility(self.app)
        if hasattr(self.used_mods_service, "_update_steam_checkbox_state"):
            self.used_mods_service._update_steam_checkbox_state()

    def on_chapter_mode_changed(self, state):
        if not self.app_state.game_mode.is_multi_tab:
            return
        self.app._previous_mode = getattr(self.app, "current_mode", "normal")
        is_chapter = bool(state)
        mode_changed = (self.app_state.current_mode == "chapter") != is_chapter
        if mode_changed:
            self.used_mods_service.save_used_mods_state()
        self.app_state.current_mode = "chapter" if is_chapter else "normal"
        if mode_changed:
            self.used_mods_service.load_used_mods_state()
        self.app.game_type_combo.setEnabled(not is_chapter)
        if hasattr(self.app, "library_display"):
            self.app.library_display.update_mod_widgets_active_status()
        self.app.game_launch.update_button_state()
        if hasattr(self.app, "chapter_tabs_widget"):
            self.app.chapter_tabs_widget.setVisible(is_chapter)
        self.app_state.selected_chapter_id = None
        if is_chapter:
            if hasattr(self.app, "library_display"):
                self.app.library_display.enter_chapter_mode()
            show_chapter_mode_instruction(self.app)
        elif hasattr(self.app, "library_display"):
            if hasattr(self.app, "installed_mods_layout"):
                from ui.common.styling import clear_layout_widgets

                clear_layout_widgets(self.app.installed_mods_layout, keep_last_n=1)
            self.app.library_display.update_display()
        update_change_path_button_text(self.app)
        self.app_state.local_config["chapter_mode_enabled"] = is_chapter
        self.settings_service.write_local_config()
        if hasattr(self.used_mods_service, "_update_steam_checkbox_state"):
            self.used_mods_service._update_steam_checkbox_state()

    def on_toggle_beta_updates(self):
        self.settings_service.on_toggle_beta_updates(
            self.app.beta_updates_checkbox.isChecked()
        )
        self.app.update_checker.check_for_updates()

    def on_toggle_fullscreen(self, enabled=None):
        fs = self.app.fullscreen_checkbox.isChecked() if enabled is None else bool(enabled)
        self.settings_service.on_toggle_fullscreen(fs)
        (self.app.showFullScreen if fs else self.app.showNormal)()
        self.settings_service.save_window_geometry(self.app)

    def on_toggle_steam_launch(self, state=None):
        is_steam = self.app.launch_via_steam_checkbox.isChecked()
        if (
            is_steam
            and self.app_state.game_mode.block_steam_with_direct_launch
            and self.app_state.current_mode == "chapter"
            and self.app_state.local_config.get("direct_launch_chapter", "")
        ):
            self._safe_show_message(
                "warning", "ui.steam_launch", tr("ui.steam_launch_direct_conflict")
            )
            self.app.launch_via_steam_checkbox.setChecked(False)
            return
        self.settings_service.on_toggle_steam_launch(is_steam)
        update_custom_executable_ui(self.app)
        update_portproton_ui(self.app)

    def on_toggle_portproton(self):
        use = (
            self.app.use_portproton_checkbox.isChecked()
            if hasattr(self.app, "use_portproton_checkbox")
            and self.app.use_portproton_checkbox
            else False
        )
        self.settings_service.on_toggle_portproton(use)
        update_portproton_ui(self.app)

    def on_toggle_dont_hide_window_on_launch(self, state):
        self.settings_service.on_toggle_dont_hide_window_on_launch(bool(state))

    def on_toggle_hide_library_filters(self, state):
        self.settings_service.on_toggle_hide_library_filters(bool(state))
        if hasattr(self.app, "library_tab_builder"):
            self.app.library_tab_builder.set_filters_collapsed(bool(state))

    def on_toggle_show_reset_buttons(self, state):
        self.settings_service.on_toggle_show_reset_buttons(bool(state))
        self.app._update_section_reset_buttons_visibility()

    def on_toggle_disable_animations(self, state):
        self.settings_service.on_toggle_disable_animations(bool(state))

    def on_toggle_disable_background(self, state):
        self.settings_service.on_toggle_disable_background(bool(state))
        if hasattr(self.app, "theme"):
            self.app.theme.update_background_button_state()

    def on_toggle_disable_startup_sound(self, state):
        self.settings_service.on_toggle_disable_startup_sound(bool(state))

    def on_toggle_pause_background_music_unfocused(self, state):
        self.settings_service.on_toggle_pause_background_music_unfocused(bool(state))
        if hasattr(self.app, "_sync_background_audio_focus"):
            self.app._sync_background_audio_focus()

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

    def _update_tab_visibility(self):
        """Dynamically update tab visibility based on settings."""
        if not hasattr(self.app, "main_tab_widget"):
            return

        tab_widget = self.app.main_tab_widget
        hide_mods_browser = self.app_state.local_config.get(
            "hide_mods_browser_tab", False
        )
        hide_library = self.app_state.local_config.get("hide_library_tab", False)

        old_suppress = getattr(self.app, "_suppress_tab_handlers", False)
        self.app._suppress_tab_handlers = True

        try:
            current_index = tab_widget.currentIndex()

            while tab_widget.count() > 0:
                tab_widget.removeTab(0)

            main_tabs_visible = 0
            if not hide_mods_browser and hasattr(self.app, "mods_browser_tab"):
                tab_widget.addTab(self.app.mods_browser_tab, tr("ui.search_tab"))
                main_tabs_visible += 1
            if not hide_library and hasattr(self.app, "library_tab"):
                tab_widget.addTab(
                    self.app.library_tab,
                    get_library_tab_title(self.app.app_state),
                )
                main_tabs_visible += 1

            self.app._num_main_tabs_visible = main_tabs_visible

            if tab_widget.count() > 0:
                if hasattr(self.app, "_restore_main_tabs_bar"):
                    self.app._restore_main_tabs_bar()
                tab_widget.setCurrentIndex(min(current_index, tab_widget.count() - 1))
            elif hasattr(self.app, "_show_empty_main_tabs_placeholder"):
                self.app._show_empty_main_tabs_placeholder()
        finally:
            self.app._suppress_tab_handlers = old_suppress


SettingsController = SettingsUiController
