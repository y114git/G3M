"""Tests for FRICKBEARS3 addon handling inside file override application."""

import json
import logging
import os
import zipfile
from pathlib import Path

import pytest

from services.backup_service import BackupManager
from utils.patching.file_override_utils import apply_file_overrides


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class _DummyPatcher:
    def __init__(self, backup_service) -> None:
        self.backup_service = backup_service
        self.patching_logger = logging.getLogger("test_frickbears3_overrides")
        self.xdelta_modpack = False

    def _backup_or_mark_file(self, chapter_id, target_file: str) -> None:
        if self.backup_service is None:
            return
        if Path(target_file).exists():
            self.backup_service.backup_file(str(chapter_id), target_file)
        else:
            self.backup_service.mark_file_added(str(chapter_id), target_file)

    def _request_warning(self, *_args, **_kwargs):
        return True

    def _apply_xdelta_to_file(self, *_args, **_kwargs):
        return False


def test_apply_file_overrides_splits_frickbears3_addons_from_regular_extra_files(
    tmp_path, monkeypatch
):
    mod_root = tmp_path / "mod"
    game_dir = tmp_path / "game"
    localappdata_dir = tmp_path / "localappdata"
    _write_text(mod_root / "addons" / "Goomba" / "extras_info.txt", json.dumps({"FULL_NAME": "Goomba"}))
    _write_text(mod_root / "docs" / "readme.txt", "hello")
    _write_text(game_dir / "docs" / "readme.txt", "old")
    _write_text(localappdata_dir / "Frickbears3" / "addons" / "Goomba" / "extras_info.txt", "oldguard")
    monkeypatch.setenv("LOCALAPPDATA", str(localappdata_dir))

    backup_mgr = BackupManager(str(tmp_path / "backups"))
    patcher = _DummyPatcher(backup_mgr)

    ok = apply_file_overrides(
        patcher,
        str(mod_root),
        str(game_dir),
        used_archive_names=set(),
        is_modpack=False,
        chapter_id="frickbears3",
        game_id="frickbears3",
        configured_paths=["addons/", "docs/readme.txt"],
        mod_root_dir=str(mod_root),
        mod_name="Guard Mix",
    )

    assert ok is True
    assert (game_dir / "docs" / "readme.txt").read_text("utf-8") == "hello"
    assert (
        localappdata_dir / "Frickbears3" / "addons" / "Goomba" / "extras_info.txt"
    ).read_text("utf-8") == '{"FULL_NAME": "Goomba"}'

    backup_mgr.restore_all_backups()

    assert (game_dir / "docs" / "readme.txt").read_text("utf-8") == "old"
    assert (
        localappdata_dir / "Frickbears3" / "addons" / "Goomba" / "extras_info.txt"
    ).read_text("utf-8") == "oldguard"


def test_configured_addons_skip_broken_links(tmp_path, monkeypatch):
    mod_root = tmp_path / "mod"
    icon = mod_root / "addons" / "Guard" / "icon.png"
    icon.parent.mkdir(parents=True)
    icon.write_bytes(b"icon")
    broken_link = icon.parent / "optional.png"
    try:
        os.symlink(icon.parent / "missing.png", broken_link)
    except OSError as exc:
        pytest.skip(f"File symlinks are unavailable: {exc}")
    localappdata_dir = tmp_path / "localappdata"
    monkeypatch.setenv("LOCALAPPDATA", str(localappdata_dir))

    ok = apply_file_overrides(
        _DummyPatcher(None),
        str(mod_root),
        str(tmp_path / "game"),
        used_archive_names=set(),
        is_modpack=False,
        chapter_id="frickbears3",
        game_id="frickbears3",
        configured_paths=["addons/"],
        mod_root_dir=str(mod_root),
    )

    installed = localappdata_dir / "Frickbears3" / "addons" / "Guard"
    assert ok is True
    assert (installed / "icon.png").read_bytes() == b"icon"
    assert not os.path.lexists(installed / "optional.png")


def test_configured_addons_archive_extracts_into_addons_directory(
    tmp_path, monkeypatch
):
    mod_root = tmp_path / "mod"
    mod_root.mkdir()
    with zipfile.ZipFile(mod_root / "addons.zip", "w") as archive:
        archive.writestr("Guard/extras_info.txt", '{"FULL_NAME":"Guard"}')
        archive.writestr("Guard/icon.png", b"icon")
    localappdata_dir = tmp_path / "localappdata"
    monkeypatch.setenv("LOCALAPPDATA", str(localappdata_dir))

    ok = apply_file_overrides(
        _DummyPatcher(None),
        str(mod_root),
        str(tmp_path / "game"),
        used_archive_names=set(),
        is_modpack=False,
        chapter_id="frickbears3",
        game_id="frickbears3",
        configured_paths=["addons.zip"],
        mod_root_dir=str(mod_root),
    )

    installed = localappdata_dir / "Frickbears3" / "addons" / "Guard"
    assert ok is True
    assert (installed / "extras_info.txt").is_file()
    assert (installed / "icon.png").read_bytes() == b"icon"
    assert not (localappdata_dir / "Frickbears3" / "Guard").exists()
