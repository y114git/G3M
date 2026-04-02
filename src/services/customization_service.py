"""UI customization and audio management."""

import contextlib
import logging
import os
from collections.abc import Callable
from multiprocessing import Process

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPixmap

from config.config import DEFAULT_COLORS
from config.settings_schema import get_theme_color_key
from services.localization_service import tr
from ui.common.styling import install_panel_style_handler, qt_hex_to_display_hex
from utils.path_utils import resource_path


def _play_background_music_process(music_path: str) -> None:
    from playsound3 import playsound

    playsound(music_path)


class CustomizationManager(QObject):
    """Manages UI customization including themes, audio, and backgrounds."""

    music_started, music_stopped = pyqtSignal(), pyqtSignal()

    def __init__(self, app_state, parent=None) -> None:
        super().__init__(parent)
        self.app_state, self.parent_widget = app_state, parent
        self._music_starting = False
        self._bg_music_instance: Process | None = None
        self._current_music_path = None
        self._focus_pause_active = False

    def _get_custom_file_path(self, base_name: str, extensions: list[str]) -> str:
        for ext in extensions:
            path = os.path.join(self.app_state.config_dir, f"{base_name}{ext}")
            if os.path.exists(path):
                return path
        return ""

    def get_background_music_path(self) -> str:
        return self._get_custom_file_path(
            "custom_background_music", [".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac"]
        )

    def get_startup_sound_path(self) -> str:
        return self._get_custom_file_path(
            "custom_startup_sound", [".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac"]
        )

    def get_background_music_button_text(self) -> str:
        return (
            tr("buttons.remove_background_music")
            if self.get_background_music_path()
            else tr("buttons.select_background_music")
        )

    def get_startup_sound_button_text(self) -> str:
        return (
            tr("buttons.remove_startup_sound")
            if self.get_startup_sound_path()
            else tr("buttons.select_startup_sound")
        )

    def get_custom_logo_path(self) -> str:
        return self._get_custom_file_path(
            "custom_logo", [".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp"]
        )

    def get_custom_font_path(self) -> str:
        return self._get_custom_file_path("custom_font", [".ttf", ".otf"])

    def get_font_button_text(self) -> str:
        return (
            tr("buttons.remove_font")
            if self.get_custom_font_path()
            else tr("buttons.change_font")
        )

    def get_logo_button_text(self) -> str:
        return (
            tr("buttons.remove_logo")
            if self.get_custom_logo_path()
            else tr("buttons.change_logo")
        )

    def update_translucent_backgrounds(self, *containers):
        for container in containers:
            install_panel_style_handler(
                container,
                self.app_state.local_config,
                attr_name="_translucent_background_style_filter",
            )

    def start_background_music(self, force: bool = False):
        if self._music_starting:
            return
        music_path = self.get_background_music_path()
        if not music_path or not os.path.exists(music_path):
            self.stop_background_music()
            return
        try:
            self._music_starting = True
            self.stop_background_music()
            process = Process(
                target=_play_background_music_process,
                args=(os.path.abspath(music_path),),
                daemon=True,
            )
            process.start()
            self._bg_music_instance = process
            self._current_music_path = music_path
            self._focus_pause_active = False
            self.music_started.emit()
        except Exception as e:
            logging.error(f"Failed to start background music: {e}", exc_info=True)
            self.stop_background_music()
        finally:
            self._music_starting = False

    def stop_background_music(
        self,
        wait_for_thread: bool = True,
        preserve_focus_pause: bool = False,
    ):
        try:
            player = self._bg_music_instance
            if player is not None and player.is_alive():
                player.terminate()
                if wait_for_thread:
                    player.join(timeout=1.0)
        except Exception as e:
            logging.error(
                f"[CustomizationManager] Error stopping music: {e}", exc_info=True
            )
        finally:
            self._bg_music_instance = None
            self._current_music_path = None
            if not preserve_focus_pause:
                self._focus_pause_active = False
            self._music_starting = False
            self.music_stopped.emit()

    def set_background_music_focus_paused(self, paused: bool) -> None:
        paused = bool(paused)
        if paused == self._focus_pause_active:
            return
        self._focus_pause_active = paused
        if paused:
            self.stop_background_music(wait_for_thread=False, preserve_focus_pause=True)
        else:
            self.maybe_start_background_music(force=True)

    def maybe_start_background_music(self, force=False):
        if self._music_starting:
            return
        try:
            music_path = self.get_background_music_path()
            if not music_path or not os.path.exists(music_path):
                if self._bg_music_instance:
                    self.stop_background_music()
                return
            if not self.parent_widget:
                return
            is_shown, is_visible = (
                getattr(self.app_state, "is_shown_to_user", False),
                self.parent_widget.isVisible(),
            )
            if force or (is_shown and is_visible):
                player = self._bg_music_instance
                if (
                    player is not None
                    and player.is_alive()
                    and self._current_music_path == music_path
                ):
                    return
                if player is not None and not player.is_alive():
                    self._bg_music_instance = None
                self.start_background_music(force=force)
        except Exception as e:
            logging.error(f"Error in maybe_start_background_music: {e}", exc_info=True)
            self._music_starting = False

    def load_custom_style_settings(
        self, color_widgets: dict, apply_theme_callback: Callable | None = None
    ):
        placeholder_defaults = dict(DEFAULT_COLORS)
        for key, widget in color_widgets.items():
            default_display_hex = qt_hex_to_display_hex(
                placeholder_defaults.get(key, "#000000")
            )
            custom_display_hex = qt_hex_to_display_hex(
                self.app_state.local_config.get(get_theme_color_key(key), "")
            )
            effective_display_hex = custom_display_hex or default_display_hex
            widget.setText(effective_display_hex)
            widget.setPlaceholderText("")
            widget.setProperty("default_display_hex", default_display_hex)
            widget.setProperty("last_valid_display_hex", effective_display_hex)
        if apply_theme_callback:
            apply_theme_callback()

    def update_mod_cards_styles(self, mod_list_widget=None, installed_mods_widget=None):
        from ui.widgets.mod.installed_mod_widget import InstalledModWidget
        from ui.widgets.mod.mod_card_widget import ModCardWidget

        for container, wtype in [
            (mod_list_widget, ModCardWidget),
            (installed_mods_widget, InstalledModWidget),
        ]:
            self._update_layout_widget_styles(container, wtype)

    def _update_layout_widget_styles(self, container, widget_type) -> None:
        if not (container and (layout := container.layout())):
            return
        for i in range(layout.count()):
            if (
                (item := layout.itemAt(i))
                and (w := item.widget())
                and isinstance(w, widget_type)
            ):
                with contextlib.suppress(Exception):
                    w._update_style()

    def load_launcher_icon(self, icon_label):
        try:
            custom = self.get_custom_logo_path()
            path = (
                custom
                if custom and os.path.exists(custom)
                else resource_path("assets/images/logo.png")
            )
            if os.path.exists(path) and not (pixmap := QPixmap(path)).isNull():
                icon_label.setScaledContents(False)

                l_width = icon_label.width()
                l_height = icon_label.height()

                if l_width > 0 and l_height > 0:
                    icon_label.setContentsMargins(0, 0, 0, 0)
                    dpr = icon_label.devicePixelRatioF()

                    scaled_pixmap = pixmap.scaled(
                        int(l_width * dpr),
                        int(l_height * dpr),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    scaled_pixmap.setDevicePixelRatio(dpr)
                    icon_label.setPixmap(scaled_pixmap)
                    icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                return
        except Exception as e:
            logging.debug(
                f"[CustomizationManager] Failed to load launcher icon: {e}",
                exc_info=True,
            )
        fb = QPixmap(icon_label.size())
        fb.fill(QColor("#333"))
        icon_label.setScaledContents(False)
        icon_label.setPixmap(fb)

    def cleanup(self):
        self.stop_background_music()
