"""Controller for theme management and UI customization."""
from PyQt6.QtWidgets import QApplication, QMessageBox
from services.localization_service import tr
from config.constants import THEMES, UI_COLORS
from utils.path_utils import resource_path
from workers.background_loader_worker import BgLoader
from ui.styles import build_stylesheet
from ui.utils.ui_utils import DebounceTimer


class ThemeController:
    """Manages theme application and UI customization operations."""

    def __init__(self, app_state, feedback_service, settings_service, customization_service, app_window):
        self.app_state = app_state
        self.feedback_service = feedback_service
        self.settings_service = settings_service
        self.customization_service = customization_service
        self.app = app_window
        self._debounce_timer = DebounceTimer(delay_ms=400)

    def apply_theme(self):
        theme = THEMES['default']
        background_disabled = self.app_state.local_config.get('background_disabled', False)
        new_background_path = None
        if not background_disabled:
            new_background_path = self.app_state.local_config.get('custom_background_path') or resource_path(f"assets/{theme.get('background', '')}")
        current_bg_path = getattr(self.app, '_current_background_path', None)
        background_was_disabled = getattr(self.app, '_background_was_disabled', False)
        background_changed = new_background_path != current_bg_path or background_disabled != background_was_disabled
        if background_changed:
            if self.app.background_movie is not None:
                self.app.background_movie.stop()
                self.app.background_movie.deleteLater()
                self.app.background_movie = None
            if background_disabled or new_background_path != current_bg_path:
                self.app.background_pixmap = None
            if not background_disabled and new_background_path:
                self.app._bg_loader = BgLoader(new_background_path, self.app.size())
                self.app._bg_loader.loaded.connect(self.on_background_ready)
                self.app._bg_loader.start()
            self.app._current_background_path = new_background_path
            self.app._background_was_disabled = background_disabled
        user_bg_hex = self.app_state.local_config.get('custom_color_background')
        if user_bg_hex and self.settings_service.is_valid_hex_color(user_bg_hex):
            frame_bg_color = f"#C0{user_bg_hex.lstrip('#')}"
        else:
            frame_bg_color = 'rgba(0, 0, 0, 150)'
        button_color = self.app_state.local_config.get('custom_color_button') or theme['colors']['button']
        border_color = self.app_state.local_config.get('custom_color_border') or theme['colors']['border']
        button_hover_color = self.app_state.local_config.get('custom_color_button_hover') or theme['colors']['button_hover']
        main_text_color = self.app_state.local_config.get('custom_color_text') or theme['colors']['text']
        base_family = self.app.custom_font_family or theme['font_family']
        font_family_main = base_family
        font_size_main = theme['font_size_main']
        font_size_small = theme['font_size_small']
        from PyQt6.QtGui import QFont
        status_font = QFont(font_family_main, font_size_small)
        self.app.status_label.setFont(status_font)
        from PyQt6.QtGui import QColor, QPalette
        palette = self.app.palette()
        txt_col = QColor(main_text_color)
        palette.setColor(QPalette.ColorRole.WindowText, txt_col)
        palette.setColor(QPalette.ColorRole.Text, txt_col)
        palette.setColor(QPalette.ColorRole.ButtonText, txt_col)
        (QApplication.instance() or self.app).setPalette(palette)
        explicit_color_widgets = [getattr(self.app, 'telegram_button', None), getattr(self.app, 'discord_button', None)]
        explicit_colors = [UI_COLORS['link'], UI_COLORS['social_discord']]
        for widget, color in zip(explicit_color_widgets, explicit_colors):
            if widget is not None:
                widget.setStyleSheet(f'color: {color};')
        scroll_handle_color = self.app_state.local_config.get('custom_color_button') or 'white'
        checkbox_checked_color = '#ffffff' if not self.app.color_widgets['button_hover'].text() else button_hover_color
        style_sheet = build_stylesheet(frame_bg_color=frame_bg_color, button_color=button_color, border_color=border_color, button_hover_color=button_hover_color, main_text_color=main_text_color, font_family_main=font_family_main, font_size_main=font_size_main, font_size_small=font_size_small, checkbox_checked_color=checkbox_checked_color, scroll_handle_color=scroll_handle_color)
        app_inst = QApplication.instance()
        (app_inst if isinstance(app_inst, QApplication) else self.app).setStyleSheet(style_sheet)
        if hasattr(self.app, 'search_display') and hasattr(self.app.search_display, 'update_all_cards_labels'):
            self.app.search_display.update_all_cards_labels()
        if hasattr(self.app, 'plugin_display') and hasattr(self.app.plugin_display, '_plugin_widgets'):
            for widget in self.app.plugin_display._plugin_widgets.values():
                if hasattr(widget, '_update_style'):
                    widget._update_style()
        from ui.common.styling import get_theme_color
        text_color = get_theme_color(self.app_state.local_config, 'text', 'white')
        if hasattr(self.app, 'plugin_tab_builder') and self.app.plugin_tab_builder is not None:
            plugin_lbl = self.app.plugin_tab_builder.widgets.get('installed_plugins_label')
            if plugin_lbl:
                plugin_lbl.setStyleSheet(f'font-weight: bold; font-size: 16px; color: {text_color};')
        if hasattr(self.app, 'installed_mods_label') and self.app.installed_mods_label:
            self.app.installed_mods_label.setStyleSheet(f'font-weight: bold; font-size: 16px; color: {text_color};')
        checkbox_style = f'\n            QCheckBox {{\n                color: {text_color};\n                font-size: 12px;\n                spacing: 5px;\n            }}\n            QCheckBox::indicator {{\n                width: 16px;\n                height: 16px;\n            }}\n        '
        if hasattr(self.app, 'library_tag_widgets'):
            for cb in self.app.library_tag_widgets:
                cb.setStyleSheet(checkbox_style)
        if hasattr(self.app, 'chapter_mode_checkbox'):
            self.app.chapter_mode_checkbox.setStyleSheet(f'color: {text_color};')
        if hasattr(self.app, 'full_install_checkbox'):
            self.app.full_install_checkbox.setStyleSheet(f'color: {text_color};')
        if hasattr(self.app, 'tag_textedit'):
            search_checkboxes = [self.app.tag_textedit, self.app.tag_customization, self.app.tag_gameplay, self.app.tag_other]
            if hasattr(self.app, 'auto_sorting_checkbox'):
                search_checkboxes.append(self.app.auto_sorting_checkbox)
            for cb in search_checkboxes:
                if cb:
                    cb.setStyleSheet(checkbox_style)
        search_container = getattr(self.app, 'search_container', None)
        library_container = getattr(self.app, 'installed_mods_container', None)
        self.customization_service.update_translucent_backgrounds(search_container, library_container)
        if hasattr(self.app, '_update_chapter_tabs_style'):
            self.app._update_chapter_tabs_style()
        if hasattr(self.app, 'library_tab_builder'):
            self.app.library_tab_builder.update_priority_button_style()
        self.update_dynamic_elements()
        self.app.update()

    def on_background_ready(self, obj):
        from PyQt6.QtGui import QMovie, QPixmap
        from PyQt6.QtCore import Qt
        if isinstance(obj, tuple):
            if obj[0] == 'gif':
                if self.app.background_movie is not None:
                    self.app.background_movie.stop()
                    self.app.background_movie.deleteLater()
                self.app.background_movie = QMovie(obj[1])
                self.app.background_movie.frameChanged.connect(self.app.update)
                self.app.background_movie.start()
                self.app.background_pixmap = None
            elif obj[0] == 'img':
                self.app.background_movie = None
                self.app.background_pixmap = QPixmap.fromImage(obj[1]).scaled(self.app.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            self.app.update()

    def on_theme_button_click(self):
        result = self.feedback_service.ask_custom_question(QMessageBox.Icon.Information, 'buttons.theme_management', 'dialogs.theme_choice', [('buttons.import', QMessageBox.ButtonRole.AcceptRole, 'import'), ('buttons.export', QMessageBox.ButtonRole.AcceptRole, 'export')])
        if result == 'import':
            self.settings_service.import_theme()
        elif result == 'export':
            self.settings_service.export_theme()

    def on_theme_changed_by_service(self):
        self.customization_service.load_custom_style_settings(self.app.color_widgets, self.apply_theme)
        self.app.disable_background_checkbox.setChecked(self.app_state.local_config.get('background_disabled', False))
        self.app.disable_splash_checkbox.setChecked(self.app_state.local_config.get('disable_splash', False))
        self.app.background_music_button.setText(self.customization_service.get_background_music_button_text())
        self.app.startup_sound_button.setText(self.customization_service.get_startup_sound_button_text())
        self.update_logo_button_state()
        if hasattr(self.app, 'launcher_icon_label'):
            self.customization_service.load_launcher_icon(self.app.launcher_icon_label)
        current_music_path = self.customization_service.get_background_music_path()
        if not current_music_path:
            self.customization_service.stop_background_music()
        else:
            should_restart = True
            if hasattr(self.customization_service, '_current_music_path'):
                if self.customization_service._current_music_path == current_music_path:
                    if hasattr(self.customization_service, '_bg_music_thread') and self.customization_service._bg_music_thread is not None and self.customization_service._bg_music_thread.isRunning():
                        should_restart = False
            if should_restart:
                self.customization_service.stop_background_music()
                self.customization_service.maybe_start_background_music(force=True)

    def on_custom_style_edited(self):
        self.settings_service.on_custom_style_edited(self.app.color_widgets)
        self._debounce_timer.call(self.apply_theme)

    def update_dynamic_elements(self):
        if hasattr(self.app, 'sort_combo') and hasattr(self.app, 'sort_order_btn'):
            search_tab = None
            for i in range(self.app.tab_widget.count()):
                if self.app.tab_widget.tabText(i) == tr('ui.search_tab'):
                    search_tab = self.app.tab_widget.widget(i)
                    break
            if search_tab:
                layout = search_tab.layout()
                if layout and layout.count() > 0:
                    item0 = layout.itemAt(0)
                    filters = item0.widget() if item0 is not None else None
                    if filters and filters.objectName() == 'filters':
                        filter_bg_color = self.app_state.local_config.get('custom_color_background') or 'rgba(0, 0, 0, 150)'
                        filter_border_color = self.app_state.local_config.get('custom_color_border') or 'white'
                        filters.setStyleSheet(f'QFrame#filters {{ background-color: {filter_bg_color}; border: 2px solid {filter_border_color}; padding: 8px; }}')
        mod_list = getattr(self.app, 'mod_list_widget', None)
        installed_mods = getattr(self.app, 'installed_mods_widget', None)
        self.customization_service.update_mod_cards_styles(mod_list, installed_mods)
        if hasattr(self.app, 'library_tab_builder'):
            self.app.library_tab_builder.update_priority_button_style()

    def on_background_button_click(self):
        self.settings_service.on_background_button_click()
        self.update_background_button_state()

    def update_background_button_state(self):
        background_disabled = self.app_state.local_config.get('background_disabled', False)
        self.app.change_background_button.setEnabled(not background_disabled)
        self.app.change_background_button.setText(tr('buttons.remove_background') if self.app_state.local_config.get('custom_background_path') else tr('buttons.change_background'))

    def on_background_music_button_click(self):
        self.customization_service.stop_background_music()
        self.settings_service.on_background_music_button_click()
        self.app.background_music_button.setText(self.customization_service.get_background_music_button_text())
        self.customization_service.maybe_start_background_music(force=True)

    def on_startup_sound_button_click(self):
        self.settings_service.on_startup_sound_button_click()
        self.app.startup_sound_button.setText(self.customization_service.get_startup_sound_button_text())

    def on_logo_button_click(self):
        self.settings_service.on_logo_button_click()
        self.update_logo_button_state()
        if hasattr(self.app, 'launcher_icon_label'):
            self.customization_service.load_launcher_icon(self.app.launcher_icon_label)

    def update_logo_button_state(self):
        if hasattr(self.app, 'change_logo_button'):
            self.app.change_logo_button.setText(self.customization_service.get_logo_button_text())
