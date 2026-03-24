"""UI customization and audio management."""

import contextlib
import logging
import os
import platform
import time
from collections.abc import Callable

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtWidgets import QLabel

from config.config import DEFAULT_COLORS
from services.localization_service import tr
from ui.common.styling import install_panel_style_handler, qt_hex_to_display_hex
from utils.path_utils import resource_path


class CustomizationManager(QObject):
    """Manages UI customization including themes, audio, and backgrounds."""

    music_started, music_stopped = pyqtSignal(), pyqtSignal()

    def __init__(self, app_state, parent=None) -> None:
        super().__init__(parent)
        self.app_state, self.parent_widget = app_state, parent
        self._bg_music_running = self._music_starting = False
        self._bg_music_thread = self._bg_music_instance = self.bg_fallback_proc = (
            self._current_music_path
        ) = None

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

    def start_background_music(self):
        if self._music_starting or (
            self._bg_music_thread and self._bg_music_thread.isRunning()
        ):
            return
        try:
            self._music_starting = True
            music_path = self.get_background_music_path()
            if not music_path or not os.path.exists(music_path):
                self._music_starting = False
                return
            self.stop_background_music()
            from playsound3 import playsound

            self._bg_music_running = True

            class _MusicLoop(QThread):
                def __init__(self, outer, path) -> None:
                    super().__init__()
                    self.outer, self.path = outer, path

                def run(self):
                    while (
                        getattr(self.outer, "_bg_music_running", False)
                        and not self.isInterruptionRequested()
                    ):
                        try:
                            inst = playsound(self.path, block=False)
                            self.outer._bg_music_instance = inst
                            while (
                                self.outer._bg_music_running
                                and not self.isInterruptionRequested()
                                and hasattr(inst, "is_alive")
                                and inst.is_alive()
                            ):
                                time.sleep(0.05)
                            if (
                                not self.outer._bg_music_running
                                or self.isInterruptionRequested()
                            ):
                                if hasattr(inst, "stop"):
                                    inst.stop()
                                break
                        except Exception:
                            if (
                                not self.outer._bg_music_running
                                or self.isInterruptionRequested()
                            ):
                                break
                            time.sleep(3)

            self._bg_music_thread = _MusicLoop(self, music_path)
            self._bg_music_thread.start()
            self._current_music_path = music_path
            self.music_started.emit()
        except Exception as e:
            logging.error(f"Failed to start background music: {e}", exc_info=True)
        finally:
            self._music_starting = False

    def stop_background_music(self):
        try:
            self._bg_music_running = False
            inst = getattr(self, "_bg_music_instance", None)
            if inst and hasattr(inst, "stop"):
                try:
                    if hasattr(inst, "is_alive") and inst.is_alive():
                        inst.stop()
                except Exception as e:
                    logging.debug(
                        f"[CustomizationManager] Failed to stop background music instance: {e}",
                        exc_info=True,
                    )
            self._bg_music_instance = None
            thr = getattr(self, "_bg_music_thread", None)
            if thr:
                if thr.isRunning():
                    thr.requestInterruption()
                    thr.quit()

                    if not thr.wait(100):
                        logging.debug(
                            "[CustomizationManager] Thread did not finish in time, terminating"
                        )
                        thr.terminate()
                        thr.wait(50)
                thr.deleteLater()
            self._bg_music_thread = None
        except Exception as e:
            logging.error(
                f"[CustomizationManager] Error stopping music: {e}", exc_info=True
            )
        try:
            if (
                hasattr(self, "bg_fallback_proc")
                and self.bg_fallback_proc
                and self.bg_fallback_proc.poll() is None
            ):
                with contextlib.suppress(Exception):
                    self.bg_fallback_proc.kill()
            if platform.system() == "Windows":
                try:
                    import winsound

                    winsound.PlaySound(None, winsound.SND_PURGE)
                except Exception as e:
                    logging.debug(
                        f"[CustomizationManager] Failed to purge winsound playback: {e}",
                        exc_info=True,
                    )
        except Exception as e:
            logging.debug(
                f"[CustomizationManager] Failed to stop fallback background music process: {e}",
                exc_info=True,
            )
        finally:
            self.bg_fallback_proc = None
            self._current_music_path = None
            self.music_stopped.emit()

    def maybe_start_background_music(self, force=False):
        if self._music_starting:
            return
        try:
            music_path = self.get_background_music_path()
            if not music_path or not os.path.exists(music_path):
                if self._bg_music_thread and self._bg_music_thread.isRunning():
                    self.stop_background_music()
                return
            if not self.parent_widget:
                return
            is_shown, is_visible = (
                getattr(self.app_state, "is_shown_to_user", False),
                self.parent_widget.isVisible(),
            )
            if force or (is_shown and is_visible):
                if (
                    not force
                    and self._bg_music_thread
                    and self._bg_music_thread.isRunning()
                    and self._current_music_path == music_path
                ):
                    return
                self.start_background_music()
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
                self.app_state.local_config.get(f"custom_color_{key}", "")
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

    def load_launcher_icon(self, icon_label: QLabel):
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
