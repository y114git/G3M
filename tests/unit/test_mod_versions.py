"""Tests for mod_versions_dialog utility functions."""

import contextlib
import os
import tempfile
import zipfile

import pytest


@pytest.fixture
def mod_folder(tmp_path):
    mod = tmp_path / "test_mod"
    mod.mkdir()
    (mod / "mod_config.json").write_text('{"name": "test"}')
    (mod / "data.txt").write_text("hello")
    return str(mod)


class TestListLocalVersions:
    """Tests for mod versions."""
    def test_empty(self, mod_folder):
        """Checks that empty input is handled."""
        from ui.dialogs.mod_versions_dialog import _list_local_versions

        assert _list_local_versions(mod_folder) == []

    def test_returns_zips(self, mod_folder):
        """Checks that returnsing zips."""
        from ui.dialogs.mod_versions_dialog import _list_local_versions

        versions_dir = os.path.join(mod_folder, "mod_versions")
        os.makedirs(versions_dir, exist_ok=True)
        zp = os.path.join(versions_dir, "v1.zip")
        with zipfile.ZipFile(zp, "w") as zf:
            zf.writestr("a.txt", "data")
        result = _list_local_versions(mod_folder)
        assert len(result) == 1
        assert result[0]["name"] == "v1"
        assert result[0]["path"] == zp
        assert result[0]["size"] > 0

    def test_ignores_non_zip(self, mod_folder):
        """Checks that ignoresing non zip."""
        from ui.dialogs.mod_versions_dialog import _list_local_versions

        versions_dir = os.path.join(mod_folder, "mod_versions")
        os.makedirs(versions_dir, exist_ok=True)
        with open(os.path.join(versions_dir, "notzip.txt"), "w") as f:
            f.write("not a zip")
        result = _list_local_versions(mod_folder)
        assert result == []


class TestClearModFolder:
    """Tests for mod versions."""
    def test_preserves_mod_versions(self, mod_folder):
        """Checks that preservesing mod versions."""
        from ui.dialogs.mod_versions_dialog import _clear_mod_folder

        versions_dir = os.path.join(mod_folder, "mod_versions")
        os.makedirs(versions_dir, exist_ok=True)
        marker = os.path.join(versions_dir, "keep.zip")
        with open(marker, "w") as f:
            f.write("keep")
        _clear_mod_folder(mod_folder)
        assert os.path.isdir(versions_dir)
        assert os.path.isfile(marker)
        remaining = os.listdir(mod_folder)
        assert remaining == ["mod_versions"]


class TestSnapshotAndApply:
    """Tests for mod versions."""
    def test_snapshot_creates_zip(self, mod_folder):
        """Checks that snapshoting creates zip."""
        from utils.mod_version_utils import create_version_zip

        zp = create_version_zip(
            mod_folder, mod_folder, "snap1", ignore_versions_dir=True
        )
        assert os.path.isfile(zp)
        with zipfile.ZipFile(zp, "r") as zf:
            names = zf.namelist()
        assert "mod_config.json" in names
        assert "data.txt" in names
        assert not any("mod_versions" in n for n in names)

    def test_apply_restores(self, mod_folder):
        """Checks that applying restores."""
        from ui.dialogs.mod_versions_dialog import _apply_version_zip
        from utils.mod_version_utils import create_version_zip

        zp = create_version_zip(
            mod_folder, mod_folder, "snap1", ignore_versions_dir=True
        )
        with open(os.path.join(mod_folder, "data.txt"), "w") as f:
            f.write("changed")
        _apply_version_zip(mod_folder, zp)
        with open(os.path.join(mod_folder, "data.txt")) as f:
            assert f.read() == "hello"

    def test_apply_preserves_mod_versions_dir(self, mod_folder):
        """Checks that applying preserves mod versions dir."""
        from ui.dialogs.mod_versions_dialog import _apply_version_zip
        from utils.mod_version_utils import create_version_zip

        versions_dir = os.path.join(mod_folder, "mod_versions")
        os.makedirs(versions_dir, exist_ok=True)
        marker = os.path.join(versions_dir, "user.zip")
        with open(marker, "w") as f:
            f.write("user version")
        zp = create_version_zip(
            mod_folder, mod_folder, "snap", ignore_versions_dir=True
        )
        _apply_version_zip(mod_folder, zp)
        assert os.path.isfile(marker)


class TestUniqueVersionName:
    """Tests for mod versions."""
    def test_returns_same_name_when_free(self, mod_folder):
        """Checks that returnsing same name when free."""
        from utils.mod_version_utils import get_unique_version_name

        assert get_unique_version_name(mod_folder, "snap1") == "snap1"

    def test_appends_counter_when_taken(self, mod_folder):
        """Checks that appendsing counter when taken."""
        from utils.mod_version_utils import create_version_zip, get_unique_version_name

        create_version_zip(mod_folder, mod_folder, "snap1", ignore_versions_dir=True)
        assert get_unique_version_name(mod_folder, "snap1") == "snap1 (2)"


class TestConvertArchiveToVersionZip:
    """Tests for mod versions."""
    def test_plain_zip(self, mod_folder):
        """Checks that plaining zip."""
        from ui.dialogs.mod_versions_dialog import (
            _convert_archive_to_version_zip,
            _list_local_versions,
        )

        with tempfile.NamedTemporaryFile(
            delete=False, suffix=".zip", prefix="mv_test_"
        ) as src:
            src_name = src.name
        try:
            with zipfile.ZipFile(src_name, "w") as zf:
                zf.writestr("file.txt", "content")
            ok = _convert_archive_to_version_zip(src_name, mod_folder, "imported")
            assert ok
            versions = _list_local_versions(mod_folder)
            assert any(v["name"] == "imported" for v in versions)
        finally:
            with contextlib.suppress(OSError):
                os.unlink(src_name)

    def test_invalid_archive_no_crash(self, mod_folder):
        """Checks that invaliding archive no crash."""
        from ui.dialogs.mod_versions_dialog import _convert_archive_to_version_zip

        with tempfile.NamedTemporaryFile(
            delete=False, suffix=".zip", prefix="mv_bad_"
        ) as bad:
            bad.write(b"not a real archive")
            bad_name = bad.name
        try:
            result = _convert_archive_to_version_zip(bad_name, mod_folder, "bad")
            assert not result
        finally:
            os.unlink(bad_name)

    def test_nested_single_folder_chain_zip(self, mod_folder):
        """Checks that nesteding single folder chain zip."""
        from ui.dialogs.mod_versions_dialog import _convert_archive_to_version_zip

        with tempfile.NamedTemporaryFile(
            delete=False, suffix=".zip", prefix="mv_nested_"
        ) as src:
            src_name = src.name
        try:
            with zipfile.ZipFile(src_name, "w") as zf:
                zf.writestr("level1/level2/level3/mod_config.json", '{"name":"nested"}')
                zf.writestr("level1/level2/level3/data.txt", "content")
            ok = _convert_archive_to_version_zip(src_name, mod_folder, "nested")
            assert ok
        finally:
            with contextlib.suppress(OSError):
                os.unlink(src_name)


class TestZipDirToVersion:
    """Tests for mod versions."""
    def test_creates_zip(self, tmp_path):
        """Checks that createsing zip."""
        from utils.mod_version_utils import create_version_zip

        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("data")
        mod = tmp_path / "mod"
        mod.mkdir()
        zp = create_version_zip(
            str(src), str(mod), "test_ver", ignore_versions_dir=False
        )
        assert os.path.isfile(zp)
        with zipfile.ZipFile(zp, "r") as zf:
            assert "a.txt" in zf.namelist()
