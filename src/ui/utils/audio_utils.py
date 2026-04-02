"""Audio playback utilities."""

import logging
import os
from multiprocessing import Process

from utils.path_utils import get_user_data_root


def _play_sound_process(sound_path: str) -> None:
    from playsound3 import playsound

    playsound(os.path.abspath(sound_path))


class AudioManager:
    """Manages audio playback for the application."""

    def __init__(self) -> None:
        self._sound_instance: Process | None = None

    def play_g3m_sound(self) -> None:
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
            self.stop_g3m_sound()
            process = Process(
                target=_play_sound_process,
                args=(os.path.abspath(sound_path),),
                daemon=True,
            )
            process.start()
            self._sound_instance = process
        except Exception as e:
            logging.debug(
                f"AudioManager.play_g3m_sound: failed to play {sound_path}: {e}"
            )
            self._sound_instance = None

    def stop_g3m_sound(self) -> None:
        process = self._sound_instance
        if process is not None:
            try:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=1.0)
                    if process.is_alive():
                        process.kill()
                        process.join(timeout=0.5)
            except Exception as e:
                logging.debug(f"AudioManager.stop_g3m_sound: failed to stop: {e}")
        self._sound_instance = None


_audio_service = AudioManager()
