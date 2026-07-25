"""Unit tests for theme install worker crash handling."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from services.localization_service import tr
from workers.install.theme_install_worker import ThemeInstallWorker


class _FailingSignal:
    def emit(self, *_args, **_kwargs):
        raise RuntimeError("receiver deleted")


def test_theme_install_worker_suppresses_emit_failure_after_error(tmp_path, caplog):
    """Checks that theme install errors cannot crash while notifying a dead UI."""
    worker = ThemeInstallWorker(
        str(tmp_path / "missing.zip"),
        str(tmp_path),
        SimpleNamespace(local_config={}),
        Mock(),
    )
    worker.result_ready = _FailingSignal()

    worker.run()

    assert "ThemeInstallWorker: failed to emit" in caplog.text


def test_cancelled_theme_download_reports_cancellation(tmp_path):
    worker = ThemeInstallWorker(
        "https://example.invalid/theme.zip",
        str(tmp_path),
        SimpleNamespace(local_config={}),
        Mock(),
    )
    worker._cancelled = True
    worker._download_archive = Mock(return_value=False)
    results = []
    worker.result_ready.connect(lambda success, message: results.append((success, message)))

    worker.run()

    assert results == [(False, tr("status.operation_cancelled"))]
