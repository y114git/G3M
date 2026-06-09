"""Unit tests for test close."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.window.close import (
    begin_close_event,
    force_finish_close_tasks,
    mark_close_task_complete,
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
