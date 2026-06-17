"""Unit tests for download worker crash handling."""

from __future__ import annotations

from unittest.mock import Mock

from helpers import FailingSignal

from workers.download_worker import DownloadWorker


def test_download_worker_suppresses_emit_failure_after_download_error(
    qapp, tmp_path, monkeypatch, caplog
):
    """Checks that handled download errors cannot crash while notifying a dead UI."""
    worker = DownloadWorker(
        "record_1",
        "https://example.invalid/mod.zip",
        str(tmp_path / "mod.zip"),
    )
    worker.download_finished = FailingSignal()

    class _Session:
        def head(self, *_args, **_kwargs):
            return type("_Response", (), {"headers": {}})()

    monkeypatch.setattr("utils.network_utils.get_session", lambda: _Session())
    monkeypatch.setattr("utils.network_utils.download_file", Mock(side_effect=RuntimeError("download failed")))

    worker.run()

    assert "DownloadWorker: download failed" in caplog.text
    assert "DownloadWorker: failed to emit" in caplog.text
