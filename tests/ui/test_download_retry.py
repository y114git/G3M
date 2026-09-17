from unittest.mock import Mock

import pytest
from PyQt6.QtCore import Qt

from models.download_models import DownloadRecord, DownloadStatus, UseStatus
from services.downloads.manager import DownloadsManager
from ui.dialogs.downloads_dialog import DownloadsDialog


@pytest.mark.parametrize("archive_exists", [True, False])
def test_failed_install_retry_uses_archive_or_downloads_again(
    qtbot, app_state, tmp_path, monkeypatch, archive_exists
):
    archive = tmp_path / "mod.zip"
    if archive_exists:
        archive.write_bytes(b"archive")
    manager = DownloadsManager(str(tmp_path), lambda: {})
    record = DownloadRecord(
        id="failed-install",
        display_name="Example Mod",
        download_status=DownloadStatus.DOWNLOADED,
        use_status=UseStatus.FAILED,
        file_path=str(archive),
        file_exists=True,
        error_message="Installation failed",
        error_code="install_failed",
    )
    manager.store.add(record)
    install = Mock()
    download = Mock()
    monkeypatch.setattr(manager, "_start_use", install)
    monkeypatch.setattr(manager, "_start_download", download)
    dialog = DownloadsDialog(manager, app_state)
    qtbot.addWidget(dialog)
    dialog.show()
    widget = dialog._record_widgets[record.id]
    assert record.effective_status_key == "failed"
    assert widget._error_label.isVisible()
    assert widget._error_label.text() == record.error_message
    assert widget._buttons["retry"].isVisible()
    qtbot.mouseClick(widget._buttons["retry"], Qt.MouseButton.LeftButton)
    assert record.error_message is None
    assert record.error_code is None
    if archive_exists:
        install.assert_called_once_with(record.id)
        download.assert_not_called()
        manager._on_use_finished(record.id, True, False, "")
        assert record.effective_status_key == "installed"
        assert not widget._error_label.isVisible()
        assert widget._buttons["reinstall"].isVisible()
    else:
        download.assert_called_once_with(record)
        install.assert_not_called()
        assert record.download_status == DownloadStatus.QUEUED
        assert widget._buttons["cancel"].isVisible()
    dialog.close()
