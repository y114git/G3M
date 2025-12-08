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
