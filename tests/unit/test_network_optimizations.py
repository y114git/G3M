"""Unit tests for network-sensitive refresh behavior."""

from unittest.mock import Mock, patch

from PyQt6.QtCore import QObject

from presentation.update_presenter import reload_global_settings


def test_reload_global_settings_skips_refresh_when_cached():
    """Checks that reloading global settings skips refresh when cached."""
    app = Mock()
    app.app_state = Mock()
    app.app_state.has_internet = True
    app.app_state.global_settings = {"announce": {}}
    app.app_state.global_settings_loaded_at = 900
    app.app_state.global_settings_load_in_progress = False
    app.app_state.initialization_completed = True
    app.app_state.is_shown_to_user = True
    app.isVisible.return_value = True
    callback = Mock()

    with patch("presentation.update_presenter.time.time", return_value=1000.0):
        reload_global_settings(app, callback=callback)

    callback.assert_called_once_with(True)
    assert app.app_state.global_settings_load_in_progress is False


def test_reload_global_settings_force_refresh_ignores_cache():
    """Checks that reloading global settings force refresh ignores cache."""
    app = Mock()
    app.app_state = Mock()
    app.app_state.has_internet = True
    app.app_state.global_settings = {"announce": {}}
    app.app_state.global_settings_loaded_at = 1000.0
    app.app_state.global_settings_load_in_progress = False
    callback = Mock()

    response = Mock()
    response.status_code = 200
    response.json.return_value = {"announce": {"version": 2}}
    session = Mock()
    session.get.return_value = response

    with patch("presentation.update_presenter.get_session", return_value=session), patch(
        "presentation.update_presenter.time.time", side_effect=[2000.0, 2000.0]
    ):
        reload_global_settings(app, callback=callback, force_refresh=True)

    callback.assert_called_once_with(True)
    assert app.app_state.global_settings["announce"]["version"] == 2
    assert session.get.called


def test_reload_global_settings_suppresses_callback_failure_when_cached():
    """Checks that a refresh callback error is logged instead of crashing the caller."""
    app = Mock()
    app.app_state = Mock()
    app.app_state.has_internet = True
    app.app_state.global_settings = {"announce": {}}
    app.app_state.global_settings_loaded_at = 900
    app.app_state.global_settings_load_in_progress = False
    callback = Mock(side_effect=RuntimeError("callback failed"))

    with patch("presentation.update_presenter.time.time", return_value=1000.0):
        reload_global_settings(app, callback=callback)

    callback.assert_called_once_with(True)
    assert app.app_state.global_settings_load_in_progress is False


def test_reload_global_settings_suppresses_callback_failure_from_worker(qapp, monkeypatch):
    """Checks that the Qt worker completion callback cannot crash global settings refresh."""
    from presentation import update_presenter

    app = QObject()
    app.app_state = Mock()
    app.app_state.has_internet = True
    app.app_state.global_settings = {}
    app.app_state.global_settings_load_in_progress = False
    callback = Mock(side_effect=RuntimeError("callback failed"))

    class _Signal:
        def __init__(self) -> None:
            self._callback = None

        def connect(self, callback):
            self._callback = callback

    class _Worker:
        def __init__(self, *_args, **_kwargs) -> None:
            self.finished = _Signal()

        def start(self):
            self.finished._callback(True, {"announce": {"version": 2}})

        def deleteLater(self):  # noqa: N802
            return None

    monkeypatch.setattr(update_presenter, "_GlobalSettingsWorker", _Worker)

    reload_global_settings(app, callback=callback, force_refresh=True)

    callback.assert_called_once_with(True)
    assert app.app_state.global_settings == {"announce": {"version": 2}}
    assert app.app_state.global_settings_load_in_progress is False
