"""Tests for mod_versions_dialog utility functions."""
import contextlib
import os
import tempfile
import zipfile

import pytest


@pytest.fixture
def mod_folder(tmp_path):
    mod = tmp_path / 'test_mod'
    mod.mkdir()
    (mod / 'mod_config.json').write_text('{"name": "test"}')
    (mod / 'data.txt').write_text('hello')
    return str(mod)


class TestListLocalVersions:
    def test_empty(self, mod_folder):
        from ui.dialogs.mod_versions_dialog import _list_local_versions
        assert _list_local_versions(mod_folder) == []

    def test_returns_zips(self, mod_folder):
        from ui.dialogs.mod_versions_dialog import (
            _ensure_versions_dir,
            _list_local_versions,
        )
        vdir = _ensure_versions_dir(mod_folder)
        zp = os.path.join(vdir, 'v1.zip')
        with zipfile.ZipFile(zp, 'w') as zf:
            zf.writestr('a.txt', 'data')
        result = _list_local_versions(mod_folder)
        assert len(result) == 1
        assert result[0]['name'] == 'v1'
        assert result[0]['path'] == zp
        assert result[0]['size'] > 0

    def test_ignores_non_zip(self, mod_folder):
        from ui.dialogs.mod_versions_dialog import (
            _ensure_versions_dir,
            _list_local_versions,
        )
        vdir = _ensure_versions_dir(mod_folder)
        with open(os.path.join(vdir, 'readme.txt'), 'w') as f:
            f.write('not a zip')
        assert _list_local_versions(mod_folder) == []


class TestClearModFolder:
    def test_preserves_mod_versions(self, mod_folder):
        from ui.dialogs.mod_versions_dialog import (
            _clear_mod_folder,
            _ensure_versions_dir,
        )
        vdir = _ensure_versions_dir(mod_folder)
        marker = os.path.join(vdir, 'keep.zip')
        with open(marker, 'w') as f:
            f.write('keep')
        _clear_mod_folder(mod_folder)
        assert os.path.isdir(vdir)
        assert os.path.isfile(marker)
        remaining = os.listdir(mod_folder)
        assert remaining == ['mod_versions']


class TestSnapshotAndApply:
    def test_snapshot_creates_zip(self, mod_folder):
        from ui.dialogs.mod_versions_dialog import _create_version_zip
        zp = _create_version_zip(mod_folder, mod_folder, 'snap1', ignore_versions_dir=True)
        assert os.path.isfile(zp)
        with zipfile.ZipFile(zp, 'r') as zf:
            names = zf.namelist()
        assert 'mod_config.json' in names
        assert 'data.txt' in names
        assert not any('mod_versions' in n for n in names)

    def test_apply_restores(self, mod_folder):
        from ui.dialogs.mod_versions_dialog import (
            _apply_version_zip,
            _create_version_zip,
        )
        zp = _create_version_zip(mod_folder, mod_folder, 'snap1', ignore_versions_dir=True)
        with open(os.path.join(mod_folder, 'data.txt'), 'w') as f:
            f.write('changed')
        _apply_version_zip(mod_folder, zp)
        with open(os.path.join(mod_folder, 'data.txt')) as f:
            assert f.read() == 'hello'

    def test_apply_preserves_mod_versions_dir(self, mod_folder):
        from ui.dialogs.mod_versions_dialog import (
            _apply_version_zip,
            _create_version_zip,
            _ensure_versions_dir,
        )
        vdir = _ensure_versions_dir(mod_folder)
        marker = os.path.join(vdir, 'user.zip')
        with open(marker, 'w') as f:
            f.write('user version')
        zp = _create_version_zip(mod_folder, mod_folder, 'snap', ignore_versions_dir=True)
        _apply_version_zip(mod_folder, zp)
        assert os.path.isfile(marker)


class TestSanitizeVersionName:
    def test_basic(self):
        from ui.dialogs.mod_versions_dialog import _sanitize_version_name
        assert _sanitize_version_name('my version 1.0') == 'my version 1.0'

    def test_special_chars(self):
        from ui.dialogs.mod_versions_dialog import _sanitize_version_name
        result = _sanitize_version_name('a/b\\c:d')
        assert '/' not in result
        assert '\\' not in result

    def test_empty(self):
        from ui.dialogs.mod_versions_dialog import _sanitize_version_name
        assert _sanitize_version_name('') == 'version'


class TestConvertArchiveToVersionZip:
    def test_plain_zip(self, mod_folder):
        from ui.dialogs.mod_versions_dialog import (
            _convert_archive_to_version_zip,
            _list_local_versions,
        )
        with tempfile.NamedTemporaryFile(delete=False, suffix='.zip', prefix='mv_test_') as src:
            src_name = src.name
        try:
            with zipfile.ZipFile(src_name, 'w') as zf:
                zf.writestr('file.txt', 'content')
            ok = _convert_archive_to_version_zip(src_name, mod_folder, 'imported')
            assert ok
            versions = _list_local_versions(mod_folder)
            assert any(v['name'] == 'imported' for v in versions)
        finally:
            with contextlib.suppress(OSError):
                os.unlink(src_name)

    def test_invalid_archive_no_crash(self, mod_folder):
        from ui.dialogs.mod_versions_dialog import _convert_archive_to_version_zip
        with tempfile.NamedTemporaryFile(delete=False, suffix='.zip', prefix='mv_bad_') as bad:
            bad.write(b'not a real archive')
            bad_name = bad.name
        try:
            result = _convert_archive_to_version_zip(bad_name, mod_folder, 'bad')
            assert not result
        finally:
            os.unlink(bad_name)


class TestZipDirToVersion:
    def test_creates_zip(self, tmp_path):
        from ui.dialogs.mod_versions_dialog import _create_version_zip
        src = tmp_path / 'src'
        src.mkdir()
        (src / 'a.txt').write_text('data')
        mod = tmp_path / 'mod'
        mod.mkdir()
        zp = _create_version_zip(str(src), str(mod), 'test_ver', ignore_versions_dir=False)
        assert os.path.isfile(zp)
        with zipfile.ZipFile(zp, 'r') as zf:
            assert 'a.txt' in zf.namelist()
