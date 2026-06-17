"""Unit tests for fetch mods worker crash handling."""

from __future__ import annotations

from types import SimpleNamespace

from workers.fetch_mods_worker import FetchModsThread


class _FailingSignal:
    def emit(self, *_args, **_kwargs):
        raise RuntimeError("receiver deleted")


def test_fetch_mods_worker_suppresses_emit_failure_after_error(caplog):
    """Checks that fetch errors cannot crash while notifying a dead UI."""
    context = SimpleNamespace(
        app_state=SimpleNamespace(
            local_config={},
            all_mods=[],
            all_mods_updated=_FailingSignal(),
        ),
        settings_service=None,
    )
    worker = FetchModsThread(context)
    worker.status = _FailingSignal()
    worker.result = _FailingSignal()
    worker._get_local_mods = lambda: (_ for _ in ()).throw(RuntimeError("local failed"))

    worker.run()

    assert "FetchModsThread: Error in run" in caplog.text
    assert "FetchModsThread: failed to emit" in caplog.text
