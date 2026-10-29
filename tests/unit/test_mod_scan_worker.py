"""Unit tests for mod scan worker signal handling."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest
from PyQt6 import sip
from PyQt6.QtCore import QObject

from config.config import MOD_CONFIG_FILENAME
from ui.utils.thread_lifetime import retire_qthread
from utils.mod.scan_utils import scan_mods_directory
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
    vars(worker)["scan_completed"] = _FailingSignal()

    worker.run()

    assert "ModScanThread: failed to emit scan_completed" in caplog.text


def test_native_scan_keeps_installation_block_after_parent_detachment(qtbot, monkeypatch, tmp_path):
    parent = _Parent()
    worker = ModScanThread(str(tmp_path), parent=parent)
    scans = []
    monkeypatch.setattr("workers.mod.scan_worker.scan_mods_directory", lambda *args, **kwargs: scans.append(args))
    with qtbot.waitSignal(worker.scan_completed, timeout=2000) as signal:
        worker.start()
    assert worker.wait(2000)
    assert signal.args == [{}]
    assert scans == []
    assert worker.parent() is None
    sip.delete(parent)
    retire_qthread(worker)
    qtbot.waitUntil(lambda: sip.isdeleted(worker))


def test_mod_scan_worker_loads_directory_symlink(tmp_path):
    external_mod = tmp_path / "shared-profile" / "linked-mod"
    external_mod.mkdir(parents=True)
    (external_mod / "mod_config.json").write_text(
        json.dumps(
            {
                "config_version": "2.0.0",
                "id": "linked-mod",
                "name": "Linked Mod",
                "version": "1.0.0",
                "authors": [],
                "game": "deltarune",
                "files": [],
            }
        ),
        encoding="utf-8",
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


def test_scan_mods_directory_loads_directory_symlink(tmp_path):
    external_mod = tmp_path / "shared-profile" / "linked-mod"
    external_mod.mkdir(parents=True)
    (external_mod / "mod_config.json").write_text(
        json.dumps(
            {
                "config_version": "2.0.0",
                "id": "linked-mod",
                "name": "Linked Mod",
                "version": "1.0.0",
                "authors": [],
                "game": "deltarune",
                "files": [],
            }
        ),
        encoding="utf-8",
    )
    mods_dir = tmp_path / "mods"
    mods_dir.mkdir()
    link = mods_dir / "linked-mod"
    try:
        os.symlink(external_mod, link, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Directory symlinks are unavailable: {exc}")

    cache, mods_by_name = scan_mods_directory(str(mods_dir))

    assert cache["linked-mod"].folder_path == str(link)
    assert mods_by_name["linked mod"] == "linked-mod"


def test_scan_mods_directory_revalidates_config_bytes_when_mtime_is_unchanged(tmp_path):
    mod_folder = tmp_path / "mods" / "mod"
    mod_folder.mkdir(parents=True)
    config_path = mod_folder / "mod_config.json"
    config = {
        "config_version": "2.0.0",
        "id": "mod",
        "name": "One",
        "version": "1.0.0",
        "authors": [],
        "game": "deltarune",
        "files": [],
    }
    config_path.write_text(json.dumps(config), encoding="utf-8")
    cache, _ = scan_mods_directory(str(mod_folder.parent))
    stamp = config_path.stat().st_mtime

    config["name"] = "Two"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    os.utime(config_path, (stamp, stamp))
    refreshed, _ = scan_mods_directory(str(mod_folder.parent), cache)

    assert refreshed["mod"].config_data["name"] == "Two"


def test_scan_mods_directory_reads_configs_migrated_by_the_owned_gateway(tmp_path):
    mod_folder = tmp_path / "mods" / "legacy"
    mod_folder.mkdir(parents=True)
    config_path = mod_folder / "mod_config.json"
    config_path.write_text(
        json.dumps(
            {
                "config_version": "1.0.0",
                "id": "legacy_mod",
                "name": "Legacy Mod",
                "version": "1.0.0",
                "author": "Author",
                "game": "deltarune",
                "files": {"deltarune_1": {"data_file_path": "DATA.win"}},
            }
        ),
        encoding="utf-8",
    )

    from services.mod_config_migration_service import migrate_managed_mods

    migration = migrate_managed_mods(mod_folder.parent)
    cache, _ = scan_mods_directory(str(mod_folder.parent))

    assert not migration.issues
    assert cache["legacy_mod"].config_data["config_version"] == "2.0.0"
    assert json.loads(config_path.read_text(encoding="utf-8"))["config_version"] == "2.0.0"


def test_scan_mods_directory_stops_when_cancelled(tmp_path):
    mod_folder = tmp_path / "mods" / "mod"
    mod_folder.mkdir(parents=True)
    (mod_folder / "mod_config.json").write_text(
        json.dumps(
            {
                "config_version": "2.0.0",
                "id": "mod",
                "name": "Mod",
                "version": "1.0.0",
                "authors": [],
                "game": "deltarune",
                "files": [],
            }
        ),
        encoding="utf-8",
    )

    cache, names = scan_mods_directory(str(mod_folder.parent), is_cancelled=lambda: True)

    assert cache == {}
    assert names == {}


def _write_config(folder, **fields):
    folder.mkdir()
    (folder / MOD_CONFIG_FILENAME).write_text(json.dumps(fields), encoding="utf-8")


def test_scan_reports_mods_saved_for_a_newer_g3m_and_keeps_the_rest(tmp_path):
    _write_config(tmp_path / "future", config_version="3.0.0", id="future", name="Future Mod")
    _write_config(tmp_path / "broken", config_version="2.0.0", id="broken")
    _write_config(tmp_path / "old", config_version="1.0.0", id="old", name="Old Mod")
    newer: list[str] = []

    cache, _ = scan_mods_directory(str(tmp_path), newer_config_mods=newer)

    assert newer == ["Future Mod"]
    assert cache == {}
