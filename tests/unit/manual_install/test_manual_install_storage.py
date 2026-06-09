"""Unit tests for test manual install storage."""

import os

from ui.dialogs.manual_install.storage import (
    build_manual_mod_identity,
    copy_file_to_relative_path,
    create_manual_mod_dir,
    join_storage_path,
)


def test_build_manual_mod_identity_uses_gamebanana_metadata():
    mod_id, mod_name = build_manual_mod_identity(
        gamebanana_metadata={"mod_id": 123, "item_type": "mod", "name": "Fancy Mod"},
        source_file_path=None,
    )

    assert mod_id == "gb_mod_123"
    assert mod_name == "Fancy Mod"


def test_copy_file_to_relative_path_deduplicates_existing_target(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("hello", encoding="utf-8")
    target_dir = tmp_path / "mod"
    target_dir.mkdir()
    existing = target_dir / "docs" / "readme.txt"
    existing.parent.mkdir(parents=True)
    existing.write_text("old", encoding="utf-8")

    copied = copy_file_to_relative_path(str(target_dir), str(source), "docs/readme.txt")

    assert copied == "docs/readme_1.txt"
    assert (target_dir / "docs" / "readme_1.txt").is_file()


def test_join_storage_path_prepends_chapter_folder_for_multi_tab():
    joined = join_storage_path(
        "deltarune_3",
        "lang",
        "file.json",
        game="deltarune",
        is_multi_tab=True,
    )

    assert joined == "chapter_3/lang/file.json"


def test_create_manual_mod_dir_creates_unique_folder(tmp_path):
    mods_dir = tmp_path / "mods"
    mods_dir.mkdir()
    os.mkdir(mods_dir / "My Mod")

    folder_name, target_path = create_manual_mod_dir(mods_dir=str(mods_dir), mod_name="My Mod")

    assert folder_name != "My Mod"
    assert os.path.isdir(target_path)
