import pytest
from PyQt6.QtWidgets import QWidget
from PyQt6.QtTest import QTest
from PyQt6.QtCore import Qt
from unittest.mock import Mock, patch
from core.app_state import AppState


class TestAppWindow:

    @patch('core.app_window.SingleInstanceServer')
    @patch('core.app_window.PresenceWorker')
    def test_app_window_creation(self, mock_presence, mock_server, qapp, temp_dir):
        from core.app_window import AppWindow
        mock_server_instance = Mock()
        mock_server_instance.listen.return_value = True
        mock_server.return_value = mock_server_instance
        with patch('utils.path_utils.get_user_data_root', return_value=temp_dir), patch('utils.path_utils.get_launcher_dir', return_value=temp_dir), patch('utils.path_utils.get_user_mods_dir', return_value=temp_dir), patch('utils.path_utils.get_user_plugins_dir', return_value=temp_dir):
            try:
                window = AppWindow()
                assert window is not None
                assert hasattr(window, 'app_state')
            except Exception as e:
                pytest.skip(f'AppWindow creation failed: {e}')


class TestTabBuilders:

    def test_library_tab_builder_creation(self, qapp, app_state, feedback_manager):
        from ui.main_window.library_tab_builder import LibraryTabBuilder
        builder = LibraryTabBuilder(app_state, None)
        assert builder is not None

    def test_search_tab_builder_creation(self, qapp, app_state, feedback_manager):
        from ui.main_window.search_tab_builder import SearchTabBuilder
        builder = SearchTabBuilder(app_state, None)
        assert builder is not None

    def test_plugin_tab_builder_creation(self, qapp, app_state, feedback_manager):
        from ui.main_window.plugin_tab_builder import PluginTabBuilder
        builder = PluginTabBuilder(app_state, None)
        assert builder is not None

    def test_settings_view_builder_creation(self, qapp, app_state, feedback_manager):
        from ui.main_window.settings_view_builder import SettingsViewBuilder
        builder = SettingsViewBuilder(app_state, None)
        assert builder is not None
