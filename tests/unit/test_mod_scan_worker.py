"""Unit tests for mod scan worker signal handling."""

from __future__ import annotations

from types import SimpleNamespace

from PyQt6.QtCore import QObject

from workers.mod.scan_worker import ModScanThread


class _Parent(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.app_state = SimpleNamespace(_scan_blocked=True)


class _FailingSignal:
    def emit(self, *_args, **_kwargs):
        raise RuntimeError("receiver deleted")


def test_mod_scan_worker_suppresses_early_emit_failure(caplog, tmp_path):
    worker = ModScanThread(str(tmp_path), parent=_Parent())
    worker.scan_completed = _FailingSignal()

    worker.run()

    assert "ModScanThread: failed to emit scan_completed" in caplog.text
