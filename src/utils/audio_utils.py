import json
import os
from typing import Optional, Protocol
from utils.path_utils import get_app_support_path

class SoundInstance(Protocol):

    def is_alive(self) -> bool:
        ...

    def stop(self) -> None:
        ...
_sound_instance: Optional[SoundInstance] = None

def get_launcher_volume() -> int:
    try:
        config_path = os.path.join(get_app_support_path(), 'config.json')
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                return config.get('launcher_volume', 100)
    except (IOError, json.JSONDecodeError):
        pass
    return 100

def play_deltahub_sound() -> None:
    global _sound_instance
    config_mp3 = os.path.join(get_app_support_path(), 'custom_startup_sound.mp3')
    config_wav = os.path.join(get_app_support_path(), 'custom_startup_sound.wav')
    asset_wav = os.path.join(os.path.dirname(__file__), '..', 'resources', 'audio', 'deltahub.wav')
    sound_candidates = [config_mp3, config_wav, asset_wav]
    sound_path = next((p for p in sound_candidates if os.path.exists(p)), None)
    if not sound_path:
        return
    try:
        from playsound3 import playsound
        _sound_instance = playsound(os.path.abspath(sound_path), block=False)
    except Exception:
        pass

def stop_deltahub_sound() -> None:
    global _sound_instance
    if _sound_instance and _sound_instance.is_alive():
        try:
            _sound_instance.stop()
        except Exception:
            pass
    _sound_instance = None