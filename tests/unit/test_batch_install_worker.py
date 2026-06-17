"""Unit tests for batch install worker crash handling."""

from __future__ import annotations

from types import SimpleNamespace

from helpers import FailingSignal
from PyQt6.QtCore import QObject

from workers.install.batch_install_worker import InstallModsThread


class _MainWindow(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.app_state = SimpleNamespace(mods_dir="C:/Mods")
        self.mod_service = SimpleNamespace(get_mod_folder_path=lambda _key: None)


def test_batch_install_worker_suppresses_emit_failure_after_install_error(
    qapp, monkeypatch, caplog
):
    """Checks that a handled install error cannot crash while notifying a dead UI."""
    worker = InstallModsThread(_MainWindow(), [], was_installed_before=False)
    worker.status = FailingSignal()
    worker.finished = FailingSignal()
    monkeypatch.setattr(
        "workers.install.batch_install_worker.tempfile.mkdtemp",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("temp failed")),
    )

    worker.run()

    assert "InstallModsThread.run: installation error" in caplog.text
    assert "InstallModsThread: failed to emit" in caplog.text
