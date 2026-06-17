"""Unit tests for main window composition signal safety."""

from unittest.mock import Mock


class _Signal:
    def __init__(self) -> None:
        self._callbacks = []

    def connect(self, callback) -> None:
        self._callbacks.append(callback)

    def emit(self, *args) -> None:
        for callback in self._callbacks:
            callback(*args)


def test_window_composition_feedback_callbacks_ignore_broken_feedback(monkeypatch):
    """Checks composition feedback signal handlers cannot crash when UI is gone."""
    from presentation import window_composition as composition_module
    from presentation.window_composition import WindowComposition

    monkeypatch.setattr(composition_module, "DebounceTimer", Mock())
    for name in (
        "GameLaunchController",
        "LibraryDisplayController",
        "ModOperationsController",
        "PluginsController",
        "RefreshController",
        "SearchDisplayController",
        "SettingsUiController",
        "ThemeController",
    ):
        monkeypatch.setattr(composition_module, name, Mock())

    window = Mock()
    window.plugin_runtime_service = None
    window.feedback_service.show_message.side_effect = RuntimeError("toast deleted")
    window.feedback_service.status_updated = _Signal()
    window.settings_service.language_changed = _Signal()
    window.settings_service.restart_required = _Signal()
    window.settings_service.status_changed = _Signal()
    window.settings_service.theme_changed = _Signal()
    window.mod_service.progress_updated = _Signal()
    window.mod_service.status_changed = _Signal()
    window.mod_service.url_prompt_required = _Signal()
    window.game_launcher.status_changed = _Signal()
    window.game_launcher.progress_updated = _Signal()
    window.game_launcher.game_launch_started = _Signal()
    window.game_launcher.game_launch_finished = _Signal()
    window.update_checker.update_available = _Signal()
    window.update_checker.status_changed = _Signal()
    window.update_checker.progress_updated = _Signal()
    window.update_checker.update_finished = _Signal()
    window.update_checker.update_error = _Signal()
    window.update_checker.quit_requested = _Signal()
    window.used_mods_service.used_mods_updated = _Signal()
    window.session_manager.online_count_changed = _Signal()
    window.update_status_signal.emit = Mock()
    window.set_progress_signal.emit = Mock()
    window.hide_window_signal.emit = Mock()
    window.restore_window_signal.emit = Mock()

    WindowComposition(window).compose()

    window.settings_service.restart_required.emit("restart needed")
    window.update_checker.update_error.emit("update failed")

    assert window.feedback_service.show_message.call_count == 2
