from unittest.mock import Mock

from models.download_models import DownloadRecord, DownloadStatus, TargetKind, UseStatus
from services.downloads.manager import DownloadsManager
from services.downloads.store import DownloadsStore


def _installed_plugin(archive):
    return DownloadRecord(
        id="plugin",
        display_name="Example Plugin",
        target_kind=TargetKind.PLUGIN,
        download_status=DownloadStatus.DOWNLOADED,
        use_status=UseStatus.READY,
        file_path=str(archive),
        file_exists=True,
        ever_installed=True,
    )


def test_installed_item_whose_archive_was_removed_stays_installed_after_a_restart(tmp_path):
    store = DownloadsStore(str(tmp_path))
    store.add(_installed_plugin(tmp_path / "gone.zip"))
    reloaded = DownloadsStore(str(tmp_path))
    reloaded.load()
    reloaded.startup_recovery()
    record = reloaded.find("plugin")
    assert not record.file_exists
    assert record.effective_status_key == "installed"


def test_downloaded_file_that_vanished_before_any_install_fails_with_a_reason(tmp_path):
    store = DownloadsStore(str(tmp_path))
    record = _installed_plugin(tmp_path / "gone.zip")
    record.ever_installed = False
    store.add(record)
    store.startup_recovery()
    assert record.effective_status_key == "failed"
    assert record.error_message
    assert record.error_code == "file_missing"


def test_reinstall_without_the_archive_downloads_it_again_and_installs(tmp_path, monkeypatch):
    manager = DownloadsManager(str(tmp_path), lambda: {})
    record = _installed_plugin(tmp_path / "gone.zip")
    record.auto_use = False
    manager.store.add(record)
    download = Mock()
    monkeypatch.setattr(manager, "_start_download", download)
    manager.action_install(record.id)
    download.assert_called_once_with(record)
    assert record.download_status == DownloadStatus.QUEUED
    assert record.auto_use


def test_install_of_a_never_installed_download_whose_file_vanished_fails_instead_of_doing_nothing(tmp_path):
    manager = DownloadsManager(str(tmp_path), lambda: {})
    record = _installed_plugin(tmp_path / "gone.zip")
    record.ever_installed = False
    manager.store.add(record)
    manager.action_install(record.id)
    assert record.effective_status_key == "failed"
    assert record.error_code == "file_missing"


def test_successful_plugin_install_records_that_its_archive_is_gone(tmp_path, monkeypatch):
    manager = DownloadsManager(str(tmp_path), lambda: {})
    record = _installed_plugin(tmp_path / "gone.zip")
    record.use_status = UseStatus.USING
    manager.store.add(record)
    manager._on_use_finished(record.id, True, False, "")
    assert not record.file_exists
    assert record.effective_status_key == "installed"
