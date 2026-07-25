"""Unit tests for FRICKBEARS3 addon detection, conversion, and apply flows."""

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.backup_service import BackupManager
from services.frickbears3_addons_service import Frickbears3AddonsService
from utils.frickbears3_addons_utils import apply_frickbears3_addons_from_mod_source


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_bytes(path: Path, content: bytes = b"x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _write_guard_layout(root: Path, *, full_name: str = "Guard Test") -> None:
    _write_text(
        root / "extras_info.txt",
        json.dumps({"FULL_NAME": full_name, "DESCRIPTION": "Guard description"}),
    )
    _write_text(root / "opening_dialogue.txt", '{"DIALOGUE":["hello"]}')
    for file_name in (
        "icon.png",
        "portrait.png",
        "selection.png",
        "reflection.png",
    ):
        _write_bytes(root / file_name)


def test_frickbears3_service_detects_single_root_addon_layout(tmp_path):
    service = Frickbears3AddonsService()
    extract_dir = tmp_path / "extract"
    guard_root = extract_dir / "Goomba"
    _write_guard_layout(guard_root, full_name="Goomba")

    inspection = service.inspect_extracted_archive(str(extract_dir))

    assert inspection.eligible is True
    assert inspection.layout == "single_root"
    assert inspection.guard_root_dirs == [str(guard_root)]


def test_frickbears3_service_detects_flat_root_addon_layout(tmp_path):
    service = Frickbears3AddonsService()
    extract_dir = tmp_path / "extract"
    _write_guard_layout(extract_dir, full_name="Blox")

    inspection = service.inspect_extracted_archive(str(extract_dir))

    assert inspection.eligible is True
    assert inspection.layout == "flat_root"
    assert inspection.guard_root_dirs == [str(extract_dir)]


def test_frickbears3_service_rejects_weak_signature(tmp_path):
    service = Frickbears3AddonsService()
    extract_dir = tmp_path / "extract"
    root = extract_dir / "BrokenGuard"
    _write_text(root / "extras_info.txt", json.dumps({"FULL_NAME": "BrokenGuard"}))
    _write_bytes(root / "icon.png")

    inspection = service.inspect_extracted_archive(str(extract_dir))

    assert inspection.eligible is False


def test_frickbears3_service_converts_addon_archive_to_g3m_mod(tmp_path):
    service = Frickbears3AddonsService()
    extract_dir = tmp_path / "extract"
    guard_root = extract_dir / "Goomba"
    _write_guard_layout(guard_root, full_name="Goomba")

    mods_dir = tmp_path / "mods"
    result = service.convert_extracted_archive(
        str(extract_dir),
        str(mods_dir),
        source_file_path="goomba.zip",
        gamebanana_metadata={"name": "GOOMBA ~ CUSTOM GUARD", "mod_id": 42, "game": "frickbears3"},
    )

    result_path = Path(result)
    config = json.loads((result_path / "mod_config.json").read_text("utf-8"))
    assert config["metadata"]["name"] == "GOOMBA ~ CUSTOM GUARD"
    assert config["metadata"]["id"] == "gb_mod_42"
    assert config["metadata"]["game"] == "frickbears3"
    assert config["files"]["frickbears3"]["extra_files"] == ["addons/"]
    assert (result_path / "addons" / "Goomba" / "extras_info.txt").exists()
    assert (result_path / "addons" / "Goomba" / "icon.png").exists()


def test_apply_frickbears3_addons_copies_into_localappdata_and_restores(
    tmp_path, monkeypatch
):
    mod_source_dir = tmp_path / "mod"
    _write_text(
        mod_source_dir / "addons" / "Goomba" / "extras_info.txt",
        json.dumps({"FULL_NAME": "Goomba"}),
    )
    _write_bytes(mod_source_dir / "addons" / "Goomba" / "icon.png", b"new")
    _write_text(mod_source_dir / "addons" / "Blox" / "opening_dialogue.txt", "hello")

    localappdata_dir = tmp_path / "localappdata"
    addons_dir = localappdata_dir / "Frickbears3" / "addons"
    existing_file = addons_dir / "Goomba" / "icon.png"
    _write_bytes(existing_file, b"old")

    backup_mgr = BackupManager(str(tmp_path / "backups"))
    monkeypatch.setenv("LOCALAPPDATA", str(localappdata_dir))

    ok = apply_frickbears3_addons_from_mod_source(
        str(mod_source_dir),
        backup_or_mark=lambda target_file: (
            backup_mgr.backup_file("frickbears3_addons", target_file)
            if os.path.exists(target_file)
            else backup_mgr.mark_file_added("frickbears3_addons", target_file)
        ),
        logger=SimpleNamespace(debug=lambda *args, **kwargs: None),
        extract_archive=lambda archive_path, target_dir: None,
    )

    assert ok is True
    assert existing_file.read_bytes() == b"new"
    assert (addons_dir / "Blox" / "opening_dialogue.txt").read_text("utf-8") == "hello"

    backup_mgr.restore_all_backups()

    assert existing_file.read_bytes() == b"old"
    assert not (addons_dir / "Blox" / "opening_dialogue.txt").exists()


def test_apply_frickbears3_addons_skips_broken_symlink(tmp_path, monkeypatch):
    mod_source_dir = tmp_path / "mod"
    valid_file = mod_source_dir / "addons" / "Guard" / "icon.png"
    _write_bytes(valid_file, b"icon")
    broken_link = mod_source_dir / "addons" / "Guard" / "optional.png"
    try:
        os.symlink(broken_link.parent / "missing.png", broken_link)
    except OSError as exc:
        pytest.skip(f"File symlinks are unavailable: {exc}")

    localappdata_dir = tmp_path / "localappdata"
    monkeypatch.setenv("LOCALAPPDATA", str(localappdata_dir))

    ok = apply_frickbears3_addons_from_mod_source(
        str(mod_source_dir),
        backup_or_mark=lambda _target_file: None,
        logger=SimpleNamespace(debug=lambda *args, **kwargs: None),
        extract_archive=lambda archive_path, target_dir: None,
    )

    copied_guard = localappdata_dir / "Frickbears3" / "addons" / "Guard"
    assert ok is True
    assert (copied_guard / "icon.png").read_bytes() == b"icon"
    assert not (copied_guard / "optional.png").exists()
