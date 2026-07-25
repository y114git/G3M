"""Unit tests for test session manager."""

from unittest.mock import Mock, patch


def test_presence_worker_uses_dedicated_session_with_bounded_timeout():
    from config.config import BROWSER_HEADERS
    from workers.presence_worker import PresenceWorker

    app_state = Mock()
    app_state.has_internet = True
    response = Mock()
    response.status_code = 200
    response.json.return_value = {"online": 7}
    session = Mock()

    worker = PresenceWorker("session-1", app_state)

    with (
        patch("workers.presence_worker.requests.Session", return_value=session),
        patch(
            "workers.presence_worker.cloud_function_request", return_value=response
        ) as request_call,
    ):
        worker.run()

    request_call.assert_called_once()
    assert request_call.call_args.kwargs["session"] is session
    assert (
        request_call.call_args.kwargs["timeout"]
        == PresenceWorker.REQUEST_TIMEOUT_SECONDS
    )
    session.headers.update.assert_called_once_with(BROWSER_HEADERS or {})
    session.close.assert_called_once_with()


def test_session_manager_stop_uses_presence_timeout_budget(app_state):
    from session.session_manager import SessionManager

    manager = SessionManager(app_state)
    manager.worker.REQUEST_TIMEOUT_SECONDS = 2

    with patch("session.session_manager.safe_stop_thread") as stop_thread:
        manager.stop()

    stop_thread.assert_called_once_with(manager._thread, timeout=2500, blocking=True)


def test_session_manager_stop_enforces_minimum_timeout(app_state):
    from session.session_manager import SessionManager

    manager = SessionManager(app_state)
    manager.worker.REQUEST_TIMEOUT_SECONDS = 1

    with patch("session.session_manager.safe_stop_thread") as stop_thread:
        manager.stop()

    stop_thread.assert_called_once_with(manager._thread, timeout=2000, blocking=True)


def test_session_manager_retries_until_first_online_count(app_state):
    from session.session_manager import SessionManager

    manager = SessionManager(app_state)
    with (
        patch.object(manager._thread, "isRunning", return_value=True),
        patch.object(manager._startup_retry_timer, "start") as start_retry,
        patch.object(manager._startup_retry_timer, "stop") as stop_retry,
    ):
        manager._handle_online_count(-1)
        start_retry.assert_called_once_with()

        manager._handle_online_count(7)
        stop_retry.assert_called_once_with()
