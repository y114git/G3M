"""Unit tests for GameBanana worker crash handling."""

from __future__ import annotations

from workers.gamebanana.search_worker import SearchGameBananaModsThread


class _FailingSignal:
    def emit(self, *_args, **_kwargs):
        raise RuntimeError("receiver deleted")


def test_search_worker_suppresses_emit_failure_after_error(monkeypatch, caplog):
    """Checks that GameBanana search errors cannot crash while notifying a dead UI."""
    worker = SearchGameBananaModsThread(123, "spamton")
    worker.status = _FailingSignal()
    worker.result = _FailingSignal()
    monkeypatch.setattr(
        "workers.gamebanana.search_worker.get_gamebanana_reverse_map",
        lambda: {123: "deltarune"},
    )
    worker.api.search_mods = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        RuntimeError("gb failed")
    )

    worker.run()

    assert "Error searching GameBanana mods" in caplog.text
    assert "SearchGameBananaModsThread: failed to emit" in caplog.text
