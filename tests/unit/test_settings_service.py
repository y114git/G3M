"""Unit tests for settings service failure handling."""

from types import SimpleNamespace
from unittest.mock import Mock

from services.localization_service import localization_service
from services.settings_service import SettingsManager
from services.user_data_root_service import DataRootChangeResult


def test_write_json_suppresses_permission_dialog_failure(monkeypatch, tmp_path):
    """Checks AppData write failures do not crash if the error dialog cannot open."""
    manager = SettingsManager(
        app_state=SimpleNamespace(),
        feedback_service=Mock(
            show_message=Mock(side_effect=RuntimeError("dialog already deleted"))
        ),
        localization_service=localization_service,
    )

    def fail_save_json(*_args, **_kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr("utils.file_utils.save_json", fail_save_json)

    manager.write_json(str(tmp_path / "config.json"), {"ok": True})

    manager.feedback_service.show_message.assert_called_once()


def test_write_json_suppresses_status_update_failure(monkeypatch, tmp_path):
    """Checks generic AppData write errors do not crash if status UI is unavailable."""
    manager = SettingsManager(
        app_state=SimpleNamespace(),
        feedback_service=Mock(
            update_status=Mock(side_effect=RuntimeError("status widget deleted"))
        ),
        localization_service=localization_service,
    )

    def fail_save_json(*_args, **_kwargs):
        raise TypeError("not json serializable")

    monkeypatch.setattr("utils.file_utils.save_json", fail_save_json)

    manager.write_json(str(tmp_path / "config.json"), {"bad": object()})

    manager.feedback_service.update_status.assert_called_once()


def test_read_json_suppresses_corruption_status_failure(monkeypatch, tmp_path):
    """Checks corrupted AppData config notice cannot crash settings reads."""
    config_path = tmp_path / "config.json"
    config_path.write_text("{bad json", encoding="utf-8")
    config_path.with_suffix(".json.invalid.bak").write_text("{}", encoding="utf-8")
    manager = SettingsManager(
        app_state=SimpleNamespace(),
        feedback_service=Mock(
            update_status=Mock(side_effect=RuntimeError("status widget deleted"))
        ),
        localization_service=localization_service,
    )
    monkeypatch.setattr("utils.file_utils.load_json", lambda _path: {})

    assert manager.read_json(str(config_path)) == {}

    manager.feedback_service.update_status.assert_called_once()


def test_theme_url_install_finished_suppresses_feedback_failures():
    """Checks theme URL completion is not undone by stale feedback widgets."""
    app_state = Mock()
    app_state.reset_install_state = Mock()
    manager = SettingsManager(
        app_state=app_state,
        feedback_service=Mock(
            update_status=Mock(side_effect=RuntimeError("status widget deleted")),
            show_message=Mock(side_effect=RuntimeError("dialog already deleted")),
        ),
        localization_service=localization_service,
    )
    theme_changed = Mock()
    settings_changed = Mock()
    manager.theme_changed.connect(theme_changed)
    manager.settings_changed.connect(settings_changed)

    manager._on_theme_install_finished(True, "installed")

    app_state.reset_install_state.assert_called_once()
    theme_changed.assert_called_once()
    settings_changed.assert_called_once()


def test_select_executable_path_invalid_feedback_failure_returns_none(monkeypatch):
    """Checks invalid executable warning failure does not crash path selection."""
    manager = SettingsManager(
        app_state=SimpleNamespace(),
        feedback_service=Mock(
            show_message=Mock(side_effect=RuntimeError("toast deleted"))
        ),
        localization_service=localization_service,
    )
    monkeypatch.setattr(
        "services.settings_service.get_open_file_name",
        lambda *_args, **_kwargs: ("C:/missing.exe", ""),
    )
    manager.get_executable_path_error = Mock(return_value="Invalid executable")

    assert manager.select_executable_path("Select executable") is None
    manager.feedback_service.show_message.assert_called_once()


def test_successful_data_root_change_writes_locator_and_requests_restart(
    monkeypatch, tmp_path
):
    manager = SettingsManager(
        app_state=SimpleNamespace(),
        feedback_service=Mock(),
        localization_service=localization_service,
    )
    write_locator = Mock()
    monkeypatch.setattr("services.settings_service.write_selected_user_data_root", write_locator)
    monkeypatch.setattr("services.settings_service.get_default_user_data_root", lambda: str(tmp_path / "default"))
    restart = Mock()
    manager.restart_required.connect(restart)

    manager.complete_user_data_root_change(
        DataRootChangeResult("ready", str(tmp_path / "custom"))
    )

    write_locator.assert_called_once_with(str(tmp_path / "default"), str(tmp_path / "custom"))
    restart.assert_called_once()


def test_failed_data_root_change_does_not_update_locator(monkeypatch, tmp_path):
    feedback = Mock()
    manager = SettingsManager(
        app_state=SimpleNamespace(),
        feedback_service=feedback,
        localization_service=localization_service,
    )
    write_locator = Mock()
    monkeypatch.setattr("services.settings_service.write_selected_user_data_root", write_locator)

    manager.complete_user_data_root_change(
        DataRootChangeResult("io_error", str(tmp_path / "custom"), "disk full")
    )

    write_locator.assert_not_called()
    feedback.show_message.assert_called_once()


def test_select_user_data_root_starts_requested_copy(monkeypatch, tmp_path):
    current = tmp_path / "current"
    selected = tmp_path / "selected"
    current.mkdir()
    manager = SettingsManager(
        app_state=SimpleNamespace(),
        feedback_service=Mock(),
        localization_service=localization_service,
    )
    monkeypatch.setattr("services.settings_service.get_user_data_root", lambda: str(current))
    monkeypatch.setattr(
        "services.settings_service.get_existing_directory",
        lambda *_args, **_kwargs: str(selected),
    )
    manager._ask_user_data_root_copy = Mock(return_value=True)
    manager._start_user_data_root_change = Mock()

    manager.select_user_data_root()

    manager._start_user_data_root_change.assert_called_once_with(
        str(selected), copy_data=True
    )


def test_reset_user_data_root_uses_platform_default(monkeypatch, tmp_path):
    current = tmp_path / "current"
    default = tmp_path / "default"
    manager = SettingsManager(
        app_state=SimpleNamespace(),
        feedback_service=Mock(),
        localization_service=localization_service,
    )
    monkeypatch.setattr("services.settings_service.get_user_data_root", lambda: str(current))
    monkeypatch.setattr("services.settings_service.get_default_user_data_root", lambda: str(default))
    manager._ask_user_data_root_copy = Mock(return_value=False)
    manager._start_user_data_root_change = Mock()

    manager.reset_user_data_root()

    manager._start_user_data_root_change.assert_called_once_with(
        str(default), copy_data=False
    )


def test_validate_selected_game_path_accepts_file_uri(monkeypatch, tmp_path):
    """Checks pasted file URIs are normalized before game-path validation."""
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    manager = SettingsManager(
        app_state=SimpleNamespace(game_mode=SimpleNamespace(), local_config={}),
        feedback_service=Mock(),
        localization_service=localization_service,
    )
    monkeypatch.setattr(
        "services.settings_service.resolve_game_executable",
        lambda path, _game_id: "C:/Games/Frickbears3.exe"
        if path == str(game_dir).replace("\\", "/")
        else None,
    )

    result = manager.validate_selected_game_path(
        game_dir.resolve().as_uri(),
        SimpleNamespace(game_id="frickbears3", custom_exec_config_key=""),
    )

    assert result is True


def test_invalid_game_path_warning_feedback_failure_is_suppressed():
    """Checks invalid game path warning cannot crash path validation flow."""
    game = SimpleNamespace(
        display_name="Deltarune",
        executables={"windows": ("DELTARUNE.exe",), "linux": (), "mac": ()},
    )
    manager = SettingsManager(
        app_state=SimpleNamespace(game_mode=game),
        feedback_service=Mock(
            show_message=Mock(side_effect=RuntimeError("toast deleted"))
        ),
        localization_service=localization_service,
    )

    manager.show_invalid_game_path_warning("C:/bad", game)

    manager.feedback_service.show_message.assert_called_once()


def test_prompt_for_game_path_success_ignores_broken_status_feedback(
    monkeypatch, tmp_path
):
    """Checks game path selection persists even when success status UI is gone."""
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    game = SimpleNamespace(
        game_id="deltarune",
        path_select_dialog_key="ui.select_game_path",
        path_not_found_dialog_key="dialogs.path_not_found",
        macos_app_names=(),
        set_game_path=lambda config, path: config.__setitem__("game_path", path),
    )
    app_state = SimpleNamespace(game_mode=game, local_config={})
    manager = SettingsManager(
        app_state=app_state,
        feedback_service=Mock(
            update_status=Mock(side_effect=RuntimeError("status deleted"))
        ),
        localization_service=localization_service,
    )
    manager.write_local_config = Mock()
    manager.validate_selected_game_path = Mock(return_value=True)
    monkeypatch.setattr(
        "services.settings_service.get_open_file_name",
        lambda *_args, **_kwargs: ("", ""),
    )
    monkeypatch.setattr(
        "services.settings_service.get_existing_directory",
        lambda *_args, **_kwargs: str(game_dir),
    )

    assert manager.prompt_for_game_path(is_initial=False) is True
    assert app_state.local_config["game_path"] == str(game_dir)
    manager.write_local_config.assert_called_once()
    manager.feedback_service.update_status.assert_called_once()


def test_prompt_for_game_path_initial_info_failure_still_opens_picker(
    monkeypatch, tmp_path
):
    """Checks initial game-path info feedback cannot block path picker flow."""
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    game = SimpleNamespace(
        game_id="deltarune",
        path_select_dialog_key="ui.select_game_path",
        path_not_found_dialog_key="dialogs.path_not_found",
        macos_app_names=(),
        set_game_path=lambda config, path: config.__setitem__("game_path", path),
    )
    app_state = SimpleNamespace(game_mode=game, local_config={})
    manager = SettingsManager(
        app_state=app_state,
        feedback_service=Mock(
            show_message=Mock(side_effect=RuntimeError("toast deleted")),
            update_status=Mock(),
        ),
        localization_service=localization_service,
    )
    manager.write_local_config = Mock()
    manager.validate_selected_game_path = Mock(return_value=True)
    monkeypatch.setattr(
        "services.settings_service.get_open_file_name",
        lambda *_args, **_kwargs: ("", ""),
    )
    monkeypatch.setattr(
        "services.settings_service.get_existing_directory",
        lambda *_args, **_kwargs: str(game_dir),
    )

    assert manager.prompt_for_game_path(is_initial=True) is True
    assert app_state.local_config["game_path"] == str(game_dir)
    manager.feedback_service.show_message.assert_called_once()


def test_reset_settings_success_feedback_failure_still_returns_true(app_state):
    """Checks settings reset completion is not undone by broken success feedback."""
    manager = SettingsManager(
        app_state=app_state,
        feedback_service=Mock(
            show_message=Mock(side_effect=RuntimeError("toast deleted"))
        ),
        localization_service=localization_service,
    )
    manager.ensure_config_defaults = Mock()
    theme_changed = Mock()
    settings_changed = Mock()
    manager.theme_changed.connect(theme_changed)
    manager.settings_changed.connect(settings_changed)

    assert manager.reset_section(
        "general",
        config_keys={"disable_animations"},
        reset_actions=[],
        has_ui_reset=False,
    ) is True

    theme_changed.assert_called_once()
    settings_changed.assert_called_once()
    manager.feedback_service.show_message.assert_called_once()


def test_background_invalid_format_feedback_failure_is_suppressed(
    monkeypatch, tmp_path
):
    """Checks invalid background warning cannot crash customization flow."""
    bad_file = tmp_path / "bad.txt"
    bad_file.write_text("not image", encoding="utf-8")
    app_state = SimpleNamespace(config_dir=str(tmp_path), local_config={})
    manager = SettingsManager(
        app_state=app_state,
        feedback_service=Mock(
            show_message=Mock(side_effect=RuntimeError("toast deleted"))
        ),
        localization_service=localization_service,
    )
    manager.write_local_config = Mock()
    monkeypatch.setattr(
        "services.settings_service.get_open_file_name",
        lambda *_args, **_kwargs: (str(bad_file), ""),
    )

    manager.on_background_button_click()

    manager.feedback_service.show_message.assert_called_once()
    manager.write_local_config.assert_not_called()


def test_audio_invalid_format_feedback_failure_is_suppressed(monkeypatch, tmp_path):
    """Checks invalid audio warning cannot crash audio customization flow."""
    bad_file = tmp_path / "bad.txt"
    bad_file.write_text("not audio", encoding="utf-8")
    app_state = SimpleNamespace(config_dir=str(tmp_path), local_config={})
    manager = SettingsManager(
        app_state=app_state,
        feedback_service=Mock(
            show_message=Mock(side_effect=RuntimeError("toast deleted"))
        ),
        localization_service=localization_service,
    )
    monkeypatch.setattr(
        "services.settings_service.get_open_file_name",
        lambda *_args, **_kwargs: (str(bad_file), ""),
    )

    manager.on_background_music_button_click()

    manager.feedback_service.show_message.assert_called_once()


def test_audio_remove_success_feedback_failure_still_emits_theme_changed(tmp_path):
    """Checks removed audio is not reported as failed when success feedback breaks."""
    audio_file = tmp_path / "custom_background_music.mp3"
    audio_file.write_bytes(b"audio")
    app_state = SimpleNamespace(config_dir=str(tmp_path), local_config={})
    manager = SettingsManager(
        app_state=app_state,
        feedback_service=Mock(
            show_message=Mock(side_effect=RuntimeError("toast deleted"))
        ),
        localization_service=localization_service,
    )
    theme_changed = Mock()
    manager.theme_changed.connect(theme_changed)

    manager.on_background_music_button_click()

    assert not audio_file.exists()
    theme_changed.assert_called_once()
    manager.feedback_service.show_message.assert_called_once()


def test_logo_invalid_format_feedback_failure_is_suppressed(monkeypatch, tmp_path):
    """Checks invalid logo warning cannot crash logo customization flow."""
    bad_file = tmp_path / "bad.txt"
    bad_file.write_text("not image", encoding="utf-8")
    app_state = SimpleNamespace(config_dir=str(tmp_path), local_config={})
    manager = SettingsManager(
        app_state=app_state,
        feedback_service=Mock(
            show_message=Mock(side_effect=RuntimeError("toast deleted"))
        ),
        localization_service=localization_service,
    )
    monkeypatch.setattr(
        "services.settings_service.get_open_file_name",
        lambda *_args, **_kwargs: (str(bad_file), ""),
    )

    manager.on_logo_button_click()

    manager.feedback_service.show_message.assert_called_once()


def test_font_invalid_format_feedback_failure_is_suppressed(monkeypatch, tmp_path):
    """Checks invalid font warning cannot crash font customization flow."""
    bad_file = tmp_path / "bad.txt"
    bad_file.write_text("not font", encoding="utf-8")
    app_state = SimpleNamespace(config_dir=str(tmp_path), local_config={})
    manager = SettingsManager(
        app_state=app_state,
        feedback_service=Mock(
            show_message=Mock(side_effect=RuntimeError("toast deleted"))
        ),
        localization_service=localization_service,
    )
    monkeypatch.setattr(
        "services.settings_service.get_open_file_name",
        lambda *_args, **_kwargs: (str(bad_file), ""),
    )

    manager.on_font_button_click()

    manager.feedback_service.show_message.assert_called_once()


def test_font_remove_error_feedback_failure_is_suppressed(tmp_path):
    """Checks font removal filesystem errors stay logged if warning feedback breaks."""
    parent = SimpleNamespace(
        customization_service=SimpleNamespace(
            get_custom_font_path=Mock(return_value=str(tmp_path / "custom_font.ttf"))
        )
    )
    app_state = SimpleNamespace(config_dir=str(tmp_path), local_config={})
    manager = SettingsManager(
        app_state=app_state,
        feedback_service=Mock(
            show_message=Mock(side_effect=RuntimeError("toast deleted"))
        ),
        localization_service=localization_service,
    )
    manager.parent_widget = parent
    manager._remove_font_files = Mock(side_effect=PermissionError("denied"))

    manager.on_font_button_click()

    manager.feedback_service.show_message.assert_called_once()
