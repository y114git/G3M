import os
import time
import platform
from typing import Optional
from PyQt6.QtCore import QObject, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QMovie, QPixmap, QColor
from PyQt6.QtWidgets import QWidget
from config.constants import THEMES
from utils.path_utils import resource_path
from ui.styling import get_theme_color


class AppearanceManager(QObject):
    theme_applied = pyqtSignal()
    background_changed = pyqtSignal()
    music_started = pyqtSignal()
    music_stopped = pyqtSignal()

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.background_movie = None
        self.background_pixmap: Optional[QPixmap] = None
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
        if os.path.exists(mp3):
            return os.path.basename(mp3)
        if os.path.exists(wav):
            return os.path.basename(wav)
        return ''

    def get_startup_sound_button_text(self) -> str:
        path = self.get_startup_sound_path()
        return os.path.basename(path) if path else ''

    def apply_theme(self, widget: QWidget) -> tuple[Optional[QMovie], Optional[QPixmap]]:
        theme = THEMES['default']
        background_path = None
        background_disabled = self.app_state.local_config.get('background_disabled', False)

        if self.background_movie is not None:
            self.background_movie.stop()
            self.background_movie.deleteLater()
            self.background_movie = None

        self.background_pixmap = None

        if not background_disabled:
            background_path = self.app_state.local_config.get('custom_background_path') or resource_path(f"resources/{theme.get('background', '')}")

            if background_path and os.path.exists(background_path):
                if background_path.lower().endswith('.gif'):
                    self.background_movie = QMovie(background_path)
                    if not self.background_movie.isValid():
                        self.background_movie = None
                    else:
                        self.background_movie.setScaledSize(widget.size())
                        self.background_movie.frameChanged.connect(widget.update)
                        self.background_movie.start()
                else:
                    self.background_pixmap = QPixmap(background_path)
                    if self.background_pixmap.isNull():
                        self.background_pixmap = None

        self.theme_applied.emit()
        return (self.background_movie, self.background_pixmap)

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
            search_container.setStyleSheet(f'''
            QWidget#search_mods_background {{
                background-color: {bg_rgba};
                border-radius: 10px;
                margin: 5px;
            }}
        ''')

        if library_container:
            library_container.setStyleSheet(f'''
            QWidget#library_mods_background {{
                background-color: {bg_rgba};
                border-radius: 10px;
                margin: 5px;
            }}
        ''')

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

        except Exception as e:
            print(f'Error starting background music: {e}')

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

        except Exception as e:
            print(f'Error stopping background music: {e}')

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

    def cleanup(self):
        self.stop_background_music()
        if self.background_movie:
            self.background_movie.stop()
            self.background_movie.deleteLater()
            self.background_movie = None
