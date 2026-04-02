"""Tests for the Downloads system: models, store, and manager."""
import os

import pytest

from models.download_models import (
    DownloadRecord,
    DownloadStatus,
    SourceKind,
    TargetKind,
    UseStatus,
)
from services.downloads_manager import DownloadsManager, _safe_filename
from services.downloads_store import DownloadsStore
from workers.use_worker import UseWorker


class TestDownloadRecord:
    """Tests for downloads."""
    def test_default_values(self):
        """Checks that defaulting values."""
        r = DownloadRecord()
        assert r.id == ''
        assert r.download_status == DownloadStatus.QUEUED
        assert r.use_status == UseStatus.NOT_STARTED
        assert r.progress == 0
        assert r.file_exists is False
        assert r.metadata == {}

    def test_to_dict_round_trip(self):
        """Checks that toing  to dict round trip."""
        r = DownloadRecord(id='abc', display_name='Test Mod', source_kind=SourceKind.GAMEBANANA)
        d = r.to_dict()
        assert d['id'] == 'abc'
        assert d['display_name'] == 'Test Mod'
        assert d['source_kind'] == 'gamebanana'
        r2 = DownloadRecord.from_dict(d)
        assert r2.id == r.id
        assert r2.display_name == r.display_name
        assert r2.source_kind == r.source_kind

    def test_from_dict_ignores_unknown_keys(self):
        """Checks that froming  from dict ignores unknown keys."""
        d = {'id': 'x', 'unknown_field': 42, 'display_name': 'M'}
        r = DownloadRecord.from_dict(d)
        assert r.id == 'x'
        assert r.display_name == 'M'
        assert not hasattr(r, 'unknown_field') or r.__dict__.get('unknown_field') is None

    def test_touch_updates_timestamp(self):
        """Checks that touching updates timestamp."""
        r = DownloadRecord(id='t')
        old = r.updated_at
        r.touch()
        assert r.updated_at >= old

    def test_is_active_downloading(self):
        """Checks that ising active downloading."""
        r = DownloadRecord(download_status=DownloadStatus.DOWNLOADING)
        assert r.is_active is True

    def test_is_active_queued(self):
        """Checks that ising active queued."""
        r = DownloadRecord(download_status=DownloadStatus.QUEUED)
        assert r.is_active is True

    def test_is_active_downloaded_not_using(self):
        """Checks that ising active downloaded not using."""
        r = DownloadRecord(download_status=DownloadStatus.DOWNLOADED, use_status=UseStatus.READY)
        assert r.is_active is False

    def test_is_active_using(self):
        """Checks that ising active using."""
        r = DownloadRecord(download_status=DownloadStatus.DOWNLOADED, use_status=UseStatus.USING)
        assert r.is_active is True

    def test_needs_attention_overwrite(self):
        """Checks that needsing attention overwrite."""
        r = DownloadRecord(use_status=UseStatus.OVERWRITE_PENDING)
        assert r.needs_attention is True

    def test_needs_attention_manual(self):
        """Checks that needsing attention manual."""
        r = DownloadRecord(use_status=UseStatus.NEEDS_MANUAL)
        assert r.needs_attention is True

    def test_needs_attention_ready(self):
        """Checks that needsing attention ready."""
        r = DownloadRecord(use_status=UseStatus.READY)
        assert r.needs_attention is False

    def test_effective_status_downloading(self):
        """Checks that effectiveing status downloading."""
        r = DownloadRecord(download_status=DownloadStatus.DOWNLOADING)
        assert r.effective_status_key == 'downloading'

    def test_effective_status_ready(self):
        """Checks that effectiveing status ready."""
        r = DownloadRecord(download_status=DownloadStatus.DOWNLOADED, file_exists=True)
        assert r.effective_status_key == 'ready'

    def test_effective_status_failed(self):
        """Checks that effectiveing status failed."""
        r = DownloadRecord(download_status=DownloadStatus.FAILED, file_exists=False)
        assert r.effective_status_key == 'failed'

    def test_effective_status_cancelled(self):
        """Checks that effectiveing status cancelled."""
        r = DownloadRecord(download_status=DownloadStatus.CANCELLED)
        assert r.effective_status_key == 'cancelled'

    def test_effective_status_installing(self):
        """Checks that effectiveing status installing."""
        r = DownloadRecord(download_status=DownloadStatus.DOWNLOADED, use_status=UseStatus.USING)
        assert r.effective_status_key == 'installing'

    def test_effective_status_overwrite_pending(self):
        """Checks that effectiveing status overwrite pending."""
        r = DownloadRecord(download_status=DownloadStatus.DOWNLOADED, use_status=UseStatus.OVERWRITE_PENDING)
        assert r.effective_status_key == 'overwrite_pending'

    def test_effective_status_needs_manual(self):
        """Checks that effectiveing status needs manual."""
        r = DownloadRecord(download_status=DownloadStatus.DOWNLOADED, use_status=UseStatus.NEEDS_MANUAL)
        assert r.effective_status_key == 'needs_manual'

    def test_effective_status_downloaded_no_file(self):
        """Checks that effectiveing status downloaded no file."""
        r = DownloadRecord(download_status=DownloadStatus.DOWNLOADED, file_exists=False)
        assert r.effective_status_key == 'failed'


class TestDownloadsStore:
    """Tests for downloads."""
    @pytest.fixture(autouse=True)
    def _setup_store(self, tmp_path):
        self.base_dir = str(tmp_path)
        self.store = DownloadsStore(self.base_dir)

    def test_dirs_created(self):
        """Checks that dirsing created."""
        assert os.path.isdir(self.store.downloads_dir)

    def test_add_and_find(self):
        """Checks that adding and find."""
        r = DownloadRecord(id='r1', display_name='Mod A')
        self.store.add(r)
        found = self.store.find('r1')
        assert found is not None
        assert found.display_name == 'Mod A'

    def test_remove(self):
        """Checks that removing works."""
        r = DownloadRecord(id='r2', display_name='Mod B')
        self.store.add(r)
        self.store.remove('r2')
        assert self.store.find('r2') is None

    def test_save_and_load(self):
        """Checks that saving and load."""
        r = DownloadRecord(id='r3', display_name='Mod C', source_kind=SourceKind.GAMEBANANA)
        self.store.add(r)
        store2 = DownloadsStore(self.base_dir)
        store2.load()
        found = store2.find('r3')
        assert found is not None
        assert found.display_name == 'Mod C'
        assert found.source_kind == SourceKind.GAMEBANANA

    def test_find_by_canonical_key(self):
        """Checks that finding  by canonical key."""
        r = DownloadRecord(id='r4', canonical_key='gb_mod_123', download_status=DownloadStatus.DOWNLOADED)
        self.store.add(r)
        assert self.store.find_by_canonical_key('gb_mod_123') is not None
        assert self.store.find_by_canonical_key('gb_mod_999') is None

    def test_find_by_canonical_key_skips_failed(self):
        """Checks that finding  by canonical key skips failed."""
        r = DownloadRecord(id='r5', canonical_key='gb_mod_456', download_status=DownloadStatus.FAILED)
        self.store.add(r)
        assert self.store.find_by_canonical_key('gb_mod_456') is None

    def test_startup_recovery_marks_downloading_as_failed(self):
        """Checks that startuping recovery marks downloading as failed."""
        r = DownloadRecord(id='r6', download_status=DownloadStatus.DOWNLOADING)
        self.store.add(r)
        self.store.startup_recovery()
        found = self.store.find('r6')
        assert found.download_status == DownloadStatus.FAILED

    def test_startup_recovery_marks_using_as_failed(self):
        """Checks that startuping recovery marks using as failed."""
        r = DownloadRecord(id='r7', download_status=DownloadStatus.DOWNLOADED, use_status=UseStatus.USING)
        self.store.add(r)
        self.store.startup_recovery()
        found = self.store.find('r7')
        assert found.use_status == UseStatus.FAILED

    def test_startup_recovery_detects_missing_file(self):
        """Checks that startuping recovery detects missing file."""
        r = DownloadRecord(id='r8', download_status=DownloadStatus.DOWNLOADED, file_path='/nonexistent/file.zip', file_exists=True)
        self.store.add(r)
        self.store.startup_recovery()
        found = self.store.find('r8')
        assert found.file_exists is False

    def test_delete_file_for_record(self):
        """Checks that deleteing file for record."""
        fp = os.path.join(self.store.downloads_dir, 'test.zip')
        with open(fp, 'w') as f:
            f.write('data')
        r = DownloadRecord(id='r9', file_path=fp, file_exists=True)
        self.store.add(r)
        self.store.delete_file_for_record(r)
        assert not os.path.exists(fp)
        assert r.file_exists is False
        assert r.file_path is None

    def test_delete_file_for_record_removes_record_prefixed_file_when_path_missing(self):
        """Checks that deleting a record also removes orphaned prefixed downloads."""
        fp = os.path.join(self.store.downloads_dir, 'rec123__orphan.zip')
        with open(fp, 'w', encoding='utf-8') as f:
            f.write('data')
        r = DownloadRecord(id='rec123', file_path=None, file_exists=True)
        self.store.add(r)

        self.store.delete_file_for_record(r)

        assert not os.path.exists(fp)
        assert r.file_exists is False
        assert r.file_path is None

    def test_corrupt_history_backup(self):
        """Checks that corrupting history backup."""
        history_path = os.path.join(self.base_dir, 'downloads', 'downloads_history.json')
        os.makedirs(os.path.dirname(history_path), exist_ok=True)
        with open(history_path, 'w') as f:
            f.write('{invalid json')
        self.store.load()
        assert self.store.records == []
        assert os.path.exists(history_path + '.bak')

    def test_update_persists(self):
        """Checks that updating persists."""
        r = DownloadRecord(id='r10', display_name='Before')
        self.store.add(r)
        r.display_name = 'After'
        self.store.update(r)
        store2 = DownloadsStore(self.base_dir)
        store2.load()
        assert store2.find('r10').display_name == 'After'


def test_use_worker_build_gb_metadata_includes_file_name(tmp_path):
    """Checks that use worker build gb metadata includes file name."""
    worker = UseWorker(
        record_id='r1',
        file_path=os.path.join(tmp_path, 'archive.zip'),
        target_kind=TargetKind.MOD,
        mods_dir=str(tmp_path),
        metadata={
            'gb_mod_id': 123,
            'item_type': 'mod',
            'file_name': 'vase1_1_0.zip',
            'homepage': 'https://gamebanana.com/mods/123',
            'icon': 'https://example.com/icon.jpg',
            'tags': [],
            'category': 'Game Files',
            'game': 'deltarune',
        },
    )

    assert worker._build_gb_metadata()['file_name'] == 'vase1_1_0.zip'


class TestSafeFilename:
    """Tests for downloads."""
    def test_basic(self):
        """Checks that basicing works."""
        assert _safe_filename('My Mod v1.0') == 'My Mod v1.0'

    def test_special_chars(self):
        """Checks that specialing chars."""
        result = _safe_filename('mod<>:"/\\|?*.zip')
        assert '<' not in result
        assert '>' not in result
        assert ':' not in result

    def test_truncation(self):
        """Checks that truncationing works."""
        long_name = 'a' * 200
        assert len(_safe_filename(long_name)) <= 80

    def test_empty(self):
        """Checks that emptying works."""
        assert _safe_filename('') == 'file'


class TestDownloadsManager:
    """Tests for downloads."""
    @pytest.fixture(autouse=True)
    def _setup_manager(self, tmp_path):
        self.base_dir = str(tmp_path)
        self.settings = {'downloads_no_auto_use': True, 'downloads_delete_after_use': False}
        self.manager = DownloadsManager(self.base_dir, lambda: self.settings)
        self.manager.set_app_context(mods_dir=str(tmp_path / 'mods'))
        os.makedirs(str(tmp_path / 'mods'), exist_ok=True)
        self.manager.startup()

        def _mock_start_download(record):
            record.download_status = DownloadStatus.DOWNLOADING
            self.manager.store.update(record)
            self.manager.record_updated.emit(record)

        self._orig_start = self.manager._start_download
        self.manager._start_download = _mock_start_download

    def test_enqueue_creates_record(self):
        """Checks that enqueueing creates record."""
        record_id, is_dup = self.manager.enqueue(
            display_name='Test Mod',
            source_url='https://example.com/mod.zip',
        )
        assert not is_dup
        assert len(record_id) == 12
        assert len(self.manager.records) == 1
        assert self.manager.records[0].display_name == 'Test Mod'

    def test_enqueue_duplicate_detection(self):
        """Checks that enqueueing duplicate detection."""
        rid1, dup1 = self.manager.enqueue(
            display_name='Mod A',
            source_url='https://example.com/a.zip',
            canonical_key='gb_mod_100',
        )
        rid2, dup2 = self.manager.enqueue(
            display_name='Mod A again',
            source_url='https://example.com/a2.zip',
            canonical_key='gb_mod_100',
        )
        assert not dup1
        assert dup2
        assert rid1 == rid2
        assert len(self.manager.records) == 1

    def test_enqueue_plugin_replaces_existing_non_active_duplicate(self, tmp_path):
        """Checks that enqueueing plugin replaces existing non active duplicate."""
        plugin_file = tmp_path / 'plugin_old.zip'
        plugin_file.write_text('old plugin data')
        existing = DownloadRecord(
            id='pluginold01',
            display_name='Plugin A',
            source_kind=SourceKind.EXTERNAL_URL,
            target_kind=TargetKind.PLUGIN,
            canonical_key='plugin:sample:1.0.0',
            download_status=DownloadStatus.DOWNLOADED,
            use_status=UseStatus.READY,
            file_path=str(plugin_file),
            file_exists=True,
        )
        self.manager.store.add(existing)

        record_id, is_dup = self.manager.enqueue(
            display_name='Plugin A',
            source_url='https://example.com/plugin.zip',
            target_kind=TargetKind.PLUGIN,
            canonical_key='plugin:sample:1.0.0',
            metadata={'plugin_id': 'sample'},
        )

        assert not is_dup
        assert record_id != 'pluginold01'
        assert self.manager.store.find('pluginold01') is None
        assert not plugin_file.exists()

    def test_action_cancel_download(self):
        """Checks that actioning cancel download."""
        rid, _ = self.manager.enqueue(
            display_name='Cancel Me',
            source_url='https://example.com/cancel.zip',
        )
        self.manager.action_cancel_download(rid)
        record = self.manager.store.find(rid)
        assert record.download_status == DownloadStatus.CANCELLED

    def test_action_delete(self):
        """Checks that actioning delete."""
        rid, _ = self.manager.enqueue(
            display_name='Delete Me',
            source_url='https://example.com/delete.zip',
        )
        self.manager.action_delete(rid)
        assert self.manager.store.find(rid) is None

    def test_action_retry_resets_state(self):
        """Checks that actioning retry resets state."""
        rid, _ = self.manager.enqueue(
            display_name='Retry Me',
            source_url='https://example.com/retry.zip',
        )
        self.manager.action_cancel_download(rid)
        record = self.manager.store.find(rid)
        assert record.download_status == DownloadStatus.CANCELLED
        self.manager.action_retry(rid)
        record = self.manager.store.find(rid)
        assert record.download_status in (DownloadStatus.QUEUED, DownloadStatus.DOWNLOADING)
        assert record.progress == 0

    def test_clear_downloads(self):
        """Checks that clearing downloads."""
        r = DownloadRecord(
            id='fin1', display_name='Done',
            download_status=DownloadStatus.DOWNLOADED,
            use_status=UseStatus.READY,
            file_exists=True,
        )
        self.manager.store.add(r)
        self.manager.clear_downloads()
        assert self.manager.store.find('fin1') is None

    def test_badge_emitted(self):
        """Checks that badgeing emitted."""
        badge_calls = []
        self.manager.badge_changed.connect(lambda c, a: badge_calls.append((c, a)))
        self.manager.enqueue(
            display_name='Badge Test',
            source_url='https://example.com/badge.zip',
        )
        assert len(badge_calls) >= 1

    def test_enqueue_local_file(self, tmp_path):
        """Checks that enqueueing local file."""
        src = tmp_path / 'local_mod.zip'
        src.write_text('fake zip data')
        rid, _ = self.manager.enqueue(
            display_name='Local Mod',
            source_kind=SourceKind.LOCAL_FILE,
            source_file_path=str(src),
        )
        record = self.manager.store.find(rid)
        assert record is not None
        assert record.source_kind == SourceKind.LOCAL_FILE

    def test_enqueue_no_url_no_file_fails(self):
        """Checks that enqueueing no url no file fails."""
        rid, _ = self.manager.enqueue(display_name='No Source')
        record = self.manager.store.find(rid)
        assert record.download_status in (DownloadStatus.DOWNLOADING, DownloadStatus.FAILED)

    def test_set_app_context(self, tmp_path):
        """Checks that setting app context."""
        manager = DownloadsManager(str(tmp_path), lambda: {})
        assert manager._mods_dir is None
        manager.set_app_context(mods_dir='/some/path')
        assert manager._mods_dir == '/some/path'
