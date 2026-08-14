import sys
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest

from ui.utils import audio_utils


@pytest.mark.parametrize(
    ("platform", "backend", "expected"),
    [
        ("linux", None, False),
        ("linux", "/usr/bin/gst-play-1.0", True),
        ("win32", None, True),
    ],
)
def test_audio_backend_availability(monkeypatch, platform, backend, expected):
    monkeypatch.setattr(audio_utils.sys, "platform", platform)
    monkeypatch.setattr(audio_utils.shutil, "which", lambda _name: backend)

    assert audio_utils.is_audio_playback_available() is expected


def test_audio_process_ignores_player_errors(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "playsound3",
        SimpleNamespace(playsound=lambda _path: (_ for _ in ()).throw(RuntimeError())),
    )

    audio_utils._play_sound_process("missing.wav")


def test_startup_sound_does_not_spawn_without_linux_backend(monkeypatch, tmp_path):
    process = Mock()
    monkeypatch.setattr(audio_utils, "get_user_data_root", lambda: str(tmp_path))
    monkeypatch.setattr(audio_utils, "is_audio_playback_available", lambda: False)
    monkeypatch.setattr(audio_utils.os.path, "exists", lambda _path: True)
    monkeypatch.setattr(audio_utils, "Process", process)

    audio_utils.AudioManager().play_g3m_sound()

    process.assert_not_called()


def test_audio_users_do_not_spawn_without_backend(monkeypatch, tmp_path, qapp):
    from services.customization_service import CustomizationManager
    from ui.dialogs.mod_diagnostics_dialog import ModDiagnosticsDialog

    music_path = tmp_path / "music.ogg"
    music_path.write_bytes(b"audio")
    process = Mock()
    monkeypatch.setattr(
        "services.customization_service.is_audio_playback_available",
        lambda: False,
    )
    monkeypatch.setattr("services.customization_service.Process", process)
    manager = CustomizationManager(
        SimpleNamespace(config_dir=str(tmp_path), game_is_running=False)
    )
    manager.start_background_music()
    manager._music_monitor.stop()

    preview = cast(
        ModDiagnosticsDialog,
        SimpleNamespace(_current_audio_path=str(music_path), _stop_preview_audio=Mock()),
    )
    monkeypatch.setattr(
        "ui.dialogs.mod_diagnostics_dialog.is_audio_playback_available",
        lambda: False,
    )
    monkeypatch.setattr("ui.dialogs.mod_diagnostics_dialog.Process", process)
    ModDiagnosticsDialog._play_preview_audio(preview)

    process.assert_not_called()


def test_audio_preview_shows_unavailable_backend_status(monkeypatch):
    from ui.dialogs.mod_diagnostics_dialog import ModDiagnosticsDialog

    play_button = Mock()
    stop_button = Mock()
    status = Mock()
    preview = cast(
        ModDiagnosticsDialog,
        SimpleNamespace(
            _stop_preview_audio=Mock(),
            _current_audio_path="",
            _audio_play_btn=play_button,
            _audio_stop_btn=stop_button,
            _audio_status=status,
            _preview_compare_panel=Mock(),
            _looks_image_like=lambda _path: False,
            _looks_audio_like=lambda _path: True,
        ),
    )
    monkeypatch.setattr(
        "ui.dialogs.mod_diagnostics_dialog.is_audio_playback_available",
        lambda: False,
    )

    ModDiagnosticsDialog._set_preview_file(preview, "sound.ogg")

    assert preview._current_audio_path == ""
    play_button.setEnabled.assert_called_with(False)
    stop_button.setEnabled.assert_called_with(False)
    assert status.setText.call_count == 2
    assert status.setText.call_args.args[0]
