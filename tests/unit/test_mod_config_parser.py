from utils.mod_config_parser import (
    build_mod_config_data,
    normalize_files_data,
    normalize_mod_config_data,
)


def test_build_mod_config_data_uses_default_order_for_new_payload():
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
            "external_url": "https://example.com",
            "version": "1.0.0",
            "icon": "icon.png",
        }
    )

    assert list(config)[:11] == [
        "id",
        "version",
        "name",
        "description",
        "author",
        "icon",
        "external_url",
        "game",
        "game_version",
        "tags",
        "files",
    ]


def test_normalize_mod_config_data_preserves_existing_order():
    legacy_description_key = "".join(("tag", "line"))
    legacy_icon_key = "_".join(("icon", "url"))
    config = {
        "name": "Test",
        "files": {"1": {}},
        legacy_description_key: "Desc",
        legacy_icon_key: "icon.png",
    }

    assert normalize_mod_config_data(config) is True
    assert list(config) == ["name", "files", "description", "icon"]


def test_normalize_files_data_converts_tab_ids_to_file_keys():
    files = normalize_files_data(
        {
            "deltarune_4": {
                "data_file_url": "DATA.win",
                "extra_files": {"extras": ["bonus.zip"]},
            }
        }
    )

    assert list(files) == ["deltarune_4"]
    assert files["deltarune_4"]["data_file_url"] == "DATA.win"
    assert files["deltarune_4"]["extra_files"] == [
        {"key": "extras", "url": "bonus.zip"}
    ]


def test_normalize_files_data_with_game_prefix_normalizes_chapter_ids():
    files = normalize_files_data(
        {
            "4": {
                "data_file_url": "DATA.win",
                "extra_files": {"extras": ["bonus.zip"]},
            }
        },
        game="deltarune"
    )

    assert list(files) == ["deltarune_4"]
    assert files["deltarune_4"]["data_file_url"] == "DATA.win"
    assert files["deltarune_4"]["extra_files"] == [
        {"key": "extras", "url": "bonus.zip"}
    ]


def test_normalize_mod_config_data_renames_legacy_file_keys_to_chapter_ids():
    config = {
        "game": "deltarune",
        "files": {"4": {"data_file_url": "DATA.win"}},
    }

    assert normalize_mod_config_data(config) is True
    assert list(config["files"]) == ["deltarune_4"]
