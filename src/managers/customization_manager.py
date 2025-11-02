import os
import time
import platform
from typing import Optional, Callable
from PyQt6.QtCore import QObject, QThread, pyqtSignal, QTimer, Qt
from PyQt6.QtGui import QPixmap, QColor
from PyQt6.QtWidgets import QWidget, QLabel
from config.constants import THEMES
from utils.path_utils import resource_path
from ui.common.styling import get_theme_color
from managers.localization_manager import tr


class CustomizationManager(QObject):
    background_changed = pyqtSignal()
    music_started = pyqtSignal()
    music_stopped = pyqtSignal()

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self._bg_music_running = False
        self._bg_music_thread = None
        self._bg_music_instance = None
        self.bg_fallback_proc = None

    def get_background_music_path(self) -> str:
        mp3_path = os.path.join(self.app_state.config_dir, 'custom_background_music.mp3')
        wav_path = os.path.join(self.app_state.config_dir, 'custom_background_music.wav')
        if os.path.exists(mp3_path):
            return mp3_path
        if os.path.exists(wav_path):
            return wav_path
        return ''

    def get_startup_sound_path(self) -> str:
        mp3 = os.path.join(self.app_state.config_dir, 'custom_startup_sound.mp3')
        wav = os.path.join(self.app_state.config_dir, 'custom_startup_sound.wav')
        if os.path.exists(mp3):
            return mp3
        if os.path.exists(wav):
            return wav
        return ''

    def get_background_music_button_text(self) -> str:
        mp3 = os.path.join(self.app_state.config_dir, 'custom_background_music.mp3')
        wav = os.path.join(self.app_state.config_dir, 'custom_background_music.wav')
        has_file = os.path.exists(mp3) or os.path.exists(wav)
        return tr('buttons.remove_background_music') if has_file else tr('buttons.select_background_music')

    def get_startup_sound_button_text(self) -> str:
        path = self.get_startup_sound_path()
        return tr('buttons.remove_startup_sound') if path else tr('buttons.select_startup_sound')

    def update_translucent_backgrounds(self, search_container: Optional[QWidget] = None, library_container: Optional[QWidget] = None):
        bg_color = get_theme_color(self.app_state.local_config, 'background', '#000000')
        if bg_color.startswith('#'):
            r = int(bg_color[1:3], 16)
            g = int(bg_color[3:5], 16)
            b = int(bg_color[5:7], 16)
            bg_rgba = f'rgba({r}, {g}, {b}, 128)'
        else:
            bg_rgba = 'rgba(0, 0, 0, 128)'
        if search_container:
            search_container.setStyleSheet(f'\n            QWidget#search_mods_background {{\n                background-color: {bg_rgba};\n                border-radius: 10px;\n                margin: 5px;\n            }}\n        ')
        if library_container:
            library_container.setStyleSheet(f'\n            QWidget#library_mods_background {{\n                background-color: {bg_rgba};\n                border-radius: 10px;\n                margin: 5px;\n            }}\n        ')

    def start_background_music(self):
        try:
            music_path = self.get_background_music_path()
            if not music_path or not os.path.exists(music_path):
                return
            self.stop_background_music()
            from playsound3 import playsound
            self._bg_music_running = True
            self._bg_music_instance = None

            class _MusicLoop(QThread):

                def __init__(self, outer, path):
                    super().__init__()
                    self.outer, self.path = (outer, path)

                def run(self):
                    while getattr(self.outer, '_bg_music_running', False):
                        try:
                            inst = playsound(self.path, block=False)
                            self.outer._bg_music_instance = inst
                            while getattr(self.outer, '_bg_music_running', False) and hasattr(inst, 'is_alive') and inst.is_alive():
                                time.sleep(0.05)
                            if not getattr(self.outer, '_bg_music_running', False):
                                try:
                                    if hasattr(inst, 'stop'):
                                        inst.stop()
                                except Exception:
                                    pass
                                break
                        except Exception:
                            time.sleep(3)
                            continue
            self._bg_music_thread = _MusicLoop(self, music_path)
            self._bg_music_thread.start()
            self.music_started.emit()
        except Exception:
            pass

    def stop_background_music(self):
        try:
            self._bg_music_running = False
            inst = getattr(self, '_bg_music_instance', None)
            if inst and hasattr(inst, 'stop'):
                try:
                    if hasattr(inst, 'is_alive') and inst.is_alive():
                        inst.stop()
                    elif hasattr(inst, 'stop'):
                        inst.stop()
                except Exception:
                    pass
            self._bg_music_instance = None
            thr = getattr(self, '_bg_music_thread', None)
            if thr and thr.isRunning():
                thr.wait(300)
            self._bg_music_thread = None
        except Exception:
            pass
        try:
            if hasattr(self, 'bg_fallback_proc') and self.bg_fallback_proc:
                if self.bg_fallback_proc.poll() is None:
                    self.bg_fallback_proc.terminate()
            if platform.system() == 'Windows':
                try:
                    import winsound
                    winsound.PlaySound(None, winsound.SND_PURGE)
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            self.bg_fallback_proc = None
            self.music_stopped.emit()

    def maybe_start_background_music(self, is_shown_to_user: bool, is_visible: bool):
        try:
            music_path = self.get_background_music_path()
            if not music_path or not os.path.exists(music_path):
                return
            if self.app_state.initialization_completed and is_shown_to_user and is_visible:
                self.start_background_music()
            else:
                QTimer.singleShot(500, lambda: self.maybe_start_background_music(is_shown_to_user, is_visible))
        except Exception:
            pass

    def load_custom_style_settings(self, color_widgets: dict, apply_theme_callback: Optional[Callable] = None):
        theme_defaults = THEMES['default']
        for key, widget in color_widgets.items():
            config_key = f'custom_color_{key}'
            placeholder = theme_defaults['colors'].get(key, '#000000')
            widget.setText(self.app_state.local_config.get(config_key, ''))
            widget.setPlaceholderText(placeholder)
        if apply_theme_callback:
            apply_theme_callback()

    def update_mod_plaques_styles(self, mod_list_widget=None, installed_mods_widget=None):
        from ui.widgets.mod.mod_plaque_widget import ModPlaqueWidget
        from ui.widgets.mod.installed_mod_widget import InstalledModWidget
        if mod_list_widget:
            layout = mod_list_widget.layout()
            if layout:
                for i in range(layout.count() - 1):
                    item = layout.itemAt(i)
                    if item and item.widget():
                        widget = item.widget()
                        if isinstance(widget, ModPlaqueWidget):
                            widget._update_style()
        if installed_mods_widget:
            layout = installed_mods_widget.layout()
            if layout:
                for i in range(layout.count() - 1):
                    item = layout.itemAt(i)
                    if item and item.widget():
                        widget = item.widget()
                        if isinstance(widget, InstalledModWidget):
                            widget._update_style()

    def load_launcher_icon(self, icon_label: QLabel):
        try:
            splash_path = resource_path('assets/images/splash.png')
            if os.path.exists(splash_path):
                pixmap = QPixmap(splash_path)
                if not pixmap.isNull():
                    target_w, target_h = (200, 60)
                    scaled_pixmap = pixmap.scaled(target_w, target_h, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                    x = max(0, (scaled_pixmap.width() - target_w) // 2)
                    y = max(0, (scaled_pixmap.height() - target_h) // 2)
                    cropped = scaled_pixmap.copy(x, y, target_w, target_h)
                    icon_label.setFixedSize(target_w, target_h)
                    icon_label.setScaledContents(False)
                    icon_label.setPixmap(cropped)
                    return
        except Exception:
            pass
        target_w, target_h = (200, 60)
        fallback_pixmap = QPixmap(target_w, target_h)
        fallback_pixmap.fill(QColor('#333'))
        icon_label.setFixedSize(target_w, target_h)
        icon_label.setScaledContents(False)
        icon_label.setPixmap(fallback_pixmap)

    def cleanup(self):
        self.stop_background_music()
