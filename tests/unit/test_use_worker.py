"""Unit tests for the Downloads Use worker."""

from __future__ import annotations

import os
import zipfile
from unittest.mock import Mock

from helpers import FailingSignal

from models.download_models import TargetKind
from workers.use_worker import UseWorker


def test_raw_gamebanana_archive_requires_setup_instead_of_fake_install(tmp_path):
    archive_path = tmp_path / "multiplayer.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("1.0 Prerelease.xdelta", b"patch")
        archive.writestr("data.win", b"replacement")
    mods_dir = tmp_path / "mods"
    mods_dir.mkdir()
    worker = UseWorker(
        record_id="wip_84933",
        file_path=str(archive_path),
        target_kind=TargetKind.MOD,
        mods_dir=str(mods_dir),
        metadata={
            "gb_mod_id": 84933,
            "item_type": "wip",
            "name": "DELTARUNE Multiplayer Mod!",
            "game": "deltarune",
        },
    )
    finished = []
    worker.use_finished.connect(lambda *args: finished.append(args))

    worker.run()

    assert finished == [("wip_84933", False, True, "")]
    assert list(mods_dir.iterdir()) == []


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
