"""Unit tests for test save."""

from ui.dialogs.mod_editor.save import build_saved_mod_config


def test_build_saved_mod_config_for_create_payload():
    data = {
        "version": "1.2.3",
        "name": "Test Mod",
        "description": "Desc",
        "author": "Author",
        "homepage": "https://example.com",
        "game": "deltarune",
        "game_version": "1.04",
        "tags": ["gameplay"],
        "info_files": {"README.md": "show"},
    }

    config = build_saved_mod_config(
        mod_id="local_123",
        data=data,
        processed_files={"deltarune_1": {"data_file_path": "data.win"}},
        icon_val="icon.png",
    )

    assert config == {
        "id": "local_123",
        "version": "1.2.3",
        "name": "Test Mod",
        "description": "Desc",
        "author": "Author",
        "homepage": "https://example.com",
        "game": "deltarune",
        "game_version": "1.04",
        "tags": ["gameplay"],
        "info_files": {"README.md": "show"},
        "files": {"deltarune_1": {"data_file_path": "data.win"}},
        "icon": "icon.png",
    }


def test_build_saved_mod_config_preserves_existing_fields_when_updating():
    data = {
        "version": "2.0.0",
        "name": "Edited",
        "description": "New",
        "author": "Author",
        "homepage": "",
        "game": "deltarune",
        "game_version": "1.05",
        "tags": [],
        "info_files": {},
    }

    config = build_saved_mod_config(
        mod_id="local_456",
        data=data,
        processed_files={},
        existing_config={"created_at": "old", "icon": "keep.png"},
    )

    assert config["created_at"] == "old"
    assert config["icon"] == "keep.png"
    assert config["id"] == "local_456"
    assert config["name"] == "Edited"
