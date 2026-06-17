"""Unit tests for the Downloads Use worker."""

from __future__ import annotations

import os
from unittest.mock import Mock

from helpers import FailingSignal

from models.download_models import TargetKind
from workers.use_worker import UseWorker


def test_plugin_use_does_not_delete_successfully_installed_plugin_when_cancelled_late(
    temp_dir,
):
    """Checks that late cancellation cannot erase an already installed plugin update."""
    archive_path = os.path.join(temp_dir, "plugin.zip")
    with open(archive_path, "wb") as handle:
        handle.write(b"plugin archive")
    install_service = Mock()
    worker = UseWorker(
        record_id="record_1",
        file_path=archive_path,
        target_kind=TargetKind.PLUGIN,
        mods_dir="",
        metadata={"source": "catalog", "plugin_id": "sample_plugin"},
        plugin_install_service=install_service,
    )

    def cancel_then_install(*_args, **_kwargs):
        worker.cancel()
        return "sample_plugin"

    install_service.install_archive.side_effect = cancel_then_install
    finished = []
    worker.use_finished.connect(lambda *args: finished.append(args))

    worker.run()

    install_service.delete_plugin.assert_not_called()
    assert finished == [("record_1", True, False, "")]


def test_plugin_use_suppresses_emit_failure_after_install_error(temp_dir, caplog):
    """Checks that plugin install failures cannot crash while notifying a dead UI."""
    archive_path = os.path.join(temp_dir, "plugin.zip")
    with open(archive_path, "wb") as handle:
        handle.write(b"plugin archive")
    install_service = Mock()
    install_service.install_archive.side_effect = RuntimeError("install failed")
    worker = UseWorker(
        record_id="record_1",
        file_path=archive_path,
        target_kind=TargetKind.PLUGIN,
        mods_dir="",
        metadata={"source": "catalog", "plugin_id": "sample_plugin"},
        plugin_install_service=install_service,
    )

    worker.use_finished = FailingSignal()

    worker.run()

    assert "UseWorker: plugin install failed" in caplog.text
    assert "UseWorker: failed to emit" in caplog.text
