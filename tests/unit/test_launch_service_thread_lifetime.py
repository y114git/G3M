from unittest.mock import Mock

from services.background_operations import BackgroundOperationManager
from services.launch_service import GameLauncher


class _Signal:
    def __init__(self) -> None:
        self.callback = None

    def connect(self, callback):
        self.callback = callback


class _RunningThread:
    def __init__(self) -> None:
        self.finished = _Signal()
        self.patcher = Mock()
        self.deleted = False

    def isRunning(self):  # noqa: N802
        return True

    def deleteLater(self):  # noqa: N802
        self.deleted = True


def test_patching_thread_is_strongly_retained_until_native_finish(qapp, monkeypatch):
    import ui.utils.thread_lifetime as thread_lifetime

    operations = BackgroundOperationManager()
    monkeypatch.setattr(thread_lifetime, "background_operations", operations)
    launcher = GameLauncher(Mock(local_config={}), Mock(), Mock())
    thread = _RunningThread()
    launcher._patching_thread = thread
    launcher._continue_after_patching = Mock()

    launcher._on_patching_finished({}, True)

    assert operations.snapshot()["threads"] == 1
    assert launcher._patching_thread is None
    assert thread.finished.callback is not None

    thread.finished.callback()

    assert operations.snapshot()["threads"] == 0
    assert thread.deleted is True
