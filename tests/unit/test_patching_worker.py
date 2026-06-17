"""Unit tests for mod patching worker crash handling."""

from __future__ import annotations

from unittest.mock import Mock

from workers.mod.patching_worker import ModPatchingThread


class _FailingSignal:
    def emit(self, *_args, **_kwargs):
        raise RuntimeError("receiver deleted")


def test_mod_patching_worker_suppresses_emit_failure_after_error(monkeypatch, caplog):
    """Checks that patching errors cannot crash while notifying a dead UI."""
    worker = ModPatchingThread(
        app_state=Mock(),
        mod_service=Mock(),
        chapter_mods={},
        session_manifest_path="session.json",
    )
    worker.status_update = _FailingSignal()
    worker.finished = _FailingSignal()

    class _BrokenPatcher:
        def __init__(self, *_args, **_kwargs) -> None:
            raise RuntimeError("patcher failed")

    monkeypatch.setattr("workers.mod.patching_worker.G3MToolPatchingService", _BrokenPatcher)

    worker.run()

    assert "ModPatchingThread failed" in caplog.text
    assert "ModPatchingThread: failed to emit" in caplog.text
