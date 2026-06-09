"""Unit tests for test network optimizations."""

from unittest.mock import Mock, patch

import requests

from presentation.update_presenter import reload_global_settings
from services.chat_service import ChatManager


def test_chat_manager_caches_messages_per_channel():
    """Checks that chat manager caches messages per channel."""
    manager = ChatManager()
    manager.base_url = "https://example.test"
    response = Mock()
    response.status_code = 200
    response.json.return_value = {"ok": True, "messages": [{"id": 1}]}
    session = Mock()
    session.get.return_value = response

    with patch("services.chat_service.get_session", return_value=session), patch(
        "services.chat_service.check_internet_connection", return_value=True
    ):
        first = manager.get_messages("en")
        second = manager.get_messages("en")

    assert first == [{"id": 1}]
    assert second == [{"id": 1}]
    assert session.get.call_count == 1


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


def test_chat_get_messages_returns_empty_when_no_internet():
    """Simulates macOS: gstatic blocked → check_internet_connection returns False → get_messages returns []."""
    manager = ChatManager()
    manager.base_url = "https://example.test"
    session = Mock()

    with patch("services.chat_service.check_internet_connection", return_value=False), patch(
        "services.chat_service.get_session", return_value=session
    ):
        result = manager.get_messages("en", force_refresh=True)

    assert result == []
    session.get.assert_not_called()


def test_chat_send_message_returns_false_when_no_internet():
    """Simulates macOS: gstatic blocked → check_internet_connection returns False → send_message fails."""
    manager = ChatManager()
    manager.base_url = "https://example.test"
    session = Mock()

    with patch("services.chat_service.check_internet_connection", return_value=False), patch(
        "services.chat_service.get_session", return_value=session
    ):
        success, _ = manager.send_message("en", "hello")

    assert success is False
    session.post.assert_not_called()


def test_chat_get_messages_returns_empty_when_ssl_error():
    """Simulates macOS PyInstaller: HTTPS request raises SSLError (certifi missing) → get_messages returns []."""
    manager = ChatManager()
    manager.base_url = "https://example.test"
    session = Mock()
    session.get.side_effect = requests.exceptions.SSLError("certificate verify failed")

    with patch("services.chat_service.check_internet_connection", return_value=True), patch(
        "services.chat_service.get_session", return_value=session
    ):
        result = manager.get_messages("en", force_refresh=True)

    assert result == []


def test_chat_send_message_returns_false_when_ssl_error():
    """Simulates macOS PyInstaller: HTTPS POST raises SSLError → send_message returns (False, 'send_error')."""
    manager = ChatManager()
    manager.base_url = "https://example.test"
    session = Mock()
    session.post.side_effect = requests.exceptions.SSLError("certificate verify failed")

    with patch("services.chat_service.check_internet_connection", return_value=True), patch(
        "services.chat_service.get_session", return_value=session
    ):
        success, _ = manager.send_message("en", "hello")

    assert success is False
