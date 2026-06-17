"""Unit tests for test close."""

import logging
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.window.close import (
    begin_close_event,
    force_finish_close_tasks,
    mark_close_task_complete,
    run_deferred_close_cleanup,
)


def test_begin_close_event_hides_window_and_schedules_cleanup():
    scheduled = []
    event = Mock()
    analytics_service = Mock()
    analytics_service.shutdown_async.return_value = False
    window = SimpleNamespace(
        _close_cleanup_started=False,
        hide=Mock(),
        _on_application_state_changed=Mock(),
        analytics_service=analytics_service,
        _mark_close_task_complete=Mock(),
        _force_finish_close_tasks=Mock(),
        _run_deferred_close_cleanup=Mock(),
    )
    app = Mock()

    with patch("app.window.close.QApplication.instance", return_value=app):
        begin_close_event(window, event, single_shot=lambda ms, cb: scheduled.append((ms, cb)))

    event.accept.assert_called_once_with()
    window.hide.assert_called_once_with()
    assert window._pending_close_tasks == {"analytics": False, "cleanup": False}
    analytics_service.shutdown_async.assert_called_once()
    assert len(scheduled) == 2


def test_mark_close_task_complete_quits_only_when_all_done():
    app = Mock()
    window = SimpleNamespace(_pending_close_tasks={"analytics": True, "cleanup": False})

    with patch("app.window.close.QApplication.instance", return_value=app):
        mark_close_task_complete(window, "cleanup")

    assert window._pending_close_tasks == {"analytics": True, "cleanup": True}
    app.quit.assert_called_once_with()


def test_force_finish_close_tasks_marks_remaining_and_quits():
    app = Mock()
    window = SimpleNamespace(_pending_close_tasks={"analytics": False, "cleanup": True})

    with patch("app.window.close.QApplication.instance", return_value=app):
        force_finish_close_tasks(window)

    assert window._pending_close_tasks == {"analytics": True, "cleanup": True}
    app.quit.assert_called_once_with()


def test_begin_close_event_logs_analytics_shutdown_failure(caplog):
    scheduled = []
    event = Mock()
    analytics_service = Mock()
    analytics_service.shutdown_async.side_effect = RuntimeError("analytics down")
    window = SimpleNamespace(
        _close_cleanup_started=False,
        hide=Mock(),
        _on_application_state_changed=Mock(),
        analytics_service=analytics_service,
        _mark_close_task_complete=Mock(),
        _force_finish_close_tasks=Mock(),
        _run_deferred_close_cleanup=Mock(),
    )
    app = Mock()

    with patch("app.window.close.QApplication.instance", return_value=app):
        begin_close_event(window, event, single_shot=lambda ms, cb: scheduled.append((ms, cb)))

    assert "Analytics shutdown failed during close" in caplog.text
    window._mark_close_task_complete.assert_called_once_with("analytics")


def test_run_deferred_close_cleanup_logs_failure_and_marks_complete(caplog):
    window = SimpleNamespace(
        plugins_ui=None,
        _mark_close_task_complete=Mock(),
    )

    with patch("app.cleanup.perform_close_cleanup", side_effect=RuntimeError("cleanup down")):
        run_deferred_close_cleanup(window)

    assert "Deferred close cleanup failed" in caplog.text
    window._mark_close_task_complete.assert_called_once_with("cleanup")


def test_mark_close_task_complete_logs_quit_reason(caplog):
    caplog.set_level(logging.INFO)
    app = Mock()
    window = SimpleNamespace(_pending_close_tasks={"analytics": True, "cleanup": False})

    with patch("app.window.close.QApplication.instance", return_value=app):
        mark_close_task_complete(window, "cleanup")

    assert "All close tasks completed; quitting application" in caplog.text


def test_force_finish_close_tasks_logs_pending_analytics_as_normal_shutdown(caplog):
    caplog.set_level(logging.INFO)
    app = Mock()
    window = SimpleNamespace(_pending_close_tasks={"analytics": False, "cleanup": True})

    with patch("app.window.close.QApplication.instance", return_value=app):
        force_finish_close_tasks(window)

    assert "Completing application quit with pending close tasks: analytics" in caplog.text
    assert not any(record.levelno >= logging.WARNING for record in caplog.records)


def test_force_finish_close_tasks_logs_stalled_cleanup_as_warning(caplog):
    app = Mock()
    window = SimpleNamespace(_pending_close_tasks={"analytics": True, "cleanup": False})

    with patch("app.window.close.QApplication.instance", return_value=app):
        force_finish_close_tasks(window)

    assert "Forcing application quit with unfinished close tasks: cleanup" in caplog.text
