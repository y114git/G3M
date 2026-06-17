"""Unit tests for chat request worker crash handling."""

from __future__ import annotations

from workers.chat_request_worker import ChatRequestThread


class _FailingSignal:
    def emit(self, *_args, **_kwargs):
        raise RuntimeError("receiver deleted")


def test_chat_request_worker_suppresses_emit_failure_after_error(caplog):
    """Checks that chat errors cannot crash while notifying a dead UI."""
    worker = ChatRequestThread()
    worker._request_type = "get_messages"
    worker._channel = "en"
    worker.chat_service.get_messages = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        RuntimeError("chat failed")
    )
    worker.error_occurred = _FailingSignal()

    worker.run()

    assert "ChatRequestThread: Error" in caplog.text
    assert "ChatRequestThread: failed to emit" in caplog.text
