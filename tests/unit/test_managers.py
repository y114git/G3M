import json
import os
from unittest.mock import Mock, patch


class TestModManager:
    def test_mod_service_initialization(self, app_state, feedback_service):
        from services.mod_service import ModManager

        mod_service = ModManager(app_state=app_state, feedback_service=feedback_service)
        assert mod_service is not None
        assert mod_service.app_state == app_state
        assert mod_service.feedback_service == feedback_service

    def test_mod_service_cache_invalidation(self, app_state, feedback_service):
        from services.mod_service import ModManager

        mod_service = ModManager(app_state=app_state, feedback_service=feedback_service)
        mod_service.invalidate_mods_cache()
        assert not mod_service._mods_cache_valid

    def test_mod_service_scan_empty_directory(self, app_state, feedback_service):
        from services.mod_service import ModManager

        mod_service = ModManager(app_state=app_state, feedback_service=feedback_service)
        cache = mod_service._get_mods_cache(use_async=False)
        assert isinstance(cache, dict)
        assert len(cache) == 0

    def test_mod_service_scan_with_mod(
        self, app_state, feedback_service, sample_mod_folder
    ):
        from services.mod_service import ModManager

        mod_service = ModManager(app_state=app_state, feedback_service=feedback_service)
        cache = mod_service._get_mods_cache(use_async=False)
        assert len(cache) > 0
        assert "test_mod_001" in cache

    def test_mod_service_validate_config_valid(self, app_state, feedback_service):
        from utils.mod_scan_utils import validate_mod_config

        valid_config = {
            "key": "test_mod",
            "name": "Test Mod",
            "version": "1.0.0",
            "files": {},
            "tags": [],
        }
        result = validate_mod_config(valid_config, "/fake/path", "test_mod")
        assert result is True

    def test_mod_service_validate_config_invalid_dict(
        self, app_state, feedback_service
    ):
        from utils.mod_scan_utils import validate_mod_config

        invalid_config = ["key", "name"]
        result = validate_mod_config(invalid_config, "/fake/path", "test_mod")
        assert result is False

    def test_mod_service_validate_config_missing_fields(
        self, app_state, feedback_service
    ):
        from utils.mod_scan_utils import validate_mod_config

        invalid_config = {"version": "1.0.0"}
        result = validate_mod_config(invalid_config, "/fake/path", "test_mod")
        assert result is False

    def test_mod_service_validate_config_invalid_types(
        self, app_state, feedback_service
    ):
        from utils.mod_scan_utils import validate_mod_config

        invalid_config = {"key": "test", "name": 123}
        result = validate_mod_config(invalid_config, "/fake/path", "test_mod")
        assert result is False

        invalid_config2 = {"key": "test", "name": "Test", "files": []}
        result2 = validate_mod_config(invalid_config2, "/fake/path", "test_mod")
        assert result2 is False

        invalid_config3 = {"key": "test", "name": "Test", "tags": {}}
        result3 = validate_mod_config(invalid_config3, "/fake/path", "test_mod")
        assert result3 is False


class TestSettingsManager:
    def test_settings_service_initialization(self, app_state, feedback_service, qapp):
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


class TestPluginManager:
    def test_plugin_service_initialization(self, app_state, feedback_service, qapp):
        from services.localization_service import localization_service
        from services.plugin_service import PluginManager
        from services.settings_service import SettingsManager

        settings_service = SettingsManager(
            app_state=app_state,
            feedback_service=feedback_service,
            localization_service=localization_service,
            parent=qapp,
        )
        plugin_service = PluginManager(
            app_state=app_state, settings_service=settings_service
        )
        assert plugin_service is not None
        assert plugin_service.app_state == app_state


class TestLocalizationManager:
    def test_localization_service_tr(self):
        from services.localization_service import tr

        result = tr("test.key")
        assert isinstance(result, str)

    def test_localization_service_detect_language(self):
        from services.localization_service import localization_service

        language = localization_service.detect_system_language()
        assert language is not None
        assert isinstance(language, str)


class TestLaunchManager:
    def test_launch_service_initialization(self, app_state, feedback_service):
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
        from services.launch_service import GameLauncher
        from services.localization_service import tr

        app_state.local_config = {"custom_color_border": "#123456"}
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
        from services.launch_service import GameLauncher
        from services.localization_service import tr

        app_state.local_config = {"custom_color_border": "#654321"}
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

    def test_handle_launch_failure_skips_restore_when_window_was_not_hidden(
        self, app_state, feedback_service
    ):
        from services.launch_service import GameLauncher

        parent = Mock()
        launcher = GameLauncher(
            app_state=app_state,
            feedback_service=feedback_service,
            mod_service=Mock(),
        )
        launcher.restore_window_callback = Mock()
        app_state.game_is_running = False

        with patch.object(launcher, "parent", return_value=parent):
            launcher._handle_launch_failure()

        launcher.restore_window_callback.assert_not_called()
        parent.game_launch.update_button_state.assert_called_once()


class TestUpdateCheckManager:
    @patch("requests.get")
    def test_update_checker_initialization(self, mock_get, app_state, feedback_service):
        from services.updatecheck_service import UpdateChecker

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"version": "1.0.0"}
        mock_get.return_value = mock_response
        checker = UpdateChecker(app_state=app_state, feedback_service=feedback_service)
        assert checker is not None


class TestCustomizationManager:
    def test_customization_service_initialization(self, app_state):
        from services.customization_service import CustomizationManager

        manager = CustomizationManager(app_state)
        assert manager is not None
        assert manager.app_state == app_state

    def test_customization_service_get_font_path(self, app_state, temp_dir):
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
    def test_backup_restoration_order(self, temp_dir):
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
    def test_customization_service_audio_formats(self, app_state, temp_dir):
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
        from services.customization_service import CustomizationManager

        manager = CustomizationManager(app_state)
        app_state.config_dir = temp_dir

        path = os.path.join(temp_dir, "custom_logo.webp")
        with open(path, "w") as f:
            f.write("dummy")
        assert manager.get_custom_logo_path() == path

    def test_settings_manager_audio_paths(self, app_state, feedback_service, qapp):
        from services.localization_service import localization_service
        from services.settings_service import SettingsManager

        manager = SettingsManager(
            app_state, feedback_service, localization_service, parent=qapp
        )

        paths = manager._get_audio_paths("background_music")
        assert any(p.endswith(".ogg") for p in paths)
        assert any(p.endswith(".flac") for p in paths)
