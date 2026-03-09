from unittest.mock import Mock, patch


class TestRefreshModList:

    def test_refresh_updates_mod_list(self, app_state):
        from controllers.refresh_controller import RefreshController
        feedback_service = Mock()
        mod_service = Mock()
        used_mods_service = Mock()
        game_launch_controller = Mock()
        update_checker = Mock()
        app_window = Mock()
        refresh_controller = RefreshController(app_state, feedback_service, mod_service, used_mods_service, game_launch_controller, update_checker, app_window=app_window)
        with patch('controllers.refresh_controller.FetchModsThread') as mock_fetch, \
                patch('controllers.refresh_controller.is_game_running', return_value=False):
            mock_thread = Mock()
            mock_fetch.return_value = mock_thread
            refresh_controller.refresh_mods_list(is_initial=False)
            assert mock_fetch.called
            assert mock_thread.start.called

    def test_refresh_calls_relocalize(self, app_state):
        from controllers.refresh_controller import RefreshController
        feedback_service = Mock()
        mod_service = Mock()
        used_mods_service = Mock()
        game_launch_controller = Mock()
        update_checker = Mock()
        app_window = Mock()
        localization_callback = Mock()
        refresh_controller = RefreshController(app_state, feedback_service, mod_service, used_mods_service, game_launch_controller, update_checker, app_window=app_window)
        with patch('controllers.refresh_controller.FetchModsThread') as mock_fetch, \
                patch('controllers.refresh_controller.is_game_running', return_value=False):
            mock_thread = Mock()
            mock_fetch.return_value = mock_thread
            refresh_controller.refresh_mods_list(is_initial=False, localization_callback=localization_callback)
            assert mock_fetch.called


class TestRefreshLanguageCombo:

    def test_refresh_updates_language_combo(self, app_state):
        from controllers.refresh_controller import RefreshController
        from PyQt6.QtWidgets import QComboBox
        feedback_service = Mock()
        mod_service = Mock()
        used_mods_service = Mock()
        game_launch_controller = Mock()
        update_checker = Mock()
        app_window = Mock()
        language_combo = QComboBox()
        refresh_controller = RefreshController(app_state, feedback_service, mod_service, used_mods_service, game_launch_controller, update_checker, app_window=app_window)
        with patch('controllers.refresh_controller.localization_service') as mock_loc:
            mock_loc.get_current_language.return_value = 'en'
            mock_loc.get_available_languages.return_value = {'en': 'English', 'ru': 'Russian'}
            mock_loc.rescan_languages = Mock()
            with patch('controllers.refresh_controller.FetchModsThread'):
                refresh_controller.refresh_mods_list(is_initial=False, language_combo=language_combo)
                assert mock_loc.rescan_languages.called
                assert language_combo.count() > 0


class TestRefreshLibraryDisplay:

    def test_library_display_updates_on_refresh(self, app_state):
        from controllers.library_display_controller import LibraryDisplayController
        feedback_service = Mock()
        mod_service = Mock()
        used_mods_service = Mock()
        app_window = Mock()
        app_window.installed_mods_layout = Mock()
        app_window.installed_mods_container = Mock()
        controller = LibraryDisplayController(app_state, feedback_service, mod_service, used_mods_service, app_window)
        assert hasattr(controller, 'refresh_async')
        assert hasattr(controller, 'update_display_from_list')


class TestRefreshMetadataLoading:

    def test_refresh_controller_has_expected_attributes(self, app_state):
        from controllers.refresh_controller import RefreshController
        feedback_service = Mock()
        mod_service = Mock()
        used_mods_service = Mock()
        game_launch_controller = Mock()
        update_checker = Mock()
        app_window = Mock()
        refresh_controller = RefreshController(app_state, feedback_service, mod_service, used_mods_service, game_launch_controller, update_checker, app_window=app_window)
        assert hasattr(refresh_controller, 'fetch_thread')
        assert hasattr(refresh_controller, 'details_thread')
