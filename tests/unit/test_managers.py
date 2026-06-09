"""Unit tests for test managers."""

import json
import os
from unittest.mock import Mock, patch

import pytest
import requests


class TestModManager:
    """Tests for managers."""
    def test_mod_service_initialization(self, app_state, feedback_service):
        """Checks that mod service initialization."""
        from services.mod.service import ModManager

        mod_service = ModManager(app_state=app_state, feedback_service=feedback_service)
        assert mod_service is not None
        assert mod_service.app_state == app_state
        assert mod_service.feedback_service == feedback_service

    def test_mod_service_cache_invalidation(self, app_state, feedback_service):
        """Checks that mod service cache invalidation."""
        from services.mod.service import ModManager

        mod_service = ModManager(app_state=app_state, feedback_service=feedback_service)
        mod_service.invalidate_mods_cache()
        assert not mod_service._mods_cache_valid

    def test_mod_service_scan_empty_directory(self, app_state, feedback_service):
        """Checks that mod service scan empty directory."""
        from services.mod.service import ModManager

        mod_service = ModManager(app_state=app_state, feedback_service=feedback_service)
        cache = mod_service._get_mods_cache(use_async=False)
        assert isinstance(cache, dict)
        assert len(cache) == 0

    def test_mod_service_scan_with_mod(
        self, app_state, feedback_service, sample_mod_folder
    ):
        """Checks that mod service scan with mod."""
        from services.mod.service import ModManager

        mod_service = ModManager(app_state=app_state, feedback_service=feedback_service)
        cache = mod_service._get_mods_cache(use_async=False)
        assert len(cache) > 0
        assert "test_mod_001" in cache

    def test_mod_service_validate_config_valid(self, app_state, feedback_service):
        """Checks that mod service validate config valid."""
        from utils.mod.scan_utils import validate_mod_config

        valid_config = {
            "config_version": "1.0.0",
            "id": "test_mod",
            "name": "Test Mod",
            "version": "1.0.0",
            "game": "deltarune",
            "files": {},
            "tags": [],
        }
        result = validate_mod_config(valid_config, "/fake/path", "test_mod")
        assert result is True

    def test_mod_service_validate_config_missing_fields(
        self, app_state, feedback_service
    ):
        """Checks that mod service validate config missing fields."""
        from utils.mod.scan_utils import validate_mod_config

        invalid_config = {"version": "1.0.0"}
        result = validate_mod_config(invalid_config, "/fake/path", "test_mod")
        assert result is False

    def test_mod_service_validate_config_invalid_types(
        self, app_state, feedback_service
    ):
        """Checks that mod service validate config invalid types."""
        from utils.mod.scan_utils import validate_mod_config

        invalid_config = {"id": "test", "name": 123}
        result = validate_mod_config(invalid_config, "/fake/path", "test_mod")
        assert result is False

        invalid_config2 = {"id": "test", "name": "Test", "files": []}
        result2 = validate_mod_config(invalid_config2, "/fake/path", "test_mod")
        assert result2 is False

        invalid_config3 = {"id": "test", "name": "Test", "tags": {}}
        result3 = validate_mod_config(invalid_config3, "/fake/path", "test_mod")
        assert result3 is False


class TestSettingsManager:
    """Tests for managers."""
    def test_settings_service_initialization(self, app_state, feedback_service, qapp):
        """Checks that settings service initialization."""
        from services.localization_service import localization_service
        from services.settings_service import SettingsManager

        settings_service = SettingsManager(
            app_state=app_state,
            feedback_service=feedback_service,
            localization_service=localization_service,
            parent=qapp,
        )
        assert settings_service is not None
        assert settings_service.app_state == app_state

    def test_settings_service_load_settings(
        self, app_state, feedback_service, temp_config_dir, qapp
    ):
        """Checks that settings service load settings."""
        from services.localization_service import localization_service
        from services.settings_service import SettingsManager

        settings_path = os.path.join(temp_config_dir, "settings.json")
        settings_data = {"test_setting": "test_value", "another_setting": 123}
        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(settings_data, f)
        app_state.config_path = settings_path
        settings_service = SettingsManager(
            app_state=app_state,
            feedback_service=feedback_service,
            localization_service=localization_service,
            parent=qapp,
        )
        loaded_data = settings_service.read_json(settings_path)
        app_state.local_config.update(loaded_data)
        assert app_state.local_config.get("test_setting") == "test_value"

    def test_settings_service_can_restore_normal_geometry_without_applying_maximized_state(
        self, app_state, feedback_service, qapp
    ):
        """Checks that settings service can restore normal geometry without applying maximized state."""
        from services.localization_service import localization_service
        from services.settings_service import SettingsManager

        manager = SettingsManager(
            app_state=app_state,
            feedback_service=feedback_service,
            localization_service=localization_service,
            parent=qapp,
        )
        app_state.local_config["window_geometry_state"] = {
            "x": 120,
            "y": 80,
            "width": 900,
            "height": 700,
            "maximized": True,
        }
        widget = Mock()
        widget.x.return_value = 0
        widget.y.return_value = 0
        widget.width.return_value = 800
        widget.height.return_value = 600
        widget.minimumWidth.return_value = 0
        widget.minimumHeight.return_value = 0
        widget.screen.return_value = None

        restored = manager.load_window_geometry(widget, apply_maximized_state=False)

        assert restored is True
        widget.resize.assert_called_once_with(900, 700)
        widget.move.assert_called_once_with(120, 80)
        widget.setWindowState.assert_not_called()
        assert manager.was_window_maximized() is True

    def test_build_theme_export_settings_includes_config_version(
        self, app_state, feedback_service, qapp
    ):
        """Checks that building theme export settings includes config version."""
        from config.config import THEME_CONFIG_VERSION
        from services.localization_service import localization_service
        from services.settings_service import SettingsManager

        manager = SettingsManager(
            app_state=app_state,
            feedback_service=feedback_service,
            localization_service=localization_service,
            parent=qapp,
        )

        settings = manager.build_theme_export_settings()

        assert settings["config_version"] == THEME_CONFIG_VERSION

    def test_write_theme_archive_uses_theme_config_filename(
        self, app_state, feedback_service, qapp, tmp_path
    ):
        """Checks that writing theme archive uses theme config filename."""
        import zipfile

        from services.localization_service import localization_service
        from services.settings_service import SettingsManager

        manager = SettingsManager(
            app_state=app_state,
            feedback_service=feedback_service,
            localization_service=localization_service,
            parent=qapp,
        )
        archive_path = tmp_path / "theme.zip"

        manager.write_theme_archive(str(archive_path))

        with zipfile.ZipFile(archive_path, "r") as zipf:
            names = zipf.namelist()
            assert "theme_config.json" in names
            assert "theme.json" not in names

    def test_install_theme_from_file_accepts_legacy_theme_json(
        self, app_state, feedback_service, qapp, tmp_path
    ):
        """Checks that installing theme from file accepts legacy theme json."""
        import zipfile

        from services.localization_service import localization_service
        from services.settings_service import SettingsManager

        manager = SettingsManager(
            app_state=app_state,
            feedback_service=feedback_service,
            localization_service=localization_service,
            parent=qapp,
        )
        manager.write_local_config = Mock()
        manager.feedback_service.show_message = Mock()
        theme_emitted = []
        settings_emitted = []
        manager.theme_changed.connect(lambda: theme_emitted.append(True))
        manager.settings_changed.connect(lambda: settings_emitted.append(True))

        archive_path = tmp_path / "legacy_theme.zip"
        with zipfile.ZipFile(archive_path, "w") as zipf:
            zipf.writestr("theme.json", json.dumps({"custom_border_color": "#ABCDEF"}))

        manager._install_theme_from_file(str(archive_path))

        assert app_state.local_config["custom_border_color"] == "#ABCDEF"
        assert theme_emitted == [True]
        assert settings_emitted == [True]
        manager.feedback_service.show_message.assert_called()

    def test_install_theme_from_file_reports_localized_error_for_source_path(
        self, app_state, feedback_service, qapp, tmp_path, monkeypatch
    ):
        from services.localization_service import localization_service, tr
        from services.settings_service import SettingsManager

        manager = SettingsManager(
            app_state=app_state,
            feedback_service=feedback_service,
            localization_service=localization_service,
            parent=qapp,
        )
        manager.feedback_service.show_message = Mock()
        manager.parent_widget = Mock()
        manager.parent_widget.do_not_save_theme_checkbox = Mock(isChecked=Mock(return_value=True))

        archive_path = tmp_path / "broken_theme.zip"
        with patch("zipfile.ZipFile") as zip_cls:
            zip_obj = Mock()
            zip_obj.__enter__ = Mock(return_value=zip_obj)
            zip_obj.__exit__ = Mock(return_value=False)
            zip_obj.namelist.return_value = ["theme.json"]
            zip_cls.return_value = zip_obj
            monkeypatch.setattr(
                "utils.archive_utils.extract_any_archive",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    PermissionError(13, "Permission denied", str(archive_path))
                ),
            )

            manager._install_theme_from_file(str(archive_path))

        manager.feedback_service.show_message.assert_called_once_with(
            "error",
            "dialogs.error",
            tr(
                "dialogs.theme_import_failed",
                error=tr("errors.permission_denied", path=str(archive_path)),
            ),
        )

    def test_validate_executable_path_accepts_unix_script_signature(
        self, app_state, feedback_service, qapp, monkeypatch, tmp_path
    ):
        from services.localization_service import localization_service
        from services.settings_service import SettingsManager

        manager = SettingsManager(
            app_state=app_state,
            feedback_service=feedback_service,
            localization_service=localization_service,
            parent=qapp,
        )
        script_path = tmp_path / "tool"
        script_path.write_bytes(b"#!/bin/sh\necho ok\n")
        script_path.chmod(0o755)
        monkeypatch.setattr("services.settings_service.platform.system", lambda: "Linux")

        assert manager.validate_executable_path(str(script_path)) is True

    def test_validate_executable_path_uses_suspended_windows_probe(
        self, app_state, feedback_service, qapp, monkeypatch, tmp_path
    ):
        from services.localization_service import localization_service
        from services.settings_service import SettingsManager

        manager = SettingsManager(
            app_state=app_state,
            feedback_service=feedback_service,
            localization_service=localization_service,
            parent=qapp,
        )
        exe_path = tmp_path / "tool.exe"
        exe_path.write_bytes(b"MZ")
        calls = []

        class _Process:
            def kill(self):
                return None

            def wait(self, timeout=None):
                return 0

        monkeypatch.setattr("services.settings_service.platform.system", lambda: "Windows")
        monkeypatch.setattr(
            "services.settings_service.subprocess.CREATE_NO_WINDOW",
            0x08000000,
            raising=False,
        )
        monkeypatch.setattr(
            "services.settings_service.subprocess.CREATE_SUSPENDED",
            0x00000004,
            raising=False,
        )
        monkeypatch.setattr(
            "services.settings_service.subprocess.Popen",
            lambda *args, **kwargs: calls.append((args, kwargs)) or _Process(),
        )

        assert manager.validate_executable_path(str(exe_path)) is True
        assert calls[0][0][0] == [str(exe_path)]
        assert calls[0][1]["creationflags"] == 0x08000000 | 0x00000004

    def test_validate_executable_path_rejects_invalid_binary_error(
        self, app_state, feedback_service, qapp, monkeypatch, tmp_path
    ):
        from services.localization_service import localization_service
        from services.settings_service import SettingsManager

        manager = SettingsManager(
            app_state=app_state,
            feedback_service=feedback_service,
            localization_service=localization_service,
            parent=qapp,
        )
        exe_path = tmp_path / "bad.exe"
        exe_path.write_bytes(b"MZ")
        monkeypatch.setattr("services.settings_service.platform.system", lambda: "Windows")

        monkeypatch.setattr(
            "services.settings_service.subprocess.Popen",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                OSError("[WinError 193] %1 is not a valid Win32 application")
            ),
        )

        assert manager.validate_executable_path(str(exe_path)) is False

    def test_select_executable_path_rejects_invalid_binary_and_shows_warning(
        self, app_state, feedback_service, qapp, monkeypatch
    ):
        from services.localization_service import localization_service
        from services.settings_service import SettingsManager

        manager = SettingsManager(
            app_state=app_state,
            feedback_service=feedback_service,
            localization_service=localization_service,
            parent=qapp,
        )
        manager.feedback_service.show_message = Mock()
        monkeypatch.setattr(
            "services.settings_service.get_open_file_name",
            lambda *args, **kwargs: ("C:/bad.bin", ""),
        )
        monkeypatch.setattr(
            manager,
            "get_executable_path_error",
            lambda *_args, **_kwargs: "Configured launch executable was not found: C:/bad.bin",
        )

        assert manager.select_executable_path("Select binary") is None
        manager.feedback_service.show_message.assert_called_once()
        assert (
            manager.feedback_service.show_message.call_args.args[2]
            == "Configured launch executable was not found: C:/bad.bin"
        )

    def test_get_executable_path_error_reports_missing_file(
        self, app_state, feedback_service, qapp
    ):
        from services.localization_service import localization_service, tr
        from services.settings_service import SettingsManager

        manager = SettingsManager(
            app_state=app_state,
            feedback_service=feedback_service,
            localization_service=localization_service,
            parent=qapp,
        )

        assert (
            manager.get_executable_path_error("C:/missing/tool.exe")
            == tr("errors.launch_command_missing_path", path="C:/missing/tool.exe")
        )

    def test_get_executable_path_error_reports_windows_permission_denied(
        self, app_state, feedback_service, qapp, monkeypatch, tmp_path
    ):
        from services.localization_service import localization_service, tr
        from services.settings_service import SettingsManager

        manager = SettingsManager(
            app_state=app_state,
            feedback_service=feedback_service,
            localization_service=localization_service,
            parent=qapp,
        )
        exe_path = tmp_path / "tool.exe"
        exe_path.write_bytes(b"MZ")
        monkeypatch.setattr("services.settings_service.platform.system", lambda: "Windows")
        monkeypatch.setattr(
            "services.settings_service.subprocess.Popen",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                PermissionError(13, "Permission denied", str(exe_path))
            ),
        )

        assert (
            manager.get_executable_path_error(str(exe_path))
            == tr("errors.launch_permission_denied", path=str(exe_path))
        )

    def test_describe_fs_error_reports_missing_file(self, app_state, feedback_service, qapp):
        from services.localization_service import localization_service, tr
        from services.settings_service import SettingsManager

        manager = SettingsManager(
            app_state=app_state,
            feedback_service=feedback_service,
            localization_service=localization_service,
            parent=qapp,
        )

        assert (
            manager._describe_fs_error(
                FileNotFoundError(2, "No such file", "C:/missing/file.png")
            )
            == tr("errors.file_not_found", path="C:/missing/file.png")
        )

    def test_validate_selected_game_path_requires_supported_executable_without_custom_exe(
        self, app_state, feedback_service, qapp, tmp_path, monkeypatch
    ):
        from services.localization_service import localization_service
        from services.settings_service import SettingsManager

        manager = SettingsManager(
            app_state=app_state,
            feedback_service=feedback_service,
            localization_service=localization_service,
            parent=qapp,
        )
        game_dir = tmp_path / "game"
        game_dir.mkdir()
        monkeypatch.setattr("services.settings_service.resolve_game_executable", lambda *_args, **_kwargs: None)

        assert manager.validate_selected_game_path(str(game_dir)) is False

    def test_validate_selected_game_path_allows_custom_exe_override(
        self, app_state, feedback_service, qapp, tmp_path, monkeypatch
    ):
        from services.localization_service import localization_service
        from services.settings_service import SettingsManager

        manager = SettingsManager(
            app_state=app_state,
            feedback_service=feedback_service,
            localization_service=localization_service,
            parent=qapp,
        )
        game_dir = tmp_path / "game"
        game_dir.mkdir()
        app_state.local_config[app_state.game_mode.get_custom_exec_config_key()] = "C:/custom.exe"
        monkeypatch.setattr("services.settings_service.resolve_game_executable", lambda *_args, **_kwargs: None)

        assert manager.validate_selected_game_path(str(game_dir)) is True

    def test_prompt_for_game_path_rejects_directory_without_supported_executable(
        self, app_state, feedback_service, qapp, monkeypatch, tmp_path
    ):
        from services.localization_service import localization_service
        from services.settings_service import SettingsManager

        manager = SettingsManager(
            app_state=app_state,
            feedback_service=feedback_service,
            localization_service=localization_service,
            parent=qapp,
        )
        manager.feedback_service.show_message = Mock()
        manager.write_local_config = Mock()
        invalid_dir = tmp_path / "invalid_game"
        invalid_dir.mkdir()
        monkeypatch.setattr(
            "services.settings_service.get_open_file_name",
            lambda *args, **kwargs: ("", ""),
        )
        monkeypatch.setattr(
            "services.settings_service.get_existing_directory",
            lambda *args, **kwargs: str(invalid_dir),
        )
        monkeypatch.setattr("services.settings_service.resolve_game_executable", lambda *_args, **_kwargs: None)

        assert manager.prompt_for_game_path(is_initial=False) is False
        assert app_state.game_mode.get_game_path(app_state.local_config) == ""
        manager.write_local_config.assert_not_called()
        manager.feedback_service.show_message.assert_called_once()

    def test_prompt_for_game_path_does_not_pass_application_as_dialog_parent_on_macos(
        self, app_state, feedback_service, qapp, monkeypatch
    ):
        from services.localization_service import localization_service
        from services.settings_service import SettingsManager

        manager = SettingsManager(
            app_state=app_state,
            feedback_service=feedback_service,
            localization_service=localization_service,
            parent=qapp,
        )
        captured = {}

        def fake_get_open_file_name(parent, *_args, **_kwargs):
            captured["open_parent"] = parent
            return "", ""

        def fake_get_existing_directory(parent, *_args, **_kwargs):
            captured["directory_parent"] = parent
            return ""

        monkeypatch.setattr("services.settings_service.platform.system", lambda: "Darwin")
        monkeypatch.setattr(
            "services.settings_service.get_open_file_name",
            fake_get_open_file_name,
        )
        monkeypatch.setattr(
            "services.settings_service.get_existing_directory",
            fake_get_existing_directory,
        )

        assert manager.prompt_for_game_path(is_initial=False) is False
        assert captured["open_parent"] is None
        assert captured["directory_parent"] is None


class TestLocalizationManager:
    """Tests for managers."""
    def test_localization_service_tr(self):
        """Checks that localization service tr."""
        from services.localization_service import tr

        result = tr("test.id")
        assert isinstance(result, str)

    def test_localization_service_detect_language(self):
        """Checks that localization service detect language."""
        from services.localization_service import localization_service

        language = localization_service.detect_system_language()
        assert language is not None
        assert isinstance(language, str)


class TestLaunchManager:
    """Tests for managers."""
    def test_launch_service_initialization(self, app_state, feedback_service):
        """Checks that launch service initialization."""
        from services.launch_service import GameLauncher
        from services.mod.service import ModManager

        mod_service = ModManager(app_state, feedback_service)
        launcher = GameLauncher(
            app_state=app_state,
            feedback_service=feedback_service,
            mod_service=mod_service,
        )
        assert launcher is not None
        assert launcher.app_state == app_state

    def test_close_game_uses_border_status_color(self, app_state, feedback_service):
        """Checks that closing game uses border status color."""
        from services.launch_service import GameLauncher
        from services.localization_service import tr

        app_state.local_config = {"custom_border_color": "#123456"}
        launcher = GameLauncher(
            app_state=app_state, feedback_service=feedback_service, mod_service=Mock()
        )
        launcher.monitor_worker = Mock(process=Mock())
        emitted = []
        launcher.status_changed.connect(
            lambda message, color: emitted.append((message, color))
        )

        launcher.close_game()

        launcher.monitor_worker.process.terminate.assert_called_once_with()
        assert len(emitted) == 1
        assert emitted[0] == (tr("status.game_closed"), "#123456")

    def test_launch_game_with_selections_uses_border_status_color_for_launch_messages(
        self, app_state, feedback_service
    ):
        """Checks that launching game with selections uses border status color for launch messages."""
        from services.launch_service import GameLauncher
        from services.localization_service import tr

        app_state.local_config = {"custom_border_color": "#654321"}
        launcher = GameLauncher(
            app_state=app_state, feedback_service=feedback_service, mod_service=Mock()
        )
        emitted = []
        launcher.status_changed.connect(
            lambda message, color: emitted.append((message, color))
        )
        launcher._has_selected_mods = Mock(return_value=False)
        launcher._get_current_game_path = Mock(return_value="C:/game")
        launcher._continue_after_patching = Mock()

        with patch("services.launch_service.os.path.exists", return_value=True):
            launcher._launch_game_with_selections({})

        assert len(emitted) == 1
        assert emitted[0] == (tr("status.launching_game"), "#654321")

    def test_handle_launch_failure_restores_window_and_updates_button(
        self, app_state, feedback_service
    ):
        """Checks that handling launch failure restores window and updates button."""
        from services.launch_service import GameLauncher

        parent = Mock()
        launcher = GameLauncher(
            app_state=app_state,
            feedback_service=feedback_service,
            mod_service=Mock(),
        )
        launcher.restore_window_callback = Mock()

        with patch.object(launcher, "parent", return_value=parent):
            launcher._handle_launch_failure()

        launcher.restore_window_callback.assert_called_once()
        parent.game_launch.update_button_state.assert_called_once()

    def test_execute_game_uses_detached_steam_launch_on_linux(
        self, app_state, feedback_service
    ):
        """Checks that executing game uses detached steam launch on linux."""
        from services.launch_service import GameLauncher

        launcher = GameLauncher(
            app_state=app_state, feedback_service=feedback_service, mod_service=Mock()
        )
        launcher._execute_plugin_hook = Mock()

        with (
            patch("services.launch_service.platform.system", return_value="Linux"),
            patch("services.launch_service.QThread", return_value=Mock()),
            patch("services.launch_service.GameMonitorWorker", return_value=Mock()),
            patch.object(
                launcher, "_start_detached_command", return_value=True
            ) as start_detached,
            patch("services.launch_service.open_url_native") as web_open,
        ):
            launcher._execute_game(
                {"target": "steam://rungameid/1690940", "cwd": None, "type": "url"}
            )

        start_detached.assert_called_once_with(
            "steam", ["steam://rungameid/1690940"]
        )
        web_open.assert_not_called()

    def test_execute_game_falls_back_to_xdg_open_when_steam_detach_fails_on_linux(
        self, app_state, feedback_service
    ):
        """Checks that executing game falls back to xdg open when steam detach fails on linux."""
        from services.launch_service import GameLauncher

        launcher = GameLauncher(
            app_state=app_state, feedback_service=feedback_service, mod_service=Mock()
        )
        launcher._execute_plugin_hook = Mock()

        with (
            patch("services.launch_service.platform.system", return_value="Linux"),
            patch("services.launch_service.QThread", return_value=Mock()),
            patch("services.launch_service.GameMonitorWorker", return_value=Mock()),
            patch.object(
                launcher, "_start_detached_command", side_effect=[False, True]
            ) as start_detached,
        ):
            launcher._execute_game(
                {"target": "steam://rungameid/1690940", "cwd": None, "type": "url"}
            )

        assert start_detached.call_args_list == [
            (("steam", ["steam://rungameid/1690940"]),),
            (("xdg-open", ["steam://rungameid/1690940"]),),
        ]

    def test_execute_game_sanitizes_linux_env_for_subprocess_launch(
        self, app_state, feedback_service
    ):
        """Checks that Linux subprocess launch restores system library paths."""
        from services.launch_service import GameLauncher

        launcher = GameLauncher(
            app_state=app_state, feedback_service=feedback_service, mod_service=Mock()
        )
        fake_process = Mock()

        with (
            patch("services.launch_service.platform.system", return_value="Linux"),
            patch("services.launch_service.os.path.isdir", return_value=True),
            patch("services.launch_service.subprocess.Popen", return_value=fake_process) as popen,
            patch("services.launch_service.QThread", return_value=Mock()),
            patch("services.launch_service.GameMonitorWorker", return_value=Mock()),
            patch.dict(
                "services.launch_service.os.environ",
                {
                    "LD_LIBRARY_PATH": "/opt/g3m-bundle",
                    "LD_LIBRARY_PATH_ORIG": "/usr/lib:/usr/local/lib",
                    "PATH": os.environ.get("PATH", ""),
                },
                clear=False,
            ),
        ):
            launcher._execute_game(
                {
                    "target": "/games/DELTARUNE.exe",
                    "cwd": "/games",
                    "type": "subprocess",
                }
            )

        popen.assert_called_once()
        assert popen.call_args.kwargs["cwd"] == "/games"
        assert popen.call_args.kwargs["creationflags"] == 0
        assert popen.call_args.kwargs["env"]["LD_LIBRARY_PATH"] == "/usr/lib:/usr/local/lib"
        assert popen.call_args.args[0] == ["wine", "/games/DELTARUNE.exe"]

    def test_execute_game_uses_wine64_when_wine_missing(
        self, app_state, feedback_service
    ):
        from services.launch_service import GameLauncher

        launcher = GameLauncher(
            app_state=app_state, feedback_service=feedback_service, mod_service=Mock()
        )
        fake_process = Mock()
        launcher.app_state.local_config["custom_wine_path"] = ""

        with (
            patch("services.launch_service.platform.system", return_value="Linux"),
            patch("services.launch_service.os.path.isdir", return_value=True),
            patch("utils.process_utils.shutil.which", side_effect=lambda name: None if name == "wine" else "/usr/bin/wine64"),
            patch("services.launch_service.subprocess.Popen", return_value=fake_process) as popen,
            patch("services.launch_service.QThread", return_value=Mock()),
            patch("services.launch_service.GameMonitorWorker", return_value=Mock()),
        ):
            launcher._execute_game(
                {
                    "target": "/games/DELTARUNE.exe",
                    "cwd": "/games",
                    "type": "subprocess",
                }
            )

        assert popen.call_args.args[0] == ["wine64", "/games/DELTARUNE.exe"]

    def test_execute_game_reports_missing_wine_command_precisely(
        self, app_state, feedback_service
    ):
        from services.launch_service import GameLauncher
        from services.localization_service import tr

        launcher = GameLauncher(
            app_state=app_state, feedback_service=feedback_service, mod_service=Mock()
        )
        emitted = []
        launcher.status_changed.connect(lambda message, color: emitted.append((message, color)))

        with (
            patch("services.launch_service.platform.system", return_value="Linux"),
            patch("services.launch_service.os.path.isdir", return_value=True),
            patch(
                "services.launch_service.subprocess.Popen",
                side_effect=FileNotFoundError(2, "No such file or directory", "wine"),
            ),
        ):
            launcher._execute_game(
                {"target": "/games/DELTARUNE.exe", "cwd": "/games", "type": "subprocess"}
            )

        assert emitted[-1][0] == tr("errors.wine_not_found")

    def test_execute_game_reports_missing_target_precisely(
        self, app_state, feedback_service
    ):
        from services.launch_service import GameLauncher
        from services.localization_service import tr

        launcher = GameLauncher(
            app_state=app_state, feedback_service=feedback_service, mod_service=Mock()
        )
        emitted = []
        launcher.status_changed.connect(lambda message, color: emitted.append((message, color)))

        missing_target = "/games/missing.exe"
        with (
            patch("services.launch_service.platform.system", return_value="Windows"),
            patch("services.launch_service.os.path.isdir", return_value=True),
            patch(
                "services.launch_service.subprocess.Popen",
                side_effect=FileNotFoundError(2, "No such file or directory", missing_target),
            ),
        ):
            launcher._execute_game(
                {"target": missing_target, "cwd": "/games", "type": "subprocess"}
            )

        assert emitted[-1][0] == tr("errors.launch_target_missing", path=missing_target)

    def test_execute_game_reports_permission_denied_precisely(
        self, app_state, feedback_service
    ):
        from services.launch_service import GameLauncher
        from services.localization_service import tr

        launcher = GameLauncher(
            app_state=app_state, feedback_service=feedback_service, mod_service=Mock()
        )
        emitted = []
        launcher.status_changed.connect(lambda message, color: emitted.append((message, color)))

        denied_path = "/games/DELTARUNE.exe"
        with (
            patch("services.launch_service.platform.system", return_value="Windows"),
            patch("services.launch_service.os.path.isdir", return_value=True),
            patch(
                "services.launch_service.subprocess.Popen",
                side_effect=PermissionError(13, "Permission denied", denied_path),
            ),
        ):
            launcher._execute_game(
                {"target": denied_path, "cwd": "/games", "type": "subprocess"}
            )

        assert emitted[-1][0] == tr("errors.launch_permission_denied", path=denied_path)


class TestUpdateCheckManager:
    """Tests for managers."""
    @patch("requests.get")
    def test_update_checker_initialization(self, mock_get, app_state, feedback_service):
        """Checks that update checker initialization."""
        from services.updatecheck_service import UpdateChecker

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"version": "1.0.0"}
        mock_get.return_value = mock_response
        checker = UpdateChecker(app_state=app_state, feedback_service=feedback_service)
        assert checker is not None

    def test_update_extract_archive_reports_missing_archive_as_app_error(
        self, app_state, feedback_service
    ):
        from models.exceptions import AppError
        from services.localization_service import tr
        from services.updatecheck_service import UpdateChecker

        checker = UpdateChecker(app_state=app_state, feedback_service=feedback_service)

        with patch(
            "utils.archive_utils.extract_archive",
            side_effect=FileNotFoundError(2, "No such file", "missing.zip"),
        ):
            with pytest.raises(AppError) as exc_info:
                checker._extract_archive("Linux", "missing.zip", "out")
            assert str(exc_info.value) == tr("errors.archive_not_found")

    def test_update_worker_error_formats_request_failures_precisely(
        self, app_state, feedback_service
    ):
        from services.localization_service import tr
        from services.updatecheck_service import UpdateChecker

        checker = UpdateChecker(app_state=app_state, feedback_service=feedback_service)
        error = requests.exceptions.ConnectionError("Connection refused")

        assert checker._format_update_worker_error(error) == tr(
            "errors.network_connection_refused"
        )

    def test_update_worker_error_formats_filesystem_failures_precisely(
        self, app_state, feedback_service
    ):
        from services.localization_service import tr
        from services.updatecheck_service import UpdateChecker

        checker = UpdateChecker(app_state=app_state, feedback_service=feedback_service)
        error = PermissionError(13, "Permission denied", "/opt/G3M")

        assert checker._format_update_worker_error(error) == tr(
            "errors.permission_denied", path="/opt/G3M"
        )


class TestCustomizationManager:
    """Tests for managers."""
    def test_customization_service_initialization(self, app_state):
        """Checks that customization service initialization."""
        from services.customization_service import CustomizationManager

        manager = CustomizationManager(app_state)
        assert manager is not None
        assert manager.app_state == app_state

    def test_customization_service_pause_is_non_blocking(self, app_state):
        """Checks that pausing background music does not block waiting for the thread."""
        from unittest.mock import Mock

        from services.customization_service import CustomizationManager

        manager = CustomizationManager(app_state)
        manager._current_music_path = "music.mp3"
        player = Mock()
        player.is_alive.return_value = True
        player.join = Mock()
        player.terminate = Mock()
        manager._bg_music_instance = player

        manager.stop_background_music(wait_for_thread=False)

        player.terminate.assert_called_once()
        player.join.assert_not_called()
        assert manager._focus_pause_active is False
        assert manager._current_music_path is None

    def test_customization_service_focus_pause_preserves_state_and_resumes(self, app_state):
        """Checks that focus pause keeps pause state until resume restarts music."""
        from unittest.mock import Mock, patch

        from services.customization_service import CustomizationManager

        manager = CustomizationManager(app_state)
        manager.get_background_music_path = Mock(return_value="music.mp3")

        with patch.object(manager, "stop_background_music") as stop_music:
            manager.set_background_music_focus_paused(True)

        stop_music.assert_called_once_with(
            wait_for_thread=False, preserve_focus_pause=True
        )
        assert manager._focus_pause_active is True

        with patch.object(manager, "maybe_start_background_music") as maybe_start:
            manager.set_background_music_focus_paused(False)

        maybe_start.assert_called_once_with(force=True)

    def test_customization_service_does_not_start_music_while_game_running(self, app_state):
        """Checks that background music stays off while the game is running."""
        from unittest.mock import Mock, patch

        from PyQt6.QtWidgets import QWidget

        from services.customization_service import CustomizationManager

        parent = QWidget()
        parent.show()
        app_state.is_shown_to_user = True
        app_state.game_is_running = True
        try:
            manager = CustomizationManager(app_state, parent)
            manager.get_background_music_path = Mock(return_value="music.mp3")

            with patch(
                "services.customization_service.os.path.exists", return_value=True
            ), patch.object(manager, "start_background_music") as start_music:
                manager.maybe_start_background_music(force=True)

            start_music.assert_not_called()
        finally:
            parent.close()

    def test_customization_service_monitor_restarts_finished_music(self, app_state):
        """Checks that finished background music starts again when playback ends."""
        from unittest.mock import Mock, patch

        from PyQt6.QtWidgets import QWidget

        from services.customization_service import CustomizationManager

        parent = QWidget()
        parent.show()
        app_state.is_shown_to_user = True
        app_state.game_is_running = False
        try:
            manager = CustomizationManager(app_state, parent)
            manager.get_background_music_path = Mock(return_value="music.mp3")
            player = Mock()
            player.is_alive.return_value = False
            manager._bg_music_instance = player
            manager._current_music_path = "music.mp3"

            with patch(
                "services.customization_service.os.path.exists", return_value=True
            ), patch.object(manager, "start_background_music") as start_music:
                manager._ensure_background_music_state()

            start_music.assert_called_once_with(force=False)
        finally:
            parent.close()

    def test_customization_service_get_font_path(self, app_state, temp_dir):
        """Checks that customization service get font path."""
        from services.customization_service import CustomizationManager

        manager = CustomizationManager(app_state)
        app_state.config_dir = temp_dir
        assert manager.get_custom_font_path() == ""
        font_path = os.path.join(temp_dir, "custom_font.ttf")
        with open(font_path, "w") as f:
            f.write("dummy")
        assert manager.get_custom_font_path() == font_path

    @patch("services.customization_service.tr")
    def test_customization_service_get_font_button_text(
        self, mock_tr, app_state, temp_dir
    ):
        """Checks that customization service get font button text."""
        from services.customization_service import CustomizationManager

        mock_tr.side_effect = lambda key, **_: key
        manager = CustomizationManager(app_state)
        app_state.config_dir = temp_dir
        assert manager.get_font_button_text() == "buttons.change_font"
        font_path = os.path.join(temp_dir, "custom_font.ttf")
        with open(font_path, "w") as f:
            f.write("dummy")
        assert manager.get_font_button_text() == "buttons.remove_font"


class TestBackupManager:
    """Tests for managers."""
    def test_backup_restoration_order(self, temp_dir):
        """Checks that backup restoration order."""
        import logging

        from services.backup_service import BackupManager

        backup_dir = os.path.join(temp_dir, "backups")
        backup_service = BackupManager(
            backup_dir, patching_logger=logging.getLogger("test")
        )
        chapter_id = 1
        test_dir = os.path.join(temp_dir, "test_game")
        os.makedirs(test_dir, exist_ok=True)
        file1 = os.path.join(test_dir, "file1.txt")
        file2 = os.path.join(test_dir, "file2.txt")
        file3 = os.path.join(test_dir, "file3.txt")
        for f in [file1, file2, file3]:
            with open(f, "w") as fh:
                fh.write("original")
        backup_service.backup_file(chapter_id, file1)
        backup_service.backup_file(chapter_id, file2)
        backup_service.backup_file(chapter_id, file3)
        for f in [file1, file2, file3]:
            with open(f, "w") as fh:
                fh.write("modified")
        backup_service.restore_backups(chapter_id)
        for f in [file1, file2, file3]:
            with open(f) as fh:
                content = fh.read()
                assert content == "original", f"File {f} was not restored correctly"

    def test_backup_restoration_validation(self, temp_dir):
        """Checks that backup restoration validation."""
        import logging

        from services.backup_service import BackupManager

        backup_dir = os.path.join(temp_dir, "backups")
        backup_service = BackupManager(
            backup_dir, patching_logger=logging.getLogger("test")
        )
        chapter_id = 1
        test_dir = os.path.join(temp_dir, "test_game")
        os.makedirs(test_dir, exist_ok=True)
        test_file = os.path.join(test_dir, "test.txt")
        original_content = "original content"
        with open(test_file, "w") as f:
            f.write(original_content)
        backup_service.backup_file(chapter_id, test_file)
        with open(test_file, "w") as f:
            f.write("modified content")
        backup_service.restore_backups(chapter_id)
        assert os.path.exists(test_file)
        with open(test_file) as f:
            restored_content = f.read()
            assert restored_content == original_content
        backup_size = os.path.getsize(os.path.join(backup_dir, "chapter_1_test.txt"))
        restored_size = os.path.getsize(test_file)
        assert backup_size == restored_size

    def test_sound_file_backup_restoration(self, temp_dir):
        """Checks that sound file backup restoration."""
        import logging

        from services.backup_service import BackupManager

        backup_dir = os.path.join(temp_dir, "backups")
        backup_service = BackupManager(
            backup_dir, patching_logger=logging.getLogger("test")
        )
        chapter_id = 1
        sound_dir = os.path.join(temp_dir, "test_game", "sound", "Desktop")
        os.makedirs(sound_dir, exist_ok=True)
        bank_file = os.path.join(sound_dir, "test.bank")
        original_content = b"BANK_FILE_CONTENT"
        with open(bank_file, "wb") as f:
            f.write(original_content)
        backup_service.backup_file(chapter_id, bank_file)
        modified_content = b"MODIFIED_BANK_CONTENT"
        with open(bank_file, "wb") as f:
            f.write(modified_content)
        backup_service.restore_backups(chapter_id)
        assert os.path.exists(bank_file)
        with open(bank_file, "rb") as f:
            restored_content = f.read()
            assert restored_content == original_content


class TestExpandedFormats:
    """Tests for managers."""
    def test_customization_service_audio_formats(self, app_state, temp_dir):
        """Checks that customization service audio formats."""
        from services.customization_service import CustomizationManager

        manager = CustomizationManager(app_state)
        app_state.config_dir = temp_dir

        for ext in [".ogg", ".flac", ".m4a", ".aac"]:
            path = os.path.join(temp_dir, f"custom_background_music{ext}")
            with open(path, "w") as f:
                f.write("dummy")
            assert manager.get_background_music_path() == path
            os.remove(path)

    def test_customization_service_webp_logo(self, app_state, temp_dir):
        """Checks that customization service webp logo."""
        from services.customization_service import CustomizationManager

        manager = CustomizationManager(app_state)
        app_state.config_dir = temp_dir

        path = os.path.join(temp_dir, "custom_logo.webp")
        with open(path, "w") as f:
            f.write("dummy")
        assert manager.get_custom_logo_path() == path

    def test_settings_manager_audio_paths(self, app_state, feedback_service, qapp):
        """Checks that settings manager audio paths."""
        from services.localization_service import localization_service
        from services.settings_service import SettingsManager

        manager = SettingsManager(
            app_state, feedback_service, localization_service, parent=qapp
        )

        paths = manager._get_audio_paths("background_music")
        assert any(p.endswith(".ogg") for p in paths)
        assert any(p.endswith(".flac") for p in paths)

    def test_settings_manager_applies_disable_startup_sound_default(
        self, app_state, feedback_service, qapp
    ):
        """Checks that settings manager applies disable startup sound default."""
        from services.localization_service import localization_service
        from services.settings_service import SettingsManager

        manager = SettingsManager(
            app_state, feedback_service, localization_service, parent=qapp
        )
        manager.ensure_config_defaults()
        assert app_state.local_config["disable_startup_sound"] is False

    def test_background_selection_copies_file_to_config_dir(
        self, app_state, feedback_service, qapp, tmp_path, monkeypatch
    ):
        """Checks that background selection copies file to config dir."""
        from services.localization_service import localization_service
        from services.settings_service import SettingsManager

        external_bg = tmp_path / "wallpaper.png"
        external_bg.write_bytes(b"image")
        config_dir = tmp_path / "settings"
        config_dir.mkdir()
        app_state.config_dir = str(config_dir)

        manager = SettingsManager(
            app_state, feedback_service, localization_service, parent=qapp
        )
        manager.write_local_config = Mock()

        monkeypatch.setattr(
            "services.settings_service.get_open_file_name",
            lambda *args, **kwargs: (str(external_bg), ""),
        )

        manager.on_background_button_click()

        expected_path = config_dir / "custom_background.png"
        assert app_state.local_config["custom_background_path"] == str(expected_path)
        assert expected_path.exists()
        assert external_bg.exists()
        manager.write_local_config.assert_called_once()

    def test_background_removal_keeps_external_legacy_file(
        self, app_state, feedback_service, qapp, tmp_path
    ):
        """Checks that background removal keeps external legacy file."""
        from services.localization_service import localization_service
        from services.settings_service import SettingsManager

        external_bg = tmp_path / "legacy_wallpaper.png"
        external_bg.write_bytes(b"image")
        config_dir = tmp_path / "settings"
        config_dir.mkdir()
        app_state.config_dir = str(config_dir)
        app_state.local_config["custom_background_path"] = str(external_bg)

        manager = SettingsManager(
            app_state, feedback_service, localization_service, parent=qapp
        )
        manager.write_local_config = Mock()

        manager.on_background_button_click()

        assert app_state.local_config["custom_background_path"] == ""
        assert external_bg.exists()
        manager.write_local_config.assert_called_once()

    def test_clear_g3mtool_cache_requires_confirmation(
        self, app_state, feedback_service, qapp, tmp_path, monkeypatch
    ):
        from services.localization_service import localization_service
        from services.settings_service import SettingsManager

        cache_dir = tmp_path / "cache" / "G3MTool"
        cache_dir.mkdir(parents=True)
        cached_file = cache_dir / "cached.g3mcache"
        cached_file.write_text("cache", encoding="utf-8")
        feedback_service.ask_question = Mock(return_value=False)

        manager = SettingsManager(
            app_state, feedback_service, localization_service, parent=qapp
        )
        monkeypatch.setattr(
            "services.settings_service.get_g3mtool_cache_dir",
            lambda: str(cache_dir),
        )

        assert manager.clear_g3mtool_cache() is False
        assert cached_file.exists()
        feedback_service.ask_question.assert_called_once()

    def test_clear_g3mtool_cache_removes_contents_only(
        self, app_state, feedback_service, qapp, tmp_path, monkeypatch
    ):
        from services.localization_service import localization_service
        from services.settings_service import SettingsManager

        cache_dir = tmp_path / "cache" / "G3MTool"
        nested_dir = cache_dir / "nested"
        nested_dir.mkdir(parents=True)
        (cache_dir / "root.g3mcache").write_text("cache", encoding="utf-8")
        (nested_dir / "nested.g3mcache").write_text("cache", encoding="utf-8")
        feedback_service.ask_question = Mock(return_value=True)
        feedback_service.show_message = Mock()

        manager = SettingsManager(
            app_state, feedback_service, localization_service, parent=qapp
        )
        monkeypatch.setattr(
            "services.settings_service.get_g3mtool_cache_dir",
            lambda: str(cache_dir),
        )

        assert manager.clear_g3mtool_cache() is True
        assert cache_dir.exists()
        assert list(cache_dir.iterdir()) == []
        feedback_service.show_message.assert_called_once()
