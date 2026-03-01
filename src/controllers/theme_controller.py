"""Controller for theme management and UI customization."""
from PyQt6.QtWidgets import QApplication
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
        self._debounce_timer = DebounceTimer(delay_ms=150)
        self._last_theme_params = {}

    def apply_theme(self, force=False):
        theme = THEMES['default']
        background_disabled = self.app_state.local_config.get('background_disabled', False)
        new_background_path = None if background_disabled else (self.app_state.local_config.get('custom_background_path') or resource_path(f"assets/{theme.get('background', '')}"))

        user_bg_hex = self.app_state.local_config.get('custom_color_background')
        if user_bg_hex and self.settings_service.is_valid_hex_color(user_bg_hex):
            h = user_bg_hex.lstrip('#')
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            frame_bg_color, tooltip_bg_color = f"rgba({r}, {g}, {b}, 150)", f"rgba({r}, {g}, {b}, 230)"
        else:
            frame_bg_color, tooltip_bg_color = 'rgba(0, 0, 0, 150)', 'rgba(0, 0, 0, 230)'

        button_color = self.app_state.local_config.get('custom_color_button') or theme['colors']['button']
        border_color = self.app_state.local_config.get('custom_color_border') or theme['colors']['border']
        button_hover_color = self.app_state.local_config.get('custom_color_button_hover') or theme['colors']['button_hover']
        main_text_color = self.app_state.local_config.get('custom_color_text') or theme['colors']['text']
        font_family_main = self.app.custom_font_family or theme['font_family']
        zoom_factor = self.app_state.local_config.get('ui_scale', 1.0)

        params = {'bg': frame_bg_color, 'btn': button_color, 'border': border_color, 'hover': button_hover_color, 'text': main_text_color, 'font': font_family_main, 'bg_path': new_background_path, 'bg_disabled': background_disabled, 'ui_scale': zoom_factor}
        if not force and params == self._last_theme_params:
            return
        self._last_theme_params = params

        current_bg_path = getattr(self.app, '_current_background_path', None)
        background_was_disabled = getattr(self.app, '_background_was_disabled', False)
        background_changed = new_background_path != current_bg_path or background_disabled != background_was_disabled
        if background_changed:
            for attr in ('background_movie', 'media_player'):
                if obj := getattr(self.app, attr, None):
                    obj.stop()
                    obj.deleteLater()
                    setattr(self.app, attr, None)
            self.app.video_sink = None
            if background_disabled or new_background_path != current_bg_path:
                self.app.background_pixmap = None
            if not background_disabled and new_background_path:
                self.app._bg_loader = BgLoader(new_background_path, self.app.size())
                self.app._bg_loader.loaded.connect(self.on_background_ready)
                self.app._bg_loader.start()
            self.app._current_background_path = new_background_path
            self.app._background_was_disabled = background_disabled

        self._current_zoom = zoom_factor
        font_size_main, font_size_small = max(1, int(theme['font_size_main'] * zoom_factor)), max(1, int(theme['font_size_small'] * zoom_factor))
        from PyQt6.QtGui import QFont, QColor, QPalette
        status_font = QFont(font_family_main, font_size_small)
        self.app.status_label.setFont(status_font)
        app_font = QFont(font_family_main)
        (QApplication.instance() or self.app).setFont(app_font)
        palette = self.app.palette()
        txt_col = QColor(main_text_color)
        for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
            palette.setColor(role, txt_col)
        (QApplication.instance() or self.app).setPalette(palette)
        for widget, color in [(getattr(self.app, 'telegram_button', None), UI_COLORS['link']), (getattr(self.app, 'discord_button', None), UI_COLORS['social_discord'])]:
            if widget:
                widget.setStyleSheet(f'color: {color};')
        scroll_handle_color = self.app_state.local_config.get('custom_color_button') or 'white'
        checkbox_checked_color = '#ffffff' if not self.app.color_widgets['button_hover'].text() else button_hover_color
        style_sheet = build_stylesheet(frame_bg_color=frame_bg_color, button_color=button_color, border_color=border_color, button_hover_color=button_hover_color, main_text_color=main_text_color, font_family_main=font_family_main, font_size_main=font_size_main, font_size_small=font_size_small, checkbox_checked_color=checkbox_checked_color, scroll_handle_color=scroll_handle_color, tooltip_bg_color=tooltip_bg_color, zoom_factor=zoom_factor)
        app_inst = QApplication.instance()
        (app_inst if isinstance(app_inst, QApplication) else self.app).setStyleSheet(style_sheet)

        from ui.common.styling import get_theme_color
        text_color = get_theme_color(self.app_state.local_config, 'text', 'white')
        if hasattr(self.app, 'plugin_tab_builder') and self.app.plugin_tab_builder is not None:
            plugin_lbl = self.app.plugin_tab_builder.widgets.get('installed_plugins_label')
            if plugin_lbl:
                plugin_lbl.setStyleSheet(f'font-weight: bold; font-size: {max(1, int(16 * zoom_factor))}px; color: {text_color};')
        if hasattr(self.app, 'installed_mods_label') and self.app.installed_mods_label:
            self.app.installed_mods_label.setStyleSheet(f'font-weight: bold; font-size: {max(1, int(16 * zoom_factor))}px; color: {text_color};')

        if hasattr(self.app, 'top_panel_widget') and self.app.top_panel_widget:
            self.app.top_panel_widget.setMinimumHeight(int(65 * zoom_factor))

        if hasattr(self.app, 'logo_placeholder') and self.app.logo_placeholder:
            self.app.logo_placeholder.setFixedSize(int(250 * zoom_factor), int(60 * zoom_factor))

        if hasattr(self.app, 'launcher_icon_label'):
            self.app.launcher_icon_label.setFixedSize(int(250 * zoom_factor), int(60 * zoom_factor))
            self.app.launcher_icon_label.setStyleSheet('background: transparent; padding: 0px;')
            self.customization_service.load_launcher_icon(self.app.launcher_icon_label)

            def _recenter_logo():
                if hasattr(self.app, 'top_panel_widget') and hasattr(self.app, 'launcher_icon_label'):
                    app = self.app
                    ph = app.top_panel_widget.height()
                    lh = app.launcher_icon_label.height()
                    pw = app.top_panel_widget.width()
                    lw = app.launcher_icon_label.width()

                    if not all(isinstance(x, (int, float)) for x in (ph, lh, pw, lw)):
                        return

                    y = max(0, (ph - lh) // 2)
                    app.launcher_icon_label.move((pw - lw) // 2, y)

            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, _recenter_logo)

        search_container = getattr(self.app, 'search_container', None)
        library_container = getattr(self.app, 'installed_mods_container', None)
        self.customization_service.update_translucent_backgrounds(search_container, library_container)

        _zf = zoom_factor
        _tc = text_color

        def _deferred_style_updates():
            if hasattr(self.app, 'search_display') and hasattr(self.app.search_display, 'update_all_cards_labels'):
                self.app.search_display.update_all_cards_labels()
            if hasattr(self.app, 'plugin_display') and hasattr(self.app.plugin_display, '_plugin_widgets'):
                for widget in self.app.plugin_display._plugin_widgets.values():
                    if hasattr(widget, '_update_style'):
                        widget._update_style()
            checkbox_style = f'\n            QCheckBox {{\n                color: {_tc};\n                font-size: {max(1, int(12 * _zf))}px;\n                spacing: {max(1, int(5 * _zf))}px;\n            }}\n            QCheckBox::indicator {{\n                width: {max(1, int(16 * _zf))}px;\n                height: {max(1, int(16 * _zf))}px;\n            }}\n        '
            if hasattr(self.app, 'library_tag_widgets'):
                for cb in self.app.library_tag_widgets:
                    cb.setStyleSheet(checkbox_style)
            if hasattr(self.app, 'chapter_mode_checkbox'):
                self.app.chapter_mode_checkbox.setStyleSheet(f'color: {_tc};')
            if hasattr(self.app, 'full_install_checkbox'):
                self.app.full_install_checkbox.setStyleSheet(f'color: {_tc};')
            if hasattr(self.app, 'tag_textedit'):
                search_checkboxes = [self.app.tag_textedit, self.app.tag_customization, self.app.tag_gameplay, self.app.tag_other]
                for cb in search_checkboxes:
                    if cb:
                        cb.setStyleSheet(checkbox_style)
            if hasattr(self.app, '_update_chapter_tabs_style'):
                self.app._update_chapter_tabs_style()
            if hasattr(self.app, 'library_tab_builder'):
                self.app.library_tab_builder.update_priority_button_style()
            self.update_dynamic_elements()

        QTimer.singleShot(0, _deferred_style_updates)
        self.app.update()

    def on_background_ready(self, obj):
        from PyQt6.QtGui import QMovie, QPixmap
        from PyQt6.QtCore import Qt, QUrl
        import logging
        if isinstance(obj, tuple):
            for attr in ('background_movie', 'media_player'):
                if ob := getattr(self.app, attr, None):
                    ob.stop()
                    ob.deleteLater()
                    setattr(self.app, attr, None)
            self.app.video_sink = None
            self.app.background_pixmap = None

            if obj[0] == 'video':
                try:
                    from PyQt6.QtMultimedia import QMediaPlayer, QVideoSink
                    self.app.video_sink = QVideoSink(self.app)
                    self.app.media_player = QMediaPlayer(self.app)
                    self.app.media_player.setVideoOutput(self.app.video_sink)
                    self.app.media_player.setSource(QUrl.fromLocalFile(obj[1]))
                    self.app.media_player.setLoops(-1)

                    def on_frame_changed(frame):
                        if not frame.isValid():
                            return
                        image = frame.toImage()
                        if not image.isNull():
                            self.app.background_pixmap = QPixmap.fromImage(image).scaled(self.app.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                            self.app.update()

                    self.app.video_sink.videoFrameChanged.connect(on_frame_changed)
                    self.app.media_player.play()
                except Exception as e:
                    logging.error(f'Failed to play video background: {e}', exc_info=True)
            elif obj[0] == 'gif':
                self.app.background_movie = QMovie(obj[1])
                self.app.background_movie.frameChanged.connect(self.app.update)
                self.app.background_movie.start()
            elif obj[0] == 'img':
                self.app.background_pixmap = QPixmap.fromImage(obj[1]).scaled(self.app.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            self.app.update()

    def on_theme_button_click(self):
        from ui.dialogs.theme_dialog import ThemeManagementDialog
        dialog = ThemeManagementDialog(self.app, self)
        dialog.exec()

    def init_theme_list(self):
        from utils.path_utils import resource_path, get_user_themes_dir
        import os

        user_dir = get_user_themes_dir()
        os.makedirs(user_dir, exist_ok=True)
        self.app.themes_list_widget.clear()

        themes = {f[:-4] for d in (resource_path('assets/themes'), user_dir) if os.path.exists(d) for f in os.listdir(d) if f.lower().endswith('.zip')}
        self.app.themes_list_widget.addItems(sorted(themes))

        try:
            self.app.themes_list_widget.currentTextChanged.connect(self._update_theme_delete_button_state)
        except TypeError:
            pass
        self._update_theme_delete_button_state(self.app.themes_list_widget.currentText())

    def _update_theme_delete_button_state(self, theme_name: str):
        if hasattr(self.app, 'theme_delete_btn') and theme_name:
            from utils.path_utils import resource_path
            import os
            self.app.theme_delete_btn.setEnabled(not os.path.exists(resource_path(f'assets/themes/{theme_name}.zip')))

    def on_theme_apply_clicked(self):
        theme_name = self.app.themes_list_widget.currentText()
        if not theme_name:
            return
        import os
        from utils.path_utils import resource_path, get_user_themes_dir

        for p in (os.path.join(get_user_themes_dir(), f'{theme_name}.zip'), resource_path(f'assets/themes/{theme_name}.zip')):
            if os.path.exists(p):
                return self.settings_service._install_theme_from_file(p)

    def on_theme_save_clicked(self):
        from PyQt6.QtWidgets import QInputDialog
        from utils.path_utils import get_user_themes_dir
        import os
        import json
        import zipfile
        name, ok = QInputDialog.getText(self.app, tr('dialogs.theme_save_title'), tr('dialogs.theme_save_prompt'))
        name = "".join(x for x in (name if ok else "") if x.isalnum() or x in " _-")
        if not name:
            return

        themes_dir = get_user_themes_dir()
        os.makedirs(themes_dir, exist_ok=True)

        settings = {k: self.app_state.local_config.get(k, '') for k in ('custom_color_background', 'custom_color_button', 'custom_color_border', 'custom_color_button_hover', 'custom_color_text', 'custom_color_version_text')}
        settings.update({k: self.app_state.local_config.get(k, False) for k in ('background_disabled', 'disable_splash', 'disable_animations')})

        try:
            with zipfile.ZipFile(os.path.join(themes_dir, f'{name}.zip'), 'w') as zipf:
                zipf.writestr('theme.json', json.dumps(settings, indent=2))
                assets = [('custom_background_path', 'background')]
                if hasattr(self.app, 'customization_service'):
                    cs = self.app.customization_service
                    assets += [(cs.get_background_music_path(), 'background_music'), (cs.get_startup_sound_path(), 'startup_sound'), (cs.get_custom_logo_path(), 'custom_logo'), (cs.get_custom_font_path(), 'custom_font')]
                for src, dest_name in assets:
                    path = self.app_state.local_config.get(src) if isinstance(src, str) else src
                    if path and os.path.isfile(path):
                        zipf.write(path, f'{dest_name}{os.path.splitext(path)[1]}')
            self.init_theme_list()
            self.feedback_service.show_message('info', 'dialogs.success', tr('dialogs.theme_exported_success'))
        except Exception as e:
            import logging
            logging.error(f"Failed to export theme: {e}")

    def on_theme_delete_clicked(self):
        theme_name = self.app.themes_list_widget.currentText()
        if not theme_name:
            return
        import os
        from utils.path_utils import resource_path, get_user_themes_dir

        if os.path.exists(resource_path(f'assets/themes/{theme_name}.zip')):
            return self.feedback_service.show_message('warning', 'dialogs.error', tr('errors.cannot_delete_builtin_theme', 'Cannot delete a built-in theme.'))

        theme_path = os.path.join(get_user_themes_dir(), f'{theme_name}.zip')
        if os.path.exists(theme_path) and self.feedback_service.ask_question('dialogs.theme_delete_title', tr('dialogs.theme_delete_prompt', theme=theme_name)):
            try:
                os.remove(theme_path)
                self.init_theme_list()
            except Exception as e:
                import logging
                logging.error(f"Failed to delete theme: {e}")

    def on_theme_changed_by_service(self):
        self._reload_custom_font()
        if hasattr(self.app, 'change_font_button'):
            self.app.change_font_button.setText(self.customization_service.get_font_button_text())
        self.customization_service.load_custom_style_settings(self.app.color_widgets, self.apply_theme)
        self.app.disable_background_checkbox.setChecked(self.app_state.local_config.get('background_disabled', False))
        self.app.disable_splash_checkbox.setChecked(self.app_state.local_config.get('disable_splash', False))
        if hasattr(self.app, 'disable_animations_checkbox'):
            self.app.disable_animations_checkbox.setChecked(self.app_state.local_config.get('disable_animations', False))
        self.app.background_music_button.setText(self.customization_service.get_background_music_button_text())
        self.app.startup_sound_button.setText(self.customization_service.get_startup_sound_button_text())
        self.update_background_button_state()
        self.update_logo_button_state()
        if hasattr(self.app, 'launcher_icon_label'):
            self.customization_service.load_launcher_icon(self.app.launcher_icon_label)

        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, self._handle_music_after_theme_change)

    def _handle_music_after_theme_change(self):
        try:
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
        except Exception as e:
            import logging
            logging.error(f'ThemeController: Error handling music after theme change: {e}', exc_info=True)

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
                        zoom_factor = self.app_state.local_config.get('ui_scale', 1.0)
                        filters.setStyleSheet(f'QFrame#filters {{ background-color: {filter_bg_color}; border: {max(1, int(2 * zoom_factor))}px solid {filter_border_color}; padding: {int(8 * zoom_factor)}px; }}')
        mod_list = getattr(self.app, 'mod_list_widget', None)
        installed_mods = getattr(self.app, 'installed_mods_widget', None)
        self.customization_service.update_mod_cards_styles(mod_list, installed_mods)
        if hasattr(self.app, 'library_tab_builder'):
            self.app.library_tab_builder.update_priority_button_style()
        section_lines = getattr(self.app, '_section_lines', None)
        if isinstance(section_lines, list) and section_lines:
            from ui.common.styling import get_section_line_color
            line_style = f'color: {get_section_line_color(self.app_state.local_config)};'
            for line_frame in section_lines:
                try:
                    line_frame.setStyleSheet(line_style)
                except RuntimeError:
                    pass

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

    def update_logo_button_state(self):
        if hasattr(self.app, 'change_logo_button'):
            self.app.change_logo_button.setText(self.customization_service.get_logo_button_text())

    def _reload_custom_font(self):
        """Reload custom font from disk, or fall back to language default."""
        import os
        from PyQt6.QtGui import QFontDatabase
        from services.localization_service import localization_service
        custom_f_path = self.customization_service.get_custom_font_path()
        if custom_f_path and os.path.exists(custom_f_path):
            f_id = QFontDatabase.addApplicationFont(custom_f_path)
            families = QFontDatabase.applicationFontFamilies(f_id) if f_id != -1 else []
            self.app.custom_font_family = families[0] if families else localization_service.load_font()
        else:
            self.app.custom_font_family = localization_service.load_font()
