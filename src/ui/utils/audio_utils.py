"""Audio playback utilities."""

import logging
import os
from typing import Protocol

from utils.path_utils import get_user_data_root


class SoundInstance(Protocol):
    """Protocol for sound playback instances."""

    def is_alive(self) -> bool: ...

    def stop(self) -> None: ...


class AudioManager:
    """Manages audio playback for the application."""

    def __init__(self) -> None:
        self._sound_instance: SoundInstance | None = None

    def play_deltahub_sound(self) -> None:
        app_support_path = os.path.join(get_user_data_root(), "settings")
        asset_wav = os.path.join(
            os.path.dirname(__file__), "..", "..", "assets", "audio", "G3M.wav"
        )
        extensions = (".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac")
        candidates = [
            os.path.join(app_support_path, f"custom_startup_sound{ext}")
            for ext in extensions
        ]
        candidates.append(asset_wav)
        sound_path = None
        for candidate in candidates:
            if os.path.exists(candidate):
                sound_path = candidate
                break
        if not sound_path:
            return
        try:
            from playsound3 import playsound

            self._sound_instance = playsound(os.path.abspath(sound_path), block=False)
        except Exception as e:
            logging.debug(
                f"AudioManager.play_deltahub_sound: failed to play {sound_path}: {e}"
            )

    def stop_deltahub_sound(self) -> None:
        if self._sound_instance and self._sound_instance.is_alive():
            try:
                self._sound_instance.stop()
            except Exception as e:
                logging.debug(f"AudioManager.stop_deltahub_sound: failed to stop: {e}")
        self._sound_instance = None


_audio_service = AudioManager()
