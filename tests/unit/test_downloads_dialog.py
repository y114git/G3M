"""Unit tests for downloads dialog safety."""

from unittest.mock import Mock

from PyQt6.QtWidgets import QApplication

from models.download_models import DownloadRecord, DownloadStatus, UseStatus
from ui.dialogs.downloads_dialog import _RecordWidget


def test_download_record_delete_confirmation_failure_does_not_delete(monkeypatch):
    """Checks broken delete confirmation keeps the download record."""
    app = QApplication.instance() or QApplication([])
    manager = Mock()
    record = DownloadRecord(
        id="download-1",
        display_name="Example Mod",
        download_status=DownloadStatus.DOWNLOADED,
        use_status=UseStatus.READY,
    )
    widget = _RecordWidget(record, manager, app_state=Mock())

    def failing_question(*_args, **_kwargs):
        raise RuntimeError("dialog deleted")

    monkeypatch.setattr(
        "ui.dialogs.downloads_dialog.QMessageBox.question",
        failing_question,
    )

    widget._on_delete()

    manager.action_delete.assert_not_called()
    widget.deleteLater()
    app.processEvents()


def test_unknown_size_download_uses_busy_progress_indicator(qapp):
    record = DownloadRecord(
        id="download-2",
        display_name="Unknown size",
        download_status=DownloadStatus.DOWNLOADING,
        bytes_total=0,
    )
    widget = _RecordWidget(record, Mock(), app_state=Mock())

    assert widget._progress_bar.minimum() == 0
    assert widget._progress_bar.maximum() == 0
    widget.deleteLater()
