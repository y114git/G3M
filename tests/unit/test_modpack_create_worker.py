"""Unit tests for modpack create worker crash handling."""

from __future__ import annotations

from unittest.mock import Mock

from workers.modpack_create_worker import CreateModpackThread


class _FailingSignal:
    def emit(self, *_args, **_kwargs):
        raise RuntimeError("receiver deleted")


def test_modpack_create_worker_suppresses_emit_failure_after_error(
    monkeypatch, tmp_path, caplog
):
    """Checks that modpack errors cannot crash while notifying a dead UI."""
    worker = CreateModpackThread(
        chapter_mods={},
        modpack_name="Pack",
        modpack_dir=str(tmp_path / "pack"),
        app_state=Mock(),
        mod_service=Mock(),
    )
    worker.status_update = _FailingSignal()
    worker.finished = _FailingSignal()

    class _BrokenPatcher:
        def __init__(self, *_args, **_kwargs) -> None:
            raise RuntimeError("patcher failed")

    monkeypatch.setattr("workers.modpack_create_worker.G3MToolPatchingService", _BrokenPatcher)

    worker.run()

    assert "CreateModpackThread failed" in caplog.text
    assert "CreateModpackThread: failed to emit" in caplog.text


def test_modpack_cancel_stops_active_patcher(tmp_path):
    worker = CreateModpackThread(
        chapter_mods={},
        modpack_name="Pack",
        modpack_dir=str(tmp_path / "pack"),
        app_state=Mock(),
        mod_service=Mock(),
    )
    worker.patcher = Mock()

    worker.cancel()

    assert worker._cancelled is True
    worker.patcher.cancel.assert_called_once_with()
