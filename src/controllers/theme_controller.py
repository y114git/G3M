"""Controller for theme management and UI customization."""

import contextlib

from PyQt6.QtCore import QSize
from PyQt6.QtWidgets import QWIDGETSIZE_MAX, QApplication

from app.game_ui import update_chapter_tabs_style
from config.config import DEFAULT_COLORS, DEFAULT_THEME, QSS_TRANSPARENT_NOPAD
from config.style_loader import build_stylesheet, invalidate_stylesheet_cache
from services.localization_service import localization_service, tr
from ui.common.styling import get_border_radius, rgba_from_color
from ui.utils.ui_utils import DebounceTimer
from utils.path_utils import resource_path
from workers.background_loader_worker import BgLoader


class ThemeController:
    """Manages theme application and UI customization operations."""

    def __init__(
        self,
        app_state,
        feedback_service,
        settings_service,
        customization_service,
        app_window,
    ) -> None:
        self.app_state = app_state
        self.feedback_service = feedback_service
        self.settings_service = settings_service
        self.customization_service = customization_service
        self.app = app_window
        self._debounce_timer = DebounceTimer(delay_ms=150)
        self._last_theme_params = {}
        self._theme_update_in_progress = False
        self._pending_theme_update = False

    def apply_theme(self, force=False):
        theme = DEFAULT_THEME
        background_disabled = self.app_state.local_config.get(
            "background_disabled", False
        )
        new_background_path = (
            None
            if background_disabled
            else (
                self.app_state.local_config.get("custom_background_path")
                or resource_path(f"assets/{theme.get('background', '')}")
            )
        )

        user_bg_hex = self.app_state.local_config.get("custom_background_color")
        if user_bg_hex and self.settings_service.is_valid_hex_color(user_bg_hex):
            frame_bg_color = rgba_from_color(
                user_bg_hex, alpha=150, fallback="rgba(40, 40, 40, 150)"
            )
            tooltip_bg_color = rgba_from_color(
                user_bg_hex, alpha=230, fallback="rgba(40, 40, 40, 230)"
            )
        else:
            frame_bg_color, tooltip_bg_color = (
                "rgba(40, 40, 40, 150)",
                "rgba(40, 40, 40, 230)",
            )

        elements_color = (
            self.app_state.local_config.get("custom_elements_color")
            or theme["colors"]["elements"]
        )
        border_color = (
            self.app_state.local_config.get("custom_border_color")
            or theme["colors"]["border"]
        )
        hover_color = (
            self.app_state.local_config.get("custom_hover_color")
            or theme["colors"]["hover"]
        )
        select_color = (
            self.app_state.local_config.get("custom_select_color")
            or theme["colors"]["select"]
        )
        main_text_color = (
            self.app_state.local_config.get("custom_main_text_color")
            or theme["colors"]["main_text"]
        )
        disabled_bg = (
            self.app_state.local_config.get("custom_disabled_bg")
            or theme["colors"].get("disabled_bg", "#333333")
        )
        disabled_text = (
            self.app_state.local_config.get("custom_disabled_text")
            or theme["colors"].get("disabled_text", "#888888")
        )
        disabled_border = (
            self.app_state.local_config.get("custom_disabled_border")
            or theme["colors"].get("disabled_border", "#555555")
        )
        font_family_main = (
            self.app.custom_font_family
            or localization_service.load_font()
            or theme["font_family"]
        )
        zoom_factor = self.app_state.local_config.get("ui_scale", 1.0)

        secondary_text_color = self.app_state.local_config.get("custom_secondary_text_color")
        border_radius_value = get_border_radius(self.app_state.local_config)
        custom_border_radius = f"{border_radius_value}px"
        params = {
            "bg": frame_bg_color,
            "elements": elements_color,
            "border": border_color,
            "hover": hover_color,
            "select": select_color,
            "main_text": main_text_color,
            "secondary_text": secondary_text_color,
            "font": font_family_main,
            "bg_path": new_background_path,
            "bg_disabled": background_disabled,
            "ui_scale": zoom_factor,
            "border_radius": border_radius_value,
        }
        should_invalidate_caches = force or params != self._last_theme_params
        if should_invalidate_caches:
            from ui.common.styling import invalidate_theme_color_cache

            invalidate_theme_color_cache()
            invalidate_stylesheet_cache()
            self._last_theme_params = dict(params)

        current_bg_path = getattr(self.app, "_current_background_path", None)
        background_was_disabled = getattr(self.app, "_background_was_disabled", False)
        background_changed = (
            new_background_path != current_bg_path
            or background_disabled != background_was_disabled
        )
        if background_changed:
            self._cleanup_background_media()
            if background_disabled or new_background_path != current_bg_path:
                self.app.background_pixmap = None
            if not background_disabled and new_background_path:
                self.app._bg_loader = BgLoader(new_background_path, self.app.size())
                self.app._bg_loader.loaded.connect(self.on_background_ready)
                self.app._bg_loader.start()
            self.app._current_background_path = new_background_path
            self.app._background_was_disabled = background_disabled

        self._current_zoom = zoom_factor

        def scale(x):
            return max(1, int(x * zoom_factor))

        font_size_main, font_size_small = (
            scale(theme["font_size_main"]),
            scale(theme["font_size_small"]),
        )
        from PyQt6.QtGui import QColor, QFont, QPalette

        status_font = QFont(font_family_main, font_size_small)
        self.app.status_label.setFont(status_font)
        app_font = QFont(font_family_main)
        (QApplication.instance() or self.app).setFont(app_font)
        palette = self.app.palette()
        txt_col = QColor(main_text_color)
        for role in (
            QPalette.ColorRole.WindowText,
            QPalette.ColorRole.Text,
            QPalette.ColorRole.ButtonText,
        ):
            palette.setColor(role, txt_col)
        (QApplication.instance() or self.app).setPalette(palette)
        scroll_handle_color = (
            self.app_state.local_config.get("custom_elements_color")
            or DEFAULT_COLORS["main_text"]
        )
        style_sheet = build_stylesheet(
            frame_bg_color=frame_bg_color,
            elements_color=elements_color,
            border_color=border_color,
            hover_color=hover_color,
            select_color=select_color,
            main_text_color=main_text_color,
            disabled_bg=disabled_bg,
            disabled_text=disabled_text,
            disabled_border=disabled_border,
            font_family_main=font_family_main,
            font_size_main=font_size_main,
            font_size_small=font_size_small,
            scroll_handle_color=scroll_handle_color,
            tooltip_bg_color=tooltip_bg_color,
            zoom_factor=zoom_factor,
            custom_border_radius=custom_border_radius,
        )
        for fs in self._iter_filter_scrolls():
            fs.setMaximumHeight(QWIDGETSIZE_MAX)
        app_inst = QApplication.instance()
        (app_inst if isinstance(app_inst, QApplication) else self.app).setStyleSheet(
            style_sheet
        )
        if hasattr(self.app, "_last_tooltip_size_key"):
            self.app._last_tooltip_size_key = None

        from ui.common.styling import get_theme_color

        text_color = get_theme_color(self.app_state.local_config, "main_text")
        bold_label_style = (
            f"font-weight: bold; font-size: {scale(16)}px; color: {text_color};"
        )
        if self.app.installed_mods_label:
            self.app.installed_mods_label.setStyleSheet(bold_label_style)

        if hasattr(self.app, "title_bar") and self.app.title_bar:
            self.app.title_bar.apply_metrics(zoom_factor)
            self._refresh_title_bar_styles()
        if hasattr(self.app, "_apply_window_corner_mask"):
            self.app._apply_window_corner_mask()
        self.app.top_panel_widget.setMinimumHeight(scale(65))
        self.app.logo_placeholder.setFixedSize(scale(250), scale(60))
        btn_size = scale(40)
        icon_size_social = scale(32)
        social_style = f"padding: {scale(4)}px; min-width: {btn_size}px; min-height: {btn_size}px; max-width: {btn_size}px; max-height: {btn_size}px;"
        for btn_attr in ("telegram_button", "discord_button"):
            btn = getattr(self.app, btn_attr, None)
            if btn:
                btn.setFixedSize(btn_size, btn_size)
                btn.setIconSize(QSize(icon_size_social, icon_size_social))
                btn.setStyleSheet(social_style)

        from PyQt6.QtCore import QTimer

        if hasattr(self.app, "launcher_icon_label"):
            self.app.launcher_icon_label.setFixedSize(scale(250), scale(60))
            self.app.launcher_icon_label.setStyleSheet(QSS_TRANSPARENT_NOPAD)
            self.customization_service.load_launcher_icon(self.app.launcher_icon_label)

            def _recenter_logo():
                if hasattr(self.app, "top_panel_widget") and hasattr(
                    self.app, "launcher_icon_label"
                ):
                    app = self.app
                    ph = app.top_panel_widget.height()
                    lh = app.launcher_icon_label.height()
                    pw = app.top_panel_widget.width()
                    lw = app.launcher_icon_label.width()

                    if not all(isinstance(x, (int, float)) for x in (ph, lh, pw, lw)):
                        return

                    y = max(0, (ph - lh) // 2)
                    app.launcher_icon_label.move((pw - lw) // 2, y)

            QTimer.singleShot(0, _recenter_logo)

        search_container = getattr(self.app, "search_container", None)
        library_container = getattr(self.app, "installed_mods_container", None)
        self.customization_service.update_translucent_backgrounds(
            search_container, library_container, None
        )

        from ui.common.styling import build_tag_checkbox_style

        checkbox_style = build_tag_checkbox_style(
            text_color, font_size=scale(14), indicator_size=scale(18), spacing=scale(5)
        )
        color_only_style = f"color: {text_color};"

        def _deferred_style_updates():
            if hasattr(self.app, "search_display") and hasattr(
                self.app.search_display, "update_all_cards_labels"
            ):
                self.app.search_display.update_all_cards_labels()
            for cb in getattr(self.app, "library_tag_widgets", ()):
                cb.setStyleSheet(checkbox_style)
            for attr in ("chapter_mode_checkbox", "full_install_checkbox"):
                w = getattr(self.app, attr, None)
                if w:
                    w.setStyleSheet(color_only_style)
            for attr in (
                "tag_textedit",
                "tag_customization",
                "tag_gameplay",
                "tag_other",
            ):
                w = getattr(self.app, attr, None)
                if w:
                    w.setStyleSheet(checkbox_style)
            update_chapter_tabs_style(self.app)
            if hasattr(self.app, "library_tab_builder"):
                self.app.library_tab_builder.update_priority_button_style()
            summary = getattr(self.app, "mod_summary_panel", None)
            if summary and hasattr(summary, "refresh_theme"):
                summary.refresh_theme()
            elif summary and hasattr(summary, "apply_theme"):
                summary.apply_theme()
            for dialog_attr in (
                "_game_versions_dialog",
                "_mod_versions_dialog",
                "_downloads_dialog",
                "_modding_tools_dialog",
            ):
                dialog = getattr(self.app, dialog_attr, None)
                if not dialog or not hasattr(dialog, "refresh_theme"):
                    continue
                with contextlib.suppress(RuntimeError):
                    dialog.refresh_theme()
            self.update_dynamic_elements()
            self._resync_filter_scroll_heights()

        QTimer.singleShot(0, _deferred_style_updates)
        self.app.update()

    def _refresh_title_bar_styles(self):
        title_bar = getattr(self.app, "title_bar", None)
        if not title_bar:
            return
        widgets = [title_bar]
        title_bar_attrs = vars(title_bar) if hasattr(title_bar, "__dict__") else {}
        for attr_name in (
            "left_widget",
            "right_widget",
            "help_button",
            "minimize_button",
            "maximize_button",
            "close_button",
        ):
            widget = title_bar_attrs.get(attr_name)
            if widget is not None:
                widgets.append(widget)
        seen = set()
        for widget in widgets:
            widget_id = id(widget)
            if widget_id in seen:
                continue
            seen.add(widget_id)
            try:
                style = widget.style()
                if style is not None:
                    style.unpolish(widget)
                    style.polish(widget)
                widget.update()
            except (AttributeError, RuntimeError):
                continue

    def _iter_filter_scrolls(self):
        for attr in ("library_tab_builder", "search_tab_builder"):
            builder = getattr(self.app, attr, None)
            if builder:
                widgets = getattr(builder, "widgets", None)
                if not widgets:
                    continue
                fs = widgets.get("filters_scroll")
                if fs:
                    yield fs

    def _cleanup_background_media(self):
        for attr in ("background_movie", "media_player"):
            if obj := getattr(self.app, attr, None):
                obj.stop()
                obj.deleteLater()
                setattr(self.app, attr, None)
        self.app.video_sink = None

    def _resync_filter_scroll_heights(self):
        for fs in self._iter_filter_scrolls():
            w = fs.widget()
            if w:
                w.adjustSize()

    def on_background_ready(self, obj):
        import logging

        from PyQt6.QtCore import Qt, QUrl
        from PyQt6.QtGui import QMovie, QPixmap

        if isinstance(obj, tuple):
            self._cleanup_background_media()
            self.app.background_pixmap = None

            if obj[0] == "video":
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
                            self.app.background_pixmap = QPixmap.fromImage(
                                image
                            ).scaled(
                                self.app.size(),
                                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                Qt.TransformationMode.SmoothTransformation,
                            )
                            self.app.update()

                    self.app.video_sink.videoFrameChanged.connect(on_frame_changed)
                    self.app.media_player.play()
                except Exception as e:
                    logging.error(
                        f"Failed to play video background: {e}", exc_info=True
                    )
            elif obj[0] == "gif":
                self.app.background_movie = QMovie(obj[1])
                self.app.background_movie.frameChanged.connect(self.app.update)
                self.app.background_movie.start()
            elif obj[0] == "img":
                self.app.background_pixmap = QPixmap.fromImage(obj[1]).scaled(
                    self.app.size(),
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
            self.app.update()

    def on_theme_button_click(self):
        from ui.dialogs.theme_dialog import ThemeManagementDialog

        dialog = ThemeManagementDialog(self.app, self)
        dialog.exec()

    def init_theme_list(self):
        import os

        from utils.path_utils import get_user_themes_dir, resource_path

        user_dir = get_user_themes_dir()
        os.makedirs(user_dir, exist_ok=True)
        self.app.themes_list_widget.clear()

        themes = {
            f[:-4]
            for d in (resource_path("assets/themes"), user_dir)
            if os.path.exists(d)
            for f in os.listdir(d)
            if f.lower().endswith(".zip")
        }
        self.app.themes_list_widget.addItems(sorted(themes))

        with contextlib.suppress(TypeError):
            self.app.themes_list_widget.currentTextChanged.connect(
                self._update_theme_delete_button_state
            )
        self._update_theme_delete_button_state(
            self.app.themes_list_widget.currentText()
        )

    def _update_theme_delete_button_state(self, theme_name: str):
        if hasattr(self.app, "theme_delete_btn") and theme_name:
            import os

            from utils.path_utils import resource_path

            self.app.theme_delete_btn.setEnabled(
                not os.path.exists(resource_path(f"assets/themes/{theme_name}.zip"))
            )

    def on_theme_apply_clicked(self):
        theme_name = self.app.themes_list_widget.currentText()
        if not theme_name:
            return
        import os

        from utils.path_utils import get_user_themes_dir, resource_path

        for p in (
            os.path.join(get_user_themes_dir(), f"{theme_name}.zip"),
            resource_path(f"assets/themes/{theme_name}.zip"),
        ):
            if os.path.exists(p):
                return self.settings_service._install_theme_from_file(p)

    def on_theme_save_clicked(self):
        import os

        from PyQt6.QtWidgets import QInputDialog

        from utils.path_utils import get_user_themes_dir

        name, ok = QInputDialog.getText(
            self.app, tr("dialogs.theme_save_title"), tr("dialogs.theme_save_prompt")
        )
        name = "".join(x for x in (name if ok else "") if x.isalnum() or x in " _-")
        if not name:
            return

        themes_dir = get_user_themes_dir()
        os.makedirs(themes_dir, exist_ok=True)

        try:
            self.settings_service.write_theme_archive(
                os.path.join(themes_dir, f"{name}.zip")
            )
            self.init_theme_list()
            self.feedback_service.show_message(
                "info", "dialogs.success", tr("dialogs.theme_exported_success")
            )
        except Exception as e:
            import logging

            logging.error(f"Failed to export theme: {e}")

    def on_theme_delete_clicked(self):
        theme_name = self.app.themes_list_widget.currentText()
        if not theme_name:
            return
        import os

        from utils.path_utils import get_user_themes_dir, resource_path

        if os.path.exists(resource_path(f"assets/themes/{theme_name}.zip")):
            return self.feedback_service.show_message(
                "warning",
                "dialogs.error",
                tr(
                    "errors.cannot_delete_builtin_theme",
                    "Cannot delete a built-in theme.",
                ),
            )

        theme_path = os.path.join(get_user_themes_dir(), f"{theme_name}.zip")
        if os.path.exists(theme_path) and self.feedback_service.ask_question(
            "dialogs.theme_delete_title",
            tr("dialogs.theme_delete_prompt", theme=theme_name),
        ):
            try:
                os.remove(theme_path)
                self.init_theme_list()
            except Exception as e:
                import logging

                logging.error(f"Failed to delete theme: {e}")

    def on_theme_changed_by_service(self):
        self._debounce_timer.call(self._apply_theme_change)

    def _apply_theme_change(self):
        if self._theme_update_in_progress:
            self._pending_theme_update = True
            return
        self._theme_update_in_progress = True
        self._pending_theme_update = False
        try:
            self._reload_custom_font()
            if hasattr(self.app, "change_font_button"):
                self.app.change_font_button.setText(
                    self.customization_service.get_font_button_text()
                )
            self.customization_service.load_custom_style_settings(
                self.app.color_widgets, self.apply_theme
            )
            self.app.disable_background_checkbox.setChecked(
                self.app_state.local_config.get("background_disabled", False)
            )
            if hasattr(self.app, "disable_startup_sound_checkbox"):
                self.app.disable_startup_sound_checkbox.setChecked(
                    self.app_state.local_config.get("disable_startup_sound", False)
                )
            if hasattr(self.app, "disable_animations_checkbox"):
                self.app.disable_animations_checkbox.setChecked(
                    self.app_state.local_config.get("disable_animations", False)
                )
            if hasattr(self.app, "border_radius_spinbox"):
                self.app.border_radius_spinbox.blockSignals(True)
                self.app.border_radius_spinbox.setValue(
                    int(get_border_radius(self.app_state.local_config))
                )
                self.app.border_radius_spinbox.blockSignals(False)
            self.app.background_music_button.setText(
                self.customization_service.get_background_music_button_text()
            )
            self.app.startup_sound_button.setText(
                self.customization_service.get_startup_sound_button_text()
            )
            self.update_background_button_state()
            self.update_logo_button_state()
            if hasattr(self.app, "launcher_icon_label"):
                self.customization_service.load_launcher_icon(
                    self.app.launcher_icon_label
                )
            self._handle_music_after_theme_change()
        finally:
            self._theme_update_in_progress = False
            if self._pending_theme_update:
                self._pending_theme_update = False
                self._debounce_timer.call(self._apply_theme_change)

    def _is_current_bg_music_running(self, current_music_path: str) -> bool:
        """Check if the same background music is currently running."""
        return (
            hasattr(self.customization_service, "_current_music_path")
            and self.customization_service._current_music_path == current_music_path
            and hasattr(self.customization_service, "_bg_music_thread")
            and self.customization_service._bg_music_thread is not None
            and self.customization_service._bg_music_thread.isRunning()
        )

    def _handle_music_after_theme_change(self):
        try:
            current_music_path = self.customization_service.get_background_music_path()
            if not current_music_path:
                self.customization_service.stop_background_music()
            else:
                should_restart = True
                if self._is_current_bg_music_running(current_music_path):
                    should_restart = False
                if should_restart:
                    self.customization_service.stop_background_music()
                    self.customization_service.maybe_start_background_music(force=True)
        except Exception as e:
            import logging

            logging.error(
                f"ThemeController: Error handling music after theme change: {e}",
                exc_info=True,
            )

    def on_custom_style_edited(self):
        self.settings_service.on_custom_style_edited(self.app.color_widgets)

    def update_dynamic_elements(self):
        from ui.builders.shared_filters_builder import apply_filters_frame_style
        from ui.common.styling import apply_panel_style, refresh_themed_button_icon

        for builder_name, widget_key in (
            ("search_tab_builder", "filters_widget"),
            ("library_tab_builder", "library_filters_widget"),
        ):
            builder = getattr(self.app, builder_name, None)
            filters = (
                getattr(builder, "widgets", {}).get(widget_key) if builder else None
            )
            if filters and filters.objectName() == "filters":
                apply_filters_frame_style(filters, self.app_state)
        for container_attr in ("mods_browser_container", "installed_mods_container"):
            container = getattr(self.app, container_attr, None)
            if container:
                apply_panel_style(container, self.app_state.local_config)
        mod_list = getattr(self.app, "mod_list_widget", None)
        installed_mods = getattr(self.app, "installed_mods_widget", None)
        self.customization_service.update_mod_cards_styles(mod_list, installed_mods)
        if hasattr(self.app, "library_tab_builder"):
            self.app.library_tab_builder.update_priority_button_style()
        for builder in (
            getattr(self.app, "search_tab_builder", None),
            getattr(self.app, "library_tab_builder", None),
        ):
            if not builder:
                continue
            widgets = getattr(builder, "widgets", {})
            for widget_key in (
                "sort_order_btn",
                "search_button",
                "downloads_button",
                "blocklist_button",
                "library_game_versions_button",
                "library_modding_tools_button",
                "library_downloads_button",
                "library_search_button",
                "library_tag_widgets",
                "chapter_mode_checkbox",
                "full_install_checkbox",
            ):
                widget = widgets.get(widget_key)
                if isinstance(widget, list):
                    for item in widget:
                        refresh_themed_button_icon(item)
                    continue
                refresh_themed_button_icon(widget)
        section_lines = getattr(self.app, "_section_lines", None)
        if isinstance(section_lines, list) and section_lines:
            from ui.common.styling import get_section_line_color

            line_style = (
                f"color: {get_section_line_color(self.app_state.local_config)};"
            )
            for line_frame in section_lines:
                with contextlib.suppress(RuntimeError):
                    line_frame.setStyleSheet(line_style)
        if hasattr(self.app, "_refresh_themed_icons"):
            self.app._refresh_themed_icons()
        summary = getattr(self.app, "mod_summary_panel", None)
        if summary and hasattr(summary, "refresh_theme"):
            summary.refresh_theme()

    def on_background_button_click(self):
        self.settings_service.on_background_button_click()
        self.update_background_button_state()

    def update_background_button_state(self):
        background_disabled = self.app_state.local_config.get(
            "background_disabled", False
        )
        self.app.change_background_button.setEnabled(not background_disabled)
        self.app.change_background_button.setText(
            tr("buttons.remove_background")
            if self.app_state.local_config.get("custom_background_path")
            else tr("buttons.change_background")
        )

    def on_background_music_button_click(self):
        self.customization_service.stop_background_music()
        self.settings_service.on_background_music_button_click()
        self.app.background_music_button.setText(
            self.customization_service.get_background_music_button_text()
        )
        self.customization_service.maybe_start_background_music(force=True)

    def on_startup_sound_button_click(self):
        self.settings_service.on_startup_sound_button_click()
        self.app.startup_sound_button.setText(
            self.customization_service.get_startup_sound_button_text()
        )

    def on_logo_button_click(self):
        self.settings_service.on_logo_button_click()
        self.update_logo_button_state()

    def update_logo_button_state(self):
        if hasattr(self.app, "change_logo_button"):
            self.app.change_logo_button.setText(
                self.customization_service.get_logo_button_text()
            )

    def _reload_custom_font(self):
        """Reload custom font from disk, or fall back to language default."""
        import logging
        import os

        from PyQt6.QtGui import QFontDatabase

        from services.localization_service import localization_service

        custom_f_path = self.customization_service.get_custom_font_path()
        font_file_key = None
        custom_font_exists = custom_f_path and os.path.exists(custom_f_path)
        if custom_font_exists:
            stat_result = os.stat(custom_f_path)
            font_file_key = (
                custom_f_path,
                stat_result.st_mtime_ns,
                stat_result.st_size,
            )
            if (
                getattr(self.app, "_custom_font_file_key", None) == font_file_key
                and getattr(self.app, "custom_font_family", None)
            ):
                return
        if custom_font_exists:
            old_id = getattr(self.app, "_custom_font_id", None)
            if old_id is not None and old_id != -1:
                QFontDatabase.removeApplicationFont(old_id)
            f_id = QFontDatabase.addApplicationFont(custom_f_path)
            if f_id != -1:
                self.app._custom_font_id = f_id
                self.app._custom_font_file_key = font_file_key
                families = QFontDatabase.applicationFontFamilies(f_id)
                if families:
                    self.app.custom_font_family = families[0]
                    logging.info(
                        f"Custom font loaded: {families[0]} from {custom_f_path}"
                    )
                else:
                    logging.warning(
                        f"No font families found in {custom_f_path}, using default"
                    )
                    self.app.custom_font_family = localization_service.load_font()
            else:
                self.app._custom_font_id = -1
                self.app._custom_font_file_key = None
                logging.error(
                    f"Failed to load font from {custom_f_path}, using default"
                )
                self.app.custom_font_family = localization_service.load_font()
        else:
            self.app._custom_font_file_key = None
            self.app.custom_font_family = localization_service.load_font()
