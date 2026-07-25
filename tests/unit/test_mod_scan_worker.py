"""Unit tests for mod scan worker signal handling."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QObject

from workers.mod.scan_worker import ModScanThread


class _Parent(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.app_state = SimpleNamespace(_scan_blocked=True)


class _FailingSignal:
    def emit(self, *_args, **_kwargs):
        raise RuntimeError("receiver deleted")


def test_mod_scan_worker_suppresses_early_emit_failure(caplog, tmp_path):
    worker = ModScanThread(str(tmp_path), parent=_Parent())
    worker.scan_completed = _FailingSignal()

    worker.run()

    assert "ModScanThread: failed to emit scan_completed" in caplog.text


def test_mod_scan_worker_loads_directory_symlink(tmp_path):
    external_mod = tmp_path / "shared-profile" / "linked-mod"
    external_mod.mkdir(parents=True)
    (external_mod / "mod_config.json").write_text(
        json.dumps({"id": "linked-mod"}), encoding="utf-8"
    )
    mods_dir = tmp_path / "mods"
    mods_dir.mkdir()
    link = mods_dir / "linked-mod"
    try:
        os.symlink(external_mod, link, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Directory symlinks are unavailable: {exc}")

    results = []
    worker = ModScanThread(str(mods_dir))
    worker.scan_completed.connect(results.append)

    worker.run()

    assert results[-1]["linked-mod"]["folder_path"] == str(link)
