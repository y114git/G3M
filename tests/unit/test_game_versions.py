"""Tests for the Game Versions system: models, store, utils, workers."""
import json
import os
import zipfile
from unittest.mock import Mock

from PyQt6.QtWidgets import QApplication

from models.game_version_models import GameVersionRecord
from services.game_versions.store import GameVersionsStore
from services.localization_service import tr
from utils.game_version_utils import (
    get_base_game_folder,
    safe_archive_name,
    unique_archive_path,
)


class TestGameVersionRecord:
    """Tests for game versions."""
    def test_default_values(self):
        """Checks that default values."""
        r = GameVersionRecord()
        assert r.archive_path == ''
        assert r.game == ''
        assert r.archive_exists is True
        assert r.size_bytes == 0
        assert r.file_count == 0
        assert r.manifest_version == 1
        assert r.imported is False

    def test_to_dict_round_trip(self):
        """Checks that to_dict round trip."""
        r = GameVersionRecord(archive_path='/test-data/test.zip', game='deltarune', size_bytes=1024, file_count=10)
        d = r.to_dict()
        assert d['archive_path'] == '/test-data/test.zip'
        assert d['game'] == 'deltarune'
        r2 = GameVersionRecord.from_dict(d)
        assert r2.archive_path == r.archive_path
        assert r2.game == r.game
        assert r2.size_bytes == r.size_bytes

    def test_from_dict_ignores_unknown_keys(self):
        """Checks that from_dict ignores unknown keys."""
        d = {'archive_path': '/x.zip', 'unknown_field': 42, 'game': 'undertale'}
        r = GameVersionRecord.from_dict(d)
        assert r.archive_path == '/x.zip'
        assert r.game == 'undertale'

    def test_touch_updates_timestamp(self):
        """Checks that touching updates timestamp."""
        r = GameVersionRecord()
        old = r.updated_at
        r.touch()
        assert r.updated_at >= old

    def test_display_name(self):
        """Checks that displaying name."""
        r = GameVersionRecord(archive_path='/path/to/my_save.zip')
        assert r.display_name == 'my_save'

    def test_display_name_empty(self):
        """Checks that displaying name empty."""
        r = GameVersionRecord(archive_path='')
        assert r.display_name == ''

    def test_effective_status_key(self):
        """Checks that effective status for key."""
        r = GameVersionRecord(archive_exists=True)
        assert r.effective_status_key == 'ready'
        r.archive_exists = False
        assert r.effective_status_key == 'missing'


def test_game_version_apply_confirmation_failure_does_not_apply(monkeypatch):
    """Checks broken apply confirmation keeps the archived game version unchanged."""
    from ui.dialogs.game.versions_dialog import _VersionRecordWidget

    app = QApplication.instance() or QApplication([])
    manager = Mock()
    manager.is_busy.return_value = False
    manager.is_applying.return_value = False
    record = GameVersionRecord(
        archive_path="C:/versions/game.zip",
        game="deltarune",
        archive_exists=True,
    )
    widget = _VersionRecordWidget(record, manager, app_state=Mock())
    monkeypatch.setattr(
        "ui.dialogs.game.versions_dialog.QMessageBox.question",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("dialog deleted")),
    )

    widget._on_apply()

    manager.apply_version.assert_not_called()
    widget.deleteLater()
    app.processEvents()


def test_game_version_delete_confirmation_failure_does_not_delete(monkeypatch):
    """Checks broken delete confirmation keeps the archived game version."""
    from ui.dialogs.game.versions_dialog import _VersionRecordWidget

    app = QApplication.instance() or QApplication([])
    manager = Mock()
    manager.is_busy.return_value = False
    manager.is_applying.return_value = False
    record = GameVersionRecord(
        archive_path="C:/versions/game.zip",
        game="deltarune",
        archive_exists=True,
    )
    widget = _VersionRecordWidget(record, manager, app_state=Mock())
    monkeypatch.setattr(
        "ui.dialogs.game.versions_dialog.QMessageBox.question",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("dialog deleted")),
    )

    widget._on_delete()

    manager.delete_version.assert_not_called()
    widget.deleteLater()
    app.processEvents()


class TestGameVersionsStore:
    """Tests for game versions."""
    def test_load_empty(self, temp_dir):
        """Checks that loading empty."""
        store = GameVersionsStore(temp_dir)
        records = store.load()
        assert records == []

    def test_add_and_find(self, temp_dir):
        """Checks that adding and find."""
        store = GameVersionsStore(temp_dir)
        store.load()
        r = GameVersionRecord(archive_path='/archives/v1.zip', game='deltarune')
        store.add(r)
        found = store.find('/archives/v1.zip')
        assert found is not None
        assert found.game == 'deltarune'

    def test_remove(self, temp_dir):
        """Checks that removing works."""
        store = GameVersionsStore(temp_dir)
        store.load()
        r = GameVersionRecord(archive_path='/archives/v1.zip', game='deltarune')
        store.add(r)
        store.remove('/archives/v1.zip')
        assert store.find('/archives/v1.zip') is None

    def test_records_for_game(self, temp_dir):
        """Checks that recordsing for game."""
        store = GameVersionsStore(temp_dir)
        store.load()
        store.add(GameVersionRecord(archive_path='/a.zip', game='deltarune'))
        store.add(GameVersionRecord(archive_path='/b.zip', game='undertale'))
        store.add(GameVersionRecord(archive_path='/c.zip', game='deltarune'))
        assert len(store.records_for_game('deltarune')) == 2
        assert len(store.records_for_game('undertale')) == 1

    def test_persistence(self, temp_dir):
        """Checks that persistenceing works."""
        store1 = GameVersionsStore(temp_dir)
        store1.load()
        store1.add(GameVersionRecord(archive_path='/archives/persist.zip', game='deltarune'))
        store2 = GameVersionsStore(temp_dir)
        store2.load()
        assert store2.find('/archives/persist.zip') is not None

    def test_atomic_write_creates_file(self, temp_dir):
        """Checks that atomicing write creates file."""
        store = GameVersionsStore(temp_dir)
        store.load()
        store.add(GameVersionRecord(archive_path='/archives/test.zip', game='deltarune'))
        data_path = os.path.join(temp_dir, 'game_versions', 'game_versions_data.json')
        assert os.path.exists(data_path)
        with open(data_path, encoding='utf-8') as f:
            data = json.load(f)
        assert len(data) == 1

    def test_corrupt_data_recovery(self, temp_dir):
        """Checks that corrupting data recovery."""
        versions_dir = os.path.join(temp_dir, 'game_versions')
        os.makedirs(versions_dir, exist_ok=True)
        data_path = os.path.join(versions_dir, 'game_versions_data.json')
        with open(data_path, 'w') as f:
            f.write('{invalid json')
        store = GameVersionsStore(temp_dir)
        records = store.load()
        assert records == []
        assert os.path.exists(data_path + '.bak')

    def test_startup_recovery_marks_missing(self, temp_dir):
        """Checks that startup recovery marks missing."""
        store = GameVersionsStore(temp_dir)
        store.load()
        r = GameVersionRecord(archive_path='/nonexistent/path.zip', game='deltarune', archive_exists=True)
        store.add(r)
        store2 = GameVersionsStore(temp_dir)
        store2.load()
        store2.startup_recovery()
        found = store2.find('/nonexistent/path.zip')
        assert found is not None
        assert found.archive_exists is False

    def test_startup_recovery_removes_stale(self, temp_dir):
        """Checks that startup recovery removes stale."""
        store = GameVersionsStore(temp_dir)
        store.load()
        r = GameVersionRecord(archive_path='/nonexistent/stale.zip', game='deltarune', archive_exists=False)
        store.add(r)
        store2 = GameVersionsStore(temp_dir)
        store2.load()
        store2.startup_recovery()
        assert store2.find('/nonexistent/stale.zip') is None

    def test_startup_recovery_marks_existing(self, temp_dir):
        """Checks that startup recovery marks existing."""
        archive_path = os.path.join(temp_dir, 'game_versions', 'test.zip')
        store = GameVersionsStore(temp_dir)
        store.load()
        with open(archive_path, 'wb') as f:
            f.write(b'fake zip')
        r = GameVersionRecord(archive_path=archive_path, game='deltarune', archive_exists=False)
        store.add(r)
        store2 = GameVersionsStore(temp_dir)
        store2.load()
        store2.startup_recovery()
        found = store2.find(archive_path)
        assert found is not None
        assert found.archive_exists is True

    def test_versions_dir_property(self, temp_dir):
        """Checks that versionsing dir property."""
        store = GameVersionsStore(temp_dir)
        assert store.versions_dir == os.path.join(temp_dir, 'game_versions')


class TestVersionUtils:
    """Tests for game versions."""
    def test_safe_archive_name(self):
        """Checks that sanitizing archive name."""
        assert safe_archive_name('My Save v1.0') == 'My Save v1.0.zip'

    def test_safe_archive_name_special_chars(self):
        """Checks that sanitizing archive name special chars."""
        result = safe_archive_name('a/b\\c:d*e?f')
        assert '/' not in result.replace('.zip', '')
        assert '\\' not in result.replace('.zip', '')
        assert result.endswith('.zip')

    def test_safe_archive_name_trims_leading_and_trailing_dots_spaces(self):
        """Checks that sanitizing archive name trims leading and trailing dots spaces."""
        assert safe_archive_name(' .. My Save . ') == 'My Save.zip'

    def test_safe_archive_name_falls_back_when_trimmed_name_is_empty(self):
        """Checks that sanitizing archive name falls back when trimmed name is empty."""
        assert safe_archive_name(' ...  ') == 'version.zip'

    def test_safe_archive_name_empty(self):
        """Checks that sanitizing archive name empty."""
        assert safe_archive_name('') == 'version.zip'

    def test_unique_archive_path_no_conflict(self, temp_dir):
        """Checks that uniqueing archive path no conflict."""
        path = unique_archive_path(temp_dir, 'test')
        assert path.endswith('.zip')
        assert 'test' in os.path.basename(path)

    def test_unique_archive_path_with_conflict(self, temp_dir):
        """Checks that uniqueing archive path with conflict."""
        first = unique_archive_path(temp_dir, 'dup')
        with open(first, 'w') as f:
            f.write('')
        second = unique_archive_path(temp_dir, 'dup')
        assert second != first
        assert '_1' in os.path.basename(second)

    def test_get_base_game_folder_nonexistent(self):
        """Checks that missing base game folder."""
        assert get_base_game_folder('/nonexistent/path') is None

    def test_get_base_game_folder_empty(self):
        """Checks that empty base game folder."""
        assert get_base_game_folder('') is None

    def test_get_base_game_folder_valid_dir(self, temp_dir):
        """Checks that valid base game folder."""
        result = get_base_game_folder(temp_dir)
        assert result == temp_dir


class TestCreateVersionWorker:
    """Tests for game versions."""
    def test_create_archive(self, temp_dir, qapp):
        """Checks that creating archive."""
        game_dir = os.path.join(temp_dir, 'game')
        os.makedirs(game_dir)
        with open(os.path.join(game_dir, 'data.win'), 'w') as f:
            f.write('game data')
        with open(os.path.join(game_dir, 'game.exe'), 'w') as f:
            f.write('exe content')
        archive_path = os.path.join(temp_dir, 'test_version.zip')
        protected = {'game.exe'}

        from workers.game_version_archive_worker import CreateVersionWorker
        results = []
        worker = CreateVersionWorker(archive_path, game_dir, protected)
        worker.result_ready.connect(lambda *args: results.append(args))
        worker.run()

        assert len(results) == 1
        success, error, _size, count = results[0]
        assert success is True
        assert error == ''
        assert count == 1
        assert os.path.isfile(archive_path)
        with zipfile.ZipFile(archive_path, 'r') as zf:
            names = zf.namelist()
            assert 'data.win' in names
            assert 'game.exe' not in names

    def test_create_archive_empty_dir(self, temp_dir, qapp):
        """Checks that creating archive empty dir."""
        archive_path = os.path.join(temp_dir, 'empty.zip')
        empty_dir = os.path.join(temp_dir, 'empty_game')
        os.makedirs(empty_dir)
        from workers.game_version_archive_worker import CreateVersionWorker
        results = []
        worker = CreateVersionWorker(archive_path, empty_dir, set())
        worker.result_ready.connect(lambda *args: results.append(args))
        worker.run()
        assert len(results) == 1
        success, _error, _size, count = results[0]
        assert success is True
        assert count == 0

    def test_create_archive_suppresses_emit_failure_after_error(
        self, temp_dir, qapp, caplog, monkeypatch
    ):
        """Checks that archive errors cannot crash while notifying a dead UI."""
        from functools import partial

        from workers import game_version_archive_worker
        from workers.game_version_archive_worker import CreateVersionWorker

        def failing_safe_emit(*_args, **_kwargs):
            raise RuntimeError("receiver deleted")

        archive_path = os.path.join(temp_dir, "missing", "version.zip")
        worker = CreateVersionWorker(archive_path, temp_dir, set())
        monkeypatch.setattr(
            game_version_archive_worker,
            "_safe_emit",
            partial(game_version_archive_worker._safe_emit, emitter=failing_safe_emit),
        )

        worker.run()

        assert "CreateVersionWorker failed" in caplog.text
        assert "CreateVersionWorker: failed to emit" in caplog.text


class TestApplyVersionWorker:
    """Tests for game versions."""
    def test_apply_version(self, temp_dir, qapp):
        """Checks that applying version."""
        game_dir = os.path.join(temp_dir, 'game')
        os.makedirs(game_dir)
        archive_path = os.path.join(temp_dir, 'version.zip')
        with zipfile.ZipFile(archive_path, 'w') as zf:
            zf.writestr('data.win', 'restored data')
            zf.writestr('subdir/extra.txt', 'extra file')

        from workers.game_version_archive_worker import ApplyVersionWorker
        results = []
        worker = ApplyVersionWorker(archive_path, game_dir, set(), full_replace=False)
        worker.result_ready.connect(lambda *args: results.append(args))
        worker.run()

        assert len(results) == 1
        assert results[0][0] is True
        assert os.path.isfile(os.path.join(game_dir, 'data.win'))
        assert os.path.isfile(os.path.join(game_dir, 'subdir', 'extra.txt'))

    def test_apply_full_replace_deletes_extra(self, temp_dir, qapp):
        """Checks that applying full replace deletes extra."""
        game_dir = os.path.join(temp_dir, 'game')
        os.makedirs(game_dir)
        with open(os.path.join(game_dir, 'old_file.txt'), 'w') as f:
            f.write('old')
        with open(os.path.join(game_dir, 'game.exe'), 'w') as f:
            f.write('exe')
        archive_path = os.path.join(temp_dir, 'version.zip')
        with zipfile.ZipFile(archive_path, 'w') as zf:
            zf.writestr('data.win', 'new data')

        from workers.game_version_archive_worker import ApplyVersionWorker
        results = []
        worker = ApplyVersionWorker(archive_path, game_dir, {'game.exe'}, full_replace=True)
        worker.result_ready.connect(lambda *args: results.append(args))
        worker.run()

        assert results[0][0] is True
        assert os.path.isfile(os.path.join(game_dir, 'data.win'))
        assert not os.path.exists(os.path.join(game_dir, 'old_file.txt'))
        assert os.path.isfile(os.path.join(game_dir, 'game.exe'))

    def test_apply_missing_archive(self, temp_dir, qapp):
        """Checks that applying missing archive."""
        from workers.game_version_archive_worker import ApplyVersionWorker
        results = []
        worker = ApplyVersionWorker('/nonexistent.zip', temp_dir, set(), full_replace=False)
        worker.result_ready.connect(lambda *args: results.append(args))
        worker.run()
        assert results[0][0] is False
        assert results[0][1] == tr("errors.file_not_found", path="/nonexistent.zip")


class TestExportImportWorkers:
    """Tests for game versions."""
    def test_export_and_import_round_trip(self, temp_dir, qapp):
        """Checks that exporting and import round trip."""
        source_archive = os.path.join(temp_dir, 'internal.zip')
        with zipfile.ZipFile(source_archive, 'w') as zf:
            zf.writestr('data.win', 'game data')

        exported_path = os.path.join(temp_dir, 'exported.zip')
        manifest = {'manifest_version': 1, 'display_name': 'Test', 'game': 'deltarune'}

        from workers.game_version_archive_worker import GameExportVersionWorker
        export_results = []
        ew = GameExportVersionWorker(source_archive, exported_path, manifest)
        ew.result_ready.connect(lambda *args: export_results.append(args))
        ew.run()
        assert export_results[0][0] is True
        assert os.path.isfile(exported_path)

        with zipfile.ZipFile(exported_path, 'r') as zf:
            assert 'game_version_data.json' in zf.namelist()
            assert 'data.win' in zf.namelist()

        reimport_path = os.path.join(temp_dir, 'reimported.zip')
        from workers.game_version_archive_worker import GameImportVersionWorker
        import_results = []
        iw = GameImportVersionWorker(exported_path, reimport_path)
        iw.result_ready.connect(lambda *args: import_results.append(args))
        iw.run()
        assert import_results[0][0] is True
        assert import_results[0][2]['game'] == 'deltarune'
        assert os.path.isfile(reimport_path)
        with zipfile.ZipFile(reimport_path, 'r') as zf:
            assert 'data.win' in zf.namelist()
            assert 'game_version_data.json' not in zf.namelist()

    def test_import_missing_manifest(self, temp_dir, qapp):
        """Checks that importing missing manifest."""
        source = os.path.join(temp_dir, 'no_manifest.zip')
        with zipfile.ZipFile(source, 'w') as zf:
            zf.writestr('data.win', 'data')

        dest = os.path.join(temp_dir, 'imported.zip')
        from workers.game_version_archive_worker import GameImportVersionWorker
        results = []
        iw = GameImportVersionWorker(source, dest)
        iw.result_ready.connect(lambda *args: results.append(args))
        iw.run()
        assert results[0][0] is False
        assert 'manifest' in results[0][1].lower()
