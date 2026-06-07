"""Additional tests for downloads manager edge cases and important functions."""
import os
from unittest.mock import Mock, patch

from models.download_models import (
    DownloadRecord,
    DownloadStatus,
    UseStatus,
)
from services.downloads_manager import DownloadsManager, _safe_filename
from services.localization_service import tr


class TestDownloadsManagerEdgeCases:
    """Tests for downloads manager edge cases."""

    def test_safe_filename_various_inputs(self):
        """Checks that sanitizing filename various inputs."""
        assert _safe_filename("mod.zip") == "mod.zip"

        assert _safe_filename("mod-v1.2.3.zip") == "mod-v1.2.3.zip"

        result = _safe_filename("mod<>|&;.zip")
        assert result.startswith("mod")
        assert result.endswith(".zip")
        assert not any(c in result for c in "<>|&;")
        assert "." in result

        long_name = "a" * 100 + ".zip"
        result = _safe_filename(long_name)
        assert len(result) <= 80

        assert _safe_filename("") == "file"

        assert _safe_filename("my mod file.zip") == "my mod file.zip"

        assert _safe_filename("мод.zip") == "мод.zip"

    def test_enqueue_with_canonical_key_existing(self, temp_dir):
        """Checks that enqueuing with canonical key existing."""
        settings_getter = Mock(return_value={'downloads_no_auto_use': False})
        manager = DownloadsManager(temp_dir, settings_getter)
        manager.startup()

        existing = DownloadRecord(
            id='existing123',
            display_name='Existing Mod',
            canonical_key='test_key'
        )
        manager._store.add(existing)

        record_id, is_duplicate = manager.enqueue(
            display_name='New Mod',
            canonical_key='test_key'
        )

        assert is_duplicate is True
        assert record_id == 'existing123'

        manager.deleteLater()

    def test_enqueue_file_extension_detection(self, temp_dir):
        """Checks that enqueuing file extension detection."""
        settings_getter = Mock(return_value={'downloads_no_auto_use': False})
        manager = DownloadsManager(temp_dir, settings_getter)
        manager.startup()

        with patch.object(manager, '_start_download') as mock_start:
            _record_id, _ = manager.enqueue(
                display_name='Test Mod',
                source_url='https://example.com/mod.zip?version=1.0'
            )
            mock_start.assert_called_once()
            record = mock_start.call_args[0][0]
            assert 'mod.zip' in record.source_url

        manager.deleteLater()

    def test_enqueue_settings_integration(self, temp_dir):
        """Checks that enqueuing settings integration."""
        settings_getter = Mock(return_value={
            'downloads_no_auto_use': True,
            'downloads_delete_after_use': True
        })
        manager = DownloadsManager(temp_dir, settings_getter)
        manager.startup()

        with patch.object(manager, '_start_download'):
            record_id, _ = manager.enqueue(display_name='Test Mod')
            record = manager._store.find(record_id)
            assert record.auto_use is False
            assert record.delete_after_use is True

        manager.deleteLater()

    def test_cancel_download(self, temp_dir):
        """Checks that canceling download."""
        settings_getter = Mock(return_value={})
        manager = DownloadsManager(temp_dir, settings_getter)
        manager.startup()

        record = DownloadRecord(
            id='test123',
            display_name='Test Mod',
            download_status=DownloadStatus.DOWNLOADING
        )
        manager._store.add(record)

        mock_worker = Mock()
        manager._workers['test123'] = mock_worker

        manager.action_cancel_download('test123')

        mock_worker.cancel.assert_called_once()
        assert 'test123' not in manager._workers

        manager.deleteLater()

    def test_cancel_completed_download(self, temp_dir):
        """Checks that canceling completed download."""
        settings_getter = Mock(return_value={})
        manager = DownloadsManager(temp_dir, settings_getter)
        manager.startup()

        record = DownloadRecord(
            id='test123',
            display_name='Test Mod',
            download_status=DownloadStatus.DOWNLOADED,
            file_exists=True
        )
        manager._store.add(record)

        manager.action_delete('test123')

        assert manager._store.find('test123') is None

        manager.deleteLater()

    def test_retry_download(self, temp_dir):
        """Checks that retrying download."""
        settings_getter = Mock(return_value={})
        manager = DownloadsManager(temp_dir, settings_getter)
        manager.startup()

        record = DownloadRecord(
            id='test123',
            display_name='Test Mod',
            download_status=DownloadStatus.FAILED,
            source_url='https://example.com/mod.zip'
        )
        manager._store.add(record)

        with patch.object(manager, '_start_download') as mock_start:
            manager.action_retry('test123')

            updated_record = manager._store.find('test123')
            assert updated_record.download_status == DownloadStatus.QUEUED
            mock_start.assert_called_once()

        manager.deleteLater()

    def test_use_download_file_not_found(self, temp_dir):
        """Checks that using download file not found."""
        settings_getter = Mock(return_value={})
        manager = DownloadsManager(temp_dir, settings_getter)
        manager.set_app_context(mods_dir=os.path.join(temp_dir, 'mods'))
        manager.startup()

        record = DownloadRecord(
            id='test123',
            display_name='Test Mod',
            download_status=DownloadStatus.DOWNLOADED,
            file_exists=False
        )
        manager._store.add(record)

        with patch('services.localization_service.tr') as mock_tr:
            mock_tr.side_effect = lambda key, *args: key
            manager.action_install('test123')

            record = manager._store.find('test123')
            assert record.use_status == UseStatus.NOT_STARTED

        manager.deleteLater()

    def test_clear_completed(self, temp_dir):
        """Checks that clearing completed."""
        settings_getter = Mock(return_value={})
        manager = DownloadsManager(temp_dir, settings_getter)
        manager.startup()

        records = [
            DownloadRecord(id='comp1', display_name='Completed 1', download_status=DownloadStatus.DOWNLOADED),
            DownloadRecord(id='comp2', display_name='Completed 2', download_status=DownloadStatus.DOWNLOADED),
            DownloadRecord(id='fail1', display_name='Failed', download_status=DownloadStatus.FAILED),
            DownloadRecord(id='down1', display_name='Downloading', download_status=DownloadStatus.DOWNLOADING),
        ]
        for record in records:
            manager._store.add(record)

        manager.clear_downloads()
        assert manager._store.find('comp1') is None
        assert manager._store.find('comp2') is None
        assert manager._store.find('fail1') is None
        assert manager._store.find('down1') is not None

        manager.deleteLater()

    def test_clear_all(self, temp_dir):
        """Checks that clearing all."""
        settings_getter = Mock(return_value={})
        manager = DownloadsManager(temp_dir, settings_getter)
        manager.startup()

        records = [
            DownloadRecord(id='rec1', display_name='Record 1'),
            DownloadRecord(id='rec2', display_name='Record 2'),
        ]
        for record in records:
            manager._store.add(record)

        manager.clear_downloads()
        assert len(manager._store.records) == 2

        manager.deleteLater()

    def test_emit_badge_counts(self, temp_dir):
        """Checks that emitting badge counts."""
        settings_getter = Mock(return_value={})
        manager = DownloadsManager(temp_dir, settings_getter)
        manager.startup()

        count = sum(1 for r in manager._store.records if r.effective_status_key in ('downloading', 'ready', 'installing', 'needs_manual'))
        attention = any(r.needs_attention for r in manager._store.records)
        assert count == 0
        assert not attention

        active_records = [
            DownloadRecord(id='down1', display_name='Downloading', download_status=DownloadStatus.DOWNLOADING),
            DownloadRecord(id='ready1', display_name='Ready', download_status=DownloadStatus.DOWNLOADED, file_exists=True),
        ]
        for record in active_records:
            manager._store.add(record)

        count = sum(1 for r in manager._store.records if r.effective_status_key in ('downloading', 'ready', 'installing', 'needs_manual'))
        attention = any(r.needs_attention for r in manager._store.records)
        assert count == 2
        assert not attention

        manager.deleteLater()

    def test_startup_recovery(self, temp_dir):
        """Checks that startup recovery."""
        settings_getter = Mock(return_value={})
        manager = DownloadsManager(temp_dir, settings_getter)

        records = [
            DownloadRecord(id='down1', display_name='Downloading', download_status=DownloadStatus.DOWNLOADING),
            DownloadRecord(id='using1', display_name='Using', use_status=UseStatus.USING),
            DownloadRecord(id='comp1', display_name='Completed', download_status=DownloadStatus.DOWNLOADED),
        ]

        for record in records:
            manager._store.add(record)

        manager.startup()

        recovered_down = manager._store.find('down1')
        recovered_using = manager._store.find('using1')

        assert recovered_down.download_status == DownloadStatus.FAILED
        assert recovered_using.use_status == UseStatus.FAILED

        manager.deleteLater()

    def test_enqueue_with_feedback_validation(self, temp_dir):
        """Checks that enqueuing with feedback validation."""
        settings_getter = Mock(return_value={})
        manager = DownloadsManager(temp_dir, settings_getter)
        manager.startup()

        feedback_service = Mock()

        result = manager.enqueue_with_feedback(
            feedback_service,
            display_name='Test Mod'
        )
        assert result[1] is False
        feedback_service.update_status.assert_called()

        result = manager.enqueue_with_feedback(
            feedback_service,
            display_name='Test Mod',
            source_url='not-a-url'
        )
        assert result[1] is False

        manager.deleteLater()

    def test_worker_cleanup_on_finish(self, temp_dir):
        """Checks that worker cleanup on finish."""
        settings_getter = Mock(return_value={})
        manager = DownloadsManager(temp_dir, settings_getter)
        manager.startup()

        with patch('workers.download_worker.DownloadWorker') as mock_worker_class:
            mock_worker = Mock()
            mock_worker.isFinished.return_value = False
            mock_worker_class.return_value = mock_worker

            record_id, _ = manager.enqueue(
                display_name='Test Mod',
                source_url='https://example.com/mod.zip'
            )

            assert record_id in manager._workers

            manager._on_download_finished(record_id, True, '', '')

            assert record_id not in manager._workers
            mock_worker.finished.connect.assert_called_once_with(mock_worker.deleteLater)
            mock_worker.deleteLater.assert_not_called()

        manager.deleteLater()

    def test_resolve_presenter_parent_walks_up_parent_chain(self, temp_dir):
        """Checks that resolving presenter parent walks up parent chain."""
        settings_getter = Mock(return_value={})
        manager = DownloadsManager(temp_dir, settings_getter)
        presenter = Mock()

        class FakeWindow:
            def __init__(self) -> None:
                self.pizza_oven_conversion_presenter = presenter

            def parent(self):
                return None

            def parentWidget(self):  # noqa: N802
                return None

        class FakeDialog:
            def __init__(self, parent) -> None:
                self._parent = parent

            def parent(self):
                return self._parent

            def parentWidget(self):  # noqa: N802
                return self._parent

        host = FakeWindow()
        dialog = FakeDialog(host)

        resolved_parent, resolved_presenter = manager._resolve_presenter_parent(dialog)

        assert resolved_parent is host
        assert resolved_presenter is presenter
        manager.deleteLater()

    def test_resolve_presenter_parent_returns_original_parent_when_presenter_missing(
        self, temp_dir
    ):
        """Checks that resolving presenter parent returns original parent when presenter missing."""
        settings_getter = Mock(return_value={})
        manager = DownloadsManager(temp_dir, settings_getter)

        class FakeWindow:
            def __init__(self) -> None:
                self.other_attribute = Mock()

            def parent(self):
                return None

            def parentWidget(self):  # noqa: N802
                return None

        class FakeDialog:
            def __init__(self, parent) -> None:
                self._parent = parent

            def parent(self):
                return self._parent

            def parentWidget(self):  # noqa: N802
                return self._parent

        host = FakeWindow()
        dialog = FakeDialog(host)

        resolved_parent, resolved_presenter = manager._resolve_presenter_parent(dialog)

        assert resolved_parent is dialog
        assert resolved_presenter is None
        manager.deleteLater()

    def test_resolve_presenter_parent_stops_on_cyclic_parent_chain(self, temp_dir):
        """Checks that resolving presenter parent stops on cyclic parent chain."""
        settings_getter = Mock(return_value={})
        manager = DownloadsManager(temp_dir, settings_getter)

        class FakeA:
            def __init__(self) -> None:
                self._parent = None

            def parent(self):
                return self._parent

            def parentWidget(self):  # noqa: N802
                return self._parent

        class FakeB:
            def __init__(self) -> None:
                self._parent = None

            def parent(self):
                return self._parent

            def parentWidget(self):  # noqa: N802
                return self._parent

        a = FakeA()
        b = FakeB()
        a._parent = b
        b._parent = a

        resolved_parent, resolved_presenter = manager._resolve_presenter_parent(a)

        assert resolved_parent is a
        assert resolved_presenter is None
        manager.deleteLater()

    def test_manual_install_dialog_records_localized_filesystem_error(self, temp_dir):
        """Checks that manual install dialog stores localized filesystem errors."""
        manager = DownloadsManager(temp_dir, Mock(return_value={}))
        manager.startup()

        archive_path = os.path.join(temp_dir, "broken.zip")
        with open(archive_path, "wb") as handle:
            handle.write(b"zip")

        record = DownloadRecord(
            id="manual1",
            display_name="Broken Mod",
            download_status=DownloadStatus.DOWNLOADED,
            use_status=UseStatus.NEEDS_MANUAL,
            file_exists=True,
            file_path=archive_path,
        )
        manager._store.add(record)

        with patch(
            "utils.archive_utils.extract_archive",
            side_effect=PermissionError(13, "Permission denied", archive_path),
        ):
            manager._open_manual_install_dialog(record)

        updated = manager._store.find("manual1")
        assert updated is not None
        assert updated.use_status == UseStatus.NEEDS_MANUAL
        assert updated.error_message == tr(
            "errors.permission_denied", path=archive_path
        )

        manager.deleteLater()
