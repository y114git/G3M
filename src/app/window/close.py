"""Close and shutdown helpers for AppWindow."""

import contextlib

from PyQt6.QtWidgets import QApplication

from config.config import THREAD_WAIT_TIMEOUT


def begin_close_event(window, event, *, single_shot):
    if getattr(window, "_close_cleanup_started", False):
        event.accept()
        return
    window._close_cleanup_started = True
    app = QApplication.instance()
    if app:
        with contextlib.suppress(Exception):
            app.removeEventFilter(window)
        with contextlib.suppress(Exception):
            app.applicationStateChanged.disconnect(window._on_application_state_changed)
        with contextlib.suppress(Exception):
            app.setQuitOnLastWindowClosed(False)
    event.accept()
    window.hide()
    window._pending_close_tasks = {"analytics": False, "cleanup": False}
    if hasattr(window, "analytics_service") and window.analytics_service:
        analytics_done = False
        try:
            analytics_done = window.analytics_service.shutdown_async(
                lambda: window._mark_close_task_complete("analytics")
            )
        except Exception:
            analytics_done = True
        if analytics_done:
            window._mark_close_task_complete("analytics")
    else:
        window._mark_close_task_complete("analytics")
    single_shot(
        max(2000, int(THREAD_WAIT_TIMEOUT) * 2), window._force_finish_close_tasks
    )
    single_shot(0, window._run_deferred_close_cleanup)


def run_deferred_close_cleanup(window) -> None:
    try:
        if hasattr(window, "plugins_ui") and window.plugins_ui:
            window.plugins_ui.shutdown()
        from app.cleanup import perform_close_cleanup

        perform_close_cleanup(window)
    finally:
        window._mark_close_task_complete("cleanup")


def mark_close_task_complete(window, task_name: str) -> None:
    pending = getattr(window, "_pending_close_tasks", None)
    if pending is None:
        return
    pending[task_name] = True
    if not all(pending.values()):
        return
    app = QApplication.instance()
    if app:
        with contextlib.suppress(Exception):
            app.quit()


def force_finish_close_tasks(window) -> None:
    pending = getattr(window, "_pending_close_tasks", None)
    if not pending or all(pending.values()):
        return
    for task_name, completed in list(pending.items()):
        if not completed:
            pending[task_name] = True
    app = QApplication.instance()
    if app:
        with contextlib.suppress(Exception):
            app.quit()
