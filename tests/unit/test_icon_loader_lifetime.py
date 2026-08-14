"""Regression tests for asynchronous icon-loader ownership."""

from types import SimpleNamespace
from unittest.mock import patch

from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QLabel

from ui.common.styling import load_mod_icon_universal
from ui.widgets.mod_details_overlay import ModDetailsOverlay


class _CapturingPool:
    def __init__(self) -> None:
        self.runnable = None

    def start(self, runnable) -> None:
        self.runnable = runnable


def test_icon_loader_signals_outlive_deleted_label(qapp):
    label = QLabel()
    pool = _CapturingPool()
    mod = SimpleNamespace(
        id="remote-mod",
        icon="https://example.com/icon.png",
        icon_path=None,
        screenshots_url=[],
    )

    with patch("ui.utils.image_loader.get_image_loader_pool", return_value=pool):
        load_mod_icon_universal(label, mod)

    assert pool.runnable is not None
    assert pool.runnable.signals.parent() is None
    label.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()

    pool.runnable.signals.result.emit(QImage())
    qapp.processEvents()


class _Signal:
    def __init__(self) -> None:
        self.callback = None

    def connect(self, callback) -> None:
        self.callback = callback


class _StuckThread:
    finished = _Signal()

    def __init__(self) -> None:
        self.terminated = False

    def blockSignals(self, _blocked) -> None:  # noqa: N802
        pass

    def isRunning(self) -> bool:  # noqa: N802
        return True

    def isFinished(self) -> bool:  # noqa: N802
        return False

    def requestInterruption(self) -> None:  # noqa: N802
        pass

    def quit(self) -> None:
        pass

    def wait(self, _timeout) -> bool:
        return False

    def terminate(self) -> None:
        self.terminated = True

    def deleteLater(self) -> None:  # noqa: N802
        pass


def test_overlay_cleanup_never_force_terminates_running_thread():
    thread = _StuckThread()

    ModDetailsOverlay._stop_thread(thread)

    assert thread.terminated is False
    assert thread.finished.callback is not None
