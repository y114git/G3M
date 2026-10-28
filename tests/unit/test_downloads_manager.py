"""Download coordinator terminal-state tests."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from models.download_models import (
    DownloadRecord,
    DownloadStatus,
    SourceKind,
    TargetKind,
    UseStatus,
)
from services.downloads.manager import DownloadsManager


def test_manual_setup_metadata_includes_the_game_version(tmp_path):
    manager = DownloadsManager(str(tmp_path), lambda: {})
    record = DownloadRecord(id="manual", display_name="Mod", metadata={"gb_mod_id": 42, "game_version": "1.08"})
    assert manager._build_dialog_metadata(record)["game_version"] == "1.08"


def test_gamebanana_checksum_mismatch_warns_instead_of_installing(tmp_path, monkeypatch):
    from workers.download_worker import CHECKSUM_WARNING, DownloadWorker

    mods_dir = tmp_path / "mods"
    mods_dir.mkdir()
    manager = DownloadsManager(str(tmp_path), lambda: {})
    manager.set_app_context(mods_dir=str(mods_dir))
    install = Mock()
    monkeypatch.setattr(manager, "_start_use", install)
    monkeypatch.setattr(DownloadWorker, "start", lambda worker: worker.run())
    monkeypatch.setattr("utils.network_utils.get_session", lambda: object())
    monkeypatch.setattr("utils.network_utils.download_file", lambda _session, _url, path, **_kwargs: Path(path).write_bytes(b"corrupt archive"))
    monkeypatch.setattr(DownloadsManager, "_fetch_live_md5", staticmethod(lambda _metadata: None))

    record_id, _duplicate = manager.enqueue(
        "Update", source_kind=SourceKind.GAMEBANANA,
        source_url="https://gamebanana.com/dl/123", metadata={"md5": "0" * 32}, auto_use=True,
    )

    record = manager.store.find(record_id)
    assert record is not None
    assert record.download_status == DownloadStatus.DOWNLOADED
    assert record.use_status == UseStatus.READY
    assert record.error_message == CHECKSUM_WARNING
    assert record.file_exists is True
    assert record.needs_attention is True
    install.assert_not_called()


def test_worker_cleanup_uses_native_safe_retirement(monkeypatch) -> None:
    from services.downloads.manager import _cleanup_worker

    worker = object()
    retired = []
    monkeypatch.setattr(
        "ui.utils.thread_lifetime.retire_qthread", retired.append
    )

    _cleanup_worker(worker)

    assert retired == [worker]


def test_mod_downloads_keep_their_original_profile_and_deduplicate_per_profile(tmp_path, monkeypatch):
    manager = DownloadsManager(str(tmp_path), lambda: {})
    monkeypatch.setattr(manager, "_start_download", lambda _record: None)
    first_dir = str(tmp_path / "first")
    second_dir = str(tmp_path / "second")
    manager.set_app_context(mods_dir=first_dir)
    first_id, duplicate = manager.enqueue("Mod", canonical_key="gb_mod_1_2")
    assert not duplicate
    manager.set_app_context(mods_dir=second_dir)
    second_id, duplicate = manager.enqueue("Mod", canonical_key="gb_mod_1_2")
    assert not duplicate
    assert second_id != first_id
    first_record = manager.store.find(first_id)
    second_record = manager.store.find(second_id)
    assert first_record is not None
    assert second_record is not None
    assert manager._mod_target_dir(first_record) == first_dir
    assert manager._mod_target_dir(second_record) == second_dir
    assert manager.enqueue("Mod", canonical_key="gb_mod_1_2") == (second_id, True)


def test_legacy_download_uses_the_manager_profile_when_matching_duplicates(tmp_path, monkeypatch):
    manager = DownloadsManager(str(tmp_path), lambda: {})
    monkeypatch.setattr(manager, "_start_download", lambda _record: None)
    manager.set_app_context(mods_dir=str(tmp_path / "active"))
    legacy = DownloadRecord(id="legacy", display_name="Mod", canonical_key="mod", metadata={})
    manager.store.add(legacy)
    record_id, duplicate = manager.enqueue("Mod", canonical_key="mod", metadata={"target_mods_dir": str(tmp_path / "other")})
    assert not duplicate
    assert record_id != legacy.id
    assert manager.enqueue("Mod", canonical_key="mod") == (legacy.id, True)


def test_catalog_theme_can_be_downloaded_again_after_deletion(tmp_path, monkeypatch):
    manager = DownloadsManager(str(tmp_path), lambda: {})
    monkeypatch.setattr(manager, "_start_download", lambda _record: None)
    previous = DownloadRecord(id="old-theme", display_name="Theme", target_kind=TargetKind.THEME,
                              canonical_key="theme:test:1", download_status=DownloadStatus.DOWNLOADED,
                              use_status=UseStatus.READY, ever_installed=True, file_exists=False)
    manager.store.add(previous)
    record_id, duplicate = manager.enqueue("Theme", target_kind=TargetKind.THEME, canonical_key="theme:test:1")
    assert not duplicate
    assert record_id != previous.id
    assert manager.store.find(previous.id) is None


def test_late_worker_success_cannot_replace_cancelled_state(tmp_path) -> None:
    manager = DownloadsManager(str(tmp_path), lambda: {})
    record = DownloadRecord(
        id="download-race",
        display_name="Race",
        download_status=DownloadStatus.DOWNLOADING,
    )
    manager.store.add(record)

    manager.action_cancel_download(record.id)
    manager._on_download_finished(record.id, True, "", str(tmp_path / "late.zip"))

    assert record.download_status == DownloadStatus.CANCELLED
    assert record.use_status == UseStatus.CANCELLED
    assert record.file_exists is False


def test_stale_retry_generation_cannot_remove_active_worker(tmp_path) -> None:
    manager = DownloadsManager(str(tmp_path), lambda: {})
    record = DownloadRecord(
        id="download-retry-race",
        display_name="Race",
        download_status=DownloadStatus.DOWNLOADING,
    )
    manager.store.add(record)
    active_worker = object()
    manager._workers[record.id] = active_worker
    manager._download_generations[record.id] = 2

    manager._on_download_finished(
        record.id, True, "", str(tmp_path / "stale.zip"), generation=1
    )

    assert manager._workers[record.id] is active_worker
    assert record.download_status == DownloadStatus.DOWNLOADING


def test_clear_downloads_removes_generation_for_deleted_record(tmp_path) -> None:
    manager = DownloadsManager(str(tmp_path), lambda: {})
    record = DownloadRecord(
        id="done", display_name="Done", download_status=DownloadStatus.DOWNLOADED
    )
    manager.store.add(record)
    manager._download_generations[record.id] = 3

    manager.clear_downloads()

    assert record.id not in manager._download_generations


def test_manual_setup_result_is_not_reported_as_installed(tmp_path) -> None:
    manager = DownloadsManager(str(tmp_path), lambda: {})
    record = DownloadRecord(
        id="wip-84933",
        display_name="DELTARUNE Multiplayer Mod!",
        download_status=DownloadStatus.DOWNLOADED,
        use_status=UseStatus.USING,
        file_path=str(tmp_path / "multiplayer.zip"),
        file_exists=True,
    )
    manager.store.add(record)
    completions = []
    manager.use_completed.connect(lambda: completions.append(True))

    manager._on_use_finished(record.id, False, True, "")

    assert record.use_status == UseStatus.NEEDS_MANUAL
    assert record.ever_installed is False
    assert completions == []


def test_gamebanana_update_uses_its_snapshotted_mods_directory(tmp_path, monkeypatch) -> None:
    queued_profile = tmp_path / "queued-profile"
    active_profile = tmp_path / "active-profile"
    queued_profile.mkdir()
    active_profile.mkdir()
    archive = tmp_path / "update.zip"
    archive.write_bytes(b"archive")
    manager = DownloadsManager(str(tmp_path), lambda: {})
    manager.set_app_context(mods_dir=str(active_profile))
    record = DownloadRecord(
        id="profile-bound-update",
        display_name="Update",
        target_kind=TargetKind.MOD,
        file_path=str(archive),
        file_exists=True,
        metadata={
            "target_mods_dir": str(queued_profile),
            "gb_mod_id": 42,
            "gb_file_id": 77,
            "timestamp": 123,
        },
    )
    manager.store.add(record)
    captured = {}

    class Worker:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)
            self.use_finished = SimpleNamespace(connect=lambda _callback: None)

        def start(self) -> None:
            pass

    monkeypatch.setattr("workers.use_worker.UseWorker", Worker)

    manager._start_use(record.id)
    manager._remember_gamebanana_file(record)

    assert captured["mods_dir"] == str(queued_profile)
    assert json.loads((queued_profile / "mods_data.json").read_text(encoding="utf-8")) == {
        "gb_mod_42": {
            "gamebanana_file_id": 77,
            "gamebanana_file_timestamp": 123,
        }
    }
    assert not (active_profile / "mods_data.json").exists()


def test_installs_run_one_at_a_time(tmp_path, monkeypatch):
    manager = DownloadsManager(str(tmp_path), lambda: {})
    manager.set_app_context(mods_dir=str(tmp_path))
    archive = tmp_path / "mod.zip"
    archive.write_bytes(b"x")
    running = DownloadRecord(id="running", target_kind=TargetKind.MOD, use_status=UseStatus.USING, file_path=str(archive), file_exists=True)
    waiting = DownloadRecord(id="waiting", target_kind=TargetKind.MOD, file_path=str(archive), file_exists=True)
    manager.store.add(running)
    manager.store.add(waiting)
    manager._workers["running"] = Mock()
    retries = []
    monkeypatch.setattr("services.downloads.manager.QTimer.singleShot", lambda ms, callback: retries.append((ms, callback)))

    manager._start_use("waiting")

    assert waiting.use_status != UseStatus.USING
    assert len(retries) == 1


def _finished_mod_record(**changes):
    return DownloadRecord(id="old", display_name="Mod", canonical_key="gb_mod_1_2", download_status=DownloadStatus.DOWNLOADED,
                          use_status=UseStatus.READY, file_exists=False, **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"ever_installed": True},
        {"use_status": UseStatus.NEEDS_MANUAL},
        {"use_status": UseStatus.FAILED},
        {"use_status": UseStatus.CANCELLED},
    ],
)
def test_a_mod_can_be_downloaded_again_after_a_finished_attempt(tmp_path, monkeypatch, changes):
    manager = DownloadsManager(str(tmp_path), lambda: {})
    started = []
    monkeypatch.setattr(manager, "_start_download", started.append)
    previous = _finished_mod_record()
    for name, value in changes.items():
        setattr(previous, name, value)
    manager.store.add(previous)

    record_id, duplicate = manager.enqueue("Mod", canonical_key="gb_mod_1_2")

    assert not duplicate
    assert record_id != previous.id
    assert manager.store.find(previous.id) is None
    assert len(started) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"download_status": DownloadStatus.DOWNLOADING},
        {"use_status": UseStatus.USING},
        {"use_status": UseStatus.PENDING_AUTO},
        {"use_status": UseStatus.READY},  # downloaded and waiting for the user to install it
    ],
)
def test_a_mod_that_is_active_or_waiting_is_not_queued_twice(tmp_path, monkeypatch, changes):
    manager = DownloadsManager(str(tmp_path), lambda: {})
    monkeypatch.setattr(manager, "_start_download", lambda _record: None)
    previous = _finished_mod_record()
    for name, value in changes.items():
        setattr(previous, name, value)
    manager.store.add(previous)

    assert manager.enqueue("Mod", canonical_key="gb_mod_1_2") == (previous.id, True)
