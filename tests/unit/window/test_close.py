"""Unit tests for application close coordination."""

import logging
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.window.close import (
    begin_close_event,
    force_finish_close_tasks,
    mark_close_task_complete,
    run_deferred_close_cleanup,
)


def test_begin_close_event_hides_window_and_schedules_cleanup() -> None:
    scheduled = []
    event = Mock()
    window = SimpleNamespace(
        _close_cleanup_started=False,
        hide=Mock(),
        _on_application_state_changed=Mock(),
        _force_finish_close_tasks=Mock(),
        _run_deferred_close_cleanup=Mock(),
    )

    with patch("app.window.close.QApplication.instance", return_value=Mock()):
        begin_close_event(
            window, event, single_shot=lambda ms, cb: scheduled.append((ms, cb))
        )

    event.accept.assert_called_once_with()
    window.hide.assert_called_once_with()
    assert window._pending_close_tasks == {"cleanup": False}
    assert len(scheduled) == 2


def test_mark_close_task_complete_quits_when_cleanup_finishes() -> None:
    app = Mock()
    window = SimpleNamespace(_pending_close_tasks={"cleanup": False})

    with patch("app.window.close.QApplication.instance", return_value=app):
        mark_close_task_complete(window, "cleanup")

    assert window._pending_close_tasks == {"cleanup": True}
    app.quit.assert_called_once_with()


def test_force_finish_close_tasks_marks_cleanup_and_quits(caplog) -> None:
    caplog.set_level(logging.WARNING)
    app = Mock()
    window = SimpleNamespace(_pending_close_tasks={"cleanup": False})

    with patch("app.window.close.QApplication.instance", return_value=app):
        force_finish_close_tasks(window)

    assert window._pending_close_tasks == {"cleanup": True}
    assert (
        "Forcing application quit with unfinished close tasks: cleanup" in caplog.text
    )
    app.quit.assert_called_once_with()


def test_run_deferred_close_cleanup_logs_failure_and_marks_complete(caplog) -> None:
    window = SimpleNamespace(plugins_ui=None, _mark_close_task_complete=Mock())

    with patch(
        "app.cleanup.perform_close_cleanup", side_effect=RuntimeError("cleanup down")
    ):
        run_deferred_close_cleanup(window)

    assert "Deferred close cleanup failed" in caplog.text
    window._mark_close_task_complete.assert_called_once_with("cleanup")
