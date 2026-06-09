"""Unit tests for test config parser."""

from utils.mod.config_parser import (
    MOD_CONFIG_VERSION,
    build_mod_config_data,
    normalize_files_data,
    normalize_mod_config_data,
)


def test_build_mod_config_data_uses_default_order_for_new_payload():
    """Checks that building mod config data uses default order for new payload."""
    config = build_mod_config_data(
        {
            "files": {"1": {}},
            "game_version": "1.0",
            "name": "Test",
            "id": "mod",
            "tags": ["other"],
            "author": "Author",
            "description": "Desc",
            "game": "deltarune",
            "homepage": "https://example.com",
            "version": "1.0.0",
            "icon": "icon.png",
            "info_files": {"README.md": "show"},
        }
    )

    assert list(config) == [
        "config_version",
        "metadata",
        "info_files",
        "files",
    ]
    assert config["config_version"] == MOD_CONFIG_VERSION
    assert list(config["metadata"]) == [
        "id",
        "name",
        "version",
        "author",
        "description",
        "homepage",
        "icon",
        "game",
        "game_version",
        "tags",
    ]
    assert config["info_files"] == {"README.md": "show"}


def test_normalize_mod_config_data_migrates_to_canonical_order():
    """Checks that normalizing mod config data migrates to canonical order."""
    config = {
        "id": "mod",
        "name": "Test",
        "files": {"1": {}},
        "description": "Desc",
        "icon": "icon.png",
        "external_url": "https://example.com/mod",
        "game": "deltarune",
    }

    assert normalize_mod_config_data(config) is True
    assert list(config) == [
        "config_version",
        "id",
        "name",
        "version",
        "description",
        "homepage",
        "icon",
        "game",
        "files",
    ]
    assert config["homepage"] == "https://example.com/mod"
    assert list(config["files"]) == ["deltarune_1"]


def test_normalize_files_data_converts_tab_ids_to_file_keys():
    """Checks that normalizing files data converts tab ids to file keys."""
    files = normalize_files_data(
        {
            "deltarune_4": {
                "data_file_path": "DATA.win",
                "extra_files": {"extras": ["bonus.zip"]},
            }
        }
    )

    assert list(files) == ["deltarune_4"]
    assert files["deltarune_4"]["data_file_path"] == "DATA.win"
    assert files["deltarune_4"]["extra_files"] == ["bonus.zip"]


def test_normalize_files_data_with_game_prefix_normalizes_chapter_ids():
    """Checks that normalizing files data with game prefix normalizes chapter ids."""
    files = normalize_files_data(
        {
            "4": {
                "data_file_path": "DATA.win",
                "extra_files": {"extras": ["bonus.zip"]},
            }
        },
        game="deltarune"
    )

    assert list(files) == ["deltarune_4"]
    assert files["deltarune_4"]["data_file_path"] == "DATA.win"
    assert files["deltarune_4"]["extra_files"] == ["bonus.zip"]


def test_normalize_mod_config_data_normalizes_file_keys_to_chapter_ids():
    """Checks that normalizing mod config data normalizes file keys to chapter ids."""
    config = {
        "game": "deltarune",
        "files": {"4": {"data_file_path": "DATA.win"}},
    }

    assert normalize_mod_config_data(config) is True
    assert list(config["files"]) == ["deltarune_4"]


def test_normalize_mod_config_data_filters_invalid_tags_and_trims_fields():
    """Checks that normalizing mod config data filters invalid tags and trims fields."""
    config = {
        "id": "x" * 80,
        "name": "n" * 80,
        "version": "v" * 40,
        "description": "d" * 250,
        "game": "g" * 80,
        "tags": ["other", "invalid", "OTHER", "cyop/afom"],
        "files": {
            "1": {
                "data_file_path": "a" * 1200,
                "extra_files": [{"file_path": "u" * 1200}],
            }
        },
    }

    assert normalize_mod_config_data(config) is True
    assert config["id"] == "x" * 50
    assert config["name"] == "n" * 50
    assert config["version"] == "v" * 20
    assert config["description"] == "d" * 200
    assert config["game"] == "g" * 30
    assert config["tags"] == ["other", "CYOP/AFOM"]
    file_info = config["files"]["deltarune_1"]
    assert len(file_info["data_file_path"]) == 1000
    assert file_info["extra_files"] == ["u" * 1000]


def test_normalize_mod_config_data_preserves_trailing_slash_for_directory_extra_files():
    config = {
        "name": "AFOM Test",
        "game": "pizzatower",
        "files": {
            "pizzatower": {
                "extra_files": ["towers/", "nested\\path\\"],
            }
        },
    }

    assert normalize_mod_config_data(config) is True
    assert config["files"]["pizzatower"]["extra_files"] == ["towers/", "nested/path/"]


def test_build_mod_config_data_preserves_directory_extra_file_targets():
    config = build_mod_config_data(
        {
            "name": "AFOM Test",
            "game": "pizzatower",
            "files": {
                "pizzatower": {
                    "extra_files": ["towers/"],
                }
            },
        }
    )

    assert config["files"]["pizzatower"]["extra_files"] == ["towers/"]


def test_normalize_mod_config_data_flattens_metadata_block():
    """Checks that normalizing mod config data flattens metadata block."""
    config = {
        "config_version": "1.0.0",
        "metadata": {
            "id": "mod",
            "name": "Test",
            "game": "deltarune",
            "homepage": "https://example.com/mod",
        },
        "files": {"1": {"data_file_path": "DATA.win"}},
    }

    assert normalize_mod_config_data(config) is True
    assert config["id"] == "mod"
    assert config["name"] == "Test"
    assert config["homepage"] == "https://example.com/mod"
    assert list(config["files"]) == ["deltarune_1"]


def test_normalize_mod_config_data_normalizes_info_files_order_and_values():
    """Checks that info_files keeps insertion order and normalizes invalid values."""
    config = {
        "game": "deltarune",
        "info_files": {
            " chapter/readme.md ": "hide",
            " old/readme.md ": "remove",
            "README.md": "weird",
            "": "show",
        },
    }

    assert normalize_mod_config_data(config) is True
    assert config["info_files"] == {
        "chapter/readme.md": "hide",
        "old/readme.md": "remove",
        "README.md": "show",
    }
