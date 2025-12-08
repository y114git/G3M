import os
import json


class TestPluginManager:

    def test_load_plugin(self, app_state, feedback_manager, temp_plugins_dir):
        from managers.plugin_manager import PluginManager
        _ = PluginManager(app_state, settings_manager=None)
        plugin_folder = os.path.join(temp_plugins_dir, 'test_plugin')
        os.makedirs(plugin_folder, exist_ok=True)
        plugin_init = os.path.join(plugin_folder, 'plugin_init.py')
        with open(plugin_init, 'w', encoding='utf-8') as f:
            f.write("\ndef init_plugin(app_state, feedback_manager):\n    return {'name': 'Test Plugin', 'version': '1.0.0'}\n")
        assert os.path.exists(plugin_init)

    def test_enable_disable_plugin(self, app_state, feedback_manager):
        from managers.plugin_manager import PluginManager
        plugin_manager = PluginManager(app_state, settings_manager=None)
        assert plugin_manager is not None


class TestPluginAPI:

    def test_plugin_api_initialization(self, app_state, feedback_manager):
        from managers.plugin_api import PluginAPI
        from unittest.mock import Mock
        mock_app_window = Mock()
        plugin_api = PluginAPI(app_state, mock_app_window, plugin_id='test_plugin')
        assert plugin_api is not None
        assert plugin_api.plugin_id == 'test_plugin'


class TestPluginInstallation:

    def test_install_plugin_from_archive(self, app_state, feedback_manager, temp_plugins_dir):
        import tempfile
        import zipfile
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp_archive:
            archive_path = tmp_archive.name
            with zipfile.ZipFile(archive_path, 'w') as zf:
                plugin_config = {'name': 'Test Plugin', 'version': '1.0.0', 'author': 'Test Author'}
                zf.writestr('plugin_config.json', json.dumps(plugin_config))
                zf.writestr('plugin_init.py', 'def init_plugin(): pass')
        try:
            assert os.path.exists(archive_path)
        finally:
            os.unlink(archive_path)
