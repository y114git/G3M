import os
import json
from unittest.mock import Mock, patch


class TestModManager:

    def test_mod_manager_initialization(self, app_state, feedback_manager):
        from managers.mod_manager import ModManager
        mod_manager = ModManager(app_state=app_state, feedback_manager=feedback_manager)
        assert mod_manager is not None
        assert mod_manager.app_state == app_state
        assert mod_manager.feedback_manager == feedback_manager

    def test_mod_manager_cache_invalidation(self, app_state, feedback_manager):
        from managers.mod_manager import ModManager
        mod_manager = ModManager(app_state=app_state, feedback_manager=feedback_manager)
        mod_manager.invalidate_mods_cache()
        assert not mod_manager._mods_cache_valid

    def test_mod_manager_scan_empty_directory(self, app_state, feedback_manager):
        from managers.mod_manager import ModManager
        mod_manager = ModManager(app_state=app_state, feedback_manager=feedback_manager)
        cache = mod_manager._get_mods_cache(use_async=False)
        assert isinstance(cache, dict)
        assert len(cache) == 0

    def test_mod_manager_scan_with_mod(self, app_state, feedback_manager, sample_mod_folder):
        from managers.mod_manager import ModManager
        mod_manager = ModManager(app_state=app_state, feedback_manager=feedback_manager)
        cache = mod_manager._get_mods_cache(use_async=False)
        assert len(cache) > 0
        assert 'test_mod_001' in cache

    def test_mod_manager_validate_config_valid(self, app_state, feedback_manager):
        from managers.mod_manager import ModManager
        mod_manager = ModManager(app_state=app_state, feedback_manager=feedback_manager)
        valid_config = {
            'key': 'test_mod',
            'name': 'Test Mod',
            'version': '1.0.0',
            'files': {},
            'tags': []
        }
        result = mod_manager._validate_mod_config(valid_config, '/fake/path', 'test_mod')
        assert result is True

    def test_mod_manager_validate_config_invalid_dict(self, app_state, feedback_manager):
        from managers.mod_manager import ModManager
        mod_manager = ModManager(app_state=app_state, feedback_manager=feedback_manager)
        invalid_config = ['key', 'name']
        result = mod_manager._validate_mod_config(invalid_config, '/fake/path', 'test_mod')
        assert result is False

    def test_mod_manager_validate_config_missing_fields(self, app_state, feedback_manager):
        from managers.mod_manager import ModManager
        mod_manager = ModManager(app_state=app_state, feedback_manager=feedback_manager)
        invalid_config = {'version': '1.0.0'}
        result = mod_manager._validate_mod_config(invalid_config, '/fake/path', 'test_mod')
        assert result is False

    def test_mod_manager_validate_config_invalid_types(self, app_state, feedback_manager):
        from managers.mod_manager import ModManager
        mod_manager = ModManager(app_state=app_state, feedback_manager=feedback_manager)
        invalid_config = {'key': 'test', 'name': 123}
        result = mod_manager._validate_mod_config(invalid_config, '/fake/path', 'test_mod')
        assert result is False

        invalid_config2 = {'key': 'test', 'name': 'Test', 'files': []}
        result2 = mod_manager._validate_mod_config(invalid_config2, '/fake/path', 'test_mod')
        assert result2 is False

        invalid_config3 = {'key': 'test', 'name': 'Test', 'tags': {}}
        result3 = mod_manager._validate_mod_config(invalid_config3, '/fake/path', 'test_mod')
        assert result3 is False


class TestSettingsManager:

    def test_settings_manager_initialization(self, app_state, feedback_manager, qapp):
        from managers.settings_manager import SettingsManager
        from managers.localization_manager import localization_manager
        settings_manager = SettingsManager(app_state=app_state, feedback_manager=feedback_manager, localization_manager=localization_manager, parent=qapp)
        assert settings_manager is not None
        assert settings_manager.app_state == app_state

    def test_settings_manager_load_settings(self, app_state, feedback_manager, temp_config_dir, qapp):
        from managers.settings_manager import SettingsManager
        from managers.localization_manager import localization_manager
        settings_path = os.path.join(temp_config_dir, 'settings.json')
        settings_data = {'test_setting': 'test_value', 'another_setting': 123}
        with open(settings_path, 'w', encoding='utf-8') as f:
            json.dump(settings_data, f)
        app_state.config_path = settings_path
        settings_manager = SettingsManager(app_state=app_state, feedback_manager=feedback_manager, localization_manager=localization_manager, parent=qapp)
        loaded_data = settings_manager.read_json(settings_path)
        app_state.local_config.update(loaded_data)
        assert app_state.local_config.get('test_setting') == 'test_value'


class TestPluginManager:

    def test_plugin_manager_initialization(self, app_state, feedback_manager, qapp):
        from managers.plugin_manager import PluginManager
        from managers.settings_manager import SettingsManager
        from managers.localization_manager import localization_manager
        settings_manager = SettingsManager(app_state=app_state, feedback_manager=feedback_manager, localization_manager=localization_manager, parent=qapp)
        plugin_manager = PluginManager(app_state=app_state, settings_manager=settings_manager)
        assert plugin_manager is not None
        assert plugin_manager.app_state == app_state


class TestLocalizationManager:

    def test_localization_manager_tr(self):
        from managers.localization_manager import tr
        result = tr('test.key')
        assert isinstance(result, str)

    def test_localization_manager_detect_language(self):
        from managers.localization_manager import localization_manager
        language = localization_manager.detect_system_language()
        assert language is not None
        assert isinstance(language, str)


class TestLaunchManager:

    def test_launch_manager_initialization(self, app_state, feedback_manager):
        from managers.launch_manager import GameLauncher
        from managers.mod_manager import ModManager
        mod_manager = ModManager(app_state, feedback_manager)
        launcher = GameLauncher(app_state=app_state, feedback_manager=feedback_manager, mod_manager=mod_manager)
        assert launcher is not None
        assert launcher.app_state == app_state


class TestUpdateCheckManager:

    @patch('requests.get')
    def test_update_checker_initialization(self, mock_get, app_state, feedback_manager):
        from managers.updatecheck_manager import UpdateChecker
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'version': '1.0.0'}
        mock_get.return_value = mock_response
        checker = UpdateChecker(app_state=app_state, feedback_manager=feedback_manager)
        assert checker is not None


class TestCustomizationManager:

    def test_customization_manager_initialization(self, app_state):
        from managers.customization_manager import CustomizationManager
        manager = CustomizationManager(app_state)
        assert manager is not None
        assert manager.app_state == app_state


class TestBackupManager:

    def test_backup_restoration_order(self, temp_dir):
        from managers.backup_manager import BackupManager
        from utils.patching_logger import get_patching_logger
        backup_dir = os.path.join(temp_dir, 'backups')
        backup_manager = BackupManager(backup_dir, patching_logger=get_patching_logger())
        chapter_id = 1
        # Create test files
        test_dir = os.path.join(temp_dir, 'test_game')
        os.makedirs(test_dir, exist_ok=True)
        file1 = os.path.join(test_dir, 'file1.txt')
        file2 = os.path.join(test_dir, 'file2.txt')
        file3 = os.path.join(test_dir, 'file3.txt')
        for f in [file1, file2, file3]:
            with open(f, 'w') as fh:
                fh.write('original')
        # Backup files in order
        backup_manager.backup_file(chapter_id, file1)
        backup_manager.backup_file(chapter_id, file2)
        backup_manager.backup_file(chapter_id, file3)
        # Modify files
        for f in [file1, file2, file3]:
            with open(f, 'w') as fh:
                fh.write('modified')
        # Restore - should restore in reverse order
        backup_manager.restore_backups(chapter_id)
        # Verify files are restored
        for f in [file1, file2, file3]:
            with open(f, 'r') as fh:
                content = fh.read()
                assert content == 'original', f'File {f} was not restored correctly'

    def test_backup_restoration_validation(self, temp_dir):
        from managers.backup_manager import BackupManager
        from utils.patching_logger import get_patching_logger
        backup_dir = os.path.join(temp_dir, 'backups')
        backup_manager = BackupManager(backup_dir, patching_logger=get_patching_logger())
        chapter_id = 1
        # Create test file
        test_dir = os.path.join(temp_dir, 'test_game')
        os.makedirs(test_dir, exist_ok=True)
        test_file = os.path.join(test_dir, 'test.txt')
        original_content = 'original content'
        with open(test_file, 'w') as f:
            f.write(original_content)
        # Backup file
        backup_manager.backup_file(chapter_id, test_file)
        # Modify file
        with open(test_file, 'w') as f:
            f.write('modified content')
        # Restore
        backup_manager.restore_backups(chapter_id)
        # Verify file integrity (size and content)
        assert os.path.exists(test_file)
        with open(test_file, 'r') as f:
            restored_content = f.read()
            assert restored_content == original_content
        backup_size = os.path.getsize(os.path.join(backup_dir, 'chapter_1_test.txt'))
        restored_size = os.path.getsize(test_file)
        assert backup_size == restored_size

    def test_sound_file_backup_restoration(self, temp_dir):
        from managers.backup_manager import BackupManager
        from utils.patching_logger import get_patching_logger
        backup_dir = os.path.join(temp_dir, 'backups')
        backup_manager = BackupManager(backup_dir, patching_logger=get_patching_logger())
        chapter_id = 1
        # Create test sound directory structure
        sound_dir = os.path.join(temp_dir, 'test_game', 'sound', 'Desktop')
        os.makedirs(sound_dir, exist_ok=True)
        bank_file = os.path.join(sound_dir, 'test.bank')
        original_content = b'BANK_FILE_CONTENT'
        with open(bank_file, 'wb') as f:
            f.write(original_content)
        # Backup sound file
        backup_manager.backup_file(chapter_id, bank_file)
        # Modify sound file
        modified_content = b'MODIFIED_BANK_CONTENT'
        with open(bank_file, 'wb') as f:
            f.write(modified_content)
        # Restore
        backup_manager.restore_backups(chapter_id)
        # Verify sound file is restored
        assert os.path.exists(bank_file)
        with open(bank_file, 'rb') as f:
            restored_content = f.read()
            assert restored_content == original_content