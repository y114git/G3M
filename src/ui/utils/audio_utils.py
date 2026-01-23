"""Audio playback utilities.

This module provides utilities for playing audio files including background music and sound effects.
"""
import logging
import os
from typing import Optional, Protocol
from utils.path_utils import get_user_data_root


class SoundInstance(Protocol):
    """Protocol for sound playback instances."""

    def is_alive(self) -> bool:
        """Check if sound is currently playing.

        Returns:
            bool: True if sound is playing.
        """
        ...

    def stop(self) -> None:
        """Stop the sound playback."""
        ...


class AudioManager:
    """Manages audio playback for the application."""

    def __init__(self):
        """Initialize the audio manager."""
        self._sound_instance: Optional[SoundInstance] = None

    def play_deltahub_sound(self) -> None:
        """Play the DELTAHUB startup sound.

        Searches for custom sound files first, then falls back to default asset.
        """
        app_support_path = os.path.join(get_user_data_root(), 'settings')
        config_mp3 = os.path.join(app_support_path, 'custom_startup_sound.mp3')
        config_wav = os.path.join(app_support_path, 'custom_startup_sound.wav')
        asset_wav = os.path.join(os.path.dirname(__file__), '..', 'assets', 'audio', 'deltahub.wav')
        sound_path = next((p for p in (config_mp3, config_wav, asset_wav) if os.path.exists(p)), None)
        if not sound_path:
            return
        try:
            from playsound3 import playsound
            self._sound_instance = playsound(os.path.abspath(sound_path), block=False)
        except Exception as e:
            logging.debug(f'AudioManager.play_deltahub_sound: failed to play {sound_path}: {e}')

    def stop_deltahub_sound(self) -> None:
        """Stop the currently playing DELTAHUB sound."""
        if self._sound_instance and self._sound_instance.is_alive():
            try:
                self._sound_instance.stop()
            except Exception as e:
                logging.debug(f'AudioManager.stop_deltahub_sound: failed to stop: {e}')
        self._sound_instance = None


_audio_service = AudioManager()
