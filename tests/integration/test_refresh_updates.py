"""Integration tests for test refresh updates."""

from unittest.mock import Mock, patch


class TestRefreshModList:
    """Tests for refresh updates."""
    def test_refresh_updates_mod_list(self, app_state):
        """Checks that refreshing updates mod list."""
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
        """Checks that refreshing calls relocalize."""
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

    def test_refresh_does_not_replace_worker_that_is_still_stopping(self, app_state):
        from controllers.refresh_controller import RefreshController

        controller = RefreshController(
            app_state, Mock(), Mock(), Mock(), Mock(), Mock(), app_window=Mock()
        )
        existing = Mock()
        existing.isRunning.return_value = True
        controller.fetch_thread = existing

        with patch("controllers.refresh_controller.FetchModsThread") as factory, patch(
            "controllers.refresh_controller.is_game_running", return_value=False
        ):
            controller.refresh_mods_list()

        assert controller.fetch_thread is existing
        factory.assert_not_called()

    def test_is_refreshing_reports_running_worker(self, app_state):
        from controllers.refresh_controller import RefreshController

        controller = RefreshController(
            app_state, Mock(), Mock(), Mock(), Mock(), Mock(), app_window=Mock()
        )
        worker = Mock()
        worker.isRunning.return_value = True
        controller.fetch_thread = worker

        assert controller.is_refreshing()

    def test_is_refreshing_discards_deleted_worker(self, app_state):
        from controllers.refresh_controller import RefreshController

        controller = RefreshController(
            app_state, Mock(), Mock(), Mock(), Mock(), Mock(), app_window=Mock()
        )
        worker = Mock()
        worker.isRunning.side_effect = RuntimeError("wrapped C/C++ object deleted")
        controller.fetch_thread = worker

        assert not controller.is_refreshing()
        assert controller.fetch_thread is None


class TestRefreshLanguageCombo:
    """Tests for refresh updates."""
    def test_refresh_updates_language_combo(self, app_state, qapp):
        """Checks that refreshing updates language combo."""
        from PyQt6.QtWidgets import QComboBox

        from controllers.refresh_controller import RefreshController
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
    """Tests for refresh updates."""
    def test_library_display_updates_on_refresh(self, app_state):
        """Checks that library display updates on refresh."""
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
    """Tests for refresh updates."""
    def test_refresh_controller_has_expected_attributes(self, app_state):
        """Checks that refreshing controller has expected attributes."""
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

    def test_initial_refresh_keeps_no_game_path_as_last_status(self, app_state, temp_dir):
        """Checks that initial refresh re-emits missing game path after other startup statuses."""
        from controllers.refresh_controller import RefreshController

        feedback_service = Mock()
        mod_service = Mock()
        used_mods_service = Mock()
        game_launch_controller = Mock()
        update_checker = Mock()
        app_window = Mock()
        app_state.local_config = {}
        app_state.all_mods = ["mod"]
        app_state.mods_loaded = False
        app_state.game_mode.get_game_path = Mock(return_value="")

        refresh_controller = RefreshController(
            app_state,
            feedback_service,
            mod_service,
            used_mods_service,
            game_launch_controller,
            update_checker,
            app_window=app_window,
        )

        class _Signal:
            def __init__(self) -> None:
                self._callback = None

            def connect(self, callback):
                self._callback = callback

        class _FakePostFetchWorker:
            def __init__(self, *_args, **_kwargs) -> None:
                self.done = _Signal()

            def start(self):
                self.done._callback(True)

            def isFinished(self):  # noqa: N802
                return True

            def deleteLater(self):  # noqa: N802
                return None

        with patch("controllers.refresh_controller._PostFetchWorker", _FakePostFetchWorker):
            refresh_controller._on_fetch_finished(success=True, is_initial=True)

        status_calls = feedback_service.update_status.call_args_list
        assert status_calls[-1].args[0] == "Game path autodetection failed. Set it in Settings > Game."

    def test_fetch_finished_ignores_broken_status_feedback(self, app_state):
        from controllers.refresh_controller import RefreshController

        feedback_service = Mock()
        feedback_service.update_status.side_effect = RuntimeError("status widget deleted")
        mod_service = Mock()
        used_mods_service = Mock()
        game_launch_controller = Mock()
        update_checker = Mock()
        app_window = Mock()
        app_state.mods_loaded = False
        app_state.all_mods = ["mod"]

        refresh_controller = RefreshController(
            app_state,
            feedback_service,
            mod_service,
            used_mods_service,
            game_launch_controller,
            update_checker,
            app_window=app_window,
        )

        class _Signal:
            def __init__(self) -> None:
                self._callback = None

            def connect(self, callback):
                self._callback = callback

        class _FakePostFetchWorker:
            def __init__(self, *_args, **_kwargs) -> None:
                self.done = _Signal()

            def start(self):
                self.done._callback(True)

            def isFinished(self):  # noqa: N802
                return True

            def deleteLater(self):  # noqa: N802
                return None

        update_installed_mods_callback = Mock()
        update_action_button_callback = Mock()

        with patch("controllers.refresh_controller._PostFetchWorker", _FakePostFetchWorker):
            refresh_controller._on_fetch_finished(
                success=True,
                update_installed_mods_callback=update_installed_mods_callback,
                update_action_button_callback=update_action_button_callback,
            )

        assert app_state.mods_loaded is True
        update_installed_mods_callback.assert_called_once()
        update_action_button_callback.assert_called_once()
        game_launch_controller.refresh_mods_in_use.assert_called_once()
        used_mods_service.load_used_mods_state.assert_called_once()
        assert refresh_controller._fetch_finished_in_progress is False
