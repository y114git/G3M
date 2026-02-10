"""UI customization and audio management."""
import os
import time
import platform
import logging
from typing import Optional, Callable
from PyQt6.QtCore import QObject, QThread, pyqtSignal, Qt
from PyQt6.QtGui import QPixmap, QColor
from PyQt6.QtWidgets import QWidget, QLabel
from config.constants import THEMES
from utils.path_utils import resource_path
from ui.common.styling import get_theme_color
from services.localization_service import tr


class CustomizationManager(QObject):
    """Manages UI customization including themes, audio, and backgrounds."""
    music_started, music_stopped = pyqtSignal(), pyqtSignal()

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state, self.parent_widget = app_state, parent
        self._bg_music_running = self._music_starting = False
        self._bg_music_thread = self._bg_music_instance = self.bg_fallback_proc = self._current_music_path = None

    def _get_custom_file_path(self, base_name: str, extensions: list[str]) -> str:
        for ext in extensions:
            path = os.path.join(self.app_state.config_dir, f'{base_name}{ext}')
            if os.path.exists(path):
                return path
        return ''

    def get_background_music_path(self) -> str:
        return self._get_custom_file_path('custom_background_music', ['.mp3', '.wav'])

    def get_startup_sound_path(self) -> str:
        return self._get_custom_file_path('custom_startup_sound', ['.mp3', '.wav'])

    def get_background_music_button_text(self) -> str:
        return tr('buttons.remove_background_music') if self.get_background_music_path() else tr('buttons.select_background_music')

    def get_startup_sound_button_text(self) -> str:
        return tr('buttons.remove_startup_sound') if self.get_startup_sound_path() else tr('buttons.select_startup_sound')

    def get_custom_logo_path(self) -> str:
        return self._get_custom_file_path('custom_logo', ['.png', '.jpg', '.jpeg', '.gif', '.bmp'])

    def get_logo_button_text(self) -> str:
        return tr('buttons.remove_logo') if self.get_custom_logo_path() else tr('buttons.change_logo')

    def update_translucent_backgrounds(self, search_container: Optional[QWidget] = None, library_container: Optional[QWidget] = None):
        bg = get_theme_color(self.app_state.local_config, 'background', '#000000')
        rgba = f'rgba({int(bg[1:3], 16)}, {int(bg[3:5], 16)}, {int(bg[5:7], 16)}, 128)' if bg.startswith('#') else 'rgba(0,0,0,128)'
        for container, name in [(search_container, 'search'), (library_container, 'library')]:
            if container:
                container.setStyleSheet(f'QWidget#{name}_mods_background {{background-color: {rgba}; border-radius: 10px; margin: 5px;}}')

    def start_background_music(self):
        if self._music_starting or (self._bg_music_thread and self._bg_music_thread.isRunning()):
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
                def __init__(self, outer, path):
                    super().__init__()
                    self.outer, self.path = outer, path

                def run(self):
                    while getattr(self.outer, '_bg_music_running', False) and not self.isInterruptionRequested():
                        try:
                            inst = playsound(self.path, block=False)
                            self.outer._bg_music_instance = inst
                            while self.outer._bg_music_running and not self.isInterruptionRequested() and hasattr(inst, 'is_alive') and inst.is_alive():
                                time.sleep(0.05)
                            if not self.outer._bg_music_running or self.isInterruptionRequested():
                                if hasattr(inst, 'stop'):
                                    inst.stop()
                                break
                        except Exception:
                            if not self.outer._bg_music_running or self.isInterruptionRequested():
                                break
                            time.sleep(3)
            self._bg_music_thread = _MusicLoop(self, music_path)
            self._bg_music_thread.start()
            self._current_music_path = music_path
            self.music_started.emit()
        except Exception as e:
            logging.error(f'Failed to start background music: {e}', exc_info=True)
        finally:
            self._music_starting = False

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
            if thr:
                if thr.isRunning():
                    thr.requestInterruption()
                    thr.quit()
                    if not thr.wait(2000):
                        logging.warning('[CustomizationManager] Thread did not finish in time, terminating')
                        thr.terminate()
                        thr.wait(500)
                thr.deleteLater()
            self._bg_music_thread = None
        except Exception as e:
            logging.error(f'[CustomizationManager] Error stopping music: {e}', exc_info=True)
        try:
            if hasattr(self, 'bg_fallback_proc') and self.bg_fallback_proc:
                if self.bg_fallback_proc.poll() is None:
                    try:
                        self.bg_fallback_proc.kill()
                    except Exception:
                        pass
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
            is_shown, is_visible = getattr(self.app_state, 'is_shown_to_user', False), self.parent_widget.isVisible()
            if force or (is_shown and is_visible):
                if not force and self._bg_music_thread and self._bg_music_thread.isRunning() and self._current_music_path == music_path:
                    return
                self.start_background_music()
        except Exception as e:
            logging.error(f'Error in maybe_start_background_music: {e}', exc_info=True)
            self._music_starting = False

    def load_custom_style_settings(self, color_widgets: dict, apply_theme_callback: Optional[Callable] = None):
        defaults = THEMES['default']['colors']
        for key, widget in color_widgets.items():
            widget.setText(self.app_state.local_config.get(f'custom_color_{key}', ''))
            widget.setPlaceholderText(defaults.get(key, '#000000'))
        if apply_theme_callback:
            apply_theme_callback()

    def update_mod_cards_styles(self, mod_list_widget=None, installed_mods_widget=None):
        from ui.widgets.mod.mod_card_widget import ModCardWidget
        from ui.widgets.mod.installed_mod_widget import InstalledModWidget
        for container, wtype in [(mod_list_widget, ModCardWidget), (installed_mods_widget, InstalledModWidget)]:
            self._update_layout_widget_styles(container, wtype)

    def _update_layout_widget_styles(self, container, widget_type) -> None:
        if not (container and (layout := container.layout())):
            return
        for i in range(layout.count() - 1):
            if (item := layout.itemAt(i)) and (w := item.widget()) and isinstance(w, widget_type):
                try:
                    w._update_style()
                except Exception:
                    pass

    def load_launcher_icon(self, icon_label: QLabel):
        try:
            custom = self.get_custom_logo_path()
            path = custom if custom and os.path.exists(custom) else resource_path('assets/images/splash.png')
            if os.path.exists(path) and not (pixmap := QPixmap(path)).isNull():
                icon_label.setScaledContents(False)
                icon_label.setPixmap(pixmap.scaled(icon_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                return
        except Exception:
            pass
        fb = QPixmap(icon_label.size())
        fb.fill(QColor('#333'))
        icon_label.setScaledContents(False)
        icon_label.setPixmap(fb)

    def cleanup(self): self.stop_background_music()
