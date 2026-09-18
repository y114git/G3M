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

    def _apply_patch_to_file(self, *_args, **_kwargs):
        return False


def test_apply_file_overrides_splits_frickbears3_addons_from_regular_extra_files(
    tmp_path,
):
    mod_root = tmp_path / "mod"
    game_dir = tmp_path / "game"
    data_dir = tmp_path / "game_data"
    _write_text(mod_root / "addons" / "Goomba" / "extras_info.txt", json.dumps({"FULL_NAME": "Goomba"}))
    _write_text(mod_root / "docs" / "readme.txt", "hello")
    _write_text(game_dir / "docs" / "readme.txt", "old")
    _write_text(data_dir / "addons" / "Goomba" / "extras_info.txt", "oldguard")

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
        data_dir=str(data_dir),
    )

    assert ok is True
    assert (game_dir / "docs" / "readme.txt").read_text("utf-8") == "hello"
    assert (
        data_dir / "addons" / "Goomba" / "extras_info.txt"
    ).read_text("utf-8") == '{"FULL_NAME": "Goomba"}'

    backup_mgr.restore_all_backups()

    assert (game_dir / "docs" / "readme.txt").read_text("utf-8") == "old"
    assert (
        data_dir / "addons" / "Goomba" / "extras_info.txt"
    ).read_text("utf-8") == "oldguard"


def test_configured_addons_skip_broken_links(tmp_path):
    mod_root = tmp_path / "mod"
    icon = mod_root / "addons" / "Guard" / "icon.png"
    icon.parent.mkdir(parents=True)
    icon.write_bytes(b"icon")
    broken_link = icon.parent / "optional.png"
    try:
        os.symlink(icon.parent / "missing.png", broken_link)
    except OSError as exc:
        pytest.skip(f"File symlinks are unavailable: {exc}")
    data_dir = tmp_path / "game_data"

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
        data_dir=str(data_dir),
    )

    installed = data_dir / "addons" / "Guard"
    assert ok is True
    assert (installed / "icon.png").read_bytes() == b"icon"
    assert not os.path.lexists(installed / "optional.png")


def test_configured_extra_directory_skips_symlink_cycle(tmp_path):
    mod_root = tmp_path / "mod"
    assets = mod_root / "assets"
    _write_text(assets / "guard.txt", "safe")
    try:
        os.symlink(assets, assets / "loop", target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Directory symlinks are unavailable: {exc}")

    target_dir = tmp_path / "game"
    ok = apply_file_overrides(
        _DummyPatcher(None),
        str(mod_root),
        str(target_dir),
        used_archive_names=set(),
        is_modpack=False,
        chapter_id="deltarune_1",
        game_id="deltarune",
        configured_paths=["assets/"],
        mod_root_dir=str(mod_root),
    )

    assert ok is True
    assert (target_dir / "assets" / "guard.txt").read_text("utf-8") == "safe"


def test_configured_extra_directory_skips_external_symlink(tmp_path):
    mod_root = tmp_path / "mod"
    assets = mod_root / "assets"
    _write_text(assets / "guard.txt", "safe")
    outside = tmp_path / "outside.txt"
    _write_text(outside, "private")
    try:
        os.symlink(outside, assets / "outside.txt")
    except OSError as exc:
        pytest.skip(f"File symlinks are unavailable: {exc}")

    target_dir = tmp_path / "game"
    assert apply_file_overrides(
        _DummyPatcher(None),
        str(mod_root),
        str(target_dir),
        used_archive_names=set(),
        is_modpack=False,
        chapter_id="deltarune_1",
        game_id="deltarune",
        configured_paths=["assets/"],
        mod_root_dir=str(mod_root),
    )
    assert (target_dir / "assets" / "guard.txt").read_text("utf-8") == "safe"
    assert not (target_dir / "assets" / "outside.txt").exists()


def test_configured_custom_target_copies_to_its_absolute_folder(tmp_path):
    mod_root = tmp_path / "mod"
    custom_target = tmp_path / "custom-target"
    _write_text(mod_root / "assets" / "guard.txt", "safe")
    custom_target.mkdir()

    assert apply_file_overrides(
        _DummyPatcher(None),
        str(mod_root),
        str(tmp_path / "game"),
        used_archive_names=set(),
        is_modpack=False,
        chapter_id="deltarune_1",
        game_id="deltarune",
        configured_paths=[
            {
                "file_path": "assets/",
                "target": "custom",
                "target_path": str(custom_target),
            }
        ],
        mod_root_dir=str(mod_root),
    )

    assert (custom_target / "assets" / "guard.txt").read_text("utf-8") == "safe"


def test_configured_addons_archive_extracts_into_addons_directory(tmp_path):
    mod_root = tmp_path / "mod"
    mod_root.mkdir()
    with zipfile.ZipFile(mod_root / "addons.zip", "w") as archive:
        archive.writestr("Guard/extras_info.txt", '{"FULL_NAME":"Guard"}')
        archive.writestr("Guard/icon.png", b"icon")
    data_dir = tmp_path / "game_data"

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
        data_dir=str(data_dir),
    )

    installed = data_dir / "addons" / "Guard"
    assert ok is True
    assert (installed / "extras_info.txt").is_file()
    assert (installed / "icon.png").read_bytes() == b"icon"
    assert not (data_dir / "Guard").exists()
