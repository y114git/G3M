"""Tests for background operation lifetime management."""

from unittest.mock import Mock

from services.background_operations import BackgroundOperationManager


class _Signal:
    def __init__(self) -> None:
        self.callbacks = []

    def connect(self, callback) -> None:
        self.callbacks.append(callback)

    def emit(self, *args) -> None:
        for callback in list(self.callbacks):
            callback(*args)


class _Thread:
    def __init__(self, running=True) -> None:
        self.finished = _Signal()
        self.running = running
        self.deleted = False

    def isRunning(self) -> bool:  # noqa: N802
        return self.running

    def deleteLater(self) -> None:  # noqa: N802
        self.deleted = True


def test_thread_is_retained_until_finished_and_then_released():
    manager = BackgroundOperationManager()
    thread = _Thread()

    manager.retain_thread(thread)

    assert manager.snapshot()["threads"] == 1
    thread.finished.emit()
    assert manager.snapshot()["threads"] == 0


def test_running_thread_is_deleted_only_after_finish():
    manager = BackgroundOperationManager()
    thread = _Thread()

    manager.retire_thread(thread)

    assert thread.deleted is False
    thread.running = False
    thread.finished.emit()
    assert thread.deleted is True


def test_runnable_is_retained_until_run_returns():
    manager = BackgroundOperationManager()
    pool = Mock()
    runnable = Mock()

    manager.start_runnable(pool, runnable)

    proxy = pool.start.call_args.args[0]
    assert manager.snapshot()["runnables"] == 1
    proxy.run()
    runnable.run.assert_called_once_with()
    assert manager.snapshot()["runnables"] == 0


def test_process_cancellation_is_scoped_by_owner():
    manager = BackgroundOperationManager()
    first = Mock()
    second = Mock()
    first_cancel = Mock()
    second_cancel = Mock()
    first_owner = object()
    second_owner = object()
    manager.register_process(first, cancel=first_cancel, owner=first_owner)
    manager.register_process(second, cancel=second_cancel, owner=second_owner)

    manager.cancel_processes(owner=first_owner)

    first_cancel.assert_called_once_with()
    second_cancel.assert_not_called()
    assert manager.snapshot()["processes"] == 1
