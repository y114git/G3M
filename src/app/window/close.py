"""Close and shutdown helpers for AppWindow."""

import contextlib
import logging

from PyQt6.QtWidgets import QApplication

from config.config import THREAD_WAIT_TIMEOUT

logger = logging.getLogger(__name__)


def begin_close_event(window, event, *, single_shot):
    if getattr(window, "_close_cleanup_started", False):
        event.accept()
        return
    window._close_cleanup_started = True
    logger.info("Application close requested; starting shutdown cleanup")
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
    window._pending_close_tasks = {"cleanup": False}
    single_shot(
        max(2000, int(THREAD_WAIT_TIMEOUT) * 2), window._force_finish_close_tasks
    )
    single_shot(0, window._run_deferred_close_cleanup)


def run_deferred_close_cleanup(window) -> None:
    try:
        try:
            if hasattr(window, "plugins_ui") and window.plugins_ui:
                window.plugins_ui.shutdown()
            from app.cleanup import perform_close_cleanup

            perform_close_cleanup(window)
        except Exception:
            logger.exception("Deferred close cleanup failed")
    finally:
        window._mark_close_task_complete("cleanup")


def mark_close_task_complete(window, task_name: str) -> None:
    pending = getattr(window, "_pending_close_tasks", None)
    if pending is None:
        return
    pending[task_name] = True
    if not all(pending.values()):
        return
    logger.info("All close tasks completed; quitting application")
    app = QApplication.instance()
    if app:
        with contextlib.suppress(Exception):
            app.quit()


def force_finish_close_tasks(window) -> None:
    pending = getattr(window, "_pending_close_tasks", None)
    if not pending or all(pending.values()):
        return
    unfinished = [task_name for task_name, completed in pending.items() if not completed]
    unfinished_text = ", ".join(unfinished)
    logger.warning(
        "Forcing application quit with unfinished close tasks: %s",
        unfinished_text,
    )
    for task_name, completed in list(pending.items()):
        if not completed:
            pending[task_name] = True
    app = QApplication.instance()
    if app:
        with contextlib.suppress(Exception):
            app.quit()
