"""Download coordinator terminal-state tests."""

from models.download_models import DownloadRecord, DownloadStatus, UseStatus
from services.downloads.manager import DownloadsManager


def test_worker_cleanup_uses_native_safe_retirement(monkeypatch) -> None:
    from services.downloads.manager import _cleanup_worker

    worker = object()
    retired = []
    monkeypatch.setattr(
        "ui.utils.thread_lifetime.retire_qthread", retired.append
    )

    _cleanup_worker(worker)

    assert retired == [worker]


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
