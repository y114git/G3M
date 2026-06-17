"""Unit tests for theme install worker crash handling."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

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
    worker.finished = _FailingSignal()

    worker.run()

    assert "ThemeInstallWorker: failed to emit" in caplog.text
