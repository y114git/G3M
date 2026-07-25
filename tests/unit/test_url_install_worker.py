"""Unit tests for URL install worker failure paths."""

import requests

from workers.install.url_install_worker import UrlInstallThread


class _UrlThatFailsBeforeNormalization:
    def startswith(self, _prefixes):
        raise requests.RequestException("protocol parse failed")


def test_url_install_worker_reports_malformed_url_without_handler_crash(qapp):
    """Checks that malformed URL input emits failure instead of crashing in except."""
    worker = UrlInstallThread(None, _UrlThatFailsBeforeNormalization())
    finished = []
    worker.result_ready.connect(lambda success, message: finished.append((success, message)))

    worker.run()

    assert finished
    assert finished[-1][0] is False
    assert finished[-1][1]


def test_url_install_worker_suppresses_emit_failure_after_error(qapp, caplog):
    """Checks that URL install errors cannot crash while notifying a dead UI."""
    worker = UrlInstallThread(None, _UrlThatFailsBeforeNormalization())

    class _FailingSignal:
        def emit(self, *_args, **_kwargs):
            raise RuntimeError("receiver deleted")

    worker.result_ready = _FailingSignal()

    worker.run()

    assert "UrlInstallThread: failed to emit" in caplog.text
