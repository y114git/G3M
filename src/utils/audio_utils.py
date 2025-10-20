import json
import os
from typing import Optional, Protocol
from utils.path_utils import get_user_data_root


class SoundInstance(Protocol):

    def is_alive(self) -> bool:
        ...

    def stop(self) -> None:
        ...


class AudioManager:
    def __init__(self):
        self._sound_instance: Optional[SoundInstance] = None

    def play_deltahub_sound(self) -> None:
        app_support_path = os.path.join(get_user_data_root(), 'settings')
        config_mp3 = os.path.join(app_support_path, 'custom_startup_sound.mp3')
        config_wav = os.path.join(app_support_path, 'custom_startup_sound.wav')
        asset_wav = os.path.join(os.path.dirname(__file__), '..', 'resources', 'audio', 'deltahub.wav')
        sound_candidates = [config_mp3, config_wav, asset_wav]
        sound_path = next((p for p in sound_candidates if os.path.exists(p)), None)
        if not sound_path:
            return
        try:
            from playsound3 import playsound
            self._sound_instance = playsound(os.path.abspath(sound_path), block=False)
        except Exception:
            pass

    def stop_deltahub_sound(self) -> None:
        if self._sound_instance and self._sound_instance.is_alive():
            try:
                self._sound_instance.stop()
            except Exception:
                pass
        self._sound_instance = None


_audio_manager = AudioManager()


def get_launcher_volume() -> int:
    try:
        config_path = os.path.join(get_user_data_root(), 'settings', 'config.json')
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                return config.get('launcher_volume', 100)
    except (IOError, json.JSONDecodeError):
        pass
    return 100
