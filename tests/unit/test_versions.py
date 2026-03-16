"""Tests for the Versions Manager system: models, store, utils, workers."""
import json
import os
import zipfile

from models.version_models import VersionRecord
from services.versions_store import VersionsStore
from utils.version_utils import (
    get_base_game_folder, safe_archive_name, unique_archive_path,
)


class TestVersionRecord:

    def test_default_values(self):
        r = VersionRecord()
        assert r.archive_path == ''
        assert r.game == ''
        assert r.archive_exists is True
        assert r.size_bytes == 0
        assert r.file_count == 0
        assert r.manifest_version == 1
        assert r.imported is False

    def test_to_dict_round_trip(self):
        r = VersionRecord(archive_path='/tmp/test.zip', game='deltarune', size_bytes=1024, file_count=10)
        d = r.to_dict()
        assert d['archive_path'] == '/tmp/test.zip'
        assert d['game'] == 'deltarune'
        r2 = VersionRecord.from_dict(d)
        assert r2.archive_path == r.archive_path
        assert r2.game == r.game
        assert r2.size_bytes == r.size_bytes

    def test_from_dict_ignores_unknown_keys(self):
        d = {'archive_path': '/x.zip', 'unknown_field': 42, 'game': 'undertale'}
        r = VersionRecord.from_dict(d)
        assert r.archive_path == '/x.zip'
        assert r.game == 'undertale'

    def test_touch_updates_timestamp(self):
        r = VersionRecord()
        old = r.updated_at
        r.touch()
        assert r.updated_at >= old

    def test_display_name(self):
        r = VersionRecord(archive_path='/path/to/my_save.zip')
        assert r.display_name == 'my_save'

    def test_display_name_empty(self):
        r = VersionRecord(archive_path='')
        assert r.display_name == ''

    def test_effective_status_key(self):
        r = VersionRecord(archive_exists=True)
        assert r.effective_status_key == 'ready'
        r.archive_exists = False
        assert r.effective_status_key == 'missing'


class TestVersionsStore:

    def test_load_empty(self, temp_dir):
        store = VersionsStore(temp_dir)
        records = store.load()
        assert records == []

    def test_add_and_find(self, temp_dir):
        store = VersionsStore(temp_dir)
        store.load()
        r = VersionRecord(archive_path='/tmp/v1.zip', game='deltarune')
        store.add(r)
        found = store.find('/tmp/v1.zip')
        assert found is not None
        assert found.game == 'deltarune'

    def test_remove(self, temp_dir):
        store = VersionsStore(temp_dir)
        store.load()
        r = VersionRecord(archive_path='/tmp/v1.zip', game='deltarune')
        store.add(r)
        store.remove('/tmp/v1.zip')
        assert store.find('/tmp/v1.zip') is None

    def test_records_for_game(self, temp_dir):
        store = VersionsStore(temp_dir)
        store.load()
        store.add(VersionRecord(archive_path='/a.zip', game='deltarune'))
        store.add(VersionRecord(archive_path='/b.zip', game='undertale'))
        store.add(VersionRecord(archive_path='/c.zip', game='deltarune'))
        assert len(store.records_for_game('deltarune')) == 2
        assert len(store.records_for_game('undertale')) == 1

    def test_persistence(self, temp_dir):
        store1 = VersionsStore(temp_dir)
        store1.load()
        store1.add(VersionRecord(archive_path='/tmp/persist.zip', game='deltarune'))
        store2 = VersionsStore(temp_dir)
        store2.load()
        assert store2.find('/tmp/persist.zip') is not None

    def test_atomic_write_creates_file(self, temp_dir):
        store = VersionsStore(temp_dir)
        store.load()
        store.add(VersionRecord(archive_path='/tmp/test.zip', game='deltarune'))
        data_path = os.path.join(temp_dir, 'versions', 'versions_data.json')
        assert os.path.exists(data_path)
        with open(data_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        assert len(data) == 1

    def test_corrupt_data_recovery(self, temp_dir):
        versions_dir = os.path.join(temp_dir, 'versions')
        os.makedirs(versions_dir, exist_ok=True)
        data_path = os.path.join(versions_dir, 'versions_data.json')
        with open(data_path, 'w') as f:
            f.write('{invalid json')
        store = VersionsStore(temp_dir)
        records = store.load()
        assert records == []
        assert os.path.exists(data_path + '.bak')

    def test_startup_recovery_marks_missing(self, temp_dir):
        store = VersionsStore(temp_dir)
        store.load()
        r = VersionRecord(archive_path='/nonexistent/path.zip', game='deltarune', archive_exists=True)
        store.add(r)
        store2 = VersionsStore(temp_dir)
        store2.load()
        store2.startup_recovery()
        found = store2.find('/nonexistent/path.zip')
        assert found is not None
        assert found.archive_exists is False

    def test_startup_recovery_removes_stale(self, temp_dir):
        store = VersionsStore(temp_dir)
        store.load()
        r = VersionRecord(archive_path='/nonexistent/stale.zip', game='deltarune', archive_exists=False)
        store.add(r)
        store2 = VersionsStore(temp_dir)
        store2.load()
        store2.startup_recovery()
        assert store2.find('/nonexistent/stale.zip') is None

    def test_startup_recovery_marks_existing(self, temp_dir):
        archive_path = os.path.join(temp_dir, 'versions', 'test.zip')
        store = VersionsStore(temp_dir)
        store.load()
        with open(archive_path, 'wb') as f:
            f.write(b'fake zip')
        r = VersionRecord(archive_path=archive_path, game='deltarune', archive_exists=False)
        store.add(r)
        store2 = VersionsStore(temp_dir)
        store2.load()
        store2.startup_recovery()
        found = store2.find(archive_path)
        assert found is not None
        assert found.archive_exists is True

    def test_versions_dir_property(self, temp_dir):
        store = VersionsStore(temp_dir)
        assert store.versions_dir == os.path.join(temp_dir, 'versions')


class TestVersionUtils:

    def test_safe_archive_name(self):
        assert safe_archive_name('My Save v1.0') == 'My Save v1.0.zip'

    def test_safe_archive_name_special_chars(self):
        result = safe_archive_name('a/b\\c:d*e?f')
        assert '/' not in result.replace('.zip', '')
        assert '\\' not in result.replace('.zip', '')
        assert result.endswith('.zip')

    def test_safe_archive_name_trims_leading_and_trailing_dots_spaces(self):
        assert safe_archive_name('  .. My Save .  ') == 'My Save.zip'

    def test_safe_archive_name_falls_back_when_trimmed_name_is_empty(self):
        assert safe_archive_name('  ...   ') == 'version.zip'

    def test_safe_archive_name_empty(self):
        assert safe_archive_name('') == 'version.zip'

    def test_unique_archive_path_no_conflict(self, temp_dir):
        path = unique_archive_path(temp_dir, 'test')
        assert path.endswith('.zip')
        assert 'test' in os.path.basename(path)

    def test_unique_archive_path_with_conflict(self, temp_dir):
        first = unique_archive_path(temp_dir, 'dup')
        with open(first, 'w') as f:
            f.write('')
        second = unique_archive_path(temp_dir, 'dup')
        assert second != first
        assert '_1' in os.path.basename(second)

    def test_get_base_game_folder_nonexistent(self):
        assert get_base_game_folder('/nonexistent/path') is None

    def test_get_base_game_folder_empty(self):
        assert get_base_game_folder('') is None

    def test_get_base_game_folder_valid_dir(self, temp_dir):
        result = get_base_game_folder(temp_dir)
        assert result == temp_dir


class TestCreateVersionWorker:

    def test_create_archive(self, temp_dir, qapp):
        game_dir = os.path.join(temp_dir, 'game')
        os.makedirs(game_dir)
        with open(os.path.join(game_dir, 'data.win'), 'w') as f:
            f.write('game data')
        with open(os.path.join(game_dir, 'game.exe'), 'w') as f:
            f.write('exe content')
        archive_path = os.path.join(temp_dir, 'test_version.zip')
        protected = {'game.exe'}

        from workers.version_archive_worker import CreateVersionWorker
        results = []
        worker = CreateVersionWorker(archive_path, game_dir, protected)
        worker.finished.connect(lambda *args: results.append(args))
        worker.run()

        assert len(results) == 1
        success, error, size, count = results[0]
        assert success is True
        assert error == ''
        assert count == 1  # only data.win, not game.exe
        assert os.path.isfile(archive_path)
        with zipfile.ZipFile(archive_path, 'r') as zf:
            names = zf.namelist()
            assert 'data.win' in names
            assert 'game.exe' not in names

    def test_create_archive_empty_dir(self, temp_dir, qapp):
        archive_path = os.path.join(temp_dir, 'empty.zip')
        empty_dir = os.path.join(temp_dir, 'empty_game')
        os.makedirs(empty_dir)
        from workers.version_archive_worker import CreateVersionWorker
        results = []
        worker = CreateVersionWorker(archive_path, empty_dir, set())
        worker.finished.connect(lambda *args: results.append(args))
        worker.run()
        assert len(results) == 1
        success, error, size, count = results[0]
        assert success is True
        assert count == 0


class TestApplyVersionWorker:

    def test_apply_version(self, temp_dir, qapp):
        game_dir = os.path.join(temp_dir, 'game')
        os.makedirs(game_dir)
        archive_path = os.path.join(temp_dir, 'version.zip')
        with zipfile.ZipFile(archive_path, 'w') as zf:
            zf.writestr('data.win', 'restored data')
            zf.writestr('subdir/extra.txt', 'extra file')

        from workers.version_archive_worker import ApplyVersionWorker
        results = []
        worker = ApplyVersionWorker(archive_path, game_dir, set(), full_replace=False)
        worker.finished.connect(lambda *args: results.append(args))
        worker.run()

        assert len(results) == 1
        assert results[0][0] is True
        assert os.path.isfile(os.path.join(game_dir, 'data.win'))
        assert os.path.isfile(os.path.join(game_dir, 'subdir', 'extra.txt'))

    def test_apply_full_replace_deletes_extra(self, temp_dir, qapp):
        game_dir = os.path.join(temp_dir, 'game')
        os.makedirs(game_dir)
        with open(os.path.join(game_dir, 'old_file.txt'), 'w') as f:
            f.write('old')
        with open(os.path.join(game_dir, 'game.exe'), 'w') as f:
            f.write('exe')
        archive_path = os.path.join(temp_dir, 'version.zip')
        with zipfile.ZipFile(archive_path, 'w') as zf:
            zf.writestr('data.win', 'new data')

        from workers.version_archive_worker import ApplyVersionWorker
        results = []
        worker = ApplyVersionWorker(archive_path, game_dir, {'game.exe'}, full_replace=True)
        worker.finished.connect(lambda *args: results.append(args))
        worker.run()

        assert results[0][0] is True
        assert os.path.isfile(os.path.join(game_dir, 'data.win'))
        assert not os.path.exists(os.path.join(game_dir, 'old_file.txt'))
        assert os.path.isfile(os.path.join(game_dir, 'game.exe'))  # protected

    def test_apply_missing_archive(self, temp_dir, qapp):
        from workers.version_archive_worker import ApplyVersionWorker
        results = []
        worker = ApplyVersionWorker('/nonexistent.zip', temp_dir, set(), full_replace=False)
        worker.finished.connect(lambda *args: results.append(args))
        worker.run()
        assert results[0][0] is False


class TestExportImportWorkers:

    def test_export_and_import_round_trip(self, temp_dir, qapp):
        source_archive = os.path.join(temp_dir, 'internal.zip')
        with zipfile.ZipFile(source_archive, 'w') as zf:
            zf.writestr('data.win', 'game data')

        exported_path = os.path.join(temp_dir, 'exported.zip')
        manifest = {'manifest_version': 1, 'display_name': 'Test', 'game': 'deltarune'}

        from workers.version_archive_worker import ExportVersionWorker
        export_results = []
        ew = ExportVersionWorker(source_archive, exported_path, manifest)
        ew.finished.connect(lambda *args: export_results.append(args))
        ew.run()
        assert export_results[0][0] is True
        assert os.path.isfile(exported_path)

        with zipfile.ZipFile(exported_path, 'r') as zf:
            assert 'version_data.json' in zf.namelist()
            assert 'data.win' in zf.namelist()

        reimport_path = os.path.join(temp_dir, 'reimported.zip')
        from workers.version_archive_worker import ImportVersionWorker
        import_results = []
        iw = ImportVersionWorker(exported_path, reimport_path)
        iw.finished.connect(lambda *args: import_results.append(args))
        iw.run()
        assert import_results[0][0] is True
        assert import_results[0][2]['game'] == 'deltarune'
        assert os.path.isfile(reimport_path)
        with zipfile.ZipFile(reimport_path, 'r') as zf:
            assert 'data.win' in zf.namelist()
            assert 'version_data.json' not in zf.namelist()

    def test_import_missing_manifest(self, temp_dir, qapp):
        source = os.path.join(temp_dir, 'no_manifest.zip')
        with zipfile.ZipFile(source, 'w') as zf:
            zf.writestr('data.win', 'data')

        dest = os.path.join(temp_dir, 'imported.zip')
        from workers.version_archive_worker import ImportVersionWorker
        results = []
        iw = ImportVersionWorker(source, dest)
        iw.finished.connect(lambda *args: results.append(args))
        iw.run()
        assert results[0][0] is False
        assert 'manifest' in results[0][1].lower()
