import json
import os
from unittest.mock import Mock, patch


class TestModManager:
    """Tests for managers."""
    def test_mod_service_initialization(self, app_state, feedback_service):
        """Checks that moding service initialization."""
        from services.mod_service import ModManager

        mod_service = ModManager(app_state=app_state, feedback_service=feedback_service)
        assert mod_service is not None
        assert mod_service.app_state == app_state
        assert mod_service.feedback_service == feedback_service

    def test_mod_service_cache_invalidation(self, app_state, feedback_service):
        """Checks that moding service cache invalidation."""
        from services.mod_service import ModManager

        mod_service = ModManager(app_state=app_state, feedback_service=feedback_service)
        mod_service.invalidate_mods_cache()
        assert not mod_service._mods_cache_valid

    def test_mod_service_scan_empty_directory(self, app_state, feedback_service):
        """Checks that moding service scan empty directory."""
        from services.mod_service import ModManager

        mod_service = ModManager(app_state=app_state, feedback_service=feedback_service)
        cache = mod_service._get_mods_cache(use_async=False)
        assert isinstance(cache, dict)
        assert len(cache) == 0

    def test_mod_service_scan_with_mod(
        self, app_state, feedback_service, sample_mod_folder
    ):
        """Checks that moding service scan with mod."""
        from services.mod_service import ModManager

        mod_service = ModManager(app_state=app_state, feedback_service=feedback_service)
        cache = mod_service._get_mods_cache(use_async=False)
        assert len(cache) > 0
        assert "test_mod_001" in cache

    def test_mod_service_validate_config_valid(self, app_state, feedback_service):
        """Checks that moding service validate config valid."""
        from utils.mod_scan_utils import validate_mod_config

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

    def test_mod_service_validate_config_invalid_dict(
        self, app_state, feedback_service
    ):
        """Checks that moding service validate config invalid dict."""
        from utils.mod_scan_utils import validate_mod_config

        invalid_config = ["id", "name"]
        result = validate_mod_config(invalid_config, "/fake/path", "test_mod")
        assert result is False

    def test_mod_service_validate_config_missing_fields(
        self, app_state, feedback_service
    ):
        """Checks that moding service validate config missing fields."""
        from utils.mod_scan_utils import validate_mod_config

        invalid_config = {"version": "1.0.0"}
        result = validate_mod_config(invalid_config, "/fake/path", "test_mod")
        assert result is False

    def test_mod_service_validate_config_invalid_types(
        self, app_state, feedback_service
    ):
        """Checks that moding service validate config invalid types."""
        from utils.mod_scan_utils import validate_mod_config

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
        """Checks that settingsing service initialization."""
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
        """Checks that settingsing service load settings."""
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
        """Checks that settingsing service can restore normal geometry without applying maximized state."""
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


class TestLocalizationManager:
    """Tests for managers."""
    def test_localization_service_tr(self):
        """Checks that localizationing service tr."""
        from services.localization_service import tr

        result = tr("test.id")
        assert isinstance(result, str)

    def test_localization_service_detect_language(self):
        """Checks that localizationing service detect language."""
        from services.localization_service import localization_service

        language = localization_service.detect_system_language()
        assert language is not None
        assert isinstance(language, str)


class TestLaunchManager:
    """Tests for managers."""
    def test_launch_service_initialization(self, app_state, feedback_service):
        """Checks that launching service initialization."""
        from services.launch_service import GameLauncher
        from services.mod_service import ModManager

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
        """Checks that executeing game uses detached steam launch on linux."""
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
            patch("services.launch_service.webbrowser.open") as web_open,
        ):
            launcher._execute_game(
                {"target": "steam://rungameid/1690940", "cwd": None, "type": "webbrowser"}
            )

        start_detached.assert_called_once_with(
            "steam", ["steam://rungameid/1690940"]
        )
        web_open.assert_not_called()

    def test_execute_game_falls_back_to_xdg_open_when_steam_detach_fails_on_linux(
        self, app_state, feedback_service
    ):
        """Checks that executeing game falls back to xdg open when steam detach fails on linux."""
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
                {"target": "steam://rungameid/1690940", "cwd": None, "type": "webbrowser"}
            )

        assert start_detached.call_args_list == [
            (("steam", ["steam://rungameid/1690940"]),),
            (("xdg-open", ["steam://rungameid/1690940"]),),
        ]


class TestUpdateCheckManager:
    """Tests for managers."""
    @patch("requests.get")
    def test_update_checker_initialization(self, mock_get, app_state, feedback_service):
        """Checks that updating checker initialization."""
        from services.updatecheck_service import UpdateChecker

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"version": "1.0.0"}
        mock_get.return_value = mock_response
        checker = UpdateChecker(app_state=app_state, feedback_service=feedback_service)
        assert checker is not None


class TestCustomizationManager:
    """Tests for managers."""
    def test_customization_service_initialization(self, app_state):
        """Checks that customizationing service initialization."""
        from services.customization_service import CustomizationManager

        manager = CustomizationManager(app_state)
        assert manager is not None
        assert manager.app_state == app_state

    def test_customization_service_get_font_path(self, app_state, temp_dir):
        """Checks that customizationing service get font path."""
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
        """Checks that customizationing service get font button text."""
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
        """Checks that backuping restoration order."""
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
        """Checks that backuping restoration validation."""
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
        """Checks that sounding file backup restoration."""
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
        """Checks that customizationing service audio formats."""
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
        """Checks that customizationing service webp logo."""
        from services.customization_service import CustomizationManager

        manager = CustomizationManager(app_state)
        app_state.config_dir = temp_dir

        path = os.path.join(temp_dir, "custom_logo.webp")
        with open(path, "w") as f:
            f.write("dummy")
        assert manager.get_custom_logo_path() == path

    def test_settings_manager_audio_paths(self, app_state, feedback_service, qapp):
        """Checks that settingsing manager audio paths."""
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
        """Checks that settingsing manager applies disable startup sound default."""
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
        """Checks that backgrounding selection copies file to config dir."""
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
            "services.settings_service.QFileDialog.getOpenFileName",
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
        """Checks that backgrounding removal keeps external legacy file."""
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
