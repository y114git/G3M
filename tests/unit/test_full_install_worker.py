"""Unit tests for the full install worker."""

from __future__ import annotations

from types import SimpleNamespace

from PyQt6.QtCore import QObject

from workers.install.full_install_worker import FullInstallThread


class _MainWindow(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.app_state = SimpleNamespace()


def test_full_install_worker_emits_failure_when_app_state_is_incomplete(qapp):
    main_window = _MainWindow()
    worker = FullInstallThread(main_window, "C:/Games/Target")
    statuses = []
    finished = []
    worker.status.connect(lambda message, color: statuses.append((message, color)))
    worker.result_ready.connect(lambda success, target: finished.append((success, target)))

    worker.run()

    assert finished == [(False, "C:/Games/Target")]
    assert statuses


def test_full_install_worker_suppresses_emit_failure_after_install_error(qapp, caplog):
    """Checks that error reporting cannot turn a handled install failure into a crash."""
    main_window = _MainWindow()
    worker = FullInstallThread(main_window, "C:/Games/Target")

    class _FailingSignal:
        def emit(self, *_args, **_kwargs):
            raise RuntimeError("receiver deleted")

    worker.status = _FailingSignal()
    worker.result_ready = _FailingSignal()

    worker.run()

    assert "FullInstallThread.run: installation error" in caplog.text
    assert "FullInstallThread: failed to emit" in caplog.text
